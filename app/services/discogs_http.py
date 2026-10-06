"""Shared pacing and bounded retries for Discogs requests."""

import math
from dataclasses import dataclass
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from oauthlib.oauth1 import Client
from app.services.discogs_session import current_credentials
from app.services.search_control import check_cancelled, interruptible_wait


BASE_URL = "https://api.discogs.com"
REQUEST_INTERVAL = 1.1
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 60.0
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class _AccountTiming:
    last_request_at: float | None = None
    retry_at: float = 0.0
    retain_until: float = 0.0


@dataclass(eq=False)
class _Waiter:
    account: str | None
    min_interval: float


class _RequestPacer:
    def __init__(self, interval: float = REQUEST_INTERVAL) -> None:
        self._lock = threading.Lock()
        self._interval = interval
        self._base_interval = interval
        self._last_request_at: float | None = None
        self._retry_at = 0.0
        self._accounts: dict[str | None, _AccountTiming] = {}
        self._queue: list[_Waiter] = []

    def _prune(self, now):
        waiting = {waiter.account for waiter in self._queue}
        expired = [account for account, timing in self._accounts.items()
                   if account not in waiting and max(timing.retain_until, timing.retry_at) <= now]
        for account in expired:
            del self._accounts[account]

    def _account_ready_at(self, waiter):
        timing = self._accounts[waiter.account]
        ready_at = timing.retry_at
        if timing.last_request_at is not None:
            ready_at = max(ready_at, timing.last_request_at + max(self._interval, waiter.min_interval))
        return ready_at

    def wait(self, min_interval: float, *, account: str | None = None) -> None:
        waiter = _Waiter(account, min_interval)
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._accounts.setdefault(account, _AccountTiming())
            self._queue.append(waiter)
        try:
            while True:
                check_cancelled()
                with self._lock:
                    now = time.monotonic()
                    ready = [candidate for candidate in self._queue
                             if self._account_ready_at(candidate) <= now]
                    # FIFO among eligible requests. A caller in its own cooldown
                    # does not prevent another account using an available slot.
                    winner = ready[0] if ready else min(self._queue, key=self._account_ready_at)
                    global_ready_at = self._retry_at
                    if self._last_request_at is not None:
                        global_ready_at = max(global_ready_at, self._last_request_at + self._interval)
                    remaining = max(global_ready_at, self._account_ready_at(waiter)) - now
                    if winner is waiter and remaining <= 0:
                        check_cancelled()
                        self._last_request_at = now
                        timing = self._accounts[account]
                        timing.last_request_at = now
                        timing.retain_until = now + max(60, min_interval)
                        return
                    delay = min(60, max(0.001, remaining)) if winner is waiter else 0.05
                interruptible_wait(delay)
        finally:
            with self._lock:
                self._queue.remove(waiter)

    def defer(self, delay: float, *, account: str | None = None) -> None:
        with self._lock:
            ready_at = time.monotonic() + delay
            if account is None:
                # Rate-limit responses may describe a shared quota. Preserve a
                # global cooldown rather than assume independent OAuth quotas.
                self._retry_at = max(self._retry_at, ready_at)
            else:
                timing = self._accounts.setdefault(account, _AccountTiming())
                timing.retry_at = max(timing.retry_at, ready_at)
                timing.retain_until = max(timing.retain_until, ready_at)

    def observe(self, response: httpx.Response):
        try:
            limit = int(response.headers["X-Discogs-Ratelimit"])
        except (KeyError, ValueError):
            limit = 0
        if 0 < limit < 1_000_000_000:
            with self._lock:
                self._interval = max(self._base_interval, 60 / limit + 0.1)
        try:
            remaining = int(response.headers["X-Discogs-Ratelimit-Remaining"])
        except (KeyError, ValueError):
            return
        if remaining <= 0:
            delay = _retry_delay(response, 0) if "Retry-After" in response.headers else 60.0
            self.defer(delay)


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
    return _request_json("GET", path, params=params, min_interval=min_interval)


def put_json(path: str, *, payload: dict) -> dict:
    return _request_json("PUT", path, payload=payload)


def _request_json(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    payload: dict | None = None,
    min_interval: float = REQUEST_INTERVAL,
) -> dict:
    if not math.isfinite(min_interval) or min_interval < 0:
        raise ValueError("min_interval must be finite and non-negative")

    credentials = current_credentials()
    signer = Client(credentials.consumer_key, client_secret=credentials.consumer_secret,
                    resource_owner_key=credentials.token, resource_owner_secret=credentials.secret)
    url = f"{BASE_URL}{path}"
    signed_url = str(httpx.URL(url, params=params)) if params else url
    account = credentials.username.casefold()
    for attempt in range(MAX_ATTEMPTS):
        _pacer.wait(min_interval, account=account)
        check_cancelled()
        # Include GET query parameters and generate a fresh nonce on every retry.
        _, headers, _ = signer.sign(signed_url, http_method=method,
                                   headers={"User-Agent": "D(e)Side/0.1"})
        try:
            if method == "GET":
                response = httpx.get(
                    f"{BASE_URL}{path}", headers=headers, params=params, timeout=10.0,
                )
            else:
                response = httpx.put(
                    f"{BASE_URL}{path}", headers=headers, json=payload, timeout=10.0,
                )
        except httpx.TransportError:
            check_cancelled()
            if attempt == MAX_ATTEMPTS - 1:
                raise
            _pacer.defer(float(2 ** attempt), account=account)
            continue

        # Keep feedback from a completed request even if its search was
        # cancelled in flight: the shared quota still applies to other callers.
        _pacer.observe(response)
        delay = None
        if response.status_code in RETRYABLE_STATUSES:
            delay = _retry_delay(response, attempt)
            _pacer.defer(delay, account=None if response.status_code == 429 else account)
        check_cancelled()
        # Do not retry earlier than requested by the server. Surface long
        # cooldowns rather than blocking this operation indefinitely.
        if delay is not None and attempt < MAX_ATTEMPTS - 1 and delay <= MAX_RETRY_DELAY:
            continue

        response.raise_for_status()
        return response.json()

    raise RuntimeError("Discogs request attempts exhausted")
