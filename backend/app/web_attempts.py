"""Atomic manual entry from the website, using the same journal domain rules."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Location, Section, Route, TrainingSession
from app.schemas import TrainingCreate, AttemptResponse
from app.service import start_training
from app.tool_service import _user, _visible, _attempt
from app.catalog_capture import private_hierarchy


async def save(session, uid, command):
    user = await _user(session, {"id": uid})
    training = None
    if command.training_id:
        training = await session.scalar(select(TrainingSession).where(
            TrainingSession.id == command.training_id, TrainingSession.user_id == uid)
            .options(selectinload(TrainingSession.sections)).with_for_update())
        if not training:
            raise HTTPException(404, "Training not found")
        if training.status != "active":
            raise HTTPException(409, "Training is completed")
    area = await session.get(Location, command.location_id) if command.location_id else None
    section = await session.get(Section, command.section_id) if command.section_id else None
    route = await session.get(Route, command.route_id) if command.route_id else None
    if (command.location_id and not area) or (command.section_id and not section) or (command.route_id and not route):
        raise HTTPException(404, "Catalogue item not found")
    for item in (area, section, route):
        await _visible(session, item)
    if route and (not section or route.section_id != section.id):
        raise HTTPException(422, "Route belongs to another sector")
    if section and (not area or section.location_id != area.id):
        raise HTTPException(422, "Sector belongs to another area")
    facts = {"region": area.name if area else command.region,
             "sector": section.name if section else command.sector,
             "location_type": "gym" if command.environment == "indoor" else "outdoor",
             "create_region": area is None, "create_sector": section is None, "create_name": route is None}
    if area:
        facts["location_id"] = area.id
    if section:
        facts["section_id"] = section.id
    await private_hierarchy(session, uid, facts, training)
    area = await session.get(Location, facts["location_id"])
    section = await session.get(Section, facts["section_id"])
    if training is None:
        training = await start_training(session, uid, TrainingCreate(date=command.date,
            environment=command.environment, location_id=area.id, section_id=section.id))
    raw = command.model_dump(include={"name", "grade", "attempts", "falls", "hangs", "style", "belay", "notes"}, exclude_none=True)
    raw["isTest"] = command.is_test
    for key, value in (("reachedTop", command.reached_top), ("cleanAscent", command.clean_ascent)):
        if value is not None:
            raw[key] = value
    if route:
        raw.update(routeId=route.id, name=route.name)
    attempt = await _attempt(session, training, area, section, raw, force_test=user.test_mode_enabled)
    return {"trainingId": training.id, "attempt": AttemptResponse.model_validate(attempt).model_dump(mode="json")}
