"""OIDC signature/claim validation and browser security without a database."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr
from starlette.requests import Request

from app.web_auth import check_browser_request, csrf_token, oidc_client, ISSUER

CONFIG = SimpleNamespace(web_origin="https://journal.test", telegram_oidc_client_id="123456",
                         telegram_oidc_client_secret=SecretStr("test-client-secret"))


def browser_request(method="POST", origin="https://journal.test", csrf=""):
    return Request({"type": "http", "method": method, "headers": [
        (b"origin", origin.encode()), (b"x-csrf-token", csrf.encode())]})


class BrowserSecurityTest(unittest.TestCase):
    def test_login_contract_has_explicit_slash_separated_routes(self):
        from app.main import app
        paths = app.openapi()["paths"]
        for path in ("/api/v1/auth/config", "/api/v1/auth/telegram/start", "/api/v1/auth/telegram/callback", "/api/v1/auth/session"):
            self.assertIn(path, paths)

    def test_cookie_mutations_require_origin_and_session_bound_csrf(self):
        token = "opaque-test-session"
        with patch("app.web_auth.get_settings", return_value=CONFIG):
            check_browser_request(browser_request(csrf=csrf_token(token)), token)
            for req in (browser_request(csrf=""), browser_request(csrf=csrf_token("other")),
                        browser_request(origin="https://attacker.test", csrf=csrf_token(token)),
                        browser_request(origin="null", csrf=csrf_token(token))):
                with self.assertRaises(HTTPException) as error:
                    check_browser_request(req, token)
                self.assertEqual(error.exception.status_code, 403)
            check_browser_request(browser_request(method="GET"), token)


class OidcValidationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = patch("app.web_auth.get_settings", return_value=CONFIG)
        self.settings.start()
        oidc_client.cache_clear()
        self.client = oidc_client()
        self.key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        self.keys = patch.object(self.client, "fetch_jwk_set", AsyncMock(return_value={"keys": [self.key.as_dict(private=False)]}))
        self.keys.start()

    async def asyncTearDown(self):
        self.keys.stop()
        self.settings.stop()
        oidc_client.cache_clear()

    def token(self, **overrides):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CONFIG.telegram_oidc_client_id, "sub": "different-from-telegram-id",
                  "id": 42, "exp": now + 300, "iat": now, "nonce": "login-nonce", **overrides}
        return {"id_token": jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, self.key),
                "access_token": "not-used-for-userinfo"}

    async def test_provider_verifies_signature_audience_expiry_issuer_and_nonce(self):
        claims = await self.client.parse_id_token(self.token(), nonce="login-nonce", leeway=0)
        self.assertEqual(claims["id"], 42)
        self.assertNotEqual(claims["sub"], "42")
        for invalid in ({"aud": "other-client"}, {"iss": "https://attacker.test"},
                        {"exp": int(time.time()) - 60}, {"nonce": "replay"}):
            with self.assertRaises(Exception):
                await self.client.parse_id_token(self.token(**invalid), nonce="login-nonce", leeway=0)
        other_key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        signed_elsewhere = jwt.encode({"alg": "RS256", "kid": "test-key"},
            {"iss": ISSUER, "aud": CONFIG.telegram_oidc_client_id, "exp": int(time.time()) + 300}, other_key)
        with self.assertRaises(Exception):
            await self.client.parse_id_token({"id_token": signed_elsewhere}, nonce="login-nonce")

    async def test_authorization_requests_pkce_and_only_profile_scope(self):
        from urllib.parse import urlsplit, parse_qs
        rv = await self.client.create_authorization_url("https://journal.test/api/v1/auth/telegram/callback",
            state="state", nonce="login-nonce", code_verifier="a" * 64)
        query = parse_qs(urlsplit(rv["url"]).query)
        self.assertEqual(query["scope"], ["openid profile"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("client_secret", query)
