"""Short-lived SQLite or Turso connections with commit/rollback boundaries.

Turso uses the documented /v2/pipeline API. A baton keeps every statement in
an interactive transaction on the same connection. Never retry a write whose
commit outcome might be unknown.
"""

import base64
import sqlite3
from contextlib import contextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.config import ConfigurationError


class DatabaseError(RuntimeError):
    """Safe database failure suitable for an API response."""


def turso_http_url(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in ("libsql", "https") and parsed.hostname
                 and not parsed.username and not parsed.password
                 and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                 and parsed.port in (None, 443)
                 and not any(char.isspace() for char in url) and "\\" not in url)
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError("TURSO_DATABASE_URL must be a libsql:// or HTTPS database origin.")
    return "https://" + parsed.netloc.rstrip("/")


def _encode(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise TypeError("Unsupported database parameter type")


def _decode(value):
    kind = value["type"]
    if kind == "null":
        return None
    if kind == "blob":
        # Hrana serializes blobs as standard Base64 without '=' padding.
        encoded = value["base64"]
        if not isinstance(encoded, str):
            raise ValueError("Invalid database blob encoding")
        return base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "text":
        return value["value"]
    raise ValueError("Unsupported database result type")


class Rows:
    def __init__(self, rows):
        self.rows = iter(rows)

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)


class TursoConnection:
    def __init__(self, url, token, timeout):
        self.origin = turso_http_url(url)
        self.base_url = self.origin
        self.client = httpx.Client(headers={"Authorization": "Bearer " + token},
                                   timeout=timeout, follow_redirects=False)
        self.baton = None
        self.in_transaction = False
        self.broken = False

    def _request(self, requests):
        operation = requests[0]["type"].upper()
        if operation == "EXECUTE":
            verb = requests[0]["stmt"]["sql"].lstrip().split(None, 1)[0].upper()
            if verb in {"SELECT", "CREATE", "INSERT", "UPDATE", "DELETE", "REPLACE",
                        "BEGIN", "COMMIT", "ROLLBACK"}:
                operation = verb

        def fail(reason):
            self.broken = True
            raise DatabaseError(f"Database {operation} failed: {reason}") from None

        try:
            response = self.client.post(self.base_url + "/v2/pipeline", json={
                "baton": self.baton, "requests": requests,
            })
            response.raise_for_status()
            body = response.json()
            self.baton = body["baton"]
            results = body["results"]
            if len(results) != len(requests):
                fail("unexpected result count.")
            for result in results:
                if result["type"] != "ok":
                    # Map known codes to fixed text; never echo server messages or SQL.
                    reason = {
                        "SQLITE_BUSY": "database is busy.",
                        "SQLITE_LOCKED": "database is locked.",
                        "SQLITE_ERROR": "SQL was rejected (SQLITE_ERROR).",
                        "SQLITE_AUTH": "database authorization was denied.",
                        "SQLITE_READONLY": "database token or database is read-only.",
                        "SQLITE_CONSTRAINT": "a database constraint was violated.",
                        "STREAM_EXPIRED": "the database connection expired.",
                        "TRANSACTION_TIMEOUT": "the database transaction timed out.",
                    }.get(result.get("error", {}).get("code"), "server rejected the operation.")
                    fail(reason)
            if self.baton is not None and (not isinstance(self.baton, str) or not self.baton):
                fail("server returned an invalid connection baton.")
            # A null baton means the stream closed. Stateless statements can
            # start a new stream next time, but an active transaction cannot.
            needs_stream = operation == "BEGIN" or (
                self.in_transaction and operation not in {"COMMIT", "ROLLBACK", "CLOSE"})
            if self.baton is None and needs_stream:
                fail("server closed the connection during a transaction.")
            if body.get("base_url"):
                try:
                    target = turso_http_url(body["base_url"])
                except ConfigurationError:
                    fail("server returned an unsupported routing URL.")
                host = urlsplit(target).hostname
                if target != self.origin and not host.endswith(".turso.io"):
                    fail("server returned an untrusted routing origin.")
                self.base_url = target
            if self.baton is None:
                self.base_url = self.origin
            return results
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            hint = {401: "check TURSO_AUTH_TOKEN", 403: "check token permissions",
                    404: "check TURSO_DATABASE_URL", 429: "request limit reached"}.get(status, "request rejected")
            fail(f"HTTP {status}; {hint}.")
        except httpx.TimeoutException:
            fail("request timed out; the write outcome may be unknown.")
        except httpx.ConnectError:
            fail("could not connect; check the database hostname, network, and TLS.")
        except httpx.HTTPError:
            fail("HTTP transport error.")
        except (ValueError, KeyError, TypeError, AttributeError):
            fail("server returned an invalid protocol response.")

    def execute(self, sql, parameters=()):
        if self.broken:
            raise DatabaseError("Database connection is unavailable.")
        command = sql.lstrip().split(None, 1)[0].upper()
        # Match sqlite3's implicit transaction behavior for our write statements.
        if command in ("INSERT", "UPDATE", "DELETE", "REPLACE") and not self.in_transaction:
            self.execute("BEGIN IMMEDIATE")
        result = self._request([{"type": "execute", "stmt": {
            "sql": sql, "args": [_encode(value) for value in parameters], "want_rows": True,
        }}])[0]
        if command == "BEGIN":
            self.in_transaction = True
        elif command in ("COMMIT", "ROLLBACK"):
            self.in_transaction = False
        try:
            return Rows([tuple(_decode(value) for value in row)
                         for row in result["response"]["result"]["rows"]])
        except (ValueError, KeyError, TypeError):
            self.broken = True
            raise DatabaseError("Database returned an invalid response.") from None

    def commit(self):
        if self.in_transaction:
            self.execute("COMMIT")

    def rollback(self):
        if self.in_transaction and not self.broken:
            self.execute("ROLLBACK")

    def close(self):
        try:
            if self.baton is not None:
                with suppress(DatabaseError):
                    self._request([{"type": "close"}])
        finally:
            self.client.close()


class Database:
    def __init__(self, path=None, *, url=None, token=None, timeout=10, private=False):
        self.path = Path(path) if path is not None else None
        self.url = url
        self._token = token
        self.timeout = timeout
        if url:
            turso_http_url(url)
            if not token:
                raise ConfigurationError("TURSO_AUTH_TOKEN is required for Turso storage.")
        else:
            if self.path is None:
                raise ConfigurationError("A SQLite database path is required.")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if private:
                self.path.touch(mode=0o600, exist_ok=True)
                self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = (TursoConnection(self.url, self._token, self.timeout) if self.url
                      else sqlite3.connect(self.path, timeout=self.timeout))
        try:
            try:
                yield connection
                connection.commit()
            except BaseException:
                with suppress(Exception):
                    connection.rollback()
                raise
        finally:
            connection.close()

    def configure(self, connection):
        if not self.url:
            connection.execute("PRAGMA journal_mode=WAL")


def configured_database(settings, path, *, private=False):
    if settings.storage_backend == "turso":
        return Database(url=settings.turso_database_url, token=settings.turso_auth_token,
                        timeout=settings.database_timeout_seconds)
    return Database(path, timeout=settings.database_timeout_seconds, private=private)
