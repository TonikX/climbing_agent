from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import jobs
from app.db import get_control_session, get_session
from app.models import ExternalRef, Gear, Location, Route, RouteAttempt, Section, TrainingSession, User
from app.public_models import Job, Outbox, TelegramUpdate, UpdateReceipt
from app.public_schemas import Claim, Completion, Failure, AttemptPatch, TrainingPatch, GearWrite, TestMode, LocationWrite, SectionWrite, RouteWrite, GearPatch, CatalogPatch, SummaryCreate, AccountBlock, StatisticsDTO
from app.security import current_user_id, require_internal_key
from app.auth import user_payload
from app.telegram_actions import complete
from app.tool_service import _area, _area_dict, _get_current, _route, _route_dict, _section, _section_dict, _statistics, _user, _visible, _writable, _gear_dict, execute_tool
from app.profile_service import ProfileService
from app.idempotency import run_mutation
from app.application_services import StatisticsService, TrainingService

router = APIRouter(prefix="/api/v1")
internal = APIRouter(prefix="/api/v1/internal", dependencies=[Depends(require_internal_key)], include_in_schema=False)
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]
Control = Annotated[AsyncSession, Depends(get_control_session, scope="function")]
UserId = Annotated[str, Depends(current_user_id)]
Key = Annotated[str | None, Header(alias="Idempotency-Key")]


async def own_telegram_id(session, uid):
    tid = await session.scalar(select(ExternalRef.external_id).where(ExternalRef.user_id == uid,
        ExternalRef.system == "telegram", ExternalRef.entity_type == "user"))
    if not tid:
        raise HTTPException(409, "Telegram identity missing")
    return tid


@router.post("/exports", status_code=202)
async def export_request(session: Control, uid: UserId):
    tid = await own_telegram_id(session, uid)
    job = Job(user_id=uid, lane="fast", payload={"command": "profile:export", "telegram_id": tid,
                                                "chat_id": tid, "mutation": False})
    session.add(job)
    await session.flush()
    return {"job_id": job.id}


@router.get("/exports/{job_id}")
async def export_status(job_id: str, session: Control, uid: UserId):
    job = await session.scalar(select(Job).where(Job.id == job_id, Job.user_id == uid))
    if not job or job.payload.get("command") != "profile:export":
        raise HTTPException(404, "Export not found")
    return {"job_id": job.id, "status": job.status}


@router.post("/account-deletion")
async def deletion_request(session: Control, uid: UserId):
    tid = await own_telegram_id(session, uid)
    job = Job(user_id=uid, lane="fast", status="succeeded", payload={"command": "profile:delete", "telegram_id": tid,
              "chat_id": tid, "mutation": False}, result={"delete_confirmation": True})
    session.add(job)
    await session.flush()
    return {"confirmation": job.id, "expires_in": 300, "warning": "Permanently delete your account and journal"}


async def consume_deletion(session, uid, confirmation):
    from datetime import timedelta
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    job = await session.scalar(select(Job).where(Job.id == confirmation, Job.user_id == uid).with_for_update())
    if not job or job.created_at < jobs.now()-timedelta(minutes=5) or not (job.result or {}).get("delete_confirmation"):
        raise HTTPException(409, "Deletion confirmation expired")
    await ProfileService.delete(session, uid, await own_telegram_id(session, uid))


@router.post("/training-summaries")
async def summary_create(command: SummaryCreate, session: Session, uid: UserId, key: Key = None):
    from app.db import set_user_context
    await set_user_context(session, uid)
    routes = []
    for item in command.routes:
        raw = item.model_dump(exclude_unset=True)
        for old, new in (("route_id", "routeId"), ("reached_top", "reachedTop"), ("clean_ascent", "cleanAscent"), ("is_test", "isTest")):
            if old in raw:
                raw[new] = raw.pop(old)
        routes.append(raw)
    payload = {"date": command.date.isoformat(), "routes": routes, "durationMinutes": command.duration_minutes, "notes": command.notes}
    if command.location_id:
        payload["area"] = {"id": command.location_id}
    if command.section_id:
        payload["sector"] = {"id": command.section_id}
    payload["mergeIntoActive"] = command.merge_into_active
    async def action():
        if command.merge_into_active:
            from app.tool_service import _active
            active = await _active(session, uid)
            if not active or command.expected_version is None:
                raise HTTPException(409, "Active training and expected_version are required for a merge")
            await versioned_training(session, uid, active.id, command.expected_version)
        return await execute_tool(session, "save_climbing_training", user_payload(payload, uid))
    return await run_mutation(session, uid, "rest:summary", key, command.model_dump(mode="json", exclude_unset=True), action)


