import threading
import time
import unittest
from unittest.mock import patch

import httpx

from app.services.discogs_http import _RequestPacer
from app.services.search_control import SearchCancelled, search_cancellation


class RequestPacingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds

    def test_account_backoff_and_extra_delay_do_not_hold_up_other_accounts(self):
        pacer = _RequestPacer()
        with patch("app.services.discogs_http.time.monotonic", side_effect=lambda: self.now), \
             patch("app.services.discogs_http.interruptible_wait", side_effect=self.advance):
            pacer.wait(0, account="Alice")
            pacer.defer(10, account="Alice")
            pacer.wait(0, account="Bob")
            self.assertAlmostEqual(self.now, 1.1)
            pacer.wait(0, account="Alice")
            self.assertAlmostEqual(self.now, 10)
            pacer.wait(20, account="Alice")
            self.assertAlmostEqual(self.now, 30)
            pacer.wait(0, account="Bob")
            self.assertAlmostEqual(self.now, 31.1)

    def test_shared_rate_limit_cooldown_still_applies_to_other_accounts(self):
        pacer = _RequestPacer()
        with patch("app.services.discogs_http.time.monotonic", side_effect=lambda: self.now), \
             patch("app.services.discogs_http.interruptible_wait", side_effect=self.advance):
            pacer.wait(0, account="Alice")
            pacer.defer(10)
            pacer.wait(0, account="Bob")
            self.assertEqual(self.now, 10)

    def test_reported_lower_limit_and_exhausted_budget_are_respected(self):
        pacer = _RequestPacer()
        with patch("app.services.discogs_http.time.monotonic", side_effect=lambda: self.now), \
             patch("app.services.discogs_http.interruptible_wait", side_effect=self.advance):
            pacer.wait(0, account="Alice")
            pacer.observe(httpx.Response(200, headers={"X-Discogs-Ratelimit": "30"}))
            pacer.wait(0, account="Bob")
            self.assertAlmostEqual(self.now, 2.1)
            pacer.observe(httpx.Response(200, headers={"X-Discogs-Ratelimit-Remaining": "0"}))
            pacer.wait(0, account="Alice")
            self.assertAlmostEqual(self.now, 62.1)
            for value in ("invalid", "nan", "-1", "9" * 500):
                pacer.observe(httpx.Response(200, headers={"X-Discogs-Ratelimit": value}))

    def test_cancelled_account_cooldown_does_not_block_an_eligible_caller(self):
        pacer = _RequestPacer(interval=0.01)
        pacer.defer(60, account="Alice")
        event = threading.Event()
        waiting = threading.Event()
        cancelled = threading.Event()
        def alice():
            try:
                with search_cancellation(event):
                    waiting.set()
                    pacer.wait(0, account="Alice")
            except SearchCancelled:
                cancelled.set()
        thread = threading.Thread(target=alice)
        thread.start()
        try:
            self.assertTrue(waiting.wait(1))
            pacer.wait(0, account="Bob")
            self.assertFalse(cancelled.is_set())
        finally:
            event.set()
            thread.join(timeout=1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(pacer._queue, [])

    def test_eligible_requests_take_turns_in_queue_order(self):
        pacer = _RequestPacer(interval=0.01)
        pacer.defer(0.1)
        order = []
        def wait(account):
            pacer.wait(0, account=account)
            order.append(account)
        threads = []
        try:
            for index, account in enumerate(("Alice", "Bob")):
                thread = threading.Thread(target=wait, args=(account,))
                threads.append(thread)
                thread.start()
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    with pacer._lock:
                        if len(pacer._queue) == index + 1:
                            break
                    time.sleep(0.001)
                else:
                    self.fail("Request did not enter the pacing queue")
        finally:
            for thread in threads:
                thread.join(timeout=1)
        self.assertEqual(order, ["Alice", "Bob"])

    def test_idle_account_state_is_pruned_without_losing_active_cooldowns(self):
        pacer = _RequestPacer()
        with patch("app.services.discogs_http.time.monotonic", side_effect=lambda: self.now), \
             patch("app.services.discogs_http.interruptible_wait", side_effect=self.advance):
            pacer.wait(0, account="Alice")
            pacer.defer(120, account="Alice")
            pacer.wait(0, account="Bob")
            self.now = 100
            pacer.wait(0, account="Charlie")
            self.assertIn("Alice", pacer._accounts)
            self.assertNotIn("Bob", pacer._accounts)


if __name__ == "__main__":
    unittest.main()
