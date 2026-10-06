"""One active scan per account, with cooperative cancellation of worker threads."""

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from app.config import get_settings


class SearchCancelled(Exception):
    pass


class SearchAlreadyRunning(Exception):
    pass


class SearchCapacityReached(Exception):
    pass


_cancelled: ContextVar[threading.Event | None] = ContextVar("search_cancelled", default=None)


@contextmanager
def search_cancellation(event: threading.Event):
    marker = _cancelled.set(event)
    try:
        yield
    finally:
        _cancelled.reset(marker)


def check_cancelled():
    event = _cancelled.get()
    if event is not None and event.is_set():
        raise SearchCancelled()


def interruptible_wait(seconds: float):
    event = _cancelled.get()
    if event is None:
        time.sleep(seconds)
    elif event.wait(seconds):
        raise SearchCancelled()


@dataclass
class SearchJob:
    username: str
    search_id: str
    cancelled: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)


class SearchRegistry:
    """Process-local: deploy one backend worker until admission is distributed."""

    def __init__(self, max_active: int | None = None):
        if max_active is not None and max_active < 1:
            raise ValueError("Search capacity must be positive")
        self.max_active = max_active
        self._lock = threading.Lock()
        self._jobs: dict[str, SearchJob] = {}

    def start(self, username: str, search_id: str | None = None) -> SearchJob:
        username = username.casefold()
        with self._lock:
            if username in self._jobs:
                raise SearchAlreadyRunning()
            limit = self.max_active if self.max_active is not None else get_settings().max_concurrent_searches
            if len(self._jobs) >= limit:
                raise SearchCapacityReached()
            job = SearchJob(username, search_id or str(uuid4()))
            self._jobs[username] = job
            return job

    def cancel(self, username: str, search_id: str) -> SearchJob | None:
        with self._lock:
            job = self._jobs.get(username.casefold())
            if not job or job.search_id != search_id:
                return None
            job.cancelled.set()
            return job

    def finish(self, job: SearchJob):
        with self._lock:
            if self._jobs.get(job.username) is job:
                del self._jobs[job.username]
            job.finished.set()


search_registry = SearchRegistry()
