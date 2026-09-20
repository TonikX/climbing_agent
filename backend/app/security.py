import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


def require_internal_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().internal_api_key.get_secret_value()
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def current_user_id(
    _: Annotated[None, Depends(require_internal_key)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-User-ID")
    return x_user_id
