"""Serialize user mutations and persist replay responses in the same transaction."""
import hashlib
import json
from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyKey, User


async def run_mutation(session: AsyncSession, user_id: str, operation: str,
                       key: str | None, payload: dict,
                       action: Callable[[], Awaitable[dict]], status: int = 200) -> dict:
    if key is not None and (not key.strip() or len(key) > 200):
        raise HTTPException(422, "Idempotency-Key must contain 1 to 200 characters")
    # Lock even without a key: start/append/finish must not race on the active training.
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise HTTPException(404, "User not found")
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=False).encode()).hexdigest()
    if key:
        existing = await session.scalar(select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.operation == operation,
            IdempotencyKey.key == key))
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "Idempotency-Key was already used with a different payload")
            return existing.response_body
    response = await action()
    if key:
        session.add(IdempotencyKey(user_id=user_id, operation=operation, key=key,
                                  request_hash=request_hash, response_status=status, response_body=response))
        await session.flush()
    return response
