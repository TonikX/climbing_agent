"""Place filters use each attempt's saved area, falling back to the training place."""
from sqlalchemy import and_, func, select

from app.models import Location, RouteAttempt, Section, TrainingSession
from app.grades import normalize_grade


def attempt_area():
    return func.coalesce(func.nullif(RouteAttempt.route_snapshot["areaId"].astext, ""),
                         TrainingSession.primary_location_id)


def attempt_filters(*, region=None, area_id=None, grade=None, include_test=False):
    conditions = [] if include_test else [RouteAttempt.is_test.is_(False)]
    if region or area_id:
        areas = select(Location.id)
        if region:
            areas = areas.where(Location.region == region)
        if area_id:
            areas = areas.where(Location.id == area_id)
        conditions.append(attempt_area().in_(areas))
    if grade:
        canonical = normalize_grade(grade)
        spellings = [canonical]
        if "/" in canonical:
            spellings.append("/".join(reversed(canonical.split("/"))))
        saved = func.translate(func.upper(func.regexp_replace(
            RouteAttempt.route_snapshot["grade"].astext, r"\s+", "", "g")), "АВС", "ABC")
        conditions.append(saved.in_(spellings))
    return and_(*conditions) if conditions else True


async def filter_options(session, uid):
    query = select(Location.id, Location.name, Location.region).select_from(TrainingSession).join(
        RouteAttempt, RouteAttempt.training_id == TrainingSession.id).join(
        Location, Location.id == attempt_area()).where(
            TrainingSession.user_id == uid, RouteAttempt.is_test.is_(False)).distinct().order_by(Location.name, Location.id)
    areas = [dict(row._mapping) for row in (await session.execute(query))]
    return {"regions": sorted({area["region"] for area in areas if area["region"]}), "areas": areas}


async def enrich_trainings(session, items):
    from app.tool_service import _grade_rank
    ids = {a.route_snapshot.get("areaId") or item.primary_location_id
           for item in items for a in item.attempts}
    ids.update(item.primary_location_id for item in items)
    areas = {area.id: area for area in (await session.scalars(select(Location).where(Location.id.in_(ids - {None, ""})))).all()} if ids else {}
    sector_ids = {a.route_snapshot.get("sectorId") for item in items for a in item.attempts}
    sectors = {sector.id: sector.name for sector in (await session.scalars(select(Section).where(Section.id.in_(sector_ids - {None, ""})))).all()} if sector_ids else {}
    result = {}
    for item in items:
        used = {a.route_snapshot.get("areaId") or item.primary_location_id for a in item.attempts}
        if not used:
            used = {item.primary_location_id}
        places = sorted((areas[key] for key in used if key in areas), key=lambda area: (area.name, area.id))
        result[item.id] = {
            "locations": [{"id": area.id, "name": area.name, "region": area.region} for area in places],
            "sectors": sorted({sectors[key] for a in item.attempts if (key := a.route_snapshot.get("sectorId")) in sectors}),
            "grades": sorted({grade for a in item.attempts if (grade := normalize_grade(a.route_snapshot.get("grade")))}, key=_grade_rank),
        }
    return result
