from app.services.release_cache import ReleaseCache
from contextvars import Context
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from app.services import discogs_client, discogs_http, inventory_service
from app.models.listing import Listing
from app.services.cache_service import SQLiteCache
from app.services.discogs_session import DiscogsCredentials, discogs_session
from app.services.search_control import SearchCancelled, search_cancellation

def response(status=200, data=None, headers=None):
    return httpx.Response(
        status,
        json={} if data is None else data,
        headers=headers,
        request=httpx.Request("GET", "https://api.discogs.com/test"),
    )


class DiscogsRequestTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        cache = SQLiteCache(Path(temp_dir.name) / "cache.sqlite3")
        scope = discogs_session(DiscogsCredentials("Owner", "test-token", "test-secret", "consumer", "consumer-secret"))
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)
        self.now = 0.0
        self.started = []
        for patcher in (
            patch.object(discogs_client, "cache", cache),
            patch.object(discogs_http, "_pacer", discogs_http._RequestPacer()),
            patch.object(discogs_http.time, "monotonic", side_effect=lambda: self.now),
            patch.object(discogs_http.time, "sleep", side_effect=self.sleep),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(discogs_http.httpx, "get", side_effect=self.get)
        self.http_get = patcher.start()
        self.addCleanup(patcher.stop)
        self.responses = iter([])

    def sleep(self, seconds):
        self.assertGreaterEqual(seconds, 0)
        self.now += seconds

    def get(self, *args, **kwargs):
        self.started.append(self.now)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def test_all_endpoints_share_pacing_and_keep_request_parameters(self):
        self.responses = iter([response()] * 5)

        discogs_client.get_release_raw(999999)
        discogs_client.get_collection_raw("test_pacing_user_12345", page=2)
        discogs_client.get_inventory_raw("test_pacing_seller_12345", page=3)
        discogs_client.get_wantlist_raw("test_pacing_user_12345", page=4)
        discogs_client.search_releases_by_style_raw("TestPacingHouse12345")

        for previous, current in zip(self.started, self.started[1:]):
            self.assertAlmostEqual(current - previous, 1.1)

        calls = self.http_get.call_args_list
        self.assertEqual(len(calls), 5)

        self.assertTrue(calls[0].args[0].endswith("/releases/999999"))
        self.assertEqual(
            calls[1].kwargs["params"],
            {"page": 2, "per_page": 100},
        )
        self.assertEqual(calls[2].kwargs["params"]["page"], 3)
        self.assertEqual(calls[3].kwargs["params"]["page"], 4)
        self.assertEqual(calls[4].kwargs["params"]["style"], "TestPacingHouse12345")

    def test_inventory_pagination_uses_shared_pacing(self):
        self.responses = iter([
            response(data={"listings": [], "pagination": {"pages": 2}}),
            response(data={"listings": [], "pagination": {"pages": 2}}),
        ])
        self.assertEqual(discogs_client.get_inventory("seller"), [])
        self.assertEqual(self.started, [0, 1.1])

    def test_rate_limit_honors_retry_after(self):
        self.responses = iter([response(429, headers={"Retry-After": "5"}), response(data={"ok": True})])
        self.assertEqual(discogs_http.get_json("/test"), {"ok": True})
        self.assertEqual(self.started, [0, 5])

    def test_retry_after_http_date(self):
        self.responses = iter([
            response(503, headers={"Retry-After": "Tue, 29 Sep 2026 12:00:05 GMT"}),
            response(),
        ])
        with patch.object(discogs_http, "datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
            discogs_http.get_json("/test")
        self.assertEqual(self.started, [0, 5])

    def test_timeout_and_server_error_retry_with_backoff(self):
        self.responses = iter([httpx.ReadTimeout("timeout"), response(502), response()])
        self.assertEqual(discogs_http.get_json("/test"), {})
        self.assertEqual(self.started, [0, 1.1, 3.1])

    def test_server_failures_defer_only_the_current_account(self):
        self.responses = iter([response(503), response()])
        with patch.object(discogs_http._pacer, "defer", wraps=discogs_http._pacer.defer) as defer:
            discogs_http.get_json("/test")
        self.assertEqual(defer.call_args.kwargs, {"account": "owner"})

    def test_rate_limits_defer_the_shared_budget(self):
        self.responses = iter([response(429), response()])
        with patch.object(discogs_http._pacer, "defer", wraps=discogs_http._pacer.defer) as defer:
            discogs_http.get_json("/test")
        self.assertEqual(defer.call_args.kwargs, {"account": None})

    def test_cancelled_inflight_response_still_paces_other_accounts_without_retrying(self):
        cases = (
            (429, {"Retry-After": "30"}, 30),
            (429, {"Retry-After": "30", "X-Discogs-Ratelimit-Remaining": "0"}, 30),
            (429, {"Retry-After": "120"}, 120),
            (429, {}, 1.1),
            (200, {"X-Discogs-Ratelimit-Remaining": "0"}, 60),
            (200, {"X-Discogs-Ratelimit": "30"}, 2.1),
        )
        for status, headers, expected_delay in cases:
            with self.subTest(status=status, headers=headers):
                self.now = 0.0
                self.started.clear()
                self.http_get.reset_mock()
                cancelled = threading.Event()
                self.responses = iter([response(status, headers=headers), response(data={"ok": True})])
                def cancel_inflight(*args, **kwargs):
                    result = self.get(*args, **kwargs)
                    cancelled.set()
                    return result
                with patch.object(discogs_http, "_pacer", discogs_http._RequestPacer()):
                    self.http_get.side_effect = cancel_inflight
                    try:
                        with search_cancellation(cancelled), self.assertRaises(SearchCancelled):
                            discogs_http.get_json("/test")
                    finally:
                        self.http_get.side_effect = self.get
                    self.assertEqual(self.http_get.call_count, 1)
                    with discogs_session(DiscogsCredentials("Other", "fake", "fake", "fake", "fake")):
                        self.assertEqual(discogs_http.get_json("/test"), {"ok": True})
                self.assertEqual(self.http_get.call_count, 2)
                self.assertEqual(self.started, [0, expected_delay])

    def test_http_retries_are_bounded(self):
        self.responses = iter([response(503)] * 3)
        with self.assertRaises(httpx.HTTPStatusError):
            discogs_http.get_json("/test")
        self.assertEqual(self.http_get.call_count, 3)

    def test_transport_retries_are_bounded(self):
        self.responses = iter([httpx.ConnectError("unreachable")] * 3)
        with self.assertRaises(httpx.ConnectError):
            discogs_http.get_json("/test")
        self.assertEqual(self.http_get.call_count, 3)

    def test_permanent_error_is_not_retried(self):
        self.responses = iter([response(404)])
        with self.assertRaises(httpx.HTTPStatusError):
            discogs_http.get_json("/test")
        self.assertEqual(self.http_get.call_count, 1)

    def test_long_retry_after_fails_without_waiting_or_retrying_early(self):
        self.responses = iter([response(429, headers={"Retry-After": "120"})])
        with self.assertRaises(httpx.HTTPStatusError):
            discogs_http.get_json("/test")
        self.assertEqual(self.started, [0])
        self.assertEqual(self.now, 0)

    def test_invalid_retry_after_falls_back_to_backoff(self):
        self.responses = iter([response(503, headers={"Retry-After": "invalid"}), response()])
        discogs_http.get_json("/test")
        self.assertEqual(self.started, [0, 1.1])

    def test_cache_hits_do_not_fetch_or_wait(self):
        self.responses = iter([response(data={"id": 1, "title": "Record"})])
        item = Listing(1, 1, 10, "EUR", "Mint (M)")
        with patch.object(inventory_service, "_release_cache", ReleaseCache(1000, 21600)):
            inventory_service.link_inventory([item, item])
            inventory_service.link_inventory([item])
        self.assertEqual(self.started, [0])
        self.assertEqual(self.now, 0)
        
    def test_inventory_raw_uses_cache_per_page_and_seller(self):
        self.responses = iter([
            response(
                data={
                    "listings": ["seller_a_page_1"],
                    "pagination": {"pages": 2},
                }
            ),
            response(
                data={
                    "listings": ["seller_a_page_2"],
                    "pagination": {"pages": 2},
                }
            ),
            response(
                data={
                    "listings": ["seller_b_page_1"],
                    "pagination": {"pages": 1},
                }
            ),
        ])

        first = discogs_client.get_inventory_raw(
            "SellerA",
            page=1,
            per_page=100,
        )

        cached = discogs_client.get_inventory_raw(
            "SellerA",
            page=1,
            per_page=100,
        )

        second_page = discogs_client.get_inventory_raw(
            "SellerA",
            page=2,
            per_page=100,
        )

        other_seller = discogs_client.get_inventory_raw(
            "SellerB",
            page=1,
            per_page=100,
        )

        self.assertEqual(first["listings"], ["seller_a_page_1"])
        self.assertEqual(cached["listings"], ["seller_a_page_1"])
        self.assertEqual(second_page["listings"], ["seller_a_page_2"])
        self.assertEqual(other_seller["listings"], ["seller_b_page_1"])

        # 4 richieste logiche, ma solo 3 chiamate API:
        # SellerA/page1 → API
        # SellerA/page1 → CACHE
        # SellerA/page2 → API
        # SellerB/page1 → API
        self.assertEqual(self.http_get.call_count, 3)

        self.assertEqual(self.started, [0, 1.1, 2.2])

    def test_inventory_raw_supports_sorting_and_separates_cache_keys(self):
        self.responses = iter([
            response(data={"listings": ["artist"]}),
            response(data={"listings": ["price"]}),
        ])

        artist = discogs_client.get_inventory_raw(
            "SellerA",
            page=1,
            per_page=100,
            sort="artist",
            sort_order="asc",
        )

        # Deve essere cache hit
        artist_cached = discogs_client.get_inventory_raw(
            "SellerA",
            page=1,
            per_page=100,
            sort="artist",
            sort_order="asc",
        )

        # Sort diverso → cache miss
        price = discogs_client.get_inventory_raw(
            "SellerA",
            page=1,
            per_page=100,
            sort="price",
            sort_order="asc",
        )

        self.assertEqual(artist["listings"], ["artist"])
        self.assertEqual(artist_cached["listings"], ["artist"])
        self.assertEqual(price["listings"], ["price"])

        self.assertEqual(self.http_get.call_count, 2)

        calls = self.http_get.call_args_list

        self.assertEqual(
            calls[0].kwargs["params"],
            {
                "page": 1,
                "per_page": 100,
                "sort": "artist",
                "sort_order": "asc",
            },
        )

        self.assertEqual(
            calls[1].kwargs["params"],
            {
                "page": 1,
                "per_page": 100,
                "sort": "price",
                "sort_order": "asc",
            },
        )

    def test_custom_interval_can_increase_but_not_bypass_shared_pacing(self):
        self.responses = iter([response()] * 3)
        discogs_http.get_json("/test")
        discogs_http.get_json("/test", min_interval=3)
        discogs_http.get_json("/test", min_interval=0)
        self.assertEqual(self.started, [0, 3, 4.1])

    def test_missing_session_fails_before_request(self):
        with self.assertRaises(RuntimeError):
            Context().run(discogs_http.get_json, "/test")
        self.http_get.assert_not_called()

    def test_add_to_wantlist_uses_session_owner_and_invalidates_cache(self):
        discogs_client.cache.set("wantlist_raw:owner", "Owner:1:100", {"wants": []})
        with patch.object(discogs_http.httpx, "put", return_value=response(201)) as put:
            discogs_client.add_to_wantlist(123)
        self.assertEqual(put.call_args.args[0], "https://api.discogs.com/users/Owner/wants/123")
        self.assertEqual(put.call_args.kwargs["json"], {"release_id": 123})
        self.assertIn('oauth_token="test-token"', put.call_args.kwargs["headers"]["Authorization"])
        self.assertIn('oauth_signature_method="HMAC-SHA1"', put.call_args.kwargs["headers"]["Authorization"])
        self.assertAlmostEqual(self.now, 0)
        self.assertIsNone(discogs_client.cache.get("wantlist_raw:owner", "Owner:1:100"))

    def test_add_to_wantlist_requires_session_without_writing(self):
        with patch.object(discogs_http.httpx, "put") as put:
            with self.assertRaises(RuntimeError):
                Context().run(discogs_client.add_to_wantlist, 123)
        put.assert_not_called()

    def test_failed_wantlist_save_preserves_cached_wantlist(self):
        discogs_client.cache.set("wantlist_raw:owner", "Owner:1:100", {"wants": []})
        with patch.object(discogs_http.httpx, "put", return_value=response(403)) as put:
            with self.assertRaises(httpx.HTTPStatusError):
                discogs_client.add_to_wantlist(123)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(discogs_client.cache.get("wantlist_raw:owner", "Owner:1:100"), {"wants": []})

    def test_wantlist_put_retries_rate_limits_with_shared_pacing(self):
        with patch.object(discogs_http.httpx, "put", side_effect=[
            response(429, headers={"Retry-After": "5"}), response(201),
        ]) as put:
            discogs_http.put_json("/users/Owner/wants/123", payload={"release_id": 123})
        self.assertEqual(put.call_count, 2)
        self.assertEqual(self.now, 5)


if __name__ == "__main__":
    unittest.main()
