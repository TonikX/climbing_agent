import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session, get_control_session, set_user_context
from app.auth import authenticate
from app.models import AuthSession
bearer = HTTPBearer(auto_error=False)


async def require_internal_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().internal_api_key.get_secret_value()
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def current_auth_session(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    control: Annotated[AsyncSession, Depends(get_control_session, scope="function")],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> AuthSession:
    authorization = f"{credentials.scheme} {credentials.credentials}" if credentials else None
    auth = await authenticate(control, authorization)
    await set_user_context(session, auth.user_id)
    # Return an object attached to the data transaction (logout remains atomic).
    result = await session.get(AuthSession, auth.id)
    if not result:
        raise HTTPException(401, "Session revoked", headers={"WWW-Authenticate": "Bearer"})
    return result


async def current_user_id(auth: Annotated[AuthSession, Depends(current_auth_session)]) -> str:
    return auth.user_id
