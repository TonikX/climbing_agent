from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ExternalRef, Gear, Location, Route, RouteAttempt, Section, TrainingSession, User


def _bad(message: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=message)


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _bad(f"Invalid datetime: {value}") from exc


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise _bad(f"Invalid date: {value}") from exc


def _today(user: User) -> date:
    try:
        return datetime.now(ZoneInfo(user.timezone)).date()
    except Exception:
        return datetime.now(UTC).date()


async def _add_refs(session: AsyncSession, entity_type: str, owner: Any, refs: Any) -> None:
    owner_field = {"user": "user_id", "location": "location_id", "section": "section_id", "route": "route_id"}[entity_type]
    for raw in refs or []:
        if not isinstance(raw, dict) or not raw.get("system") or not raw.get("id"):
            continue
        existing = await session.scalar(select(ExternalRef).where(
            ExternalRef.system == str(raw["system"]),
            ExternalRef.entity_type == entity_type,
            ExternalRef.external_id == str(raw["id"]),
        ))
        if existing and getattr(existing, owner_field) != owner.id:
            raise _bad(f"External reference already belongs to another {entity_type}", 409)
        if not existing:
            existing = ExternalRef(system=str(raw["system"]), entity_type=entity_type,
                                   external_id=str(raw["id"]), url=raw.get("url"))
            setattr(existing, owner_field, owner.id)
            session.add(existing)
        elif raw.get("url"):
            existing.url = str(raw["url"])


async def _by_ref(session: AsyncSession, entity_type: str, refs: Any) -> Any | None:
    owner_field = {"user": "user_id", "location": "location_id", "section": "section_id", "route": "route_id"}[entity_type]
    model = {"user": User, "location": Location, "section": Section, "route": Route}[entity_type]
    for raw in refs or []:
        if isinstance(raw, dict) and raw.get("system") and raw.get("id"):
            ref = await session.scalar(select(ExternalRef).where(
                ExternalRef.system == str(raw["system"]), ExternalRef.entity_type == entity_type,
                ExternalRef.external_id == str(raw["id"]),
            ))
            if ref:
                return await session.get(model, getattr(ref, owner_field))
    return None


async def _user(session: AsyncSession, raw: dict[str, Any]) -> User:
    item = await session.get(User, str(raw["id"])) if raw.get("id") else None
    item = item or await _by_ref(session, "user", raw.get("externalRefs"))
    if not item and raw.get("name"):
        matches = list((await session.scalars(select(User).where(func.lower(User.name) == _norm(raw["name"])))).all())
        if len(matches) > 1:
            raise _bad("User name is ambiguous")
        item = matches[0] if matches else None
    if not item:
        if not raw.get("name"):
            raise _bad("Cannot create a user without a name")
        item = User(name=str(raw["name"]), timezone=str(raw.get("timezone") or "Europe/Moscow"))
        session.add(item)
        await session.flush()
    await _add_refs(session, "user", item, raw.get("externalRefs"))
    return item


async def _area(session: AsyncSession, raw: dict[str, Any] | None) -> Location | None:
    if not raw:
        return None
    item = await session.get(Location, str(raw["id"])) if raw.get("id") else None
    item = item or await _by_ref(session, "location", raw.get("externalRefs"))
    if not item and raw.get("name"):
        item = await session.scalar(select(Location).where(func.lower(Location.name) == _norm(raw["name"])))
    if not item:
        if not raw.get("name"):
            raise _bad("Cannot create an area without a name")
        item = Location(type="outdoor", name=str(raw["name"]), country=raw.get("country"),
                        latitude=raw.get("latitude"), longitude=raw.get("longitude"))
        session.add(item)
        await session.flush()
    elif raw.get("country") and not item.country:
        item.country = str(raw["country"])
    await _add_refs(session, "location", item, raw.get("externalRefs"))
    return item


