import hashlib
import json
import time

from pathlib import Path
from typing import Any, Callable
from app.services.database import Database


DEFAULT_CACHE_PATH = Path("data/cache.sqlite3")


class SQLiteCache:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_CACHE_PATH,
        clock: Callable[[], float] = time.time,
        *,
        database=None,
    ):
        self.db_path = Path(db_path)
        self.clock = clock

        self.database = database or Database(self.db_path)

        self._initialize()


    def _connect(self):
        return self.database.connect()


    def _initialize(self):
        with self._connect() as connection:
            self.database.configure(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY (
                        namespace,
                        cache_key
                    )
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS cache_expiry ON cache_entries(expires_at)")
            connection.execute("""CREATE TABLE IF NOT EXISTS cache_namespaces (
                namespace TEXT PRIMARY KEY, version INTEGER NOT NULL
            )""")


    def get(
        self,
        namespace: str,
        cache_key: str,
    ) -> Any | None:

        now = self.clock()

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    payload,
                    expires_at
                FROM cache_entries
                WHERE
                    namespace = ?
                    AND cache_key = ?
                """,
                (
                    namespace,
                    cache_key,
                ),
            ).fetchone()

            if row is None:
                return None

            payload, expires_at = row

            if (
                expires_at is not None
                and expires_at <= now
            ):
                return None

        return json.loads(
            payload
        )


    def set(
        self,
        namespace: str,
        cache_key: str,
        value: Any,
        ttl_seconds: int | None = None,
        *,
        expected_version: int | None = None,
    ) -> bool:
        """Store a response, optionally only if its namespace was not invalidated."""
        if (
            ttl_seconds is not None
            and ttl_seconds <= 0
        ):
            raise ValueError(
                "ttl_seconds must be greater than 0"
            )

        now = self.clock()

        expires_at = (
            None
            if ttl_seconds is None
            else now + ttl_seconds
        )

        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        with self._connect() as connection:
            if expected_version is not None:
                # Serialize the version check and write with invalidation.
                # No transaction is held while the caller fetches upstream data.
                connection.execute("BEGIN IMMEDIATE")
                if self._namespace_version(connection, namespace) != expected_version:
                    return False
            connection.execute(
                """
                INSERT INTO cache_entries (
                    namespace,
                    cache_key,
                    payload,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?)

                ON CONFLICT(
                    namespace,
                    cache_key
                )
                DO UPDATE SET
                    payload = excluded.payload,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    namespace,
                    cache_key,
                    payload,
                    now,
                    expires_at,
                ),
            )
        return True


    @staticmethod
    def _namespace_version(connection, namespace: str) -> int:
        row = connection.execute(
            "SELECT version FROM cache_namespaces WHERE namespace = ?", (namespace,),
        ).fetchone()
        return row[0] if row else 0


    def namespace_version(self, namespace: str) -> int:
        """Capture an invalidation version before beginning an upstream fetch."""
        with self._connect() as connection:
            return self._namespace_version(connection, namespace)


    def delete(
        self,
        namespace: str,
        cache_key: str,
    ):
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM cache_entries
                WHERE
                    namespace = ?
                    AND cache_key = ?
                """,
                (
                    namespace,
                    cache_key,
                ),
            )


    def clear_namespace(
        self,
        namespace: str,
    ):
        with self._connect() as connection:
            # Bump and delete in one transaction, including for an empty cache.
            connection.execute("""
                INSERT INTO cache_namespaces (namespace, version) VALUES (?, 1)
                ON CONFLICT(namespace) DO UPDATE SET version = version + 1
            """, (namespace,))
            connection.execute(
                """
                DELETE FROM cache_entries
                WHERE namespace = ?
                """,
                (namespace,),
            )


    def clear_expired(self):
        now = self.clock()

        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM cache_entries
                WHERE
                    expires_at IS NOT NULL
                    AND expires_at <= ?
                """,
                (now,),
            )


def make_cache_key(
    url: str,
    params: dict | None = None,
) -> str:

    data = {
        "url": url,
        "params": params or {},
    }

    serialized = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()
