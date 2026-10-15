"""One bounded PostgreSQL search for public and owned catalogue entries."""
from fastapi import HTTPException
from sqlalchemy import select, func, or_, and_, exists, literal, text

from app.models import CatalogAlias, Location, Section, Route

KINDS = {"locations": (Location, "location_id"), "sections": (Section, "section_id"), "routes": (Route, "route_id")}
NORMALIZE_SQL = """CREATE OR REPLACE FUNCTION catalog_normalize(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
 SELECT regexp_replace(translate(lower(replace(value,'İ','I')),
 'ığşçöüâîûáàäãåéèêëíìïóòôõúùÿñё',
 'igscouaiuaaaaaeeeeiiioooouuynе'), '[^[:alnum:]]+', '', 'g')
$$"""


def visible(uid):
    return or_(Location.visibility == "public", and_(Location.visibility == "private", Location.owner_id == uid))


async def target(session, uid, kind, item_id):
    model, _ = KINDS[kind]
    query = select(model)
    if model is Section:
        query = query.join(Location)
    elif model is Route:
        query = query.join(Section).join(Location)
    item = await session.scalar(query.where(model.id == item_id, visible(uid)))
    if not item:
        raise HTTPException(404, "Catalogue item not found")
    return item


async def search(session, uid, kind, query="", parent_id=None, offset=0, limit=8):
    if kind not in KINDS or len(query) > 200 or offset < 0 or offset > 10000 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid catalogue search")
    # Nested RLS policies inflate the estimate: JIT compilation cost 14 s for a 40 ms query.
    # SET LOCAL affects only this transaction, never the shared server configuration.
    await session.execute(text("SET LOCAL jit=off"))
    model, alias_field = KINDS[kind]
    name = func.catalog_normalize(model.name)
    q = await session.scalar(select(func.catalog_normalize(query)))
    if query.strip() and not q:
        raise HTTPException(422, "Enter a name containing letters or digits")
    aliases = select(CatalogAlias).where(CatalogAlias.owner_id == uid,
        getattr(CatalogAlias, alias_field) == model.id)
    exact_alias = exists(aliases.where(func.catalog_normalize(CatalogAlias.name) == q))
    exact = or_(name == q, exact_alias) if q else name == ""
    alias_score = select(func.max(func.public.similarity(func.catalog_normalize(CatalogAlias.name), q))).where(
        CatalogAlias.owner_id == uid, getattr(CatalogAlias, alias_field) == model.id).correlate(model).scalar_subquery()
    score = func.greatest(func.public.similarity(name, q), func.coalesce(alias_score, 0)) if q else literal(0.0)
    stmt = select(model, score.label("score"), exact.label("exact"), Location.country,
                  Location.name.label("area_name")).select_from(model)
    if model is Section:
        stmt = stmt.join(Location)
        if parent_id:
            stmt = stmt.where(Section.location_id == parent_id)
    elif model is Route:
        stmt = stmt.join(Section).join(Location)
        if parent_id:
            stmt = stmt.where(Route.section_id == parent_id)
    elif parent_id:
        raise HTTPException(422, "Locations have no parent")
    stmt = stmt.where(visible(uid))
    if q:
        stmt = stmt.where(or_(exact, name.startswith(q, autoescape=True), name.op("OPERATOR(public.%)")(q), exists(
            aliases.where(func.catalog_normalize(CatalogAlias.name).op("OPERATOR(public.%)")(q)))))
    stmt = stmt.order_by(exact.desc(), score.desc(), model.name, model.id).offset(offset).limit(limit+1)
    values = (await session.execute(stmt)).all()
    items = []
    for item, rank, is_exact, country, area_name in values[:limit]:
        items.append({"id": item.id, "name": item.name, "grade": getattr(item, "grade", None),
            "parent_id": getattr(item, "location_id", None) or getattr(item, "section_id", None),
            "location": area_name, "country": country, "type": getattr(item, "type", None), "visibility": getattr(item, "visibility", None),
            "match": "exact" if is_exact else "similar", "score": round(float(rank), 3)})
    return {"items": items, "next_offset": offset+limit if len(values) > limit and offset+limit <= 10000 else None}


async def remember(session, uid, kind, item_id, name):
    await target(session, uid, kind, item_id)
    if not name.strip() or len(name) > 200:
        raise HTTPException(422, "Alias must contain 1 to 200 characters")
    _, field = KINDS[kind]
    if not await session.scalar(select(CatalogAlias.id).where(CatalogAlias.owner_id == uid,
        getattr(CatalogAlias, field) == item_id, func.catalog_normalize(CatalogAlias.name) == func.catalog_normalize(name))):
        session.add(CatalogAlias(owner_id=uid, name=name.strip(), **{field: item_id}))
        await session.flush()
