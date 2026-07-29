from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.gallery import router as gallery_router
from app.api.videos import router as videos_router
from app.db import get_db
from app.dependencies.context import require_context


def test_gallery_and_video_list_routes_cleanup_request_context_in_asgi_request(db_session) -> None:
    app = FastAPI()
    app.state.services = SimpleNamespace()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_context] = lambda: SimpleNamespace(workspace_id=1)
    app.include_router(gallery_router)
    app.include_router(videos_router)

    with TestClient(app, raise_server_exceptions=True) as client:
        gallery_response = client.get("/api/gallery/photos")
        video_response = client.get("/api/videos")

    assert gallery_response.status_code == 200
    assert gallery_response.json()["total"] == 0
    assert video_response.status_code == 200
    assert video_response.json()["total"] == 0