@router.patch("/gear/{gear_id}")
async def gear_patch(gear_id: str, command: GearPatch, session: Session, uid: UserId):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    gear = await session.scalar(select(Gear).where(Gear.id == gear_id, Gear.user_id == uid).with_for_update())
    if not gear:
        raise HTTPException(404, "Gear not found")
    for key, value in command.model_dump(exclude_unset=True).items():
        if key == "active" and value is None:
            raise HTTPException(422, "active cannot be null")
        setattr(gear, key, value)
    return _gear_dict(gear)


@router.delete("/gear/{gear_id}")
async def gear_remove(gear_id: str, session: Session, uid: UserId):
    from app.models import training_gear
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    gear = await session.scalar(select(Gear).where(Gear.id == gear_id, Gear.user_id == uid).with_for_update())
    if not gear:
        raise HTTPException(404, "Gear not found")
    if await session.scalar(select(training_gear.c.gear_id).where(training_gear.c.gear_id == gear_id).limit(1)):
        raise HTTPException(409, "Gear is used in training history; mark it inactive")
    await session.delete(gear)
    return {"deleted": True}


@router.get("/catalog/{kind}/{item_id}")
async def catalog_get(kind: Literal["locations", "sections", "routes"], item_id: str, session: Session, uid: UserId):
    model, formatter = {"locations": (Location, _area_dict), "sections": (Section, _section_dict), "routes": (Route, _route_dict)}[kind]
    item = await session.get(model, item_id)
    if not item:
        raise HTTPException(404, "Catalogue item not found")
    await _visible(session, item)
    return formatter(item)


@router.patch("/catalog/{kind}/{item_id}")
async def catalog_patch(kind: Literal["locations", "sections", "routes"], item_id: str, command: CatalogPatch, session: Session, uid: UserId):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    model, formatter = {"locations": (Location, _area_dict), "sections": (Section, _section_dict), "routes": (Route, _route_dict)}[kind]
    item = await session.get(model, item_id, with_for_update=True)
    if not item:
        raise HTTPException(404, "Catalogue item not found")
    await _writable(session, item)
    changes = command.model_dump(exclude_unset=True)
    allowed = {"name", "country"} if kind == "locations" else {"name", "grade"} if kind == "routes" else {"name"}
    if set(changes) - allowed or changes.get("name", "ok") is None:
        raise HTTPException(422, "Invalid catalogue fields")
    for key, value in changes.items():
        setattr(item, key, value)
    return formatter(item)


async def owner_admin(session, uid):
    from app.access import require_approver
    from app.config import get_settings
    actor = await session.get(User, uid)
    await require_approver(session, actor, await own_telegram_id(session, uid), get_settings().access_approval_chat_id or "")
    return actor


@router.get("/admin/access-requests")
async def access_list(session: Control, uid: UserId, cursor: str | None = None, limit: int = Query(20, ge=1, le=100)):
    from app.public_models import AccessRequest
    await owner_admin(session, uid)
    query = select(AccessRequest).where(AccessRequest.status == "pending")
    if cursor:
        query = query.where(AccessRequest.id > cursor)
    rows = list((await session.scalars(query.order_by(AccessRequest.id).limit(limit+1))).all())
    return {"items": [{"id": x.id, "user_id": x.user_id, "status": x.status, "created_at": x.created_at} for x in rows[:limit]],
            "next_cursor": rows[limit-1].id if len(rows)>limit else None}


