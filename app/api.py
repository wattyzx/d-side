from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx

from app.services.discogs_client import add_to_wantlist

from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from app.services.recommendation_service import (
    recommend,
    recommend_stream,
)

app = FastAPI(
    title="D(e)Side API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RecommendRequest(BaseModel):
    username: str = Field(min_length=1)
    seller: str = Field(min_length=1)


class RecommendStreamRequest(RecommendRequest):
    exclude_release_ids: list[int] = Field(default_factory=list)
    inventory_page_limit: int | None = Field(
        default=None, ge=1, deprecated=True,
        description="Legacy argument; searches scan all accessible inventory pages (up to 100).",
    )


class WantlistRequest(BaseModel):
    username: str = Field(min_length=1)
    release_id: int = Field(gt=0)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "d-side",
    }


@app.post("/recommend")
def recommend_endpoint(
    request: RecommendRequest,
):
    try:
        return recommend(
            username=request.username,
            seller=request.seller,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Recommendation failed: {exc}",
        ) from exc

@app.post("/recommend/stream")
def recommend_stream_endpoint(
    request: RecommendStreamRequest,
):
    return StreamingResponse(
        recommend_stream(
            username=request.username,
            seller=request.seller,
            exclude_release_ids=request.exclude_release_ids,
            inventory_page_limit=request.inventory_page_limit,
        ),
        media_type="application/x-ndjson",
    )

@app.post("/wantlist")
def add_wantlist_endpoint(request: WantlistRequest):
    try:
        add_to_wantlist(request.username, request.release_id)
        return {"release_id": request.release_id, "added": True}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = (
            "Discogs could not authorize this save. Check the configured token."
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
