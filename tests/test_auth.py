from dataclasses import replace
import sqlite3
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qsl, unquote

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.auth import AuthServices, get_auth_services, router
from app.services.auth_store import AuthStore
from app.services.discogs_oauth import DiscogsOAuth


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.key = Fernet.generate_key().decode()
        self.path = Path(self.temp.name) / "auth.sqlite3"
        self.store = AuthStore(self.path, self.key, clock=lambda: self.now)
        self.services = AuthServices(
            DiscogsOAuth("consumer-key", "consumer-secret"), self.store,
            Settings(callback_url="http://127.0.0.1:8000/auth/discogs/callback"),
        )
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_auth_services] = lambda: self.services
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        self.http = patch("app.services.discogs_oauth.httpx.request", side_effect=self.discogs)
        self.requests = self.http.start()
        self.addCleanup(self.http.stop)
        self.addCleanup(self.client.close)
        self.addCleanup(self.temp.cleanup)

    def discogs(self, method, url, **kwargs):
        auth = dict(parse_qsl(kwargs["headers"]["Authorization"][6:].replace('", ', '"&').replace('"', '')))
        # The real signing library must send signed requests, not the personal token.
        self.assertEqual(auth["oauth_signature_method"], "HMAC-SHA1")
        self.assertEqual(auth["oauth_consumer_key"], "consumer-key")
        self.assertTrue(auth["oauth_signature"])
        request = httpx.Request(method, url)
        if url.endswith("request_token"):
            self.assertEqual(method, "POST")
            self.assertEqual(unquote(auth["oauth_callback"]), self.services.settings.callback_url)
            return httpx.Response(200, text="oauth_token=request-token&oauth_token_secret=request-secret&oauth_callback_confirmed=true", request=request)
        if url.endswith("access_token"):
            self.assertEqual(auth["oauth_token"], "request-token")
            self.assertEqual(auth["oauth_verifier"], "verifier")
            return httpx.Response(200, text="oauth_token=access-token&oauth_token_secret=access-secret", request=request)
        self.assertEqual(auth["oauth_token"], "access-token")
        return httpx.Response(200, json={"username": "recordlover", "id": 42}, request=request)

    def start(self):
        return self.client.get("/auth/discogs/login", follow_redirects=False)

    def finish(self, client=None, token="request-token"):
        return (client or self.client).get("/auth/discogs/callback", params={
            "oauth_token": token, "oauth_verifier": "verifier",
        }, follow_redirects=False)

    def assertLoginFailure(self, response, code):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], self.services.settings.frontend_url + "?auth_error=" + code)

    def test_complete_login_identity_and_encrypted_persistence(self):
        response = self.start()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://www.discogs.com/oauth/authorize?oauth_token=request-token")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertNotIn("request-secret", response.headers["set-cookie"])
        response = self.finish()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], self.services.settings.frontend_url)
        self.assertNotIn("access-token", response.text)
        self.assertNotIn("access-secret", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/auth/me").json()["username"], "recordlover")
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT digest, payload FROM auth_records").fetchall()
        self.assertNotIn(self.client.cookies["dside_session"], repr(rows))
        self.assertNotIn("access-secret", repr(rows))
        reopened = AuthStore(self.path, self.key, clock=lambda: self.now)
        self.assertEqual(reopened.read("session", self.client.cookies["dside_session"])["token"], "access-token")

    def test_callback_is_bound_to_browser(self):
        self.start()
        with TestClient(self.app) as other:
            self.assertLoginFailure(self.finish(other), "incomplete")
        self.assertEqual(self.requests.call_count, 1)
        self.assertEqual(self.finish().status_code, 302)

    def test_mismatched_token_cannot_exchange_credentials(self):
        self.start()
        self.assertLoginFailure(self.finish(token="attacker-token"), "expired")
        self.assertEqual(self.requests.call_count, 1)

    def test_non_ascii_callback_token_is_rejected(self):
        self.start()
        self.assertLoginFailure(self.finish(token="invalid-\u00e9"), "expired")

    def test_pending_state_is_consumed_atomically(self):
        pending = self.store.create("pending", {"token": "test"}, 600)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.read("pending", pending, consume=True), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_changed_encryption_key_invalidates_session(self):
        self.start()
        self.finish()
        self.services.store = AuthStore(self.path, Fernet.generate_key().decode())
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_callback_is_single_use(self):
        self.start()
        pending = self.client.cookies["dside_oauth"]
        self.assertEqual(self.finish().status_code, 302)
        self.client.cookies.set("dside_oauth", pending, domain="127.0.0.1", path="/auth")
        self.assertLoginFailure(self.finish(), "expired")
        self.assertEqual(self.requests.call_count, 3)

    def test_pending_login_expires(self):
        self.start()
        self.now += 600
        self.assertLoginFailure(self.finish(), "expired")
        self.assertEqual(self.requests.call_count, 1)

    def test_session_expires(self):
        self.start()
        self.finish()
        self.now += 7 * 24 * 3600
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_configured_durations_apply_to_cookies_and_stored_sessions(self):
        self.services.settings = replace(self.services.settings, pending_ttl_seconds=30, session_ttl_seconds=1800)
        self.assertIn("Max-Age=30", self.start().headers["set-cookie"])
        self.assertIn("Max-Age=1800", self.finish().headers["set-cookie"])
        self.now += 1800
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_logout_rejects_cross_site_requests_and_revokes_session(self):
        self.start()
        self.finish()
        session = self.client.cookies["dside_session"]
        for headers in ({}, {"Origin": "https://attacker.example"}):
            self.assertEqual(self.client.post("/auth/logout", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/auth/logout", headers={"Origin": "http://localhost:5173"}).status_code, 200)
        self.assertIsNone(self.store.read("session", session))
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_secure_cookie_in_production(self):
        self.services.settings = replace(self.services.settings, cookie_secure=True)
        self.assertIn("Secure", self.start().headers["set-cookie"])

    def test_provider_errors_do_not_expose_secrets(self):
        self.requests.side_effect = httpx.ConnectError("consumer-secret")
        response = self.start()
        self.assertLoginFailure(response, "provider")
        self.assertNotIn("consumer-secret", response.text)

    def test_incomplete_callback_and_unauthenticated_identity(self):
        self.assertLoginFailure(self.client.get("/auth/discogs/callback", follow_redirects=False), "incomplete")
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_relogin_replaces_previous_session(self):
        self.start()
        self.finish()
        old = self.client.cookies["dside_session"]
        self.start()
        self.finish()
        self.assertIsNone(self.store.read("session", old))
        self.assertNotEqual(self.client.cookies["dside_session"], old)

    def test_missing_configuration_returns_service_unavailable(self):
        get_auth_services.cache_clear()
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(Exception) as caught:
                get_auth_services()
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