@router.post("/admin/users/{target_id}/block")
async def block_user(target_id: str, command: AccountBlock, session: Control, uid: UserId):
    from sqlalchemy import update
    from app.public_models import AccessRequest, AuditEvent
    await owner_admin(session, uid)
    target = await session.scalar(select(User).where(User.id == target_id).with_for_update())
    if not target or target_id == uid:
        raise HTTPException(404, "User not found")
    target.status = "blocked" if command.blocked else "pending_approval"
    await session.execute(update(AccessRequest).where(AccessRequest.user_id == target_id, AccessRequest.status == "pending")
                          .values(status="rejected", decided_at=jobs.now(), decided_by=uid))
    for model in (Job, Outbox):
        await session.execute(update(model).where(model.user_id == target_id, model.status.in_(["pending", "processing"]))
                              .values(status="cancelled", worker_id=None, lease_until=None))
    session.add(AuditEvent(actor_id=uid, action="user:block" if command.blocked else "user:reset-access", subject_id=target_id))
    return {"status": target.status}


@router.get("/admin/metrics")
async def admin_metrics(session: Control, uid: UserId):
    await owner_admin(session, uid)
    result = {"users": await session.scalar(select(func.count(User.id)))}
    for model in (Job, Outbox):
        result[model.__tablename__] = [{"status": status, "count": count} for status, count in
                (await session.execute(select(model.status, func.count(model.id)).group_by(model.status))).all()]
        oldest = await session.scalar(select(func.min(model.created_at)).where(model.status.in_(["pending", "processing"])))
        result[model.__tablename__+"_oldest_age_seconds"] = (jobs.now()-oldest).total_seconds() if oldest else 0
    from app.telemetry import metrics
    from app.public_models import Usage
    from app.db import engine, control_engine
    result["http"] = metrics()
    result["db_pool"] = {"data_checked_out": engine.pool.checkedout(), "control_checked_out": control_engine.pool.checkedout()}
    global_usage = await session.scalar(select(Usage).where(Usage.scope == "global", Usage.day == jobs.now().strftime("%Y-%m-%d")))
    result["reserved_ai_kopecks_today"] = global_usage.budget_units if global_usage else 0
    result["alerts"] = [name+"_delayed" for name in ("jobs", "outbox") if result[name+"_oldest_age_seconds"] > 300]
    return result


@internal.post("/telegram/updates")
async def receive(raw: dict, session: Control):
    from aiogram.types import Update
    from pydantic import ValidationError
    try:
        update = Update.model_validate(raw)
    except ValidationError:
        raise HTTPException(422, "Invalid Telegram update")
    from app.config import get_settings
    existing = await session.scalar(select(UpdateReceipt.update_id).where(UpdateReceipt.bot_id == get_settings().telegram_bot_id,
                                                                         UpdateReceipt.update_id == update.update_id))
    if existing:
        return {"accepted": True, "duplicate": True}
    # Database uniqueness is the final guard if two receivers race.
    from sqlalchemy.exc import IntegrityError
    try:
        async with session.begin_nested():
            return await jobs.ingest(session, raw)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        return {"accepted": True, "duplicate": True}


@internal.post("/jobs/claim")
async def claim(command: Claim, session: Control):
    return {"item": await jobs.claim(session, command.lane, command.worker_id)}


@internal.post("/jobs/{lane}/{item_id}/heartbeat")
async def heartbeat(lane: Literal["fast", "ai", "delivery"], item_id: str, command: Completion, session: Control):
    from datetime import timedelta
    item = await jobs.leased(session, lane, item_id, command.worker_id)
    if lane == "ai":
        active = await session.scalar(select(User.status).where(User.id == item.user_id))
        if active != "active":
            raise HTTPException(403, "AI access revoked")
    item.lease_until = jobs.now() + timedelta(seconds=120)
    return {"ok": True}


@internal.post("/jobs/{lane}/{item_id}/complete")
async def finish_job(lane: Literal["fast", "ai", "delivery"], item_id: str, command: Completion, session: Control):
    if lane != "delivery":
        uid = await session.scalar(select(Job.user_id).where(Job.id == item_id))
        await session.scalar(select(User).where(User.id == uid).with_for_update())
    item = await jobs.leased(session, lane, item_id, command.worker_id)
    if lane == "delivery":
        item.telegram_message_id = command.telegram_message_id
        item.status, item.worker_id, item.lease_until = "succeeded", None, None
    else:
        if item.lane != lane or (lane == "ai" and command.intent is None) or (lane == "fast" and command.intent is not None):
            raise HTTPException(422, "Invalid completion lane")
        try:
            async with session.begin_nested():
                await complete(session, item, command.intent, command.tokens)
                await session.flush()
        except HTTPException:
            await jobs.fail(session, lane, item_id, command.worker_id, "validation_failed", 0)
    return {"ok": True}


