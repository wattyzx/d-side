import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet

from app.config import ConfigurationError, Settings
from app.services.auth_store import AuthStore
from app.services.cache_service import SQLiteCache
from app.services.database import Database, DatabaseError, configured_database, _decode


class DatabaseTests(unittest.TestCase):
    def test_blob_results_accept_padded_and_unpadded_base64(self):
        for payload in (b"", b"a", b"ab", b"abc", bytes(range(256))):
            encoded = base64.b64encode(payload).decode("ascii")
            for wire_value in (encoded, encoded.rstrip("=")):
                with self.subTest(payload_length=len(payload), wire_length=len(wire_value)):
                    self.assertEqual(_decode({"type": "blob", "base64": wire_value}), payload)
        for malformed in ("!invalid!", "a", "ab cd", None, 123):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                _decode({"type": "blob", "base64": malformed})

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "db.sqlite3"

    def test_local_transactions_commit_and_rollback(self):
        database = Database(self.path)
        with database.connect() as db:
            db.execute("CREATE TABLE items (value TEXT)")
            db.execute("INSERT INTO items VALUES (?)", ("kept",))
        with self.assertRaises(ValueError), database.connect() as db:
            db.execute("INSERT INTO items VALUES (?)", ("discarded",))
            raise ValueError("abort")
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT value FROM items").fetchall(), [("kept",)])

    def test_configuration_is_opt_in_and_secrets_are_not_represented(self):
        credentials = {"TURSO_DATABASE_URL": "libsql://example.turso.io", "TURSO_AUTH_TOKEN": "private-token"}
        self.assertEqual(Settings.from_environment(credentials).storage_backend, "sqlite")
        settings = Settings.from_environment({**credentials, "STORAGE_BACKEND": "turso"})
        database = configured_database(settings, self.path)
        self.assertIsNone(database.path)
        self.assertFalse(self.path.exists())
        self.assertNotIn("private-token", repr(settings))
        self.assertNotIn("private-token", repr(database))
        for env in ({"STORAGE_BACKEND": "unknown"}, {"STORAGE_BACKEND": "turso"},
                    {**credentials, "STORAGE_BACKEND": "turso", "TURSO_DATABASE_URL": "http://example.com"},
                    {**credentials, "STORAGE_BACKEND": "turso", "TURSO_AUTH_TOKEN": ""},
                    {"DATABASE_TIMEOUT_SECONDS": "0"}):
            with self.subTest(env_keys=list(env)), self.assertRaises(ConfigurationError):
                Settings.from_environment(env)

    def test_remote_failures_are_sanitized_and_never_retried(self):
        reasons = {"http": "HTTP 403", "sql": "server rejected", "timeout": "timed out",
                   "missing_baton": "connection baton", "invalid_origin": "untrusted routing",
                   "sql_code": "SQLITE_ERROR"}
        for kind, reason in reasons.items():
            requests = []

            def handler(request):
                requests.append(request)
                if kind == "timeout":
                    raise httpx.ReadTimeout("private-token", request=request)
                if kind == "http":
                    return httpx.Response(403, text="private-token")
                return httpx.Response(200, json={
                    "baton": "" if kind == "missing_baton" else None if kind == "sql_code" else "baton",
                    "base_url": "https://untrusted.example" if kind == "invalid_origin" else None,
                    "results": [{"type": "error", "error": {"message": "private-token",
                                "code": "SQLITE_ERROR" if kind == "sql_code" else "private-token"}}]
                        if kind in ("sql", "sql_code") else [{"type": "ok", "response": {"result": {"rows": []}}}],
                })

            client = httpx.Client(transport=httpx.MockTransport(handler))
            with self.subTest(kind=kind), patch("app.services.database.httpx.Client", return_value=client):
                with self.assertRaises(DatabaseError) as caught:
                    with Database(url="libsql://example.turso.io", token="private-token").connect() as db:
                        db.execute("SELECT 1")
                self.assertNotIn("private-token", str(caught.exception))
                self.assertIn("Database SELECT failed", str(caught.exception))
                self.assertIn(reason, str(caught.exception))
                execute_requests = [r for r in requests if json.loads(r.content)["requests"][0]["type"] == "execute"]
                self.assertEqual(len(execute_requests), 1)
                self.assertTrue(client.is_closed)

    def test_closed_stream_during_transaction_stops_further_statements(self):
        for failed_command in ("BEGIN IMMEDIATE", "INSERT INTO items VALUES (1)"):
            commands = []

            def handler(request):
                operation = json.loads(request.content)["requests"][0]
                commands.append(operation["stmt"]["sql"])
                return httpx.Response(200, json={
                    "baton": None if commands[-1] == failed_command else "baton",
                    "results": [{"type": "ok", "response": {"result": {"rows": []}}}],
                })

            client = httpx.Client(transport=httpx.MockTransport(handler))
            with self.subTest(command=failed_command), patch("app.services.database.httpx.Client", return_value=client):
                with self.assertRaisesRegex(DatabaseError, "closed the connection during a transaction"):
                    with Database(url="libsql://example.turso.io", token="test").connect() as db:
                        db.execute("INSERT INTO items VALUES (1)")
                        db.execute("SELECT 1")
                self.assertEqual(commands[-1], failed_command)
                self.assertNotIn("COMMIT", commands)
                self.assertTrue(client.is_closed)

    def test_uncertain_commit_is_not_retried_or_followed_by_more_writes(self):
        commands = []

        def handler(request):
            operation = json.loads(request.content)["requests"][0]
            if operation["type"] == "close":
                return httpx.Response(200, json={"baton": None, "results": [
                    {"type": "ok", "response": {"type": "close"}},
                ]})
            commands.append(operation["stmt"]["sql"])
            if commands[-1] == "COMMIT":
                raise httpx.ReadTimeout("Commit outcome unknown", request=request)
            return httpx.Response(200, json={"baton": "baton", "results": [
                {"type": "ok", "response": {"result": {"rows": []}}},
            ]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("app.services.database.httpx.Client", return_value=client):
            with self.assertRaises(DatabaseError), Database(url="libsql://example.turso.io", token="test").connect() as db:
                db.execute("INSERT INTO items VALUES (?)", ("once",))
        self.assertEqual(commands, ["BEGIN IMMEDIATE", "INSERT INTO items VALUES (?)", "COMMIT"])
        self.assertTrue(client.is_closed)


class TursoStoreContractTests(unittest.TestCase):
    """Exercise real store SQL through the HTTP adapter using an isolated SQL server stub."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "server.sqlite3"
        self.connections = {}
        self.next_id = 0
        self.statements = []
        real_client = httpx.Client

        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(self.handle), **kwargs)

        patcher = patch("app.services.database.httpx.Client", side_effect=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.database = Database(url="libsql://example.turso.io", token="test-token")

    @staticmethod
    def encode(value):
        if value is None:
            return {"type": "null"}
        if isinstance(value, bytes):
            return {"type": "blob", "base64": base64.b64encode(value).decode().rstrip("=")}
        kind = "integer" if isinstance(value, int) else "float" if isinstance(value, float) else "text"
        return {"type": kind, "value": str(value) if kind == "integer" else value}

    def handle(self, request):
        self.assertEqual(request.headers["authorization"], "Bearer test-token")
        self.assertEqual(str(request.url), "https://example.turso.io/v2/pipeline")
        body = json.loads(request.content)
        baton = body["baton"]
        if baton is None:
            self.next_id += 1
            baton = str(self.next_id)
            self.connections[baton] = sqlite3.connect(self.path, isolation_level=None)
        db = self.connections[baton]
        results = []
        for operation in body["requests"]:
            if operation["type"] == "close":
                db.close()
                del self.connections[baton]
                baton = None
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = operation["stmt"]
            self.statements.append(stmt["sql"].strip())
            args = []
            for value in stmt["args"]:
                kind = value["type"]
                args.append(None if kind == "null" else base64.b64decode(value["base64"]) if kind == "blob"
                            else int(value["value"]) if kind == "integer" else value["value"])
            cursor = db.execute(stmt["sql"], args)
            rows = [[self.encode(value) for value in row] for row in cursor.fetchall()]
            results.append({"type": "ok", "response": {"type": "execute", "result": {"rows": rows}}})
        # Model a server that closes idle autocommit streams after CREATE,
        # SELECT, COMMIT, or ROLLBACK while retaining active transactions.
        if baton is not None and not db.in_transaction:
            db.close()
            del self.connections[baton]
            baton = None
        return httpx.Response(200, json={"baton": baton, "base_url": None, "results": results})

    def test_encrypted_sessions_persist_and_pending_tokens_are_single_use(self):
        key = Fernet.generate_key().decode()
        store = AuthStore(self.path.parent / "unused", key, database=self.database)
        identifier = store.create("session", {"token": "secret-oauth-token"}, 60)
        reopened = AuthStore(self.path.parent / "unused", key, database=self.database)
        self.assertEqual(reopened.read("session", identifier), {"token": "secret-oauth-token"})
        pending = store.create("pending", {"token": "pending-token"}, 60)
        self.assertEqual(reopened.read("pending", pending, consume=True), {"token": "pending-token"})
        self.assertIsNone(store.read("pending", pending, consume=True))
        with self.database.connect() as db:
            payload = db.execute("SELECT payload FROM auth_records WHERE kind = ?", ("session",)).fetchone()[0]
        self.assertNotIn(b"secret-oauth-token", payload)
        store.delete("session", identifier)
        self.assertIsNone(reopened.read("session", identifier))
        self.assertIn("BEGIN IMMEDIATE", self.statements)
        self.assertFalse(any("PRAGMA" in sql for sql in self.statements))
        self.assertFalse(self.connections)

    def test_cache_invalidation_rejects_stale_writes_and_rolls_back_on_failure(self):
        cache = SQLiteCache(database=self.database)
        other = SQLiteCache(database=self.database)
        old = cache.namespace_version("alice")
        cache.set("bob", "wantlist", {"ids": [7]}, ttl_seconds=60)
        cache.set("alice", "wantlist", {"ids": []}, ttl_seconds=60)
        other.clear_namespace("alice")
        self.assertFalse(cache.set("alice", "wantlist", {"ids": []}, expected_version=old))
        self.assertIsNone(cache.get("alice", "wantlist"))
        self.assertEqual(other.get("bob", "wantlist"), {"ids": [7]})
        with self.assertRaises(ValueError), self.database.connect() as db:
            db.execute("DELETE FROM cache_entries WHERE namespace = ?", ("bob",))
            raise ValueError("rollback")
        self.assertEqual(cache.get("bob", "wantlist"), {"ids": [7]})
        self.assertIn("ROLLBACK", self.statements)
        self.assertFalse(self.connections)
