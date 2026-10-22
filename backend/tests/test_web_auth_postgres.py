"""Browser login and revocation using disposable, rolled-back PostgreSQL schemas."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update

from app.auth import hash_token
from app.main import app
from app.models import AuthSession, User, WebLoginState
from app.web_auth import LOGIN_COOKIE, SESSION_COOKIE, csrf_token
from tests.test_auth_postgres import AuthPostgresTest

CONFIG = SimpleNamespace(web_origin="https://journal.test", telegram_oidc_client_id="123456",
                         telegram_oidc_client_secret=SecretStr("test-client-secret"))


class WebAuthPostgresTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = AuthPostgresTest.asyncSetUp
    asyncTearDown = AuthPostgresTest.asyncTearDown
    login = AuthPostgresTest.login

    async def browser(self):
        await self.client.aclose()
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="https://journal.test", follow_redirects=False)
        self.addCleanup(patch.stopall)

    async def handshake(self):
        client = SimpleNamespace(create_authorization_url=AsyncMock(return_value={"url": "https://oauth.telegram.org/auth"}),
            fetch_access_token=AsyncMock(return_value={"id_token": "signed"}),
            parse_id_token=AsyncMock(return_value={"id": 42, "sub": "wrong-identity"}))
        patch("app.web_auth.get_settings", return_value=CONFIG).start()
        patch("app.web_auth.oidc_client", return_value=client).start()
        started = await self.client.get("/api/v1/auth/telegram/start")
        self.assertEqual(started.status_code, 302, started.text)
        cookie = started.headers["set-cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=lax", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Domain=", cookie)
        params = client.create_authorization_url.call_args.kwargs
        self.assertEqual(len(params["code_verifier"]), 86)
        return params["state"], client

    async def test_web_login_identity_cookie_csrf_logout_and_replay(self):
        await self.browser()
        bearer = await self.login("42")
        self.client.cookies.set(SESSION_COOKIE, bearer["Authorization"].split()[1], domain="journal.test", path="/")
        self.assertEqual((await self.client.get("/api/v1/me")).status_code, 401)
        self.client.cookies.clear()
        state, provider = await self.handshake()
        response = await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "https://journal.test/")
        cookie = self.client.cookies.get(SESSION_COOKIE)
        self.assertIsNotNone(cookie)
        session = (await self.client.get("/api/v1/auth/session")).json()
        self.assertEqual(session["user"]["status"], "active")
        self.assertEqual(session["csrfToken"], csrf_token(cookie))
        replay = await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        self.assertIn("expired", replay.headers["location"])
        self.assertEqual(provider.fetch_access_token.await_count, 1)
        self.assertEqual((await self.client.post("/api/v1/auth/logout")).status_code, 403)
        headers = {"Origin": "https://journal.test", "X-CSRF-Token": session["csrfToken"]}
        self.assertEqual((await self.client.post("/api/v1/auth/logout", headers={**headers, "Origin": "https://evil.test"})).status_code, 403)
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer)).status_code, 400)
        self.assertEqual((await self.client.post("/api/v1/auth/logout", headers=headers)).status_code, 204)
        self.assertEqual((await self.client.get("/api/v1/me")).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer)).status_code, 200)

    async def test_wrong_browser_pending_account_and_invalid_token_cannot_log_in(self):
        await self.browser()
        state, provider = await self.handshake()
        browser = self.client.cookies.get(LOGIN_COOKIE)
        self.client.cookies.clear()
        wrong = await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        self.assertIn("expired", wrong.headers["location"])
        provider.fetch_access_token.assert_not_awaited()
        self.client.cookies.set(LOGIN_COOKIE, browser, domain="journal.test", path="/")
        # Unknown identities do not get silently registered or approved by the web.
        denied = await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        self.assertIn("approval", denied.headers["location"])
        self.assertIsNone(self.client.cookies.get(SESSION_COOKIE))
        await self.login("42")
        state, provider = await self.handshake()
        provider.parse_id_token.side_effect = ValueError("invalid signature")
        failed = await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        self.assertIn("failed", failed.headers["location"])
        self.assertIsNone(self.client.cookies.get(SESSION_COOKIE))
        # An invalid token also consumes the state permanently.
        provider.parse_id_token.side_effect = None
        replay = await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        self.assertIn("expired", replay.headers["location"])

    async def test_blocking_and_logout_all_revoke_web_and_bot_sessions(self):
        await self.browser()
        bearer = await self.login("42")
        state, _ = await self.handshake()
        await self.client.get("/api/v1/auth/telegram/callback", params={"state": state, "code": "code"})
        info = (await self.client.get("/api/v1/auth/session")).json()
        cookie = self.client.cookies.get(SESSION_COOKIE)
        await self.conn.execute(update(User).values(status="blocked"))
        self.assertEqual((await self.client.get("/api/v1/me")).status_code, 401)
        await self.conn.execute(update(User).values(status="active"))
        headers = {"Origin": "https://journal.test", "X-CSRF-Token": info["csrfToken"]}
        self.assertEqual((await self.client.post("/api/v1/auth/logout-all", headers=headers)).status_code, 204)
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer)).status_code, 401)
        self.client.cookies.set(SESSION_COOKIE, cookie, domain="journal.test", path="/")
        self.assertEqual((await self.client.get("/api/v1/me")).status_code, 401)
