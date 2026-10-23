import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.services.database import Database, DatabaseError
from app.services.usage_store import UsageStore


class UsageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.now = datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp()
        self.store = UsageStore(Database(Path(temp.name) / "usage.db"), "test-secret",
                                clock=lambda: self.now)

    def record_days_ago(self, days, username):
        self.now -= days * 86400
        try:
            self.store.record_search(username)
        finally:
            self.now += days * 86400

    def test_distinct_accounts_and_inclusive_utc_windows(self):
        self.assertEqual(self.store.counts(), dict(today=0, last_7_days=0, last_30_days=0))
        for days, name in [(0, "Alice"), (0, "ALICE"), (6, "alice"), (6, "Bob"),
                           (7, "Charlie"), (29, "Dora"), (30, "Eve"), (-1, "Future")]:
            self.record_days_ago(days, name)
        self.assertEqual(self.store.counts(), dict(today=1, last_7_days=2, last_30_days=4))
        with self.store.database.connect() as db:
            rows = db.execute("SELECT account_hash FROM search_activity").fetchall()
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(len(row[0]) == 64 and "Alice" not in row[0] for row in rows))

    def test_retention_boundary(self):
        self.record_days_ago(89, "Alice")
        self.record_days_ago(90, "Bob")
        self.store.clear_expired()
        with self.store.database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM search_activity").fetchone()[0], 1)

    def test_failure_is_logged_without_identity_and_does_not_raise(self):
        with patch.object(self.store.database, "connect", side_effect=DatabaseError("secret")):
            with self.assertLogs("app.services.usage_store", level="WARNING") as logs:
                self.store.record_search("Alice")
        self.assertNotIn("Alice", str(logs.output))
        self.assertNotIn("secret", str(logs.output))
