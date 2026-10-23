"""Daily pseudonymous search activity in the configured authentication database."""

import hashlib
import hmac
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from app.services.database import DatabaseError

logger = logging.getLogger(__name__)
RETENTION_DAYS = 90


class UsageStore:
    def __init__(self, database, secret, clock=time.time):
        self.database = database
        self.key = hmac.digest(secret.encode(), b"d-side/search-activity/v1", "sha256")
        self.clock = clock

    def today(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).date()

    @staticmethod
    def schema(db):
        db.execute("""CREATE TABLE IF NOT EXISTS search_activity (
            activity_date TEXT NOT NULL,
            account_hash TEXT NOT NULL,
            PRIMARY KEY (activity_date, account_hash)
        )""")

    def record_search(self, username):
        account_hash = hmac.new(self.key, username.casefold().encode(), hashlib.sha256).hexdigest()
        try:
            with self.database.connect() as db:
                self.schema(db)
                db.execute("INSERT OR IGNORE INTO search_activity VALUES (?, ?)",
                           (self.today().isoformat(), account_hash))
        except (DatabaseError, sqlite3.Error):
            # Do not expose identities or credentials in logs, or fail searches.
            logger.warning("Could not record search activity; usage counts may be incomplete")

    def clear_expired(self):
        cutoff = (self.today() - timedelta(days=RETENTION_DAYS - 1)).isoformat()
        with self.database.connect() as db:
            self.schema(db)
            db.execute("DELETE FROM search_activity WHERE activity_date < ?", (cutoff,))

    def counts(self):
        today = self.today()
        with self.database.connect() as db:
            self.schema(db)
            row = db.execute("""SELECT
                COUNT(DISTINCT CASE WHEN activity_date = ? THEN account_hash END),
                COUNT(DISTINCT CASE WHEN activity_date >= ? THEN account_hash END),
                COUNT(DISTINCT account_hash)
                FROM search_activity WHERE activity_date >= ? AND activity_date <= ?""",
                (today.isoformat(), (today - timedelta(days=6)).isoformat(),
                 (today - timedelta(days=29)).isoformat(), today.isoformat())).fetchone()
        return dict(zip(("today", "last_7_days", "last_30_days"), row))
