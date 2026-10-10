"""Account admission and auditable, one-time owner decisions."""
import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.models import ExternalRef, User, new_id
from app.public_models import AccessRequest, AuditEvent, Outbox


async def telegram_user(session: AsyncSession, telegram_id: str, name: str = "Скалолаз") -> User:
    key = int.from_bytes(hashlib.sha256(f"telegram:{telegram_id}".encode()).digest()[:8], signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    user = await session.scalar(select(User).join(ExternalRef, ExternalRef.user_id == User.id).where(
        ExternalRef.system == "telegram", ExternalRef.entity_type == "user", ExternalRef.external_id == telegram_id))
    if not user:
        user = User(name=name[:200] or "Скалолаз", timezone="Europe/Moscow", status="pending_approval")
        session.add(user)
        await session.flush()
        session.add(ExternalRef(system="telegram", entity_type="user", external_id=telegram_id, user_id=user.id))
        await session.flush()
    return user


async def message(session: AsyncSession, user_id: str | None, chat_id: str, key: str, text_value: str,
                  keyboard: list | None = None, document: dict | None = None, access_request_id: str | None = None) -> None:
    payload = {"text": text_value[:4000]}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if document:
        payload["document"] = document
    await session.execute(insert(Outbox).values(id=new_id("outbox"), user_id=user_id, chat_id=chat_id,
        dedupe_key=key, payload=payload, access_request_id=access_request_id).on_conflict_do_nothing(index_elements=[Outbox.dedupe_key]))


async def request_access(session: AsyncSession, user: User, telegram_id: str, username: str | None = None) -> str:
    cfg = get_settings()
    await session.scalar(select(User).where(User.id == user.id).with_for_update())
    if user.status == "blocked":
        return "Доступ заблокирован. Повторная заявка недоступна."
    if user.status == "active":
        return "Доступ уже открыт. Нажмите /journal."
    last = await session.scalar(select(AccessRequest).where(AccessRequest.user_id == user.id)
                                .order_by(AccessRequest.created_at.desc()).limit(1))
    if last and last.status == "pending":
        return "Заявка ожидает решения владельца."
    if last and last.decided_at and last.decided_at + timedelta(hours=cfg.access_retry_hours) > datetime.now(UTC):
        return f"Повторная заявка доступна через {cfg.access_retry_hours} ч после решения."
    if not cfg.access_approval_chat_id or not cfg.access_approver_telegram_id:
        return "Приём заявок ещё не настроен. Попробуйте позже."
    item = AccessRequest(user_id=user.id)
    session.add(item)
    await session.flush()
    card = (f"Заявка {item.id}\n{item.created_at.isoformat()}\nTelegram ID: {telegram_id}\n"
            f"Имя: {user.name}" + (f"\n@{username[:100]}" if username else ""))
    recent = await session.scalar(select(func.count(AccessRequest.id)).where(AccessRequest.created_at >= datetime.now(UTC)-timedelta(minutes=1)))
    if recent > 10:
        await message(session, None, cfg.access_approval_chat_id, "access-batch:"+datetime.now(UTC).strftime("%Y%m%d%H%M"),
                      "Поступает много заявок. Просмотрите их по одной через /requests. Автоматического одобрения нет.")
    else:
        await message(session, user.id, cfg.access_approval_chat_id, f"access:{item.id}", card,
                      [[{"text": "Разрешить", "callback_data": f"approve:{item.id}"},
                        {"text": "Отклонить", "callback_data": f"reject:{item.id}"}]], access_request_id=item.id)
    return "Заявка отправлена владельцу. Здесь появится результат."


async def require_approver(session: AsyncSession, actor: User, telegram_id: str, chat_id: str) -> None:
    cfg = get_settings()
    if (telegram_id != cfg.access_approver_telegram_id or chat_id != cfg.access_approval_chat_id
            or actor.role != "admin" or actor.status != "active"):
        raise HTTPException(403, "Only the configured owner can decide access requests")


async def decide_access(session: AsyncSession, actor: User, telegram_id: str, chat_id: str,
                        request_id: str, approved: bool, origin: dict) -> str:
    await require_approver(session, actor, telegram_id, chat_id)
    card = await session.scalar(select(Outbox.id).where(Outbox.access_request_id == request_id,
        Outbox.chat_id == chat_id, Outbox.telegram_message_id == origin.get("callback_message_id"), Outbox.status == "succeeded"))
    if not card or origin.get("forwarded_callback") or origin.get("callback_source_bot_id") != get_settings().telegram_bot_id:
        return "Карточка не подтверждена или устарела. Откройте /requests и выберите заявку заново."
    # Lock user before request, matching request_access and blocking/deletion order.
    uid = await session.scalar(select(AccessRequest.user_id).where(AccessRequest.id == request_id))
    target = await session.scalar(select(User).where(User.id == uid).with_for_update()) if uid else None
    item = await session.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update())
    if not item or not target:
        raise HTTPException(404, "Request no longer exists")
    if item.status != "pending":
        return "По этой заявке уже принято решение."
    if target.status != "pending_approval":
        return "Заявка устарела: состояние аккаунта изменилось."
    item.status = "approved" if approved else "rejected"
    item.decided_at, item.decided_by = datetime.now(UTC), actor.id
    if approved:
        target.status = "active"
    session.add(AuditEvent(actor_id=actor.id, action=f"access:{item.status}", subject_id=item.id))
    recipient = await session.scalar(select(ExternalRef.external_id).where(ExternalRef.user_id == target.id,
                                  ExternalRef.system == "telegram", ExternalRef.entity_type == "user"))
    if recipient:
        await message(session, target.id, recipient, f"access-result:{item.id}",
                      "Доступ открыт. Нажмите /journal." if approved else "Заявка отклонена владельцем.")
    return "Доступ разрешён." if approved else "Заявка отклонена."
