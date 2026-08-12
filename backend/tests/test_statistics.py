from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.statistics import router as statistics_router
from app.db import get_db
from app.dependencies.context import require_context
from app.models import (
    AcquisitionAsset,
    AcquisitionImportBatch,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GalleryPhotoTag,
    Person,
    Tag,
    UploadHistory,
    Workspace,
)


def _client(db_session, workspace_id: int) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_context] = lambda: SimpleNamespace(workspace_id=workspace_id)
    app.include_router(statistics_router)
    return TestClient(app, raise_server_exceptions=True)


def _photo(workspace_id: int, ordinal: int, *, source: str, is_rich_text: bool = False) -> GalleryPhoto:
    return GalleryPhoto(
        workspace_id=workspace_id,
        filename=f"photo-{ordinal}.jpg",
        sha256=f"{ordinal:064x}",
        object_key=f"gallery/photo-{ordinal}.jpg",
        is_rich_text=is_rich_text,
        ingest_source=source,
    )


def test_statistics_overview_uses_current_gallery_and_workspace_scope(db_session) -> None:
    current_workspace = Workspace(name="当前空间")
    other_workspace = Workspace(name="其他空间")
    db_session.add_all([current_workspace, other_workspace])
    db_session.flush()

    manual = _photo(current_workspace.id, 1, source="manual_upload")
    zip_photo = _photo(current_workspace.id, 2, source="gallery_zip", is_rich_text=True)
    acquisition = _photo(current_workspace.id, 3, source="acquisition")
    legacy = _photo(current_workspace.id, 4, source="legacy_unclassified")
    other_photo = _photo(other_workspace.id, 5, source="manual_upload")
    person = Person(workspace_id=current_workspace.id, name="张三", display_name="张三", is_unknown=False)
    tag = Tag(workspace_id=current_workspace.id, name="舞台", is_system=False)
    db_session.add_all([manual, zip_photo, acquisition, legacy, other_photo, person, tag])
    db_session.flush()
    db_session.add_all(
        [
            GalleryPhotoPersonTag(gallery_photo_id=manual.id, person_id=person.id, source="manual"),
            GalleryPhotoPersonTag(gallery_photo_id=zip_photo.id, person_id=person.id, source="manual"),
            GalleryPhotoTag(gallery_photo_id=zip_photo.id, tag_id=tag.id),
            GalleryPhotoTag(gallery_photo_id=acquisition.id, tag_id=tag.id),
            AcquisitionAsset(
                id="asset-pending",
                workspace_id=current_workspace.id,
                sha256="a" * 64,
                filename="pending.jpg",
                status="pending_review",
            ),
            AcquisitionAsset(
                id="asset-other",
                workspace_id=other_workspace.id,
                sha256="b" * 64,
                filename="other.jpg",
                status="import_failed",
            ),
        ]
    )
    db_session.commit()

    with _client(db_session, current_workspace.id) as client:
        response = client.get("/api/statistics/overview")

    assert response.status_code == 200
    assert response.json() == {
        "gallery_total": 4,
        "gallery_photo_count": 3,
        "rich_photo_count": 1,
        "source_counts": {
            "acquisition": 1,
            "gallery_zip": 1,
            "legacy_unclassified": 1,
            "manual_upload": 1,
        },
        "person_covered_count": 2,
        "tag_covered_count": 2,
        "acquisition_status_counts": {"pending_review": 1},
    }


def test_image_intake_history_merges_zip_and_acquisition_batches(db_session) -> None:
    workspace = Workspace(name="统计空间")
    other_workspace = Workspace(name="其他空间")
    db_session.add_all([workspace, other_workspace])
    db_session.flush()
    db_session.add_all(
        [
            UploadHistory(
                workspace_id=workspace.id,
                upload_type="gallery",
                total_count=3,
                success_count=2,
                duplicate_count=1,
                created_at=datetime(2026, 1, 1, 9, 0, 0),
            ),
            UploadHistory(
                workspace_id=workspace.id,
                upload_type="gallery_zip",
                total_count=5,
                success_count=4,
                duplicate_count=1,
                created_at=datetime(2026, 1, 2, 9, 0, 0),
            ),
            UploadHistory(
                workspace_id=other_workspace.id,
                upload_type="gallery_zip",
                total_count=9,
                success_count=9,
                duplicate_count=0,
                created_at=datetime(2026, 1, 4, 9, 0, 0),
            ),
            AcquisitionImportBatch(
                id="batch-current",
                workspace_id=workspace.id,
                status="completed_with_errors",
                total_count=6,
                imported_count=3,
                duplicate_count=2,
                failed_count=1,
                completed_at=datetime(2026, 1, 3, 9, 0, 0),
            ),
        ]
    )
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.get("/api/statistics/intake-history?limit=2")
        zip_response = client.get("/api/statistics/intake-history?source=gallery_zip")

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert [item["source"] for item in response.json()["items"]] == ["acquisition", "gallery_zip"]
    assert response.json()["items"][0]["failed_count"] == 1
    assert response.json()["items"][1] == {
        "id": response.json()["items"][1]["id"],
        "source": "gallery_zip",
        "status": "completed",
        "total_count": 5,
        "imported_count": 3,
        "updated_count": 1,
        "skipped_count": 1,
        "failed_count": 0,
        "completed_at": "2026-01-02T09:00:00+08:00",
    }
    assert zip_response.status_code == 200
    assert zip_response.json()["total"] == 1
    assert zip_response.json()["items"][0]["source"] == "gallery_zip"
