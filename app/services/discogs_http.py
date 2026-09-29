"""Shared pacing and bounded retries for Discogs GET requests."""

import math
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


BASE_URL = "https://api.discogs.com"
REQUEST_INTERVAL = 1.1
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 60.0
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class _RequestPacer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request_at: float | None = None
        self._retry_at = 0.0

    def wait(self, min_interval: float) -> None:
        with self._lock:
            ready_at = self._retry_at
            if self._last_request_at is not None:
                ready_at = max(
                    ready_at,
                    self._last_request_at + max(REQUEST_INTERVAL, min_interval),
                )
            remaining = ready_at - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def defer(self, delay: float) -> None:
        with self._lock:
            self._retry_at = max(self._retry_at, time.monotonic() + delay)


_pacer = _RequestPacer()


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Accept both Retry-After forms; fall back to exponential backoff."""
    value = response.headers.get("Retry-After")
    if value is not None:
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = float("nan")
        if math.isfinite(seconds):
            return max(0.0, seconds)
    return float(2 ** attempt)


def get_json(
    path: str,
    *,
    params: dict | None = None,
    min_interval: float = REQUEST_INTERVAL,
) -> dict:
    if not math.isfinite(min_interval) or min_interval < 0:
        raise ValueError("min_interval must be finite and non-negative")

    token = os.getenv("DISCOGS_TOKEN")
    if not token:
        raise RuntimeError("DISCOGS_TOKEN is missing from .env")

    headers = {
        "Authorization": f"Discogs token={token}",
        "User-Agent": "D(e)Side/0.1",
    }
    for attempt in range(MAX_ATTEMPTS):
        _pacer.wait(min_interval)
        try:
            response = httpx.get(
                f"{BASE_URL}{path}", headers=headers, params=params, timeout=10.0,
            )
        except httpx.TransportError:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            _pacer.defer(float(2 ** attempt))
            continue

        if response.status_code in RETRYABLE_STATUSES:
            delay = _retry_delay(response, attempt)
            _pacer.defer(delay)
            # Do not retry earlier than requested by the server. Surface long
            # cooldowns rather than blocking this operation indefinitely.
            if attempt < MAX_ATTEMPTS - 1 and delay <= MAX_RETRY_DELAY:
                continue

        response.raise_for_status()
        return response.json()

    raise RuntimeError("Discogs request attempts exhausted")
