import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from app.services import discogs_client, discogs_http, inventory_service
from app.models.listing import Listing


def response(status=200, data=None, headers=None):
    return httpx.Response(
        status,
        json={} if data is None else data,
        headers=headers,
        request=httpx.Request("GET", "https://api.discogs.com/test"),
    )


class DiscogsRequestTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.started = []
        for patcher in (
            patch.dict(os.environ, {"DISCOGS_TOKEN": "test-token"}),
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
        discogs_client.get_release_raw(7)
        discogs_client.get_collection_raw("user", page=2)
        discogs_client.get_inventory_raw("seller", page=3)
        discogs_client.get_wantlist_raw("user", page=4)
        discogs_client.search_releases_by_style_raw("House")
        for previous, current in zip(self.started, self.started[1:]):
            self.assertAlmostEqual(current - previous, 1.1)
        calls = self.http_get.call_args_list
        self.assertTrue(calls[0].args[0].endswith("/releases/7"))
        self.assertEqual(calls[1].kwargs["params"], {"page": 2, "per_page": 100})
        self.assertEqual(calls[2].kwargs["params"]["page"], 3)
        self.assertEqual(calls[3].kwargs["params"]["page"], 4)
        self.assertEqual(calls[4].kwargs["params"]["style"], "House")

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
        with patch.dict(inventory_service._release_cache, {}, clear=True):
            inventory_service.link_inventory([item, item])
            inventory_service.link_inventory([item])
        self.assertEqual(self.started, [0])
        self.assertEqual(self.now, 0)

    def test_custom_interval_can_increase_but_not_bypass_shared_pacing(self):
        self.responses = iter([response()] * 3)
        discogs_http.get_json("/test")
        discogs_http.get_json("/test", min_interval=3)
        discogs_http.get_json("/test", min_interval=0)
        self.assertEqual(self.started, [0, 3, 4.1])

    def test_missing_token_fails_before_request(self):
        with patch.dict(os.environ, {"DISCOGS_TOKEN": ""}):
            with self.assertRaises(RuntimeError):
                discogs_http.get_json("/test")
        self.http_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
