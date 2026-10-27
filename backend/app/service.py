from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.models import ExternalRef, Location, RouteAttempt, Section, TrainingSession, TrainingStatus, User
from app.tool_service import _attempt, _user, _visible, _gear_ids
from app.schemas import AttemptCreate, FinishTraining, TrainingCreate, UserResolveRequest

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
    user = await _user(session, {"id": user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    active = await session.scalar(
        select(TrainingSession).where(
            TrainingSession.user_id == user_id,
            TrainingSession.status == TrainingStatus.ACTIVE.value,
        ).with_for_update()
    )
    if active:
        raise HTTPException(409, "Finish the current training before starting another")
    location = await session.get(Location, command.location_id) if command.location_id else None
    section = await session.get(Section, command.section_id) if command.section_id else None
    if command.location_id and not location or command.section_id and not section:
        raise HTTPException(404, "Catalogue item not found")
    await _visible(session, location)
    await _visible(session, section)
    if section:
        if location and section.location_id != location.id:
            raise HTTPException(422, "Section belongs to another location")
        location = location or await session.get(Location, section.location_id)
    training = TrainingSession(
        primary_location_id=location.id if location else None,
        sections=[section] if section else [],
        gear=await _gear_ids(session, user_id, command.gear_ids),
        started_at=datetime.now(UTC),
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

async def list_trainings(
    session: AsyncSession, user_id: str, include_test: bool = False, cursor: str | None = None, limit: int = 50,
    date_from: date | None = None, date_to: date | None = None, region: str | None = None,
    area_id: str | None = None, grade: str | None = None,
) -> list[TrainingSession]:
    query = select(TrainingSession).options(selectinload(TrainingSession.attempts))
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    if date_from:
        query = query.where(TrainingSession.local_date >= date_from)
    if date_to:
        query = query.where(TrainingSession.local_date <= date_to)
    if region or area_id or grade:
        from app.training_places import attempt_filters
        matching = select(RouteAttempt.id).where(RouteAttempt.training_id == TrainingSession.id,
            attempt_filters(region=region, area_id=area_id, grade=grade, include_test=include_test)).correlate(TrainingSession).exists()
        query = query.where(matching)
    if cursor:
        anchor = await session.scalar(select(TrainingSession).where(TrainingSession.id == cursor, TrainingSession.user_id == user_id))
        if not anchor:
            raise HTTPException(404, "Training cursor not found")
        query = query.where(tuple_(TrainingSession.local_date, TrainingSession.created_at, TrainingSession.id) <
                            tuple_(anchor.local_date, anchor.created_at, anchor.id))
    if not include_test:
        from app.training_visibility import not_test_only
        query = query.where(not_test_only())
        query = query.options(
            with_loader_criteria(RouteAttempt, RouteAttempt.is_test.is_(False), include_aliases=True)
        )
    return list((await session.scalars(
        query
        .where(TrainingSession.user_id == user_id)
        .order_by(TrainingSession.local_date.desc(), TrainingSession.created_at.desc(), TrainingSession.id.desc()).limit(limit)
    )).all())


async def edit_training(session: AsyncSession, user_id: str, training_id: str, command) -> TrainingSession:
    training = await session.scalar(select(TrainingSession).where(
        TrainingSession.id == training_id, TrainingSession.user_id == user_id
    ).options(selectinload(TrainingSession.attempts)).with_for_update())
    if not training:
        raise HTTPException(404, "Training not found")
    if training.version != command.expected_version:
        raise HTTPException(409, "Training changed; reload before editing")
    changes = command.model_dump(exclude_unset=True, exclude={"expected_version"})
    if not changes:
        raise HTTPException(422, "Specify at least one changed field")
    for field, value in changes.items():
        setattr(training, "local_date" if field == "date" else field, value)
    training.version += 1
    await session.flush()
    return training


async def append_attempt(
    session: AsyncSession, user_id: str, training_id: str, command: AttemptCreate
) -> RouteAttempt:
    await _user(session, {"id": user_id})
    training = await session.scalar(
        select(TrainingSession).options(selectinload(TrainingSession.sections)).where(
            TrainingSession.id == training_id,
            TrainingSession.user_id == user_id,
        ).with_for_update()
    )
    if not training:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training not found")
    if training.status != TrainingStatus.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Training is completed")
    raw = command.model_dump(exclude_unset=True)
    for old, new in (("reached_top", "reachedTop"), ("clean_ascent", "cleanAscent"),
                     ("route_id", "routeId"), ("is_test", "isTest")):
        if old in raw: raw[new] = raw.pop(old)
    section = await session.get(Section, command.section_id) if command.section_id else None
    if command.section_id and not section:
        raise HTTPException(404, "Section not found")
    await _visible(session, section)
    area = await session.get(Location, training.primary_location_id) if training.primary_location_id else None
    user = await _user(session, {"id": user_id})
    return await _attempt(session, training, area, section, raw, force_test=user.test_mode_enabled)


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


async def resume_training(session: AsyncSession, user_id: str, training_id: str,
                          expected_version: int) -> TrainingSession:
    # All entry points share the user lock with start/finish and Telegram jobs.
    await session.scalar(select(User).where(User.id == user_id).with_for_update())
    training = await session.scalar(select(TrainingSession).options(selectinload(TrainingSession.attempts)).where(
        TrainingSession.user_id == user_id, TrainingSession.id == training_id).with_for_update())
    if not training:
        raise HTTPException(404, "Training not found")
    if training.version != expected_version:
        raise HTTPException(409, "Training changed; refresh before resuming")
    active = await session.scalar(select(TrainingSession.id).where(
        TrainingSession.user_id == user_id, TrainingSession.status == "active"))
    if active:
        raise HTTPException(409, "Finish the current training before resuming another")
    latest = await session.scalar(select(TrainingSession.id).where(
        TrainingSession.user_id == user_id, TrainingSession.status == "completed").order_by(
            TrainingSession.local_date.desc(), TrainingSession.created_at.desc(), TrainingSession.id.desc()).limit(1))
    if latest != training.id or training.status != "completed":
        raise HTTPException(409, "Only the last completed training can be resumed")
    training.status = "active"
    training.completed_at = None
    # Recompute elapsed duration from the original start, including the pause.
    training.duration_minutes = None
    training.version += 1
    await session.flush()
    return training
