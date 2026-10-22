"""Telegram OIDC with PostgreSQL state and opaque HttpOnly browser sessions."""
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_token
from app.config import get_settings
from app.db import get_control_session
from app.models import AuthSession, ExternalRef, User, WebLoginState

router = APIRouter(prefix="/api/v1/auth", tags=["web authentication"])
SESSION_COOKIE = "__Host-climbing_session"
LOGIN_COOKIE = "__Host-climbing_login"
LOGIN_SECONDS = 600
WEB_SESSION_SECONDS = 86400
CALLBACK = "/api/v1/auth/telegram/callback"
ISSUER = "https://oauth.telegram.org"
Control = Annotated[AsyncSession, Depends(get_control_session, scope="function")]


def web_origin() -> str:
    origin = get_settings().web_origin
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise HTTPException(503, "HTTPS WEB_ORIGIN is not configured")
    return origin.rstrip("/")


def login_enabled() -> bool:
    cfg = get_settings()
    try:
        web_origin()
    except HTTPException:
        return False
    return bool(cfg.telegram_oidc_client_id and cfg.telegram_oidc_client_secret.get_secret_value())


@lru_cache(maxsize=1)
def oidc_client():
    cfg = get_settings()
    # Fixed, documented provider endpoints; never derived from Host or client input.
    oauth = OAuth()
    return oauth.register("telegram", client_id=cfg.telegram_oidc_client_id,
        client_secret=cfg.telegram_oidc_client_secret.get_secret_value(),
        authorize_url=ISSUER + "/auth", access_token_url=ISSUER + "/token",
        issuer=ISSUER, jwks_uri=ISSUER + "/.well-known/jwks.json",
        id_token_signing_alg_values_supported=["RS256", "ES256"],
        client_kwargs={"scope": "openid profile", "code_challenge_method": "S256",
                       "token_endpoint_auth_method": "client_secret_basic", "timeout": 10, "trust_env": False})


def set_cookie(response, name: str, token: str, seconds: int):
    response.set_cookie(name, token, max_age=seconds, path="/", secure=True, httponly=True, samesite="lax")


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def csrf_token(token: str) -> str:
    # Bound to the opaque session, but not usable as a session credential.
    return hash_token("web-csrf:" + token)


def check_browser_request(request: Request, token: str):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("origin") != web_origin():
        raise HTTPException(403, "Invalid request origin")
    supplied = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(supplied, csrf_token(token)):
        raise HTTPException(403, "Invalid CSRF token")


@router.get("/config")
async def auth_config():
    return {"telegramLoginEnabled": login_enabled()}


@router.get("/telegram/start")
async def start(request: Request, session: Control):
    if not login_enabled():
        raise HTTPException(503, "Telegram web login is not configured")
    now = datetime.now(UTC)
    state, browser, verifier, nonce = (secrets.token_urlsafe(32), secrets.token_urlsafe(32),
                                       secrets.token_urlsafe(64), secrets.token_urlsafe(32))
    previous = request.cookies.get(LOGIN_COOKIE, "")
    await session.execute(delete(WebLoginState).where(WebLoginState.expires_at <= now))
    if previous and len(previous) <= 200:
        await session.execute(delete(WebLoginState).where(WebLoginState.browser_hash == hash_token(previous)))
    try:
        auth = await oidc_client().create_authorization_url(web_origin() + CALLBACK,
            state=state, code_verifier=verifier, nonce=nonce)
    except Exception:
        # Provider errors never expose token response bodies or configuration.
        raise HTTPException(503, "Telegram login is temporarily unavailable") from None
    session.add(WebLoginState(state_hash=hash_token(state), browser_hash=hash_token(browser),
        verifier=verifier, nonce=nonce, expires_at=now + timedelta(seconds=LOGIN_SECONDS)))
    await session.flush()
    response = RedirectResponse(auth["url"], status_code=302)
    set_cookie(response, LOGIN_COOKIE, browser, LOGIN_SECONDS)
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def finish_redirect(error: str | None = None):
    response = RedirectResponse(web_origin() + ("/?auth_error=" + error if error else "/"), status_code=303)
    response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/telegram/callback")
async def callback(request: Request, session: Control):
    if not login_enabled():
        raise HTTPException(503, "Telegram web login is not configured")
    state = request.query_params.get("state", "")
    browser = request.cookies.get(LOGIN_COOKIE, "")
    if not state or not browser or len(state) > 200 or len(browser) > 200:
        return finish_redirect("expired")
    # DELETE RETURNING consumes the handshake atomically across API workers. Returning
    # a redirect on errors lets the enclosing transaction commit this deletion too.
    row = (await session.execute(delete(WebLoginState).where(
        WebLoginState.state_hash == hash_token(state), WebLoginState.browser_hash == hash_token(browser),
        WebLoginState.expires_at > datetime.now(UTC)).returning(WebLoginState.verifier, WebLoginState.nonce))).first()
    if not row:
        return finish_redirect("expired")
    if request.query_params.get("error"):
        return finish_redirect("cancelled")
    code = request.query_params.get("code", "")
    if not code or len(code) > 2048:
        return finish_redirect("failed")
    try:
        client = oidc_client()
        tokens = await client.fetch_access_token(redirect_uri=web_origin() + CALLBACK,
            code=code, code_verifier=row.verifier)
        claims = await client.parse_id_token(tokens, nonce=row.nonce, leeway=30,
            claims_options={"iss": {"essential": True, "value": ISSUER},
                            "aud": {"essential": True}, "exp": {"essential": True},
                            "iat": {"essential": True}, "sub": {"essential": True},
                            "nonce": {"essential": True}, "id": {"essential": True}})
        # Telegram profile.id is the existing identity, NOT the OIDC subject.
        telegram_id = claims["id"]
        if isinstance(telegram_id, bool) or not str(telegram_id).isascii() or not str(telegram_id).isdigit() or int(telegram_id) <= 0:
            return finish_redirect("failed")
    except Exception:
        return finish_redirect("failed")
    user = await session.scalar(select(User).join(ExternalRef, ExternalRef.user_id == User.id).where(
        ExternalRef.system == "telegram", ExternalRef.entity_type == "user",
        ExternalRef.external_id == str(telegram_id)).with_for_update())
    if not user or user.status != "active":
        return finish_redirect("approval")
    now = datetime.now(UTC)
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= now))
    # Rotating an existing browser session must not revoke any other device.
    old_token = request.cookies.get(SESSION_COOKIE, "")
    if old_token and len(old_token) <= 200:
        await session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(old_token),
            AuthSession.channel == "web"))
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(user_id=user.id, token_hash=hash_token(token), channel="web",
        expires_at=now + timedelta(seconds=WEB_SESSION_SECONDS)))
    await session.flush()
    response = finish_redirect()
    set_cookie(response, SESSION_COOKIE, token, WEB_SESSION_SECONDS)
    return response
