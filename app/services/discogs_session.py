"""Keep each operation's Discogs credentials isolated, including streamed work."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DiscogsCredentials:
    username: str
    token: str = field(repr=False)
    secret: str = field(repr=False)
    consumer_key: str = field(repr=False)
    consumer_secret: str = field(repr=False)


_credentials: ContextVar[DiscogsCredentials | None] = ContextVar("discogs_credentials", default=None)


def current_credentials() -> DiscogsCredentials:
    credentials = _credentials.get()
    if credentials is None:
        raise RuntimeError("Sign in with Discogs before making requests.")
    return credentials


@contextmanager
def discogs_session(credentials: DiscogsCredentials):
    marker = _credentials.set(credentials)
    try:
        yield
    finally:
        _credentials.reset(marker)


def personal_namespace(name: str) -> str:
    return f"{name}:{current_credentials().username.casefold()}"
