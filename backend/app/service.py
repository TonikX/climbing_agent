from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.models import ExternalRef, Location, RouteAttempt, Section, TrainingSession, TrainingStatus, User
from app.tool_service import _attempt
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

async def list_trainings(
    session: AsyncSession, user_id: str, include_test: bool = False
) -> list[TrainingSession]:
    query = select(TrainingSession).options(selectinload(TrainingSession.attempts))
    if not include_test:
        query = query.options(
            with_loader_criteria(RouteAttempt, RouteAttempt.is_test.is_(False), include_aliases=True)
        )
    return list((await session.scalars(
        query
        .where(TrainingSession.user_id == user_id)
        .order_by(TrainingSession.local_date.desc(), TrainingSession.created_at.desc())
    )).all())


async def append_attempt(
    session: AsyncSession, user_id: str, training_id: str, command: AttemptCreate
) -> RouteAttempt:
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
    area = await session.get(Location, training.primary_location_id) if training.primary_location_id else None
    user = await session.get(User, user_id)
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