async def _section(session: AsyncSession, area: Location | None, raw: dict[str, Any] | None) -> Section | None:
    if not raw:
        return None
    item = await session.get(Section, str(raw["id"])) if raw.get("id") else None
    item = item or await _by_ref(session, "section", raw.get("externalRefs"))
    if not item and raw.get("name") and area:
        item = await session.scalar(select(Section).where(
            Section.location_id == area.id, func.lower(Section.name) == _norm(raw["name"])))
    if item and area and item.location_id != area.id:
        raise _bad("Sector does not belong to the selected area")
    if not item:
        if not raw.get("name"):
            raise _bad("Cannot create a sector without a name")
        if not area:
            raise _bad("An area is required to create a sector")
        item = Section(location_id=area.id, type="sector", name=str(raw["name"]))
        session.add(item)
        await session.flush()
    await _add_refs(session, "section", item, raw.get("externalRefs"))
    return item


async def _route(session: AsyncSession, section: Section | None, raw: dict[str, Any]) -> Route | None:
    item = await session.get(Route, str(raw["routeId"])) if raw.get("routeId") else None
    item = item or await _by_ref(session, "route", raw.get("externalRefs"))
    if not item and raw.get("name") and section:
        item = await session.scalar(select(Route).where(
            Route.section_id == section.id, func.lower(Route.name) == _norm(raw["name"])))
    if item and section and item.section_id != section.id:
        raise _bad("Route does not belong to the selected sector")
    if not item and raw.get("name") and section:
        item = Route(section_id=section.id, name=str(raw["name"]), grade=raw.get("grade"))
        session.add(item)
        await session.flush()
    if item:
        if raw.get("grade") and not item.grade:
            item.grade = str(raw["grade"])
        await _add_refs(session, "route", item, raw.get("externalRefs"))
    elif raw.get("routeId"):
        raise _bad(f"Route {raw['routeId']} does not exist")
    return item


async def _gear_ids(session: AsyncSession, user_id: str, ids: Any) -> list[Gear]:
    if ids is None:
        return []
    values = [str(value) for value in ids]
    items = list((await session.scalars(select(Gear).where(Gear.user_id == user_id, Gear.id.in_(values)))).all()) if values else []
    if len(items) != len(set(values)):
        raise _bad("Unknown gear ID for this user")
    return items


async def _active(session: AsyncSession, user_id: str) -> TrainingSession | None:
    return await session.scalar(select(TrainingSession).options(
        selectinload(TrainingSession.attempts).selectinload(RouteAttempt.route).selectinload(Route.section),
        selectinload(TrainingSession.sections),
        selectinload(TrainingSession.gear)).where(
        TrainingSession.user_id == user_id, TrainingSession.status == "active").with_for_update())


async def _last_attempt(session: AsyncSession, user_id: str, active_only: bool = False) -> RouteAttempt | None:
    query = select(RouteAttempt).join(TrainingSession).options(
        selectinload(RouteAttempt.route).selectinload(Route.section)).where(
        TrainingSession.user_id == user_id)
    if active_only:
        query = query.where(TrainingSession.status == "active")
    return await session.scalar(query.order_by(RouteAttempt.created_at.desc(), RouteAttempt.sequence.desc()).limit(1))


