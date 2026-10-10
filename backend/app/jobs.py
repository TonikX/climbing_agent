"""Leased PostgreSQL jobs. Journal mutations and their replies commit together."""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, delete, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.access import message, telegram_user
from app.config import get_settings
from app.db import set_user_context
from app.models import TrainingSession, User
from app.public_models import Job, Outbox, TelegramUpdate, Usage, DialogState, UpdateReceipt, AuditEvent


def now():
    return datetime.now(UTC)


async def ingest(session, raw: dict) -> dict:
    from aiogram.types import Update
    envelope = Update.model_validate(raw)
    event = envelope.callback_query or envelope.message
    if not event:
        return {"accepted": True, "ignored": True}
    msg = event.message if envelope.callback_query else event
    actor = event.from_user
    if not actor or actor.is_bot or actor.id <= 0 or actor.id >= 2**63 or not msg or msg.chat.type != "private":
        return {"accepted": True, "ignored": True}
    # Callback origin and forwarding never replace verified from.id.
    tid, cid = str(actor.id), str(msg.chat.id)
    if tid != cid:
        return {"accepted": True, "ignored": True}
    cfg = get_settings()
    saved = await session.scalar(insert(UpdateReceipt).values(bot_id=cfg.telegram_bot_id, update_id=envelope.update_id)
                                 .on_conflict_do_nothing().returning(UpdateReceipt.update_id))
    if saved is None:
        return {"accepted": True, "duplicate": True}
    user = await telegram_user(session, tid, actor.full_name)
    incoming = TelegramUpdate(bot_id=cfg.telegram_bot_id, update_id=envelope.update_id,
                              user_id=user.id, payload=raw)
    session.add(incoming)
    await session.flush()
    command = event.data if envelope.callback_query else (msg.text or "")
    command = command.split("@", 1)[0] if command.startswith("/") else command
    voice = msg.voice if not envelope.callback_query else None
    lane = "fast" if envelope.callback_query or command.startswith("/") or user.status != "active" else "ai"
    if await session.get(DialogState, user.id):
        lane = "fast"
    if not command and not voice:
        lane, command = "fast", "unsupported"
    if lane == "ai":
        queued = await session.scalar(select(func.count(Job.id)).where(Job.user_id == user.id, Job.lane == "ai",
                                                 Job.status.in_(["pending", "processing"])))
        if queued >= cfg.ai_queue_per_user:
            lane, command = "fast", "quota:queued"
    read_only = command.startswith(("stats:", "gear:menu", "training:details:")) or command in ("/stats", "/journal", "journal", "stats:menu", "profile", "/profile", "/gear")
    if command in ("training:finish", "training:finish:cancel", "/finish"):
        read_only = True  # The handler offers wait/cancel instead of waiting behind AI.
    await set_user_context(session, user.id)
    active = await session.scalar(select(TrainingSession).where(TrainingSession.user_id == user.id, TrainingSession.status == "active"))
    payload = {"command": command[:8000], "telegram_id": tid, "chat_id": cid, "username": actor.username,
               "mutation": not read_only}
    if command == "quota:queued":
        payload["mutation"] = False
    if envelope.callback_query:
        payload.update(callback_message_id=msg.message_id, callback_source_bot_id=str(msg.from_user.id) if msg.from_user else None,
                       forwarded_callback=msg.forward_origin is not None)
        await message(session, user.id, cid, f"callback:{envelope.callback_query.id}", "")
        ack = await session.scalar(select(Outbox).where(Outbox.dedupe_key == f"callback:{envelope.callback_query.id}"))
        ack.payload = {"callback_id": envelope.callback_query.id}
    if voice:
        payload["voice"] = {"file_id": voice.file_id, "duration": voice.duration, "file_size": voice.file_size}
    job = Job(update_id=incoming.id, user_id=user.id, lane=lane, payload=payload,
              training_id=active.id if active else None, expected_version=active.version if active else None)
    session.add(job)
    await session.flush()
    return {"accepted": True, "job_id": job.id}


async def reserve_ai(session, job: Job, user: User) -> None:
    cfg = get_settings()
    if user.status != "active":
        raise HTTPException(403, "Access requires approval")
    duration = int((job.payload.get("voice") or {}).get("duration", 0))
    if duration > cfg.audio_max_seconds or int((job.payload.get("voice") or {}).get("file_size") or 0) > 8_000_000:
        raise HTTPException(429, "Voice message is too long")
    day = now().strftime("%Y-%m-%d")
    # Consistent global/user lock order; reservations are charged conservatively even after crashes.
    values = []
    for scope in ("global", user.id):
        await session.execute(insert(Usage).values(id=f"usage:{scope}:{day}", scope=scope, day=day,
                              requests=0, audio_seconds=0, budget_units=0, tokens=0).on_conflict_do_nothing())
        values.append(await session.scalar(select(Usage).where(Usage.scope == scope, Usage.day == day).with_for_update()))
    global_usage, personal = values
    cost = cfg.ai_call_reservation_units * (2 if job.payload.get("voice") else 1)
    if cfg.ai_daily_budget_units <= 0 or cost <= 0 or global_usage.budget_units + cost > cfg.ai_daily_budget_units:
        raise HTTPException(429, "AI budget is unavailable or exhausted")
    if personal.requests >= cfg.ai_daily_requests or personal.audio_seconds + duration > cfg.audio_daily_seconds:
        raise HTTPException(429, "Daily AI quota exhausted")
    personal.requests += 1
    personal.audio_seconds += duration
    global_usage.budget_units += cost
    job.reservation_day = day


