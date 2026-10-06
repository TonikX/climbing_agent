from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Response
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.idempotency import run_mutation
from app.schemas import (
    AttemptCreate, AttemptResponse, FinishTraining,
    ToolCommand, TrainingCreate, TrainingResponse, UserResponse, TelegramLogin, ProfileUpdate,
)
from app.tool_service import execute_tool, _get_trainings, _gear_dict
from app.security import current_auth_session, current_user_id, require_internal_key
from app.auth import telegram_login, user_payload
from app.models import AuthSession, Gear, TrainingSession, User
from app.service import (
    append_attempt, finish_training, list_trainings, start_training,
)

app = FastAPI(title="Climbing Journal API", version="0.1.0")
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[str, Depends(current_user_id)]
RequestKey = Annotated[str | None, Header(alias="Idempotency-Key")]
CurrentAuth = Annotated[AuthSession, Depends(current_auth_session)]


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
async def ready(session: Session) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ready"}


@app.post("/api/v1/tools/{operation}")
async def execute_tool_endpoint(operation: str, command: ToolCommand, session: Session, user_id: CurrentUser,
                                idempotency_key: RequestKey = None) -> dict:
    return await execute_tool(session, operation, user_payload(command.payload, user_id), idempotency_key)


@app.post("/api/v1/internal/auth/telegram", dependencies=[Depends(require_internal_key)])
async def telegram_login_endpoint(command: TelegramLogin, session: Session, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await telegram_login(session, command.telegram_id)


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(session: Session, auth: CurrentAuth):
    await session.delete(auth)


@app.post("/api/v1/auth/logout-all", status_code=204)
async def logout_all(session: Session, user_id: CurrentUser):
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


@app.get("/api/v1/me", response_model=UserResponse)
async def profile(session: Session, user_id: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(await session.get(User, user_id))


@app.patch("/api/v1/me", response_model=UserResponse)
async def update_profile(command: ProfileUpdate, session: Session, user_id: CurrentUser) -> UserResponse:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    for key, value in command.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await session.flush()
    return UserResponse.model_validate(user)


@app.get("/api/v1/me/export")
async def export_profile(session: Session, user_id: CurrentUser, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="climbing-journal.json"'
    user = await session.get(User, user_id)
    history = await _get_trainings(session, {"user": {"id": user_id}, "includeTest": True}, export_all=True)
    gear = list((await session.scalars(select(Gear).where(Gear.user_id == user_id))).all())
    return {"profile": UserResponse.model_validate(user).model_dump(), "testMode": user.test_mode_enabled,
            "trainings": history["trainings"], "gear": [_gear_dict(item) for item in gear]}


@app.delete("/api/v1/me", status_code=204)
async def delete_profile(session: Session, user_id: CurrentUser):
    await session.scalar(select(User).where(User.id == user_id).with_for_update())
    # Delete owned associations before gear (training_gear uses RESTRICT).
    await session.execute(delete(TrainingSession).where(TrainingSession.user_id == user_id))
    await session.execute(delete(Gear).where(Gear.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))


@app.post("/api/v1/trainings", response_model=TrainingResponse, status_code=201)
async def start_training_endpoint(command: TrainingCreate, session: Session, user_id: CurrentUser,
                                  idempotency_key: RequestKey = None) -> dict:
    async def action():
        result = await start_training(session, user_id, command)
        return TrainingResponse.model_validate(result).model_dump(mode="json")
    return await run_mutation(session, user_id, "rest:start", idempotency_key,
                              command.model_dump(mode="json"), action, 201)


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
    training_id: str, command: AttemptCreate, session: Session, user_id: CurrentUser,
    idempotency_key: RequestKey = None,
) -> dict:
    async def action():
        result = await append_attempt(session, user_id, training_id, command)
        return AttemptResponse.model_validate(result).model_dump(mode="json")
    return await run_mutation(session, user_id, f"rest:append:{training_id}", idempotency_key,
                              command.model_dump(mode="json", exclude_unset=True), action, 201)


@app.post("/api/v1/trainings/{training_id}/finish", response_model=TrainingResponse)
async def finish_training_endpoint(
    training_id: str, command: FinishTraining, session: Session, user_id: CurrentUser,
    idempotency_key: RequestKey = None,
) -> dict:
    async def action():
        result = await finish_training(session, user_id, training_id, command)
        return TrainingResponse.model_validate(result).model_dump(mode="json")
    return await run_mutation(session, user_id, f"rest:finish:{training_id}", idempotency_key,
                              command.model_dump(mode="json"), action)