async def _attempt(session: AsyncSession, training: TrainingSession, area: Location | None,
                   default_section: Section | None, raw: dict[str, Any]) -> RouteAttempt:
    previous = await _last_attempt(session, training.user_id, active_only=True)
    continuing = bool(raw.get("continueCurrentRoute"))
    if continuing and not previous:
        raise _bad("There is no current route to continue", 409)
    if continuing and previous:
        if raw.get("routeId") or raw.get("name") or raw.get("sector"):
            raise _bad("continueCurrentRoute cannot be combined with another route", 409)
        raw = {**raw, "routeId": previous.route_id,
               "name": (previous.route_snapshot or {}).get("name"),
               "grade": (previous.route_snapshot or {}).get("grade")}
        if previous.route:
            default_section = previous.route.section
        elif (previous.route_snapshot or {}).get("sectorId"):
            default_section = await session.get(Section, previous.route_snapshot["sectorId"])
        if default_section:
            area = await session.get(Location, default_section.location_id)
    section = await _section(session, area, raw.get("sector")) if raw.get("sector") else default_section
    route = await _route(session, section, raw)
    if route and not section:
        section = await session.get(Section, route.section_id)
    if section and not area:
        area = await session.get(Location, section.location_id)
    if area and section and area.id != section.location_id:
        raise _bad("Route does not belong to the selected area")
    sequence = int(await session.scalar(select(func.coalesce(func.max(RouteAttempt.sequence), 0)).where(
        RouteAttempt.training_id == training.id))) + 1
    same_as_previous = bool(previous and (
        (route and previous.route_id == route.id) or
        (not route and _norm((previous.route_snapshot or {}).get("name")) == _norm(raw.get("name")) and
         _norm((previous.route_snapshot or {}).get("grade")) == _norm(raw.get("grade")))))
    route_session_key = (previous.route_session_key if previous and (continuing or same_as_previous) else None) \
        or f"route_session_{uuid4()}"
    attempt_number = int(await session.scalar(select(func.count(RouteAttempt.id)).where(
        RouteAttempt.training_id == training.id,
        RouteAttempt.route_session_key == route_session_key))) + 1
    result = str(raw.get("result") or "unknown")
    falls = raw.get("falls")
    if falls is not None and int(falls) > 0 and result == "send":
        result = "project"
    style = str(raw.get("style") or "unknown")
    if result == "send" and attempt_number > 1 and style == "unknown":
        style = "redpoint"
    item = RouteAttempt(
        training_id=training.id, route_id=route.id if route else None, sequence=sequence,
        route_session_key=route_session_key, attempt_number=attempt_number,
        attempts=int(raw.get("attempts") or 1), result=result,
        style=style, belay=str(raw.get("belay") or "unknown"),
        feel=str(raw.get("feel") or "unknown"), notes=raw.get("notes"),
        high_point=raw.get("highPoint"), total_moves=raw.get("totalMoves"), falls=falls,
        is_test=bool(raw.get("isTest", False)),
        route_snapshot={"name": raw.get("name") or (route.name if route else None),
                        "grade": raw.get("grade") or (route.grade if route else None),
                        "areaId": area.id if area else None, "sectorId": section.id if section else None},
    )
    session.add(item)
    if section and section not in training.sections:
        training.sections.append(section)
    training.version += 1
    await session.flush()
    return item


def _attempt_dict(item: RouteAttempt, route: Route | None = None, section: Section | None = None) -> dict[str, Any]:
    return {"id": item.id, "number": item.attempt_number, "routeId": item.route_id,
            "routeSessionKey": item.route_session_key, "routeSnapshot": item.route_snapshot, "belay": item.belay,
            "attempts": item.attempts, "result": item.result, "style": item.style, "feel": item.feel,
            "highPoint": item.high_point, "totalMoves": item.total_moves, "falls": item.falls,
            "notes": item.notes, "isTest": item.is_test, "route": _route_dict(route) if route else None,
            "sector": _section_dict(section) if section else None}


def _area_dict(item: Location | None) -> dict[str, Any] | None:
    return None if not item else {"id": item.id, "name": item.name, "country": item.country,
                                  "latitude": float(item.latitude) if item.latitude is not None else None,
                                  "longitude": float(item.longitude) if item.longitude is not None else None}


def _section_dict(item: Section | None) -> dict[str, Any] | None:
    return None if not item else {"id": item.id, "areaId": item.location_id, "name": item.name}


def _route_dict(item: Route | None) -> dict[str, Any] | None:
    return None if not item else {"id": item.id, "sectorId": item.section_id, "name": item.name,
                                  "grade": item.grade}


