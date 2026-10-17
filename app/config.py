"""Backend configuration. Loading .env is an explicit startup operation."""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    """Safe configuration error messages that never include secret values."""


def origin(url: str) -> str:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = parsed.port
    suffix = f":{port}" if port and (parsed.scheme, port) not in (("http", 80), ("https", 443)) else ""
    return f"{parsed.scheme}://{host}{suffix}"


def _url(value: str, name: str, *, origin_only=False) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # Validate malformed or out-of-range port numbers.
        valid = (parsed.scheme in ("http", "https") and parsed.hostname
                 and not any(character.isspace() for character in value)
                 and "\\" not in value and "*" not in parsed.hostname
                 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and (parsed.scheme == "https" or parsed.hostname in ("localhost", "127.0.0.1", "::1"))
                 and (not origin_only or parsed.path in ("", "/")))
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(f"{name} must be a valid HTTPS URL (HTTP is allowed on localhost).")
    return origin(value) + parsed.path.rstrip("/")


def _positive_integer(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be a positive integer.") from None
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer.")
    return value


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    serve_frontend: bool = False
    frontend_url: str = "http://localhost:5173"
    callback_url: str = "http://localhost:5173/auth/discogs/callback"
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    auth_db_path: Path = PROJECT_ROOT / "data/auth.sqlite3"
    cache_db_path: Path = PROJECT_ROOT / "data/cache.sqlite3"
    storage_backend: str = "sqlite"
    turso_database_url: str = field(default="", repr=False)
    turso_auth_token: str = field(default="", repr=False)
    database_timeout_seconds: int = 10
    cache_cleanup_interval_seconds: int = 300
    release_cache_max_entries: int = 1000
    release_cache_ttl_seconds: int = 21600
    max_concurrent_searches: int = 4
    pending_ttl_seconds: int = 600
    session_ttl_seconds: int = 7 * 24 * 3600
    cookie_secure: bool = False
    cookie_httponly: bool = True
    cookie_samesite: str = "lax"
    cookie_path: str = "/"
    pending_cookie_name: str = "dside_oauth"
    session_cookie_name: str = "dside_session"
    discogs_consumer_key: str = field(default="", repr=False)
    discogs_consumer_secret: str = field(default="", repr=False)
    auth_encryption_key: str = field(default="", repr=False)

    @property
    def trusted_origins(self) -> frozenset[str]:
        return frozenset((origin(self.frontend_url), origin(self.callback_url)))

    def require_auth_configuration(self):
        if not all((self.discogs_consumer_key, self.discogs_consumer_secret, self.auth_encryption_key)):
            raise ConfigurationError("Discogs login is not configured. See the login setup in README.")

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        defaults = cls()
        storage_backend = env.get("STORAGE_BACKEND", "sqlite").lower()
        if storage_backend not in ("sqlite", "turso"):
            raise ConfigurationError("STORAGE_BACKEND must be sqlite or turso.")
        turso_url = env.get("TURSO_DATABASE_URL", "")
        turso_token = env.get("TURSO_AUTH_TOKEN", "")
        if storage_backend == "turso":
            from app.services.database import turso_http_url
            turso_http_url(turso_url)
            if not turso_token or any(char.isspace() for char in turso_token):
                raise ConfigurationError("TURSO_AUTH_TOKEN is required and must not contain whitespace.")
        serve_frontend = env.get("SERVE_FRONTEND", "false").lower()
        if serve_frontend not in ("true", "false"):
            raise ConfigurationError("SERVE_FRONTEND must be true or false.")
        frontend = _url(env.get("FRONTEND_URL", defaults.frontend_url), "FRONTEND_URL")
        callback = _url(env.get("DISCOGS_CALLBACK_URL", frontend + "/auth/discogs/callback"),
                        "DISCOGS_CALLBACK_URL")
        origins = env.get("CORS_ALLOWED_ORIGINS", origin(frontend)).split(",")
        if not all(value.strip() for value in origins):
            raise ConfigurationError("CORS_ALLOWED_ORIGINS must contain explicit origins.")
        origins = tuple(dict.fromkeys(origin(_url(value.strip(), "CORS_ALLOWED_ORIGINS", origin_only=True))
                                      for value in origins))
        encryption_key = env.get("AUTH_ENCRYPTION_KEY", "")
        if encryption_key:
            try:
                Fernet(encryption_key.encode())
            except (ValueError, TypeError):
                raise ConfigurationError("AUTH_ENCRYPTION_KEY must be a valid Fernet key.") from None
        secure = urlsplit(callback).scheme == "https"
        if "COOKIE_SECURE" in env:
            value = env["COOKIE_SECURE"].lower()
            if value not in ("true", "false"):
                raise ConfigurationError("COOKIE_SECURE must be true or false.")
            if secure and value == "false":
                raise ConfigurationError("COOKIE_SECURE cannot be false with an HTTPS callback.")
            secure = value == "true"
        return cls(
            storage_backend=storage_backend, turso_database_url=turso_url, turso_auth_token=turso_token,
            database_timeout_seconds=_positive_integer(env, "DATABASE_TIMEOUT_SECONDS", defaults.database_timeout_seconds),
            serve_frontend=serve_frontend == "true",
            frontend_url=frontend, callback_url=callback, cors_allowed_origins=origins,
            auth_db_path=_path(env.get("AUTH_DB_PATH", str(defaults.auth_db_path))),
            cache_db_path=_path(env.get("CACHE_DB_PATH", str(defaults.cache_db_path))),
            cache_cleanup_interval_seconds=_positive_integer(env, "CACHE_CLEANUP_INTERVAL_SECONDS", defaults.cache_cleanup_interval_seconds),
            release_cache_max_entries=_positive_integer(env, "RELEASE_CACHE_MAX_ENTRIES", defaults.release_cache_max_entries),
            release_cache_ttl_seconds=_positive_integer(env, "RELEASE_CACHE_TTL_SECONDS", defaults.release_cache_ttl_seconds),
            max_concurrent_searches=_positive_integer(env, "MAX_CONCURRENT_SEARCHES", defaults.max_concurrent_searches),
            pending_ttl_seconds=_positive_integer(env, "AUTH_PENDING_TTL_SECONDS", defaults.pending_ttl_seconds),
            session_ttl_seconds=_positive_integer(env, "AUTH_SESSION_TTL_SECONDS", defaults.session_ttl_seconds),
            cookie_secure=secure, discogs_consumer_key=env.get("DISCOGS_CONSUMER_KEY", ""),
            discogs_consumer_secret=env.get("DISCOGS_CONSUMER_SECRET", ""),
            auth_encryption_key=encryption_key,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()


def load_environment():
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    get_settings.cache_clear()