@internal.post("/jobs/{lane}/{item_id}/fail")
async def fail_job(lane: Literal["fast", "ai", "delivery"], item_id: str, command: Failure, session: Control):
    if lane != "delivery":
        uid = await session.scalar(select(Job.user_id).where(Job.id == item_id))
        await session.scalar(select(User).where(User.id == uid).with_for_update())
    await jobs.fail(session, lane, item_id, command.worker_id, command.code, command.retry_seconds)
    return {"ok": True}


@internal.post("/maintenance/retention")
async def retention(session: Control):
    await jobs.cleanup(session)
    return {"ok": True}


@router.get("/trainings/current")
async def current_training(session: Session, uid: UserId, detail: Literal["summary", "full"] = "summary"):
    return await TrainingService.current(session, {"user": {"id": uid}, "detail": detail})


@router.get("/trainings/{training_id}")
async def training(training_id: str, session: Session, uid: UserId, include_test: bool = False):
    from app.schemas import TrainingResponse
    item = await session.scalar(select(TrainingSession).options(selectinload(TrainingSession.attempts)).where(
        TrainingSession.user_id == uid, TrainingSession.id == training_id))
    if not item:
        raise HTTPException(404, "Training not found")
    dto = TrainingResponse.model_validate(item).model_dump(mode="json")
    if not include_test:
        dto["attempts"] = [x for x in dto["attempts"] if not x["is_test"]]
    return dto


@router.get("/statistics/trainings/last", response_model=StatisticsDTO, response_model_exclude_unset=True)
async def last_training(session: Session, uid: UserId, detail: Literal["summary", "full"] = "summary"):
    return await StatisticsService.read(session, {"user": {"id": uid}, "scope": "last_training", "detail": detail})


@router.get("/statistics/current-training", response_model=StatisticsDTO, response_model_exclude_unset=True)
async def current_statistics(session: Session, uid: UserId):
    return await TrainingService.current(session, {"user": {"id": uid}})


@router.get("/statistics/{scope}", response_model=StatisticsDTO, response_model_exclude_unset=True)
async def stats(scope: Literal["week", "month", "progress", "grades", "locations", "projects", "records"],
                session: Session, uid: UserId, date_from: str | None = None, date_to: str | None = None,
                grade: str | None = Query(default=None, max_length=30)):
    return await StatisticsService.read(session, {"user": {"id": uid}, "scope": scope, "dateFrom": date_from, "dateTo": date_to, "grade": grade})


async def versioned_training(session, uid, training_id, expected):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    item = await session.scalar(select(TrainingSession).where(TrainingSession.id == training_id,
                                TrainingSession.user_id == uid).with_for_update())
    if not item:
        raise HTTPException(404, "Training not found")
    if item.version != expected:
        raise HTTPException(409, "Training changed; refresh before editing")
    return item


@router.patch("/trainings/{training_id}")
async def patch_training(training_id: str, command: TrainingPatch, session: Session, uid: UserId, key: Key = None):
    async def action():
        item = await versioned_training(session, uid, training_id, command.expected_version)
        for key, value in command.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
            if key == "environment" and value is None:
                raise HTTPException(422, "environment cannot be null")
            setattr(item, key, value)
        item.version += 1
        return {"id": item.id, "version": item.version}
    return await run_mutation(session, uid, f"rest:patch-training:{training_id}", key,
                              command.model_dump(mode="json", exclude_unset=True), action)



@router.patch("/attempts/{attempt_id}")
async def patch_attempt(attempt_id: str, command: AttemptPatch, session: Session, uid: UserId, key: Key = None):
    async def action():
        item = await session.scalar(select(RouteAttempt).join(TrainingSession).where(RouteAttempt.id == attempt_id,
                                                          TrainingSession.user_id == uid))
        if not item:
            raise HTTPException(404, "Attempt not found")
        await versioned_training(session, uid, item.training_id, command.expected_version)
        raw = command.model_dump(exclude_unset=True, exclude={"expected_version"})
        for snake, camel in (("reached_top", "reachedTop"), ("clean_ascent", "cleanAscent"), ("is_test", "isTest")):
            if snake in raw:
                raw[camel] = raw.pop(snake)
        if raw.get("hangs"):
            raw["cleanAscent"] = False
            raw["notes"] = (raw.get("notes") or item.notes or "") + "; зависание"
        for required in ("style", "belay", "isTest"):
            if required in raw and raw[required] is None:
                raise HTTPException(422, f"{required} cannot be null")
        return await execute_tool(session, "update_climbing_attempt", user_payload({"attemptId": attempt_id, **raw}, uid))
    return await run_mutation(session, uid, f"rest:patch-attempt:{attempt_id}", key,
                              command.model_dump(mode="json", exclude_unset=True), action)