def _gear_dict(item: Gear) -> dict[str, Any]:
    return {"id": item.id, "userId": item.user_id, "type": item.type, "brand": item.brand,
            "model": item.model, "size": item.size, "nickname": (item.attributes or {}).get("nickname"),
            "active": item.active, "notes": item.notes}


async def _start(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    current = await _active(session, user.id)
    if current:
        current.status, current.completed_at = "completed", datetime.now(UTC)
    area = await _area(session, p.get("area"))
    section = await _section(session, area, p.get("sector"))
    item = TrainingSession(user_id=user.id, status="active", local_date=_date(p["date"]) if p.get("date") else _today(user),
                           started_at=_dt(p.get("startedAt")), timezone=user.timezone,
                           environment=p.get("environment") or "unknown", primary_location_id=area.id if area else None,
                           weather=p.get("weather"), notes=p.get("notes"), attempts=[],
                           sections=[section] if section else [], gear=await _gear_ids(session, user.id, p.get("gearIds")))
    session.add(item)
    await session.flush()
    return {"success": True, "trainingId": item.id, "status": "active"}


async def _append(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    raw_attempt = p.get("attempt") or p
    training = await _active(session, user.id)
    local_date = _date(p["date"]) if p.get("date") else _today(user)
    if training and training.local_date != local_date:
        raise _bad("Active training has a different date; finish it or explicitly start a new training", 409)
    area = await _area(session, p.get("area"))
    if not area and training and training.primary_location_id:
        area = await session.get(Location, training.primary_location_id)
    section = await _section(session, area, p.get("sector"))
    if not section and training and training.sections:
        section = training.sections[-1]
    if not training:
        training = TrainingSession(user_id=user.id, status="active", local_date=local_date,
                                   timezone=user.timezone, environment="unknown",
                                   primary_location_id=area.id if area else None, attempts=[], sections=[], gear=[])
        session.add(training)
        await session.flush()
    if area and not training.primary_location_id:
        training.primary_location_id = area.id
    item = await _attempt(session, training, area, section, raw_attempt)
    previous_best = await session.scalar(select(func.max(RouteAttempt.high_point)).where(
        RouteAttempt.route_session_key == item.route_session_key, RouteAttempt.id != item.id))
    snapshot = item.route_snapshot or {}
    return {
        "attemptId": item.id,
        "number": item.attempt_number,
        "route": {"name": snapshot.get("name"), "grade": snapshot.get("grade")},
        "result": {"completed": item.result == "send", "highPoint": item.high_point,
                   "totalMoves": item.total_moves, "falls": item.falls},
        "derived": {"isNewBest": item.high_point is not None and
                    (previous_best is None or item.high_point > previous_best),
                    "isProject": item.result == "project"},
    }


async def _save(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    training = await _active(session, user.id) if p.get("mergeIntoActive") else None
    if training and training.local_date != _date(p["date"]):
        raise _bad("Summary date differs from active training date", 409)
    area = await _area(session, p.get("area"))
    if not area and training and training.primary_location_id:
        area = await session.get(Location, training.primary_location_id)
    section = await _section(session, area, p.get("sector"))
    if not section and training and training.sections:
        section = training.sections[-1]
    merged = training is not None
    if not training:
        training = TrainingSession(user_id=user.id, status="completed", local_date=_date(p["date"]),
                                   timezone=user.timezone, completed_at=datetime.now(UTC), attempts=[], sections=[], gear=[])
        session.add(training)
        await session.flush()
    training.started_at = _dt(p.get("startedAt")) or training.started_at
    if p.get("durationMinutes") is not None: training.duration_minutes = int(p["durationMinutes"])
    if p.get("environment") and (not merged or p["environment"] != "unknown"): training.environment = p["environment"]
    if area: training.primary_location_id = area.id
    if p.get("weather"): training.weather = {**(training.weather or {}), **p["weather"]}
    if p.get("gearIds") is not None:
        for gear in await _gear_ids(session, user.id, p["gearIds"]):
            if gear not in training.gear: training.gear.append(gear)
    if p.get("physicalState"): training.physical_state = p["physicalState"]
    if p.get("notes"): training.notes = p["notes"]
    # Summaries are authoritative per route when there is one unambiguous match.
    for raw in p.get("routes") or []:
        route = await _route(session, section, raw)
        candidates = [a for a in training.attempts if (route and a.route_id == route.id) or (
            not route and _norm(a.route_snapshot.get("name")) == _norm(raw.get("name")) and
            _norm(a.route_snapshot.get("grade")) == _norm(raw.get("grade")))]
        if merged and len(candidates) == 1:
            item = candidates[0]
            for source, target in (("attempts", "attempts"), ("result", "result"), ("style", "style"),
                                   ("belay", "belay"), ("feel", "feel"), ("notes", "notes")):
                if raw.get(source) is not None: setattr(item, target, raw[source])
            if "isTest" in raw: item.is_test = bool(raw["isTest"])
        else:
            await _attempt(session, training, area, section, raw)
    await session.flush()
    count = await session.scalar(select(func.count(RouteAttempt.id)).where(RouteAttempt.training_id == training.id))
    return {"success": True, "merged": merged, "trainingId": training.id, "routeCount": count}


async def _update(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    training = await session.scalar(select(TrainingSession).options(
        selectinload(TrainingSession.sections), selectinload(TrainingSession.gear)).where(
        TrainingSession.id == str(p["trainingId"]), TrainingSession.user_id == user.id).with_for_update()) if p.get("trainingId") else await _active(session, user.id)
    if not training: raise _bad("No matching climbing training found", 404)
    area = await _area(session, p.get("area"))
    if not area and training.primary_location_id: area = await session.get(Location, training.primary_location_id)
    section = await _section(session, area, p.get("sector"))
    if p.get("durationMinutes") is not None: training.duration_minutes = int(p["durationMinutes"])
    if p.get("environment"): training.environment = p["environment"]
    if area: training.primary_location_id = area.id
    if section and section not in training.sections: training.sections.append(section)
    if p.get("weather"): training.weather = {**(training.weather or {}), **p["weather"]}
    if p.get("gearIds") is not None:
        for gear in await _gear_ids(session, user.id, p["gearIds"]):
            if gear not in training.gear: training.gear.append(gear)
    if p.get("physicalState"): training.physical_state = p["physicalState"]
    if p.get("notes"): training.notes = p["notes"]
    training.version += 1
    return {"success": True, "trainingId": training.id}


async def _attempt_target(session: AsyncSession, user_id: str, p: dict[str, Any]) -> RouteAttempt:
    if p.get("attemptId"):
        item = await session.scalar(select(RouteAttempt).join(TrainingSession).where(
            RouteAttempt.id == str(p["attemptId"]), TrainingSession.user_id == user_id).with_for_update())
    elif p.get("useLastAttempt"):
        item = await _last_attempt(session, user_id)
    else:
        raise _bad("attemptId or useLastAttempt=true is required")
    if not item:
        raise _bad("Climbing attempt not found", 404)
    return item


async def _update_attempt(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    item = await _attempt_target(session, user.id, p)
    updated: dict[str, Any] = {}
    mapping = {
        "highPoint": "high_point", "totalMoves": "total_moves", "falls": "falls",
        "result": "result", "style": "style", "feel": "feel", "notes": "notes",
    }
    for source, target in mapping.items():
        if source in p:
            setattr(item, target, p[source])
            updated[source] = p[source]
    if item.falls is not None and item.falls > 0 and item.result == "send":
        item.result = "project"
        updated["result"] = "project"
    return {"success": True, "attemptId": item.id, "number": item.attempt_number, "updated": updated}


async def _delete_attempt(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    item = await _attempt_target(session, user.id, p)
    attempt_id, route_session_key = item.id, item.route_session_key
    await session.delete(item)
    await session.flush()
    remaining = await session.scalar(select(func.count(RouteAttempt.id)).where(
        RouteAttempt.route_session_key == route_session_key)) if route_session_key else 0
    return {"success": True, "deletedAttemptId": attempt_id, "currentRouteAttempts": remaining}


def _grade_rank(value: str | None) -> tuple[int, int, int]:
    if not value:
        return (-1, -1, -1)
    grade = value.strip().upper()
    digits = "".join(ch for ch in grade if ch.isdigit())
    number = int(digits) if digits else -1
    letter = next((ch for ch in grade if ch in "ABC"), "")
    modifier = 1 if "+" in grade else 0
    return (number, "ABC".find(letter), modifier)


def _summary(attempts: list[RouteAttempt]) -> dict[str, Any]:
    sessions = {a.route_session_key or a.id for a in attempts}
    completed = {a.route_session_key or a.id for a in attempts if a.result == "send"}
    projects = {a.route_session_key or a.id for a in attempts if a.result == "project"} - completed
    grades = [(a.route_snapshot or {}).get("grade") or (a.route.grade if a.route else None) for a in attempts]
    max_grade = max((grade for grade in grades if grade), key=_grade_rank, default=None)
    return {
        "routesCount": len(sessions),
        "attemptsCount": sum(a.attempts for a in attempts),
        "completedRoutes": len(completed),
        "activeProjects": len(projects),
        "flashCount": sum(1 for a in attempts if a.style == "flash"),
        "redpointCount": sum(1 for a in attempts if a.style == "redpoint"),
        "maxGrade": max_grade,
    }


async def _get_current(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    training = await _active(session, user.id)
    if not training:
        return {"active": False}
    area = await session.get(Location, training.primary_location_id) if training.primary_location_id else None
    attempts = [a for a in training.attempts if not a.is_test]
    response: dict[str, Any] = {
        "active": True, "id": training.id, "status": training.status,
        "location": {"name": area.name} if area else None,
        "summary": _summary(attempts),
    }
    if p.get("detail", "summary") == "full":
        route_groups: dict[str, dict[str, Any]] = {}
        for attempt in sorted(attempts, key=lambda value: value.sequence):
            key = attempt.route_session_key or attempt.id
            snapshot = attempt.route_snapshot or {}
            group = route_groups.setdefault(key, {
                "route": {"name": snapshot.get("name"), "grade": snapshot.get("grade")},
                "section": next(({"id": s.id, "name": s.name} for s in training.sections
                                 if s.id == snapshot.get("sectorId")), None),
                "attempts": [],
            })
            group["attempts"].append(_attempt_dict(attempt, attempt.route))
        response["routes"] = list(route_groups.values())
    return response


async def _statistics_rows(session: AsyncSession, user_id: str, start: date | None,
                           end: date | None) -> list[tuple[TrainingSession, RouteAttempt]]:
    query = select(TrainingSession).options(
        selectinload(TrainingSession.attempts).selectinload(RouteAttempt.route)).where(
        TrainingSession.user_id == user_id)
    if start: query = query.where(TrainingSession.local_date >= start)
    if end: query = query.where(TrainingSession.local_date <= end)
    trainings = list((await session.scalars(query)).unique().all())
    return [(training, attempt) for training in trainings for attempt in training.attempts if not attempt.is_test]


async def _statistics(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    today, scope = _today(user), p.get("scope", "week")
    start: date | None = _date(p["dateFrom"]) if p.get("dateFrom") else None
    end: date | None = _date(p["dateTo"]) if p.get("dateTo") else None
    previous_start = previous_end = None
    if scope == "week":
        start, end = today - timedelta(days=today.weekday()), today
        previous_start, previous_end = start - timedelta(days=7), start - timedelta(days=1)
    elif scope == "month":
        start, end = today.replace(day=1), today
        previous_end = start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
    rows = await _statistics_rows(session, user.id, start, end)
    route_name = _norm(p.get("route"))
    if p.get("routeId") or route_name:
        rows = [(t, a) for t, a in rows if
                (p.get("routeId") and a.route_id == p["routeId"]) or
                (route_name and route_name in _norm((a.route_snapshot or {}).get("name") or
                                                    (a.route.name if a.route else None)))]
    attempts = [attempt for _, attempt in rows]
    result = {"scope": scope, "dateFrom": start.isoformat() if start else None,
              "dateTo": end.isoformat() if end else None,
              "trainingsCount": len({training.id for training, _ in rows}), **_summary(attempts)}
    if previous_start and previous_end:
        previous_rows = await _statistics_rows(session, user.id, previous_start, previous_end)
        previous_attempts = [attempt for _, attempt in previous_rows]
        previous_summary = _summary(previous_attempts)
        result["previousPeriod"] = {
            "trainingsCount": len({training.id for training, _ in previous_rows}),
            "completedRoutes": previous_summary["completedRoutes"],
            "attemptsCount": previous_summary["attemptsCount"],
        }
    if scope == "projects":
        latest: dict[str, RouteAttempt] = {}
        for attempt in attempts:
            key = attempt.route_session_key or attempt.id
            if key not in latest or attempt.sequence > latest[key].sequence:
                latest[key] = attempt
        limit = min(int(p.get("limit") or 10), 50)
        result["projects"] = [
            {"route": {"name": (a.route_snapshot or {}).get("name"),
                       "grade": (a.route_snapshot or {}).get("grade")},
             "highPoint": a.high_point, "totalMoves": a.total_moves, "falls": a.falls}
            for a in latest.values() if a.result == "project"
        ][:limit]
    return result


async def _finish(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user = await _user(session, p["user"])
    training = await _active(session, user.id)
    if not training: raise _bad("No active climbing training found", 404)
    training.status, training.completed_at = "completed", datetime.now(UTC)
    if p.get("durationMinutes") is not None: training.duration_minutes = int(p["durationMinutes"])
    if p.get("physicalState"): training.physical_state = p["physicalState"]
    if p.get("notes"): training.notes = p["notes"]
    training.version += 1
    return {"success": True, "trainingId": training.id, "status": "completed", "routeCount": len(training.attempts)}


async def _upsert_gear(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    user, raw = await _user(session, p["user"]), p["gear"]
    item = await session.get(Gear, str(raw["id"])) if raw.get("id") else None
    if item and item.user_id != user.id: raise _bad("Unknown gear ID for this user")
    if not item:
        item = await session.scalar(select(Gear).where(
            Gear.user_id == user.id, Gear.type == raw["type"],
            func.lower(func.coalesce(Gear.brand, "")) == _norm(raw.get("brand")),
            func.lower(func.coalesce(Gear.model, "")) == _norm(raw.get("model")),
            func.lower(func.coalesce(Gear.size, "")) == _norm(raw.get("size"))))
    if not item:
        item = Gear(user_id=user.id, type=raw["type"]); session.add(item)
    for key in ("brand", "model", "size", "active", "notes"):
        if key in raw: setattr(item, key, raw[key])
    if "nickname" in raw: item.attributes = {**(item.attributes or {}), "nickname": raw["nickname"]}
    await session.flush()
    return {"success": True, "gear": _gear_dict(item)}


async def _find_routes(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    items = list((await session.scalars(select(Route).options(
        selectinload(Route.section).selectinload(Section.location)))).all())
    result = []
    for item in items:
        section, area = item.section, item.section.location
        if p.get("name") and _norm(p["name"]) not in _norm(item.name): continue
        if p.get("grade") and _norm(p["grade"]) != _norm(item.grade): continue
        if p.get("sector") and _norm(p["sector"]) not in _norm(section.name): continue
        if p.get("area") and _norm(p["area"]) not in _norm(area.name): continue
        result.append({**_route_dict(item), "sector": _section_dict(section), "area": _area_dict(area)})
    return {"count": len(result), "routes": result}


async def _get_trainings(session: AsyncSession, p: dict[str, Any]) -> dict[str, Any]:
    query = select(TrainingSession).options(
        selectinload(TrainingSession.attempts).selectinload(RouteAttempt.route).selectinload(Route.section),
        selectinload(TrainingSession.sections), selectinload(TrainingSession.gear))
    if p.get("userId"): query = query.where(TrainingSession.user_id == p["userId"])
    elif p.get("userName"):
        user = await session.scalar(select(User).where(func.lower(User.name) == _norm(p["userName"])))
        if not user: return {"count": 0, "trainings": []}
        query = query.where(TrainingSession.user_id == user.id)
    if p.get("status"): query = query.where(TrainingSession.status == p["status"])
    if p.get("dateFrom"): query = query.where(TrainingSession.local_date >= _date(p["dateFrom"]))
    if p.get("dateTo"): query = query.where(TrainingSession.local_date <= _date(p["dateTo"]))
    items = list((await session.scalars(query.order_by(TrainingSession.local_date.desc(), TrainingSession.created_at.desc()))).unique().all())
    users = {u.id: u for u in (await session.scalars(select(User))).all()}
    result = []
    for item in items:
        area = await session.get(Location, item.primary_location_id) if item.primary_location_id else None
        attempts = [a for a in item.attempts if p.get("includeTest") or not a.is_test]
        if p.get("area") and _norm(p["area"]) not in _norm(area.name if area else None): continue
        def attempt_matches(a: RouteAttempt) -> bool:
            route, snapshot = a.route, a.route_snapshot or {}
            section = route.section if route else next((s for s in item.sections if s.id == snapshot.get("sectorId")), None)
            return (not p.get("sector") or _norm(p["sector"]) in _norm(section.name if section else None)) and \
                   (not p.get("route") or _norm(p["route"]) in _norm(snapshot.get("name") or (route.name if route else None))) and \
                   (not p.get("grade") or _norm(p["grade"]) == _norm(snapshot.get("grade") or (route.grade if route else None)))
        if (p.get("sector") or p.get("route") or p.get("grade")) and not any(attempt_matches(a) for a in attempts): continue
        user = users[item.user_id]
        result.append({"id": item.id, "userId": item.user_id, "status": item.status,
                       "createdAt": item.created_at.isoformat(), "completedAt": item.completed_at.isoformat() if item.completed_at else None,
                       "date": item.local_date.isoformat(), "startedAt": item.started_at.isoformat() if item.started_at else None,
                       "durationMinutes": item.duration_minutes, "environment": item.environment,
                       "areaId": item.primary_location_id, "sectorIds": [s.id for s in item.sections],
                       "weather": item.weather, "gearIds": [g.id for g in item.gear],
                       "physicalState": item.physical_state, "notes": item.notes,
                       "user": {"id": user.id, "name": user.name, "timezone": user.timezone},
                       "area": _area_dict(area), "sectors": [_section_dict(s) for s in item.sections],
                       "gear": [_gear_dict(g) for g in item.gear],
                       "routes": [_attempt_dict(a, a.route, a.route.section if a.route else next((s for s in item.sections if s.id == (a.route_snapshot or {}).get("sectorId")), None)) for a in attempts]})
        if len(result) >= int(p.get("limit") or 100): break
    return {"count": len(result), "trainings": result}


HANDLERS = {
    "start_climbing_training": _start, "append_climbing_attempt": _append,
    "save_climbing_training": _save, "update_climbing_training": _update,
    "update_climbing_attempt": _update_attempt, "delete_climbing_attempt": _delete_attempt,
    "finish_climbing_training": _finish, "upsert_climbing_gear": _upsert_gear,
    "find_climbing_routes": _find_routes, "get_current_climbing_training": _get_current,
    "get_climbing_trainings": _get_trainings, "get_climbing_statistics": _statistics,
}


async def execute_tool(session: AsyncSession, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLERS.get(operation)
    if not handler: raise _bad("Unknown climbing operation", 404)
    return await handler(session, payload)
