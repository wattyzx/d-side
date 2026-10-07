"""Optional serving of the built frontend on the API's origin."""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from app.config import ConfigurationError


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Unknown backend paths must never resolve to files from the build.
        if path.split("/", 1)[0] in {
            "auth", "recommend", "wantlist", "health", "docs", "redoc", "openapi.json",
        }:
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        if path in (".", "", "index.html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_frontend(app: FastAPI, directory: Path):
    """Call after registering backend routes so they retain priority."""
    if not (directory / "index.html").is_file():
        raise ConfigurationError(
            "SERVE_FRONTEND requires a frontend build. Run npm run build --prefix frontend."
        )
    app.mount("/", FrontendFiles(directory=directory, html=True), name="frontend")