@router.delete("/attempts/{attempt_id}")
async def remove_attempt(attempt_id: str, session: Session, uid: UserId, expected_version: int = Query(ge=1), key: Key = None):
    async def action():
        item = await session.scalar(select(RouteAttempt).join(TrainingSession).where(RouteAttempt.id == attempt_id,
                                                          TrainingSession.user_id == uid))
        if not item:
            raise HTTPException(404, "Attempt not found")
        training = await versioned_training(session, uid, item.training_id, expected_version)
        await session.delete(item)
        training.version += 1
        return {"deleted": True, "version": training.version}
    return await run_mutation(session, uid, f"rest:delete-attempt:{attempt_id}", key,
                              {"expected_version": expected_version}, action)



@router.put("/me/test-mode")
async def test_mode(command: TestMode, session: Session, uid: UserId, key: Key = None):
    return await execute_tool(session, "set_climbing_test_mode", user_payload(command.model_dump(), uid), key)


@router.get("/gear")
async def gear_list(session: Session, uid: UserId, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
    from app.tool_service import _gear_dict
    query = select(Gear).where(Gear.user_id == uid)
    if cursor:
        query = query.where(Gear.id > cursor)
    rows = list((await session.scalars(query.order_by(Gear.id).limit(limit+1))).all())
    return {"items": [_gear_dict(x) for x in rows[:limit]], "next_cursor": rows[limit-1].id if len(rows)>limit else None}


@router.post("/gear")
async def gear_create(command: GearWrite, session: Session, uid: UserId, key: Key = None):
    return await execute_tool(session, "upsert_climbing_gear", user_payload({"gear": command.model_dump()}, uid), key)


@router.get("/catalog/{kind}")
async def catalog_list(kind: Literal["locations", "sections", "routes"], session: Session, uid: UserId,
                       parent_id: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
    from sqlalchemy import or_
    models = {"locations": (Location, _area_dict), "sections": (Section, _section_dict), "routes": (Route, _route_dict)}
    model, formatter = models[kind]
    visible = or_(Location.visibility == "public", Location.owner_id == uid)
    query = select(model)
    if model is Section:
        query = query.join(Location)
        if parent_id:
            query = query.where(Section.location_id == parent_id)
    elif model is Route:
        query = query.join(Section).join(Location)
        if parent_id:
            query = query.where(Route.section_id == parent_id)
    query = query.where(visible)
    if cursor:
        query = query.where(model.id > cursor)
    rows = list((await session.scalars(query.order_by(model.id).limit(limit+1))).all())
    return {"items": [formatter(x) for x in rows[:limit]], "next_cursor": rows[limit-1].id if len(rows)>limit else None}


@router.post("/catalog/locations")
async def location_create(command: LocationWrite, session: Session, uid: UserId):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    await _user(session, {"id": uid})
    return _area_dict(await _area(session, command.model_dump()))


@router.post("/catalog/sections")
async def section_create(command: SectionWrite, session: Session, uid: UserId):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    await _user(session, {"id": uid})
    area = await session.get(Location, command.location_id)
    if not area:
        raise HTTPException(404, "Location not found")
    return _section_dict(await _section(session, area, {"name": command.name}))


@router.post("/catalog/routes")
async def route_create(command: RouteWrite, session: Session, uid: UserId):
    await session.scalar(select(User).where(User.id == uid).with_for_update())
    await _user(session, {"id": uid})
    section = await session.get(Section, command.section_id)
    if not section:
        raise HTTPException(404, "Section not found")
    return _route_dict(await _route(session, section, {"name": command.name, "grade": command.grade}))
