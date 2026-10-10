"""Telegram bootstrap is service-only; data APIs accept revocable user sessions."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthSession, ExternalRef, User

SESSION_SECONDS = 15 * 60


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def telegram_login(session: AsyncSession, telegram_id: str) -> dict:
    # Serialize first registration as well as simultaneous logins for the same identity.
    lock_id = int.from_bytes(hashlib.sha256(f"telegram:{telegram_id}".encode()).digest()[:8], signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    user = await session.scalar(select(User).join(ExternalRef, ExternalRef.user_id == User.id).where(
        ExternalRef.system == "telegram", ExternalRef.entity_type == "user", ExternalRef.external_id == telegram_id).with_for_update())
    if not user:
        user = User(name="Скалолаз", timezone="Europe/Moscow", status="pending_approval")
        session.add(user)
        await session.flush()
        session.add(ExternalRef(system="telegram", entity_type="user", external_id=telegram_id, user_id=user.id))
    if user.status != "active":
        raise HTTPException(403, "Access requires owner approval")
    now = datetime.now(UTC)
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=SESSION_SECONDS)
    session.add(AuthSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    await session.flush()
    return {"access_token": token, "token_type": "bearer", "expires_in": SESSION_SECONDS}


async def authenticate(session: AsyncSession, authorization: str | None) -> AuthSession:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 200:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    auth = await session.scalar(select(AuthSession).join(User, User.id == AuthSession.user_id).where(
        AuthSession.token_hash == hash_token(token), AuthSession.expires_at > datetime.now(UTC), User.status == "active"))
    if not auth:
        raise HTTPException(401, "Session expired or revoked", headers={"WWW-Authenticate": "Bearer"})
    return auth


def user_payload(payload: dict, user_id: str) -> dict:
    # Identity is never taken from model output or client-supplied resource filters.
    return {**{key: value for key, value in payload.items() if key not in ("user", "userId", "userName")},
            "user": {"id": user_id}}
