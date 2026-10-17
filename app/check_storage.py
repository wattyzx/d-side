"""Run an explicit Turso smoke test using isolated records, then remove them."""

import sys
from uuid import uuid4

from app.config import get_settings, load_environment
from app.services.auth_store import AuthStore
from app.services.cache_service import SQLiteCache
from app.services.database import DatabaseError, configured_database


def main():
    load_environment()
    settings = get_settings()
    if settings.storage_backend != "turso":
        raise SystemExit("Run with STORAGE_BACKEND=turso to check the remote database.")
    if not settings.auth_encryption_key:
        raise SystemExit("AUTH_ENCRYPTION_KEY is required to check encrypted sessions.")
    database = configured_database(settings, settings.auth_db_path)
    namespace = "storage-check:" + uuid4().hex
    print("Checking session schema...", flush=True)
    store = AuthStore(settings.auth_db_path, settings.auth_encryption_key, database=database)
    print("Checking cache schema...", flush=True)
    cache = SQLiteCache(settings.cache_db_path, database=database)
    try:
        print("Checking encrypted sessions and single-use tokens...", flush=True)
        identifier = store.create(namespace, {"check": True}, 60)
        reopened = AuthStore(settings.auth_db_path, settings.auth_encryption_key, database=database)
        assert reopened.read(namespace, identifier) == {"check": True}
        assert reopened.read(namespace, identifier, consume=True) == {"check": True}
        assert store.read(namespace, identifier, consume=True) is None
        print("Checking cache persistence and invalidation...", flush=True)
        version = cache.namespace_version(namespace)
        cache.set(namespace, "probe", {"check": True}, ttl_seconds=60)
        assert SQLiteCache(settings.cache_db_path, database=database).get(namespace, "probe") == {"check": True}
        cache.clear_namespace(namespace)
        assert not cache.set(namespace, "probe", {"stale": True}, expected_version=version)
        assert cache.get(namespace, "probe") is None
    finally:
        failed = sys.exc_info()[0] is not None
        # Only remove the records belonging to this probe, never application data.
        try:
            with database.connect() as db:
                db.execute("DELETE FROM auth_records WHERE kind = ?", (namespace,))
                db.execute("DELETE FROM cache_entries WHERE namespace = ?", (namespace,))
                db.execute("DELETE FROM cache_namespaces WHERE namespace = ?", (namespace,))
        except DatabaseError as exc:
            if not failed:
                raise
            print(f"Probe cleanup also failed: {exc}", file=sys.stderr)
    print("Turso storage checks passed: encrypted records, persistence, token consumption, cache invalidation.")


if __name__ == "__main__":
    try:
        main()
    except DatabaseError as exc:
        raise SystemExit(str(exc)) from None
