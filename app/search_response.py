"""Observe disconnects while synchronous recommendation work runs off the event loop."""

import anyio
from anyio.lowlevel import RunVar
from starlette.responses import StreamingResponse

from app.config import get_settings
from app.services.discogs_session import discogs_session
from app.services.search_control import (
    SearchCancelled, check_cancelled, search_cancellation, search_registry,
)

_END = object()
_search_limiter: RunVar[anyio.CapacityLimiter] = RunVar("search_worker_limiter")


async def run_search_worker(operation):
    # Share a limiter within each event loop, separate from FastAPI's default
    # workers. The registry bounds admitted searches across the whole process.
    try:
        limiter = _search_limiter.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(get_settings().max_concurrent_searches)
        _search_limiter.set(limiter)
    # Wait for a running worker on cancellation so its admission slot remains
    # occupied until it exits; never leave an abandoned search thread behind.
    return await anyio.to_thread.run_sync(operation, limiter=limiter, abandon_on_cancel=False)


class SearchStreamingResponse(StreamingResponse):
    def __init__(self, iterator, account, job):
        self.iterator = iterator
        self.account = account
        self.job = job
        super().__init__(self.events(), media_type="application/x-ndjson")

    def next_event(self):
        with discogs_session(self.account), search_cancellation(self.job.cancelled):
            try:
                check_cancelled()
                event = next(self.iterator, _END)
                check_cancelled()
                return event
            except SearchCancelled:
                return _END

    async def events(self):
        while True:
            event = await run_search_worker(self.next_event)
            if event is _END:
                return
            yield event

    def close_iterator(self):
        with discogs_session(self.account), search_cancellation(self.job.cancelled):
            self.iterator.close()

    async def __call__(self, scope, receive, send):
        try:
            # Always listen for disconnects, including ASGI 2.4 servers. A send
            # failure alone cannot detect a disconnect during a long worker step.
            async with anyio.create_task_group() as group:
                async def stream():
                    try:
                        await self.stream_response(send)
                    except OSError:
                        pass  # The client has closed the connection.
                    finally:
                        self.job.cancelled.set()
                        group.cancel_scope.cancel()

                async def disconnected():
                    try:
                        await self.listen_for_disconnect(receive)
                    finally:
                        self.job.cancelled.set()
                        group.cancel_scope.cancel()

                group.start_soon(stream)
                await disconnected()
        finally:
            self.job.cancelled.set()
            # A worker may still be finishing its current HTTP call. Keep the
            # admission slot until it has exited and the iterator is closed.
            with anyio.CancelScope(shield=True):
                try:
                    await run_search_worker(self.close_iterator)
                finally:
                    search_registry.finish(self.job)


async def run_search(request, account, job, operation):
    def work():
        with discogs_session(account), search_cancellation(job.cancelled):
            check_cancelled()
            result = operation()
            check_cancelled()
            return result

    try:
        result = None
        error = None
        async with anyio.create_task_group() as group:
            async def disconnected():
                try:
                    while True:
                        message = await request.receive()
                        if message["type"] == "http.disconnect":
                            return
                finally:
                    job.cancelled.set()

            group.start_soon(disconnected)
            try:
                result = await run_search_worker(work)
            except Exception as exc:
                error = exc
            finally:
                job.cancelled.set()
                group.cancel_scope.cancel()
        if error is not None:
            raise error
        return result
    finally:
        search_registry.finish(job)
