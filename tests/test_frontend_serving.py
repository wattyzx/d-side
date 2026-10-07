import tempfile
import unittest
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import app as api
from app.auth import require_account
from app.config import ConfigurationError
from app.frontend import mount_frontend


class FrontendServingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.build = self.root / "dist"
        self.build.mkdir()
        (self.build / "index.html").write_text("<html>D(e)Side</html>")
        (self.build / "assets").mkdir()
        (self.build / "assets" / "app.js").write_text("console.log('ready');")
        (self.build / "crate.png").write_bytes(b"image")
        (self.root / "secret.txt").write_text("private")
        (self.build / "outside.txt").symlink_to(self.root / "secret.txt")
        (self.build / "auth").mkdir()
        (self.build / "auth" / "unknown.txt").write_text("not an auth response")

        self.app = FastAPI()
        # Exercise the actual backend routes without mutating the global app.
        backend_routes = APIRouter(routes=[
            route for route in api.routes if getattr(route, "name", None) != "frontend"
        ])
        self.app.include_router(backend_routes)

        def anonymous():
            raise HTTPException(401, "Sign in with Discogs.")

        self.app.dependency_overrides[require_account] = anonymous
        mount_frontend(self.app, self.build)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_serves_index_and_build_assets(self):
        for path in ("/", "/index.html"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.headers["content-type"])
            self.assertEqual(response.text, "<html>D(e)Side</html>")
            self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertEqual(self.client.get("/assets/app.js").text, "console.log('ready');")
        self.assertEqual(self.client.get("/crate.png").content, b"image")
        self.assertEqual(self.client.head("/").status_code, 200)

    def test_backend_routes_keep_priority(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        for path, body in (("/recommend", {"seller": "shop"}),
                           ("/recommend/stream", {"seller": "shop"}),
                           ("/recommend/cancel", {"search_id": "00000000-0000-0000-0000-000000000001"}),
                           ("/wantlist", {"release_id": 123})):
            with self.subTest(path=path):
                response = self.client.post(path, json=body)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Sign in with Discogs.")

    def test_missing_files_and_unknown_backend_paths_return_404(self):
        for path in ("/assets/missing.js", "/unknown", "/auth/unknown.txt", "/recommend/unknown"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_cannot_serve_files_outside_build(self):
        for path in ("/%2e%2e/secret.txt", "/outside.txt"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_missing_build_fails_with_actionable_error(self):
        for directory in (self.root / "missing", self.build / "assets"):
            with self.subTest(directory=directory), self.assertRaisesRegex(
                ConfigurationError, "npm run build --prefix frontend"
            ):
                mount_frontend(FastAPI(), directory)

    def test_frontend_is_not_served_without_mounting(self):
        with TestClient(FastAPI()) as client:
            self.assertEqual(client.get("/").status_code, 404)
