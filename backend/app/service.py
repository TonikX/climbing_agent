from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ExternalRef, RouteAttempt, TrainingSession, TrainingStatus, User
from app.schemas import AttemptCreate, FinishTraining, TrainingCreate, UserResolveRequest


async def resolve_user(session: AsyncSession, command: UserResolveRequest) -> User:
    ref = await session.scalar(
        select(ExternalRef).options(selectinload(ExternalRef.user)).where(
            ExternalRef.system == command.system,
            ExternalRef.external_id == command.external_id,
        )
    )
    if ref:
        return ref.user
    user = User(name=command.name, timezone=command.timezone)
    user.external_refs.append(ExternalRef(system=command.system, external_id=command.external_id))
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
