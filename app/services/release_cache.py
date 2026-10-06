"""Thread-safe TTL and least-recently-used cache for public release metadata."""

import threading
import time
from collections import OrderedDict

from app.models.release import Release


class ReleaseCache:
    def __init__(self, max_entries: int, ttl_seconds: int, clock=time.monotonic):
        if max_entries <= 0 or ttl_seconds <= 0:
            raise ValueError("Cache size and TTL must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries: OrderedDict[int, tuple[Release, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, release_id: int) -> Release | None:
        with self._lock:
            entry = self._entries.get(release_id)
            if entry is None:
                return None
            release, expires_at = entry
            if expires_at <= self.clock():
                del self._entries[release_id]
                return None
            self._entries.move_to_end(release_id)
            return release

    def set(self, release_id: int, release: Release):
        with self._lock:
            now = self.clock()
            self._clear_expired(now)
            self._entries[release_id] = (release, now + self.ttl_seconds)
            self._entries.move_to_end(release_id)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear_expired(self):
        with self._lock:
            self._clear_expired(self.clock())

    def _clear_expired(self, now):
        expired = [key for key, (_, expires_at) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]

    def __len__(self):
        with self._lock:
            return len(self._entries)
