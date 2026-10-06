import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.auth import authenticate
from app.models import AuthSession


def require_internal_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().internal_api_key.get_secret_value()
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def current_auth_session(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthSession:
    return await authenticate(session, authorization)


def current_user_id(auth: Annotated[AuthSession, Depends(current_auth_session)]) -> str:
    return auth.user_id
