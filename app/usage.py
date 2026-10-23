"""Print distinct search account counts: python -m app.usage."""

import json
import sqlite3

from app.config import ConfigurationError, get_settings, load_environment
from app.services.database import DatabaseError, configured_database
from app.services.usage_store import UsageStore


def main():
    load_environment()
    settings = get_settings()
    if not settings.auth_encryption_key:
        raise SystemExit("AUTH_ENCRYPTION_KEY is required to read usage statistics.")
    store = UsageStore(configured_database(settings, settings.auth_db_path, private=True),
                       settings.auth_encryption_key)
    print(json.dumps({"as_of_utc": store.today().isoformat(), **store.counts()}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ConfigurationError, DatabaseError, sqlite3.Error):
        raise SystemExit("Could not read usage statistics. Check database configuration and availability.") from None
