"""Durable encrypted OAuth state and sessions, separate from disposable caches."""

import hashlib
import json
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from app.services.database import Database
from app.services.usage_store import UsageStore


class AuthStore:
    def __init__(self, db_path: Path, encryption_key: str, clock=time.time, *, database=None):
        self.clock = clock
        self.cipher = Fernet(encryption_key.encode())
        self.db_path = Path(db_path)
        self.database = database or Database(self.db_path, private=True)
        self.usage = UsageStore(self.database, encryption_key, clock)
        with self.connect() as db:
            self.database.configure(db)
            db.execute("""CREATE TABLE IF NOT EXISTS auth_records (
                kind TEXT NOT NULL, digest TEXT NOT NULL, payload BLOB NOT NULL,
                expires_at REAL NOT NULL, PRIMARY KEY (kind, digest)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS auth_expiry ON auth_records(expires_at)")

    def connect(self):
        return self.database.connect()

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def create(self, kind: str, payload: dict, ttl: int) -> str:
        identifier = secrets.token_urlsafe(32)
        encrypted = self.cipher.encrypt(json.dumps(payload).encode())
        with self.connect() as db:
            db.execute("DELETE FROM auth_records WHERE expires_at <= ?", (self.clock(),))
            db.execute("INSERT INTO auth_records VALUES (?, ?, ?, ?)",
                       (kind, self.digest(identifier), encrypted, self.clock() + ttl))
        return identifier

    def read(self, kind: str, identifier: str, *, consume=False) -> dict | None:
        with self.connect() as db:
            # Only consuming a token needs a write transaction. Ordinary session
            # reads remain read-only, even when the record has expired.
            if consume:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload, expires_at FROM auth_records WHERE kind = ? AND digest = ?",
                (kind, self.digest(identifier)),
            ).fetchone()
            if row and consume:
                db.execute("DELETE FROM auth_records WHERE kind = ? AND digest = ?",
                           (kind, self.digest(identifier)))
        if not row or row[1] <= self.clock():
            return None
        try:
            return json.loads(self.cipher.decrypt(row[0]))
        except InvalidToken:
            # A changed encryption key invalidates old logins and sessions.
            return None

    def clear_expired(self):
        with self.connect() as db:
            db.execute("DELETE FROM auth_records WHERE expires_at <= ?", (self.clock(),))
        self.usage.clear_expired()

    def delete(self, kind: str, identifier: str):
        with self.connect() as db:
            db.execute("DELETE FROM auth_records WHERE kind = ? AND digest = ?",
                       (kind, self.digest(identifier)))
