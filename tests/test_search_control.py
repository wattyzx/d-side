import asyncio
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import anyio
import httpx

from app.search_response import SearchStreamingResponse
from app.services import discogs_http
from app.services.discogs_session import DiscogsCredentials, discogs_session
from app.services.search_control import (
    SearchAlreadyRunning, SearchCancelled, SearchCapacityReached, SearchRegistry,
    check_cancelled, search_cancellation, search_registry,
)


class SearchControlTests(unittest.TestCase):
    def setUp(self):
        self.account = DiscogsCredentials("test-cancel-user", "token", "secret", "consumer", "secret")

    def test_account_limit_and_cancel_identifier(self):
        registry = SearchRegistry()
        alice = registry.start("Alice", "alice-search")
        bob = registry.start("Bob", "bob-search")
        with self.assertRaises(SearchAlreadyRunning):
            registry.start("ALICE")
        self.assertIsNone(registry.cancel("Alice", "bob-search"))
        self.assertIsNone(registry.cancel("Bob", "alice-search"))
        self.assertFalse(alice.cancelled.is_set())
        self.assertIs(registry.cancel("alice", "alice-search"), alice)
        with self.assertRaises(SearchAlreadyRunning):
            registry.start("Alice")
        registry.finish(alice)
        replacement = registry.start("Alice", "replacement")
        self.assertIsNone(registry.cancel("Alice", "alice-search"))
        registry.finish(alice)  # Late cleanup cannot remove a replacement job.
        with self.assertRaises(SearchAlreadyRunning):
            registry.start("Alice")
        registry.finish(replacement)
        registry.finish(bob)

    def test_pacing_wait_is_interruptible_without_another_http_request(self):
        event = threading.Event()
        entered = threading.Event()
        errors = []
        pacer = discogs_http._RequestPacer()
        pacer.defer(60)
        def work():
            try:
                with search_cancellation(event):
                    entered.set()
                    pacer.wait(1.1)
            except SearchCancelled:
                errors.append("cancelled")
        thread = threading.Thread(target=work)
        thread.start()
        self.assertTrue(entered.wait(1))
        event.set()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["cancelled"])

    def test_global_capacity_is_atomic_and_cancel_keeps_slot_until_worker_finishes(self):
        registry = SearchRegistry(max_active=2)
        barrier = threading.Barrier(8)
        def start(index):
            barrier.wait(timeout=2)
            try:
                return registry.start(str(index))
            except SearchCapacityReached:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [job for job in pool.map(start, range(8)) if job is not None]
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        registry.cancel(job.username, job.search_id)
        with self.assertRaises(SearchCapacityReached):
            registry.start("replacement")
        registry.finish(job)
        replacement = registry.start("replacement")
        registry.finish(job)  # Repeated cleanup must not free another slot.
        with self.assertRaises(SearchCapacityReached):
            registry.start("overflow")
        registry.finish(replacement)
        registry.finish(jobs[1])

    def test_cancellation_after_inflight_http_call_prevents_retry(self):
        event = threading.Event()
        def response(*args, **kwargs):
            event.set()
            return httpx.Response(503, request=httpx.Request("GET", "https://api.discogs.com/test"))
        with discogs_session(self.account), search_cancellation(event), \
             patch.object(discogs_http, "_pacer", discogs_http._RequestPacer()), \
             patch.object(discogs_http.httpx, "get", side_effect=response) as get:
            with self.assertRaises(SearchCancelled):
                discogs_http.get_json("/test")
        self.assertEqual(get.call_count, 1)

    def test_disconnect_stops_worker_on_both_asgi_versions_and_releases_slot(self):
        for spec in ("2.0", "2.4"):
            with self.subTest(spec=spec):
                job = search_registry.start(self.account.username)
                started = threading.Event()
                closed = threading.Event()
                calls = []
                def records():
                    try:
                        yield '{"type":"status"}\n'
                        started.set()
                        job.cancelled.wait(2)
                        check_cancelled()
                        calls.append("unexpected-next-request")
                        yield '{"type":"done"}\n'
                    finally:
                        closed.set()
                response = SearchStreamingResponse(records(), self.account, job)
                async def receive():
                    await anyio.to_thread.run_sync(started.wait)
                    return {"type": "http.disconnect"}
                async def send(message):
                    pass
                asyncio.run(response({"type": "http", "asgi": {"spec_version": spec}}, receive, send))
                self.assertEqual(calls, [])
                self.assertTrue(closed.is_set())
                self.assertTrue(job.finished.is_set())
                next_job = search_registry.start(self.account.username)
                search_registry.finish(next_job)

    def test_stream_delivers_events_and_heartbeats_before_worker_finishes(self):
        job = search_registry.start(self.account.username)
        heartbeat_received = threading.Event()
        messages = []

        def records():
            yield '{"type":"status"}\n'
            if not heartbeat_received.wait(2):
                raise AssertionError("No heartbeat while the worker was blocked")
            yield '{"type":"done"}\n'

        response = SearchStreamingResponse(records(), self.account, job)

        async def receive():
            await anyio.sleep_forever()

        async def send(message):
            messages.append(message)
            if message.get("body") == b"\n":
                self.assertTrue(any(item.get("body") == b'{"type":"status"}\n'
                                    for item in messages))
                heartbeat_received.set()

        with patch("app.search_response.STREAM_HEARTBEAT_SECONDS", 0.02):
            asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"cache-control"], b"no-store, no-transform")
        self.assertEqual(headers[b"x-accel-buffering"], b"no")
        self.assertTrue(heartbeat_received.is_set())
        self.assertTrue(any(item.get("body") == b'{"type":"done"}\n' for item in messages))
        self.assertFalse(messages[-1]["more_body"])
        self.assertTrue(job.finished.is_set())

    def test_send_failure_and_parent_cancellation_release_admission(self):
        for mode in ("send-failure", "parent-cancellation"):
            with self.subTest(mode=mode):
                job = search_registry.start(self.account.username)
                started = threading.Event()
                def records():
                    started.set()
                    if mode == "parent-cancellation":
                        job.cancelled.wait(2)
                        check_cancelled()
                    yield '{"type":"done"}\n'
                response = SearchStreamingResponse(records(), self.account, job)
                async def receive():
                    await anyio.sleep_forever()
                async def send(message):
                    if mode == "send-failure":
                        raise OSError("connection closed")
                async def run():
                    async with anyio.create_task_group() as group:
                        group.start_soon(response, {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
                        if mode == "parent-cancellation":
                            await anyio.to_thread.run_sync(started.wait)
                            group.cancel_scope.cancel()
                asyncio.run(run())
                self.assertTrue(job.finished.is_set())


if __name__ == "__main__":
    unittest.main()
