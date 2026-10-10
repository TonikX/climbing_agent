from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, get_control_session
from app.idempotency import run_mutation
from app.schemas import (
    AttemptCreate, AttemptResponse, FinishTraining,
    ToolCommand, TrainingCreate, TrainingResponse, TrainingPage, UserResponse, TelegramLogin, ProfileUpdate,
)
from app.tool_service import execute_tool, _get_trainings, _gear_dict
from app.security import current_auth_session, current_user_id, require_internal_key
from app.auth import telegram_login, user_payload
from app.models import AuthSession, ExternalRef, Gear, TrainingSession, User
from app.service import (
    append_attempt, finish_training, list_trainings, start_training,
)

app = FastAPI(title="Climbing Journal API", version="1.0.0-beta.1", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
from app.telemetry import requests as request_telemetry
app.middleware("http")(request_telemetry)
from app.public_api import router as public_router, internal as internal_router
app.include_router(public_router)
app.include_router(internal_router)
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]
CurrentUser = Annotated[str, Depends(current_user_id)]
RequestKey = Annotated[str | None, Header(alias="Idempotency-Key")]
CurrentAuth = Annotated[AuthSession, Depends(current_auth_session)]
ControlSession = Annotated[AsyncSession, Depends(get_control_session, scope="function")]


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
async def ready(session: Session, control: ControlSession) -> dict[str, str]:
    await session.execute(text("select 1"))
    from app.config import get_settings
    if get_settings().public_mode:
        cfg = get_settings()
        if not cfg.access_approver_telegram_id or not cfg.access_approver_telegram_id.isdigit() or cfg.access_approval_chat_id != cfg.access_approver_telegram_id:
            raise HTTPException(503, "Verified private approver chat required")
        if not get_settings().db_control_user or get_settings().db_control_user == get_settings().db_user:
            raise HTTPException(503, "Separate control/runtime roles required")
        role = (await session.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
        owner = await session.scalar(text("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public' AND pg_has_role(current_user,tableowner,'MEMBER'))"))
        rls = await session.scalar(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='training_sessions'::regclass"))
        if any(role) or owner or not rls:
            raise HTTPException(503, "Unsafe runtime database permissions")
        control_role = (await control.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
        if any(control_role):
            raise HTTPException(503, "Unsafe control database permissions")
        for connection in (session, control):
            inherited = await connection.scalar(text("""SELECT EXISTS(SELECT FROM pg_roles
                WHERE (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)
                AND pg_has_role(current_user,oid,'MEMBER'))"""))
            owns_tables = await connection.scalar(text("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public' AND pg_has_role(current_user,tableowner,'MEMBER'))"))
            if inherited or owns_tables:
                raise HTTPException(503, "Runtime roles inherit migration privileges")
        from app.models import Base
        tables = list(Base.metadata.tables)
        protected = await session.scalar(text("""SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace
            AND relname=ANY(CAST(:tables AS text[])) AND relrowsecurity AND relforcerowsecurity"""), {"tables": tables})
        if protected != len(tables):
            raise HTTPException(503, "Row security is incomplete")
        approver = await control.scalar(select(User.id).join(ExternalRef, ExternalRef.user_id == User.id).where(
            User.status == "active", User.role == "admin", ExternalRef.system == "telegram",
            ExternalRef.entity_type == "user", ExternalRef.external_id == cfg.access_approver_telegram_id))
        if not approver:
            raise HTTPException(503, "Configured approver has not been verified and activated")
    return {"status": "ready"}


@app.post("/api/v1/tools/{operation}", include_in_schema=False)
async def execute_tool_endpoint(operation: str, command: ToolCommand, session: Session, user_id: CurrentUser,
                                idempotency_key: RequestKey = None) -> dict:
    from app.config import get_settings
    if get_settings().public_mode:
        raise HTTPException(404, "Use the typed API")
    return await execute_tool(session, operation, user_payload(command.payload, user_id), idempotency_key)


@app.post("/api/v1/internal/auth/telegram", dependencies=[Depends(require_internal_key)], include_in_schema=False)
async def telegram_login_endpoint(command: TelegramLogin, session: ControlSession, response: Response) -> dict:
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
async def export_profile(session: ControlSession, user_id: CurrentUser, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="climbing-journal.json"'
    from app.profile_service import ProfileService
    return await ProfileService.export(session, user_id)


@app.delete("/api/v1/me", status_code=204)
async def delete_profile(session: ControlSession, user_id: CurrentUser, confirmation: str = Query(min_length=1)):
    from app.public_api import consume_deletion
    await consume_deletion(session, user_id, confirmation)


@app.post("/api/v1/trainings", response_model=TrainingResponse, status_code=201)
async def start_training_endpoint(command: TrainingCreate, session: Session, user_id: CurrentUser,
                                  idempotency_key: RequestKey = None) -> dict:
    async def action():
        result = await start_training(session, user_id, command)
        return TrainingResponse.model_validate(result).model_dump(mode="json")
    return await run_mutation(session, user_id, "rest:start", idempotency_key,
                              command.model_dump(mode="json"), action, 201)


@app.get("/api/v1/trainings", response_model=TrainingPage)
async def list_trainings_endpoint(
    session: Session,
    user_id: CurrentUser,
    include_test: bool = Query(default=False),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> TrainingPage:
    rows = await list_trainings(session, user_id, include_test=include_test, cursor=cursor, limit=limit+1)
    return TrainingPage(items=[TrainingResponse.model_validate(item) for item in rows[:limit]],
                        next_cursor=rows[limit-1].id if len(rows)>limit else None)


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
    training_id: str, command: FinishTraining, session: ControlSession, user_id: CurrentUser,
    idempotency_key: RequestKey = None,
) -> dict:
    from app.db import set_user_context
    await set_user_context(session, user_id)
    async def action():
        from app.public_models import Job
        pending = list((await session.scalars(select(Job).where(
            Job.user_id == user_id, Job.training_id == training_id, Job.lane == "ai",
            Job.status.in_(["pending", "processing"])).with_for_update())).all())
        if pending and not command.cancel_pending:
            raise HTTPException(409, "Wait for pending messages or set cancel_pending=true")
        for job in pending:
            job.status = "cancelled"
            job.lease_until = None
        result = await finish_training(session, user_id, training_id, command)
        return TrainingResponse.model_validate(result).model_dump(mode="json")
    return await run_mutation(session, user_id, f"rest:finish:{training_id}", idempotency_key,
                              command.model_dump(mode="json"), action)
