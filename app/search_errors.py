"""User-facing search failures, without upstream URLs or internal details."""

import httpx

from app.services.database import DatabaseError


def search_error_message(error):
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status in (401, 403):
            return "Discogs could not authorize this search. Sign out and connect with Discogs again."
        if status == 429:
            return "Discogs is receiving too many requests. Wait a minute, then try searching again."
        if status == 404:
            return "Discogs could not find the requested data. Check the seller name or shop URL and try again."
        return "Discogs is temporarily unavailable. Please try searching again shortly."
    if isinstance(error, httpx.TimeoutException):
        return "Discogs took too long to respond. Please try searching again shortly."
    if isinstance(error, httpx.TransportError):
        return "We could not connect to Discogs. Please try searching again shortly."
    if isinstance(error, DatabaseError):
        return "Saved data is temporarily unavailable. Please try again shortly."
    return "We could not finish this search. Please try again; any results already found are kept."
