from uuid import UUID
from contextlib import asynccontextmanager

import anyio
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.services.database import DatabaseError
from pydantic import BaseModel, Field, field_validator, model_validator
from app.seller_input import normalize_seller

from app.config import PROJECT_ROOT, get_settings, load_environment
from app.frontend import mount_frontend

# Initialize configuration before importing application services.
load_environment()
settings = get_settings()

from app.services.discogs_client import add_to_wantlist, cache
from app.auth import router as auth_router, require_account, trusted_origin, get_auth_services
from app.services.discogs_session import DiscogsCredentials, discogs_session
from app.search_response import SearchStreamingResponse, run_search
from app.services.search_control import SearchAlreadyRunning, SearchCancelled, SearchCapacityReached, search_registry
from app.services.inventory_service import _release_cache
from app.services.maintenance import clear_expired, periodic_cleanup
from starlette.concurrency import run_in_threadpool

from app.services.recommendation_service import (
    recommend,
    recommend_stream,
    validate_price_range,
)

@asynccontextmanager
async def lifespan(app):
    auth_store = None
    if settings.discogs_consumer_key and settings.discogs_consumer_secret and settings.auth_encryption_key:
        auth_store = get_auth_services().store
    stores = (cache, auth_store, _release_cache)
    await run_in_threadpool(clear_expired, *stores)
    async with anyio.create_task_group() as group:
        group.start_soon(periodic_cleanup, settings.cache_cleanup_interval_seconds, *stores)
        try:
            yield
        finally:
            group.cancel_scope.cancel()


app = FastAPI(
    title="D(e)Side API",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(auth_router)


@app.exception_handler(DatabaseError)
async def database_unavailable(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RecommendRequest(BaseModel):
    seller: str = Field(min_length=1, max_length=2048)
    search_id: UUID | None = None
    min_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("seller")
    @classmethod
    def parse_seller(cls, value):
        return normalize_seller(value)

    @model_validator(mode="after")
    def check_price_range(self):
        validate_price_range(self.min_price, self.max_price)
        return self

    def price_options(self):
        return self.model_dump(include={"min_price", "max_price"}, exclude_none=True)


class RecommendStreamRequest(RecommendRequest):
    exclude_release_ids: list[int] = Field(default_factory=list)
    include_demand: bool = False


class CancelSearchRequest(BaseModel):
    search_id: UUID


class WantlistRequest(BaseModel):
    release_id: int = Field(gt=0)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "d-side",
    }


def start_search(account, search_id):
    try:
        return search_registry.start(account.username, str(search_id) if search_id else None)
    except SearchAlreadyRunning:
        raise HTTPException(409, "A search is already running for your account. Cancel it or wait for it to finish.") from None
    except SearchCapacityReached:
        raise HTTPException(503, "All search slots are busy. Please try again shortly.",
                            headers={"Retry-After": "5"}) from None


@app.post("/recommend")
async def recommend_endpoint(
    request: RecommendRequest,
    connection: Request,
    account: DiscogsCredentials = Depends(require_account),
):
    job = start_search(account, request.search_id)
    try:
        return await run_search(connection, account, job,
                                lambda: recommend(username=account.username, seller=request.seller,
                                                  **request.price_options()))
    except SearchCancelled:
        raise HTTPException(499, "Search cancelled.") from None
    except DatabaseError:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Recommendation failed. Please try again.") from exc


@app.post("/recommend/stream")
def recommend_stream_endpoint(
    request: RecommendStreamRequest,
    account: DiscogsCredentials = Depends(require_account),
):
    job = start_search(account, request.search_id)
    try:
        iterator = recommend_stream(username=account.username, seller=request.seller,
                                    exclude_release_ids=request.exclude_release_ids,
                                    **request.price_options(),
                                    **({"include_demand": True} if request.include_demand else {}))
        return SearchStreamingResponse(iterator, account, job)
    except Exception:
        search_registry.finish(job)
        raise


@app.post("/recommend/cancel")
async def cancel_search_endpoint(
    request: CancelSearchRequest,
    account: DiscogsCredentials = Depends(require_account),
    _=Depends(trusted_origin),
):
    job = search_registry.cancel(account.username, str(request.search_id))
    if job is None:
        return {"cancelled": False}
    # Acknowledge only after the worker exits, so Search more can safely start.
    while not job.finished.is_set():
        await anyio.sleep(0.05)
    return {"cancelled": True}

@app.post("/wantlist")
def add_wantlist_endpoint(request: WantlistRequest,
                         account: DiscogsCredentials = Depends(require_account),
                         _=Depends(trusted_origin)):
    try:
        with discogs_session(account):
            add_to_wantlist(request.release_id)
        return {"release_id": request.release_id, "added": True}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = (
            "Discogs could not authorize this save. Reconnect your account."
            if status in (401, 403)
            else "Discogs could not save this record. Please try again."
        )
        raise HTTPException(
            status_code=403 if status in (401, 403) else 502, detail=message,
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.TransportError as exc:
        raise HTTPException(
            status_code=502, detail="Could not reach Discogs. Please try again.",
        ) from exc


# Register last so authentication, API endpoints, and docs retain priority.
if settings.serve_frontend:
    mount_frontend(app, PROJECT_ROOT / "frontend" / "dist")
