import hashlib
import json
import sqlite3
import time

from pathlib import Path
from typing import Any, Callable


DEFAULT_CACHE_PATH = Path("data/cache.sqlite3")


class SQLiteCache:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_CACHE_PATH,
        clock: Callable[[], float] = time.time,
    ):
        self.db_path = Path(db_path)
        self.clock = clock

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()


    def _connect(self):
        return sqlite3.connect(
            self.db_path
        )


    def _initialize(self):
        with self._connect() as connection:
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
    ):
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