async def claim(session, lane: str, worker_id: str):
    model = Outbox if lane == "delivery" else Job
    timestamp = now()
    query = select(model).where(or_(and_(model.status == "pending", model.available_at <= timestamp),
                                  and_(model.status == "processing", model.lease_until < timestamp)))
    if model is Job:
        earlier = aliased(Job)
        # Read-only UI bypasses AI; mutations of the same user remain ordered.
        query = query.where(Job.lane == lane, or_(Job.payload["mutation"].as_boolean().is_(False), ~exists(
            select(earlier.id).where(earlier.user_id == Job.user_id, earlier.status.in_(["pending", "processing"]),
                                    earlier.payload["mutation"].as_boolean().is_(True),
                                    earlier.sequence < Job.sequence))))
    else:
        earlier = aliased(Outbox)
        query = query.where(~exists(select(earlier.id).where(earlier.chat_id == Outbox.chat_id,
                    earlier.status.in_(["pending", "processing"]), earlier.sequence < Outbox.sequence)))
    if model is Job:
        # Always lock user before job, matching apply/cancel/delete and preventing deadlocks.
        fairness = User.last_fast_job_at if lane == "fast" else User.last_ai_job_at
        item = await session.scalar(query.join(User, User.id == Job.user_id).order_by(fairness.asc().nullsfirst(), Job.sequence)
                                    .with_for_update(of=User, skip_locked=True).limit(1))
        if item:
            await session.refresh(item, with_for_update=True)
            user = await session.get(User, item.user_id)
            setattr(user, "last_fast_job_at" if lane == "fast" else "last_ai_job_at", timestamp)
    else:
        item = await session.scalar(query.order_by(model.sequence).with_for_update(skip_locked=True).limit(1))
    if not item:
        return None
    if model is Outbox and "document" in item.payload and item.created_at < timestamp-timedelta(days=1):
        item.status, item.error_code = "cancelled", "export_expired"
        return None
    if item.retries >= 5:
        item.status, item.error_code = "failed", "retry_exhausted"
        return None
    if model is Job and lane == "ai":
        user = await session.get(User, item.user_id)
        from zoneinfo import ZoneInfo
        item.payload = {**item.payload, "local_date": datetime.now(ZoneInfo(user.timezone)).date().isoformat()}
        await set_user_context(session, user.id)
        from app.models import RouteAttempt
        previous = await session.scalar(select(RouteAttempt).join(TrainingSession).where(
            TrainingSession.user_id == user.id, TrainingSession.id == item.training_id,
            TrainingSession.status == "active").order_by(RouteAttempt.sequence.desc()).limit(1))
        if previous:
            item.payload = {**item.payload, "last_route": {"name": previous.route_snapshot.get("name"),
                                                         "grade": previous.route_snapshot.get("grade")}}
        queued = await session.scalar(select(func.count(Job.id)).where(Job.user_id == item.user_id,
                   Job.lane == "ai", Job.status.in_(["pending", "processing"])))
        try:
            if queued > get_settings().ai_queue_per_user:
                raise HTTPException(429, "Too many AI jobs")
            await reserve_ai(session, item, user)
        except HTTPException as exc:
            item.status, item.error_code = "failed", "quota_or_access"
            await message(session, item.user_id, item.payload["chat_id"], f"job:{item.id}",
                          "Запрос не обработан: нет доступа или достигнут лимит. Статистика доступна через кнопки.")
            return None
    item.status, item.worker_id = "processing", worker_id
    item.lease_until = timestamp + timedelta(seconds=120)
    item.retries += 1
    return {"id": item.id, "payload": item.payload,
            "chat_id": item.chat_id if model is Outbox else None}


async def leased(session, lane: str, item_id: str, worker_id: str):
    model = Outbox if lane == "delivery" else Job
    item = await session.scalar(select(model).where(model.id == item_id).with_for_update())
    if not item or item.status != "processing" or item.worker_id != worker_id or item.lease_until <= now():
        raise HTTPException(409, "Lease expired or ownership changed")
    return item


async def fail(session, lane: str, item_id: str, worker_id: str, code: str, retry_seconds: int):
    item = await leased(session, lane, item_id, worker_id)
    item.error_code, item.worker_id, item.lease_until = code, None, None
    item.status = "pending" if retry_seconds and item.retries < 5 else "failed"
    item.available_at = now() + timedelta(seconds=retry_seconds)
    if isinstance(item, Job) and item.status == "failed":
        await message(session, item.user_id, item.payload["chat_id"], f"job:{item.id}",
                      "Не удалось обработать запрос. Попробуйте позже или используйте кнопки.")


async def cleanup(session):
    # Queue state remains durable until terminal; raw incoming data expires after seven days.
    terminal = ["succeeded", "failed", "cancelled"]
    await session.execute(delete(TelegramUpdate).where(TelegramUpdate.created_at < now()-timedelta(days=7),
        ~exists(select(Job.id).where(Job.update_id == TelegramUpdate.id, Job.status.not_in(terminal)))))
    await session.execute(delete(Outbox).where(Outbox.created_at < now()-timedelta(days=1), Outbox.status.in_(terminal)))
    await session.execute(delete(Usage).where(Usage.day < (now()-timedelta(days=30)).strftime("%Y-%m-%d")))
    await session.execute(delete(DialogState).where(DialogState.created_at < now()-timedelta(minutes=30)))
    await session.execute(delete(Job).where(Job.created_at < now()-timedelta(days=7), Job.status.in_(terminal)))
    await session.execute(delete(AuditEvent).where(AuditEvent.created_at < now()-timedelta(days=30)))
