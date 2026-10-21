"""One bounded PostgreSQL search for public and owned catalogue entries."""
from fastapi import HTTPException
from sqlalchemy import select, func, or_, and_, exists, literal, text

from app.models import CatalogAlias, Location, Section, Route
from app.search_spelling import TRANSLIT_SQL

KINDS = {"locations": (Location, "location_id"), "sections": (Section, "section_id"), "routes": (Route, "route_id")}
NORMALIZE_SQL = """CREATE OR REPLACE FUNCTION catalog_normalize(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
 SELECT regexp_replace(translate(lower(replace(value,'İ','I')),
 'ığşçöüâîûáàäãåéèêëíìïóòôõúùÿñё',
 'igscouaiuaaaaaeeeeiiioooouuynе'), '[^[:alnum:]]+', '', 'g')
$$""" + ";\n" + TRANSLIT_SQL


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
    raw_names = [model.name]
    if model in (Section, Route):
        raw_names += [model.name_en, model.name_native]
    names = [func.catalog_normalize(field) for field in raw_names]
    fields = [Location.country, Location.region, Location.city]
    if model in (Section, Route):
        fields += [Location.name, Section.type]
    if model is Route:
        fields += [Section.name, Section.name_en, Section.name_native,
                   Route.grade, Route.color, Route.route_number, Route.setter]
    raw_fields = raw_names + fields
    fields = [func.catalog_normalize(field) for field in raw_fields]
    q = await session.scalar(select(func.catalog_normalize(query)))
    translit_q = await session.scalar(select(func.catalog_translit(query)))
    translit_fields = [func.catalog_translit(field) for field in raw_fields]
    if query.strip() and not q:
        raise HTTPException(422, "Enter a name containing letters or digits")
    aliases = select(CatalogAlias).where(CatalogAlias.owner_id == uid,
        getattr(CatalogAlias, alias_field) == model.id)
    exact_alias = exists(aliases.where(func.catalog_normalize(CatalogAlias.name) == q))
    # Only names/confirmed aliases can select an entity automatically, never metadata.
    exact = func.coalesce(or_(*(name == q for name in names), exact_alias), False) if q else literal(False)
    alias_score = select(func.max(func.public.similarity(func.catalog_normalize(CatalogAlias.name), q))).where(
        CatalogAlias.owner_id == uid, getattr(CatalogAlias, alias_field) == model.id).correlate(model).scalar_subquery()
    translit_alias_score = select(func.max(func.public.similarity(func.catalog_translit(CatalogAlias.name), translit_q))).where(
        CatalogAlias.owner_id == uid, getattr(CatalogAlias, alias_field) == model.id).correlate(model).scalar_subquery()
    score = func.greatest(*(func.public.similarity(field, q) for field in fields),
        *(func.public.similarity(field, translit_q) for field in translit_fields),
        func.coalesce(alias_score, 0), func.coalesce(translit_alias_score, 0)) if q else literal(0.0)
    stmt = select(model, score.label("score"), exact.label("exact"), Location.country,
                  Location.name.label("area_name"),
                  Section.name if model is Route else literal(None)).select_from(model)
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
        def matches(field, needle=q):
            return or_(field.contains(needle, autoescape=True), field.op("OPERATOR(public.%)")(needle))
        stmt = stmt.where(or_(exact, *(matches(field) for field in fields),
            *(matches(field, translit_q) for field in translit_fields), exists(
            aliases.where(or_(matches(func.catalog_normalize(CatalogAlias.name)),
                              matches(func.catalog_translit(CatalogAlias.name), translit_q))))))
    stmt = stmt.order_by(exact.desc(), score.desc(), model.name, model.id).offset(offset).limit(limit+1)
    values = (await session.execute(stmt)).all()
    items = []
    for item, rank, is_exact, country, area_name, section_name in values[:limit]:
        items.append({"id": item.id, "name": item.name, "grade": getattr(item, "grade", None),
            "name_en": getattr(item, "name_en", None), "name_native": getattr(item, "name_native", None),
            "section": section_name,
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
