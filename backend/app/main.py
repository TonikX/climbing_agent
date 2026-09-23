from typing import Annotated

from fastapi import Depends, FastAPI, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import (
    AttemptCreate, AttemptResponse, FinishTraining,
    ToolCommand, TrainingCreate, TrainingResponse, UserResolveRequest, UserResponse,
)
from app.tool_service import execute_tool
from app.security import current_user_id, require_internal_key
from app.service import (
    append_attempt, finish_training, list_trainings, resolve_user, start_training,
)

app = FastAPI(title="Climbing Journal API", version="0.1.0")
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[str, Depends(current_user_id)]


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
async def ready(session: Session) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ready"}


@app.post("/api/v1/tools/{operation}", dependencies=[Depends(require_internal_key)])
async def execute_tool_endpoint(operation: str, command: ToolCommand, session: Session) -> dict:
    return await execute_tool(session, operation, command.payload)


@app.post("/api/v1/users/resolve", response_model=UserResponse, dependencies=[Depends(require_internal_key)])
async def resolve_user_endpoint(command: UserResolveRequest, session: Session) -> UserResponse:
    return UserResponse.model_validate(await resolve_user(session, command))


@app.post("/api/v1/trainings", response_model=TrainingResponse, status_code=201)
async def start_training_endpoint(command: TrainingCreate, session: Session, user_id: CurrentUser) -> TrainingResponse:
    return TrainingResponse.model_validate(await start_training(session, user_id, command))


@app.get("/api/v1/trainings", response_model=list[TrainingResponse])
async def list_trainings_endpoint(
    session: Session,
    user_id: CurrentUser,
    include_test: bool = Query(default=False),
) -> list[TrainingResponse]:
    return [
        TrainingResponse.model_validate(item)
        for item in await list_trainings(session, user_id, include_test=include_test)
    ]


@app.post("/api/v1/trainings/{training_id}/attempts", response_model=AttemptResponse, status_code=201)
async def append_attempt_endpoint(
    training_id: str, command: AttemptCreate, session: Session, user_id: CurrentUser
) -> AttemptResponse:
    return AttemptResponse.model_validate(await append_attempt(session, user_id, training_id, command))


@app.post("/api/v1/trainings/{training_id}/finish", response_model=TrainingResponse)
async def finish_training_endpoint(
    training_id: str, command: FinishTraining, session: Session, user_id: CurrentUser
) -> TrainingResponse:
    return TrainingResponse.model_validate(await finish_training(session, user_id, training_id, command))
