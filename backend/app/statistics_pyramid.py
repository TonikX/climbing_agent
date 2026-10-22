"""Disjoint route-session buckets shared by the pyramid and its drill-down."""
from collections import defaultdict
from typing import Literal

from sqlalchemy import select

from app.models import Location, Section

PyramidBucket = Literal["onsight", "flash", "redpoint", "top_rope", "other_clean", "not_clean"]
BUCKETS = ("onsight", "flash", "redpoint", "top_rope", "other_clean", "not_clean")
STYLES = ("onsight", "flash", "redpoint", "with_falls", "with_hangs", "unknown")
BELAYS = ("lead", "top_rope", "auto_belay", "bouldering", "unknown")


def actual_style(attempt):
    # Legacy top_rope is not a climbing style. Do not guess a style or overwrite belay.
    return attempt.style if attempt.style in STYLES else "unknown"


def dimensions(attempts):
    styles, belays = dict.fromkeys(STYLES, 0), dict.fromkeys(BELAYS, 0)
    for group in route_groups(attempts):
        item = representative(group)
        styles[actual_style(item)] += 1
        belays[item.belay if item.belay in BELAYS else "unknown"] += 1
    return {"styles": styles, "belays": belays}


def route_groups(attempts):
    groups = defaultdict(list)
    for attempt in attempts:
        if not attempt.is_test:
            groups[attempt.route_session_key or attempt.id].append(attempt)
    return list(groups.values())


def representative(group):
    ordered = sorted(group, key=lambda a: (a.sequence, a.id))
    return next((a for a in ordered if a.clean_ascent is True), ordered[-1])


def bucket(group):
    first = representative(group)
    if first.clean_ascent is not True:
        return "not_clean"
    return first.style if first.style in BUCKETS[:4] else "other_clean"


def counts(attempts):
    result = dict.fromkeys(BUCKETS, 0)
    for group in route_groups(attempts):
        result[bucket(group)] += 1
    return result


async def ascents(session, user_id, *, date_from=None, date_to=None, grade=None,
                  region=None, area_id=None, style=None, group_style=None, belay=None, offset=0, limit=20):
    from app.tool_service import _date, _grade_key, _historical_grade, _statistics_rows, _user
    from app.schemas import AttemptResponse
    from fastapi import HTTPException
    await _user(session, {"id": user_id})
    start, end = _date(date_from) if date_from else None, _date(date_to) if date_to else None
    if start and end and start > end:
        raise HTTPException(422, "date_from must not be after date_to")
    rows = await _statistics_rows(session, user_id, start, end, region=region, area_id=area_id)
    selected_grade = _grade_key(grade) if grade != "Без категории" else None
    rows = [(t, a) for t, a in rows if _historical_grade(a) == selected_grade]
    trainings = {a.id: t for t, a in rows}
    groups = [g for g in route_groups([a for _, a in rows])
              if (not style or bucket(g) == style)
              and (not group_style or actual_style(representative(g)) == group_style)
              and (not belay or representative(g).belay == belay)]
    groups.sort(key=lambda g: (trainings[representative(g).id].local_date,
                              trainings[representative(g).id].id,
                              representative(g).sequence, representative(g).id), reverse=True)
    page = groups[offset:offset + limit]
    reps = [representative(g) for g in page]
    area_ids = {(a.route_snapshot or {}).get("areaId") or trainings[a.id].primary_location_id for a in reps}
    sector_ids = {(a.route_snapshot or {}).get("sectorId") for a in reps}
    areas = {a.id: a for a in (await session.scalars(select(Location).where(Location.id.in_(area_ids - {None, ""})))).all()} if area_ids else {}
    sectors = {s.id: s for s in (await session.scalars(select(Section).where(Section.id.in_(sector_ids - {None, ""})))).all()} if sector_ids else {}
    items = []
    for group, attempt in zip(page, reps):
        training = trainings[attempt.id]
        snap = attempt.route_snapshot or {}
        area = areas.get(snap.get("areaId") or training.primary_location_id)
        sector = sectors.get(snap.get("sectorId"))
        items.append({"trainingId": training.id, "date": training.local_date.isoformat(),
            "routeSessionKey": attempt.route_session_key or attempt.id,
            "route": {"name": snap.get("name") or (attempt.route.name if attempt.route else None),
                      "grade": _historical_grade(attempt)},
            "location": {"id": area.id, "name": area.name, "region": area.region} if area else None,
            "sector": {"id": sector.id, "name": sector.name} if sector else None,
            "bucket": bucket(group), "style": actual_style(attempt), "belay": attempt.belay,
            "cleanAscent": attempt.clean_ascent, "reachedTop": attempt.reached_top,
            "attemptsCount": sum(a.attempts for a in group),
            "attempts": [AttemptResponse.model_validate(a).model_dump(mode="json")
                         for a in sorted(group, key=lambda a: (a.sequence, a.id))]})
    return {"items": items, "total": len(groups),
            "nextOffset": offset + limit if offset + limit < len(groups) else None}
