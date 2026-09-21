from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ExternalRef, Gear, Location, Route, RouteAttempt, Section, TrainingSession,
    TrainingStatus, User,
)
from app.schemas import AttemptCreate, FinishTraining, JournalSnapshot, TrainingCreate, UserResolveRequest


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _sync_refs(
    session: AsyncSession, entity_type: str, owner_id: str, refs: object
) -> None:
    owner_field = {
        "user": "user_id", "location": "location_id", "section": "section_id", "route": "route_id"
    }[entity_type]
    for raw in refs if isinstance(refs, list) else []:
        if not isinstance(raw, dict) or not raw.get("system") or not raw.get("id"):
            continue
        ref = await session.scalar(select(ExternalRef).where(
            ExternalRef.system == str(raw["system"]),
            ExternalRef.entity_type == entity_type,
            ExternalRef.external_id == str(raw["id"]),
        ))
        if ref is None:
            ref = ExternalRef(
                system=str(raw["system"]), entity_type=entity_type,
                external_id=str(raw["id"]), url=raw.get("url"),
            )
            setattr(ref, owner_field, owner_id)
            session.add(ref)
        elif getattr(ref, owner_field) == owner_id and raw.get("url"):
            ref.url = str(raw["url"])


async def sync_journal_snapshot(session: AsyncSession, snapshot: JournalSnapshot) -> dict:
    """Idempotently mirror the plugin's current JSON snapshot into PostgreSQL."""
    counts = {name: 0 for name in ("users", "locations", "sections", "routes", "gear", "trainings", "attempts")}

    for raw in snapshot.users:
        if not raw.get("id") or not raw.get("name"):
            continue
        item = await session.get(User, str(raw["id"]))
        if item is None:
            item = User(id=str(raw["id"]), name=str(raw["name"]))
            session.add(item)
        else:
            item.name = str(raw["name"])
        if raw.get("createdAt"):
            item.created_at = _datetime(raw["createdAt"]) or item.created_at
        await _sync_refs(session, "user", item.id, raw.get("externalRefs"))
        counts["users"] += 1
    await session.flush()

    for raw in snapshot.areas:
        if not raw.get("id") or not raw.get("name"):
            continue
        item = await session.get(Location, str(raw["id"]))
        values = {
            "type": "outdoor", "name": str(raw["name"]), "country": raw.get("country"),
            "latitude": raw.get("latitude"), "longitude": raw.get("longitude"),
        }
        if item is None:
            item = Location(id=str(raw["id"]), **values)
            session.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
        if raw.get("createdAt"):
            item.created_at = _datetime(raw["createdAt"]) or item.created_at
        await _sync_refs(session, "location", item.id, raw.get("externalRefs"))
        counts["locations"] += 1
    await session.flush()

    for raw in snapshot.sectors:
        if not raw.get("id") or not raw.get("areaId") or not raw.get("name"):
            continue
        item = await session.get(Section, str(raw["id"]))
        values = {"location_id": str(raw["areaId"]), "type": "sector", "name": str(raw["name"])}
        if item is None:
            item = Section(id=str(raw["id"]), **values)
            session.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
        if raw.get("createdAt"):
            item.created_at = _datetime(raw["createdAt"]) or item.created_at
        await _sync_refs(session, "section", item.id, raw.get("externalRefs"))
        counts["sections"] += 1
    await session.flush()

    for raw in snapshot.routes:
        if not raw.get("id") or not raw.get("sectorId") or not raw.get("name"):
            continue
        item = await session.get(Route, str(raw["id"]))
        values = {"section_id": str(raw["sectorId"]), "name": str(raw["name"]), "grade": raw.get("grade")}
        if item is None:
            item = Route(id=str(raw["id"]), **values)
            session.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
        if raw.get("createdAt"):
            item.created_at = _datetime(raw["createdAt"]) or item.created_at
        await _sync_refs(session, "route", item.id, raw.get("externalRefs"))
        counts["routes"] += 1
    await session.flush()

    for raw in snapshot.gear:
        if not raw.get("id") or not raw.get("userId") or not raw.get("type"):
            continue
        item = await session.get(Gear, str(raw["id"]))
        attributes = {"nickname": raw.get("nickname")} if raw.get("nickname") else {}
        values = {
            "user_id": str(raw["userId"]), "type": str(raw["type"]), "brand": raw.get("brand"),
            "model": raw.get("model"), "size": raw.get("size"), "active": raw.get("active", True),
            "notes": raw.get("notes"), "attributes": attributes,
        }
        if item is None:
            item = Gear(id=str(raw["id"]), **values)
            session.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
        if raw.get("createdAt"):
            item.created_at = _datetime(raw["createdAt"]) or item.created_at
        counts["gear"] += 1
    await session.flush()

    skipped: list[str] = []
    for raw in snapshot.trainings:
        training_id, user_id, local_date = raw.get("id"), raw.get("userId"), raw.get("date")
        if not training_id or not user_id or not local_date:
            skipped.append(str(training_id or "<missing-id>"))
            continue
        item = await session.scalar(
            select(TrainingSession)
            .options(selectinload(TrainingSession.sections), selectinload(TrainingSession.gear))
            .where(TrainingSession.id == str(training_id))
        )
        status_value = raw.get("status") if raw.get("status") in ("active", "completed") else "completed"
        environment = raw.get("environment") if raw.get("environment") in ("indoor", "outdoor", "unknown") else "unknown"
        values = {
            "user_id": str(user_id), "primary_location_id": raw.get("areaId"), "status": status_value,
            "local_date": datetime.fromisoformat(str(local_date)).date(), "timezone": "Europe/Moscow",
            "environment": environment, "duration_minutes": raw.get("durationMinutes"),
            "physical_state": raw.get("physicalState"), "notes": raw.get("notes"), "weather": raw.get("weather"),
            "completed_at": _datetime(raw.get("completedAt")),
        }
        if item is None:
            item = TrainingSession(id=str(training_id), **values)
            session.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
        if raw.get("createdAt"):
            item.created_at = _datetime(raw["createdAt"]) or item.created_at
        if raw.get("updatedAt"):
            item.updated_at = _datetime(raw["updatedAt"]) or item.updated_at
        item.sections = list((await session.scalars(select(Section).where(
            Section.id.in_([str(value) for value in raw.get("sectorIds", [])])
        ))).all()) if raw.get("sectorIds") else []
        item.gear = list((await session.scalars(select(Gear).where(
            Gear.id.in_([str(value) for value in raw.get("gearIds", [])])
        ))).all()) if raw.get("gearIds") else []
        await session.flush()
        await session.execute(delete(RouteAttempt).where(RouteAttempt.training_id == item.id))
        for sequence, attempt_raw in enumerate(raw.get("routes", []), start=1):
            if not isinstance(attempt_raw, dict):
                continue
            session.add(RouteAttempt(
                id=f"{item.id}_attempt_{sequence}", training_id=item.id,
                route_id=attempt_raw.get("routeId"), sequence=sequence,
                attempts=attempt_raw.get("attempts") or 1,
                result=attempt_raw.get("result") or "unknown", style=attempt_raw.get("style") or "unknown",
                belay=attempt_raw.get("belay") or "unknown", feel=attempt_raw.get("feel") or "unknown",
                notes=attempt_raw.get("notes"), route_snapshot=attempt_raw.get("routeSnapshot") or {},
            ))
            counts["attempts"] += 1
        counts["trainings"] += 1
    await session.flush()
    return {**counts, "skipped_training_ids": skipped}


