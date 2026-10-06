import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import api
from app.config import Settings
from app.models.release import Release
from app.services.auth_store import AuthStore
from app.services.cache_service import SQLiteCache
from app.services.maintenance import clear_expired
from app.services.release_cache import ReleaseCache


class StorageMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.auth = AuthStore(Path(self.temp.name) / "auth.sqlite3", Fernet.generate_key().decode(), clock=lambda: self.now)
        self.cache = SQLiteCache(Path(self.temp.name) / "cache.sqlite3", clock=lambda: self.now)

    def test_session_read_completes_while_writer_holds_transaction(self):
        identifier = self.auth.create("session", {"username": "Alice"}, 100)
        with self.auth.connect() as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE auth_records SET expires_at = expires_at + 100")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.auth.read, "session", identifier)
                try:
                    self.assertEqual(future.result(timeout=1), {"username": "Alice"})
                finally:
                    writer.rollback()

    def test_expired_reads_are_read_only_and_sweep_removes_records(self):
        identifier = self.auth.create("session", {"username": "Alice"}, 10)
        self.cache.set("collection", "Alice", {"ids": []}, ttl_seconds=10)
        self.now += 10
        with self.auth.connect() as writer:
            writer.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.auth.read, "session", identifier)
                try:
                    self.assertIsNone(future.result(timeout=1))
                finally:
                    writer.rollback()
        self.assertIsNone(self.cache.get("collection", "Alice"))
        with self.auth.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM auth_records").fetchone()[0], 1)
        clear_expired(self.auth, self.cache)
        with self.auth.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM auth_records").fetchone()[0], 0)
        with self.cache._connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM cache_entries").fetchone()[0], 0)

    def test_cache_reader_sees_committed_payload_during_write(self):
        self.cache.set("release", "1", {"title": "Old"})
        with self.cache._connect() as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE cache_entries SET payload = ?", ('{"title":"New"}',))
            self.assertEqual(self.cache.get("release", "1"), {"title": "Old"})
        self.assertEqual(self.cache.get("release", "1"), {"title": "New"})

    def test_failed_cleanup_does_not_skip_other_stores(self):
        busy = Mock()
        busy.clear_expired.side_effect = sqlite3.OperationalError("database locked")
        healthy = Mock()
        with self.assertLogs("app.services.maintenance", level="ERROR"):
            clear_expired(busy, healthy)
        healthy.clear_expired.assert_called_once()

    def test_startup_and_periodic_cleanup_follow_app_lifetime(self):
        periodic = threading.Event()
        cache = Mock()
        cache.clear_expired.side_effect = lambda: periodic.set() if cache.clear_expired.call_count >= 2 else None
        releases = Mock()
        with patch.object(api, "settings", Settings(cache_cleanup_interval_seconds=0.02)), \
             patch.object(api, "cache", cache), patch.object(api, "_release_cache", releases):
            with TestClient(api.app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertTrue(periodic.wait(1))
            self.assertGreaterEqual(cache.clear_expired.call_count, 2)
            self.assertGreaterEqual(releases.clear_expired.call_count, 2)


class ReleaseCacheTests(unittest.TestCase):
    def test_recency_eviction_keeps_hot_releases(self):
        cache = ReleaseCache(2, 60)
        for identifier in (1, 2):
            cache.set(identifier, Release(identifier, str(identifier)))
        cache.get(1)
        cache.set(3, Release(3, "3"))
        self.assertIsNone(cache.get(2))
        self.assertEqual(cache.get(1).id, 1)
        self.assertEqual(len(cache), 2)

    def test_expired_entries_are_removed_before_evicting_valid_entries(self):
        now = [0.0]
        cache = ReleaseCache(2, 10, clock=lambda: now[0])
        cache.set(1, Release(1, "1"))
        now[0] = 5
        cache.set(2, Release(2, "2"))
        cache.get(1)  # The oldest release is now the most recently used.
        now[0] = 10
        cache.set(3, Release(3, "3"))
        self.assertIsNone(cache.get(1))
        self.assertIsNotNone(cache.get(2))
        now[0] = 20
        cache.clear_expired()
        self.assertEqual(len(cache), 0)

    def test_concurrent_access_respects_size_limit(self):
        cache = ReleaseCache(20, 60)
        def use(identifier):
            cache.set(identifier, Release(identifier, str(identifier)))
            cache.get(identifier)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(use, range(100)))
        self.assertLessEqual(len(cache), 20)


if __name__ == "__main__":
    unittest.main()
