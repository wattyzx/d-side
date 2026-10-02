from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware
from app.services.recommendation_service import recommend


app = FastAPI(
    title="D(e)Side API",
    version="1.0.0",
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