async def resolve_user(session: AsyncSession, command: UserResolveRequest) -> User:
    ref = await session.scalar(
        select(ExternalRef).options(selectinload(ExternalRef.user)).where(
            ExternalRef.system == command.system,
            ExternalRef.entity_type == "user",
            ExternalRef.external_id == command.external_id,
        )
    )
    if ref:
        return ref.user
    user = User(name=command.name, timezone=command.timezone)
    user.external_refs.append(
        ExternalRef(system=command.system, entity_type="user", external_id=command.external_id)
    )
    session.add(user)
    await session.flush()
    return user


async def start_training(session: AsyncSession, user_id: str, command: TrainingCreate) -> TrainingSession:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    active = await session.scalar(
        select(TrainingSession).where(
            TrainingSession.user_id == user_id,
            TrainingSession.status == TrainingStatus.ACTIVE.value,
        ).with_for_update()
    )
    if active:
        active.status = TrainingStatus.COMPLETED.value
        active.completed_at = datetime.now(UTC)
        active.version += 1
    training = TrainingSession(
        user_id=user_id,
        local_date=command.date,
        timezone=user.timezone,
        environment=command.environment,
        notes=command.notes,
        attempts=[],
    )
    session.add(training)
    await session.flush()
    return training


async def list_trainings(session: AsyncSession, user_id: str) -> list[TrainingSession]:
    return list((await session.scalars(
        select(TrainingSession)
        .options(selectinload(TrainingSession.attempts))
        .where(TrainingSession.user_id == user_id)
        .order_by(TrainingSession.local_date.desc(), TrainingSession.created_at.desc())
    )).all())


async def append_attempt(
    session: AsyncSession, user_id: str, training_id: str, command: AttemptCreate
) -> RouteAttempt:
    training = await session.scalar(
        select(TrainingSession).where(
            TrainingSession.id == training_id,
            TrainingSession.user_id == user_id,
        ).with_for_update()
    )
    if not training:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training not found")
    if training.status != TrainingStatus.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Training is completed")
    last_sequence = await session.scalar(
        select(func.coalesce(func.max(RouteAttempt.sequence), 0)).where(RouteAttempt.training_id == training_id)
    )
    attempt = RouteAttempt(
        training_id=training_id,
        route_id=command.route_id,
        sequence=int(last_sequence) + 1,
        attempts=command.attempts,
        result=command.result,
        style=command.style,
        belay=command.belay,
        feel=command.feel,
        notes=command.notes,
        route_snapshot={"name": command.name, "grade": command.grade, "sectionId": command.section_id},
    )
    training.version += 1
    session.add(attempt)
    await session.flush()
    return attempt


async def finish_training(
    session: AsyncSession, user_id: str, training_id: str, command: FinishTraining
) -> TrainingSession:
    training = await session.scalar(
        select(TrainingSession).options(selectinload(TrainingSession.attempts)).where(
            TrainingSession.id == training_id,
            TrainingSession.user_id == user_id,
        ).with_for_update()
    )
    if not training:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training not found")
    if training.status == TrainingStatus.ACTIVE.value:
        training.status = TrainingStatus.COMPLETED.value
        training.completed_at = datetime.now(UTC)
        training.version += 1
    if command.duration_minutes is not None:
        training.duration_minutes = command.duration_minutes
    if command.physical_state is not None:
        training.physical_state = command.physical_state
    if command.notes is not None:
        training.notes = command.notes
    await session.flush()
    return training
