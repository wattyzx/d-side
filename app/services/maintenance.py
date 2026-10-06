"""Expired data cleanup tied to the backend's lifetime."""

import logging
import sqlite3

import anyio
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def clear_expired(*stores):
    for store in stores:
        if store is None:
            continue
        try:
            store.clear_expired()
        except sqlite3.Error:
            # A temporarily busy database must not stop future cleanup runs.
            logger.exception("Could not remove expired records")


async def periodic_cleanup(interval_seconds, *stores):
    while True:
        await anyio.sleep(interval_seconds)
        await run_in_threadpool(clear_expired, *stores)
