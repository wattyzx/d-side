import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4
from unittest.mock import patch

import anyio
import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.api import app
from app.auth import AuthServices, get_auth_services
from app.services.auth_store import AuthStore
from app.services.cache_service import SQLiteCache
from app.services.database import DatabaseError
from app.services.discogs_oauth import DiscogsOAuth
from app.services.discogs_session import current_credentials, discogs_session, DiscogsCredentials
from app.services import discogs_client
from app.services.search_control import check_cancelled, search_registry


class AuthenticatedAPITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = AuthStore(Path(temp.name) / "auth.sqlite3", Fernet.generate_key().decode())
        self.cache = SQLiteCache(Path(temp.name) / "cache.sqlite3")
        self.services = AuthServices(DiscogsOAuth("consumer", "secret"), self.store,
                                     Settings())
        app.dependency_overrides[get_auth_services] = lambda: self.services
        self.addCleanup(app.dependency_overrides.clear)

    def client(self, username=None):
        client = TestClient(app, base_url="http://localhost:5173")
        self.addCleanup(client.close)
        if username:
            session = self.store.create("session", {"username": username,
                "token": username + "-token", "secret": username + "-secret"}, 3600)
            client.cookies.set("dside_session", session, path="/")
        return client

    def credentials(self, username):
        return DiscogsCredentials(username, username + "-token", username + "-secret", "consumer", "secret")

    def test_database_failure_returns_service_unavailable_without_losing_session(self):
        client = self.client("Alice")
        with patch.object(self.store, "read", side_effect=DatabaseError("Database request failed. Please try again.")):
            response = client.get("/auth/me")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Database request failed. Please try again.")
        self.assertEqual(client.get("/auth/me").status_code, 200)

    def test_price_range_is_validated_before_search_and_forwarded_to_both_endpoints(self):
        client = self.client("Alice")
        for endpoint in ("/recommend", "/recommend/stream"):
            for bounds in ({"min_price": -1}, {"max_price": -1},
                           {"min_price": 20, "max_price": 10},
                           {"min_price": "NaN"}, {"max_price": "Infinity"}):
                with self.subTest(endpoint=endpoint, bounds=bounds):
                    self.assertEqual(client.post(endpoint, json={"seller": "shop", **bounds}).status_code, 422)
        with patch("app.api.recommend", return_value={}) as recommend:
            response = client.post("/recommend", json={"seller": "shop", "min_price": 0, "max_price": 20})
            self.assertEqual(response.status_code, 200)
            recommend.assert_called_once_with(username="Alice", seller="shop", min_price=0, max_price=20)
        def records(**kwargs):
            yield '{"type":"done"}\n'

        with patch("app.api.recommend_stream", side_effect=records) as stream:
            response = client.post("/recommend/stream", json={
                "seller": "shop", "min_price": 10, "max_price": 20, "exclude_release_ids": [3],
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, '{"type":"done"}\n')
            stream.assert_called_once_with(username="Alice", seller="shop", exclude_release_ids=[3],
                                           min_price=10, max_price=20)

    def test_all_personal_endpoints_require_login(self):
        client = self.client()
        for path, body in (("/recommend", {"seller": "shop"}),
                           ("/recommend/stream", {"seller": "shop"}),
                           ("/wantlist", {"release_id": 123})):
            self.assertEqual(client.post(path, json=body).status_code, 401)
        self.assertEqual(client.get("/health").status_code, 200)

    def test_seller_urls_are_normalized_before_search(self):
        client = self.client("Alice")
        url = "https://www.discogs.com/seller/Some.Shop/shop?limit=250"
        with patch("app.api.recommend", return_value={}) as recommend:
            self.assertEqual(client.post("/recommend", json={"seller": url}).status_code, 200)
            recommend.assert_called_once_with(username="Alice", seller="Some.Shop")
        with patch("app.api.recommend_stream", return_value=(event for event in ['{"type":"done"}\n'])) as stream:
            self.assertEqual(client.post("/recommend/stream", json={"seller": url}).status_code, 200)
            stream.assert_called_once_with(username="Alice", seller="Some.Shop", exclude_release_ids=[])
        for endpoint in ("/recommend", "/recommend/stream"):
            self.assertEqual(client.post(endpoint, json={"seller": "https://example.com/user/shop"}).status_code, 422)

    def test_search_uses_session_identity_and_credentials_despite_supplied_username(self):
        def recommend(username, seller):
            self.assertEqual(current_credentials().token, "Alice-token")
            return {"username": username, "seller": seller}
        with patch("app.api.recommend", side_effect=recommend):
            response = self.client("Alice").post("/recommend", json={"seller": "shop", "username": "Bob"})
        self.assertEqual(response.json(), {"username": "Alice", "seller": "shop"})
        with self.assertRaises(RuntimeError):
            current_credentials()

    def test_concurrent_streams_keep_credentials_through_every_event(self):
        barrier = Barrier(2)
        def recommend(username, seller, exclude_release_ids):
            for _ in range(3):
                barrier.wait(timeout=5)
                credentials = current_credentials()
                self.assertEqual(credentials.username, username)
                self.assertEqual(credentials.token, username + "-token")
                yield '{"type":"status","message":"' + username + '"}\n'
            yield '{"type":"done"}\n'
        alice, bob = self.client("Alice"), self.client("Bob")
        with patch("app.api.recommend_stream", side_effect=recommend), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.post, "/recommend/stream", json={"seller": "shop"})
                       for client in (alice, bob)]
            results = [future.result(timeout=10) for future in futures]
        for username, response in zip(("Alice", "Bob"), results):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text.count(username), 3)

    def test_wantlist_uses_logged_in_owner_and_requires_trusted_origin(self):
        client = self.client("Alice")
        def save(release_id):
            self.assertEqual(current_credentials().username, "Alice")
            self.assertEqual(current_credentials().token, "Alice-token")
        with patch("app.api.add_to_wantlist", side_effect=save) as write:
            response = client.post("/wantlist", json={"release_id": 123, "username": "Bob"},
                                   headers={"Origin": "http://localhost:5173"})
            self.assertEqual(response.status_code, 200)
            response = client.post("/wantlist", json={"release_id": 123},
                                   headers={"Origin": "https://attacker.example"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(write.call_count, 1)

    def test_collection_and_inventory_caches_are_isolated_by_account(self):
        def read(*args, **kwargs):
            return {"owner": current_credentials().username}
        with patch.object(discogs_client, "cache", self.cache), patch.object(discogs_client, "get_json", side_effect=read) as fetch:
            for method in (discogs_client.get_collection_raw, discogs_client.get_inventory_raw):
                for username in ("Alice", "Bob", "Alice"):
                    with discogs_session(self.credentials(username)):
                        self.assertEqual(method("same-profile")["owner"], username)
            self.assertEqual(fetch.call_count, 4)

    def test_wantlist_save_only_invalidates_own_cache(self):
        for username in ("Alice", "Bob"):
            self.cache.set("wantlist_raw:" + username.casefold(), username + ":1:100", {"wants": []})
        with patch.object(discogs_client, "cache", self.cache), patch.object(discogs_client, "put_json", return_value={}):
            with discogs_session(self.credentials("Alice")):
                discogs_client.add_to_wantlist(123)
        self.assertIsNone(self.cache.get("wantlist_raw:alice", "Alice:1:100"))
        self.assertEqual(self.cache.get("wantlist_raw:bob", "Bob:1:100"), {"wants": []})

    def test_save_during_wantlist_fetch_cannot_restore_stale_pages(self):
        for fill_fresh_before_old_finishes in (False, True):
            with self.subTest(fill_fresh_before_old_finishes=fill_fresh_before_old_finishes):
                self.cache.clear_namespace("wantlist_raw:alice")
                started, release = Event(), Event()
                old = {"wants": [], "pagination": {"pages": 1}}
                fresh = {"wants": [{"basic_information": {"id": 123}}], "pagination": {"pages": 1}}

                def slow_read(*args, **kwargs):
                    started.set()
                    if not release.wait(3):
                        raise TimeoutError("Test did not release the wantlist fetch")
                    return old

                def read():
                    with discogs_session(self.credentials("Alice")):
                        return discogs_client.get_wantlist_ids("Alice")

                def cached_read():
                    return self.cache.get("wantlist_raw:alice", "Alice:1:100")

                with patch.object(discogs_client, "cache", self.cache), \
                     patch.object(discogs_client, "get_json", side_effect=slow_read) as fetch, \
                     patch.object(discogs_client, "put_json", return_value={}), \
                     ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(read)
                    try:
                        self.assertTrue(started.wait(1))
                        # A save from another tab completes while the old GET waits.
                        with discogs_session(self.credentials("Alice")):
                            discogs_client.add_to_wantlist(123)
                        fetch.side_effect = None
                        fetch.return_value = fresh
                        if fill_fresh_before_old_finishes:
                            self.assertEqual(read(), {123})
                    finally:
                        release.set()
                    self.assertEqual(pending.result(timeout=2), set())
                    if fill_fresh_before_old_finishes:
                        self.assertEqual(cached_read(), fresh)
                    else:
                        self.assertIsNone(cached_read())
                    self.assertEqual(read(), {123})
                    fetch.reset_mock()
                    self.assertEqual(read(), {123})
                    fetch.assert_not_called()

    def test_duplicate_searches_share_limit_across_both_endpoints(self):
        started, release = Event(), Event()
        def records(**kwargs):
            yield '{"type":"status"}\n'
            started.set()
            release.wait(3)
            yield '{"type":"done"}\n'
        alice, other_tab = self.client("Alice"), self.client("Alice")
        with patch("app.api.recommend_stream", side_effect=records), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(alice.post, "/recommend/stream", json={"seller": "shop"})
            try:
                self.assertTrue(started.wait(1))
                for endpoint in ("/recommend", "/recommend/stream"):
                    self.assertEqual(other_tab.post(endpoint, json={"seller": "shop"}).status_code, 409)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=5).status_code, 200)
        with patch("app.api.recommend", return_value={}):
            self.assertEqual(other_tab.post("/recommend", json={"seller": "shop"}).status_code, 200)

    def test_explicit_cancel_stops_only_matching_account_and_waits_for_exit(self):
        search_id = str(uuid4())
        started = Event()
        job = None
        def records(**kwargs):
            nonlocal job
            # The registered lease is held until this generator exits.
            job = search_registry._jobs["alice"]
            yield '{"type":"status"}\n'
            started.set()
            job.cancelled.wait(3)
            check_cancelled()
            yield '{"type":"done"}\n'
        alice, tab, bob = self.client("Alice"), self.client("Alice"), self.client("Bob")
        with patch("app.api.recommend_stream", side_effect=records), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(alice.post, "/recommend/stream", json={"seller": "shop", "search_id": search_id})
            self.assertTrue(started.wait(1))
            for client, identifier in ((bob, search_id), (tab, str(uuid4()))):
                response = client.post("/recommend/cancel", json={"search_id": identifier}, headers={"Origin": "http://localhost:5173"})
                self.assertEqual(response.json(), {"cancelled": False})
            self.assertFalse(job.cancelled.is_set())
            self.assertEqual(tab.post("/recommend/cancel", json={"search_id": search_id},
                                     headers={"Origin": "https://attacker.example"}).status_code, 403)
            response = tab.post("/recommend/cancel", json={"search_id": search_id}, headers={"Origin": "http://localhost:5173"})
            self.assertEqual(response.json(), {"cancelled": True})
            self.assertTrue(job.finished.is_set())
            self.assertEqual(pending.result(timeout=5).status_code, 200)

    def test_failed_regular_search_releases_slot(self):
        client = self.client("Alice")
        with patch("app.api.recommend", side_effect=ValueError("Invalid seller")):
            self.assertEqual(client.post("/recommend", json={"seller": "shop"}).status_code, 400)
        with patch("app.api.recommend", return_value={}):
            self.assertEqual(client.post("/recommend", json={"seller": "shop"}).status_code, 200)

    def test_cancel_applies_to_regular_endpoint_and_releases_slot(self):
        search_id = str(uuid4())
        started = Event()
        def recommend(**kwargs):
            job = search_registry._jobs["alice"]
            started.set()
            job.cancelled.wait(3)
            check_cancelled()
            return {}
        alice, tab = self.client("Alice"), self.client("Alice")
        with patch("app.api.recommend", side_effect=recommend), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(alice.post, "/recommend", json={"seller": "shop", "search_id": search_id})
            self.assertTrue(started.wait(1))
            response = tab.post("/recommend/cancel", json={"search_id": search_id}, headers={"Origin": "http://localhost:5173"})
            self.assertEqual(response.json(), {"cancelled": True})
            self.assertEqual(pending.result(timeout=5).status_code, 499)
        with patch("app.api.recommend", return_value={}):
            self.assertEqual(tab.post("/recommend", json={"seller": "shop"}).status_code, 200)

    def test_full_search_capacity_keeps_health_login_and_cancellation_responsive(self):
        started = {name: Event() for name in ("Alice", "Bob")}
        cookies = {name: {"Cookie": "dside_session=" + self.store.create("session", {
            "username": name, "token": name + "-token", "secret": name + "-secret",
        }, 3600)} for name in ("Alice", "Bob", "Charlie")}

        def work(username, **kwargs):
            if username in started:
                job = search_registry._jobs[username.casefold()]
                started[username].set()
                job.cancelled.wait(5)
                check_cancelled()
            return {"username": username}

        def records(**kwargs):
            yield '{"type":"status"}\n'
            work(**kwargs)
            yield '{"type":"done"}\n'

        async def run():
            default = anyio.to_thread.current_default_thread_limiter()
            original = default.total_tokens
            # Saturate both search workers while allowing just one default worker.
            default.total_tokens = 1
            tasks = []
            ids = {name: str(uuid4()) for name in started}
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://localhost:5173") as client:
                    tasks = [asyncio.create_task(client.post(endpoint, headers=cookies[name],
                        json={"seller": "shop", "search_id": ids[name]}))
                        for name, endpoint in (("Alice", "/recommend"), ("Bob", "/recommend/stream"))]
                    try:
                        with anyio.fail_after(2):
                            while not all(event.is_set() for event in started.values()):
                                await anyio.sleep(0.005)
                        self.assertEqual(default.borrowed_tokens, 0)
                        with anyio.fail_after(2):
                            self.assertEqual((await client.get("/health")).status_code, 200)
                            self.assertEqual((await client.get("/auth/me", headers=cookies["Alice"])).status_code, 200)
                            self.assertEqual((await client.get("/auth/discogs/login")).status_code, 302)
                            for endpoint in ("/recommend", "/recommend/stream"):
                                response = await client.post(endpoint, headers=cookies["Charlie"], json={"seller": "shop"})
                                self.assertEqual(response.status_code, 503)
                                self.assertEqual(response.headers["Retry-After"], "5")
                            response = await client.post("/recommend", headers=cookies["Alice"], json={"seller": "shop"})
                            self.assertEqual(response.status_code, 409)
                            for name in ("Bob", "Alice"):
                                response = await client.post("/recommend/cancel",
                                    headers={**cookies[name], "Origin": "http://localhost:5173"},
                                    json={"search_id": ids[name]})
                                self.assertEqual(response.json(), {"cancelled": True})
                            response = await client.post("/recommend", headers=cookies["Charlie"], json={"seller": "shop"})
                            self.assertEqual(response.status_code, 200)
                    finally:
                        for name in started:
                            search_registry.cancel(name, ids[name])
                        with anyio.fail_after(6):
                            results = await asyncio.gather(*tasks)
                    self.assertEqual([response.status_code for response in results], [499, 200])
            finally:
                default.total_tokens = original

        with patch.object(search_registry, "max_active", 2), \
             patch("app.search_response.get_settings", return_value=Settings(max_concurrent_searches=2)), \
             patch("app.api.recommend", side_effect=work), \
             patch("app.api.recommend_stream", side_effect=records), \
             patch.object(self.services.oauth, "begin", return_value={"oauth_token": "fake", "oauth_token_secret": "fake"}):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
