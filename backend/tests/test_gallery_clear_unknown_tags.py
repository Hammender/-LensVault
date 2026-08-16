from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.gallery import router as gallery_router
from app.db import get_db
from app.dependencies.context import require_context
from app.models import GalleryPhoto, GalleryPhotoPersonTag, Person, Workspace
from app.services.importer import PictureService


def _picture_service() -> PictureService:
    return PictureService(
        storage=SimpleNamespace(),
        face_service=SimpleNamespace(),
        vector_store=SimpleNamespace(),
        ocr_service=SimpleNamespace(),
        settings=SimpleNamespace(face_embedding_version="test-v1"),
    )


def _client(db_session, workspace_id: int) -> TestClient:
    app = FastAPI()
    app.state.services = SimpleNamespace(pictures=_picture_service())
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_context] = lambda: SimpleNamespace(workspace_id=workspace_id)
    app.include_router(gallery_router)
    return TestClient(app, raise_server_exceptions=True)


def _add_workspace_people_and_photos(db_session):
    workspace = Workspace(name="测试空间")
    unknown = Person(
        name="__system_unknown_person__:1",
        display_name="未知人物",
        is_unknown=True,
    )
    first = Person(name="first", display_name="第一人物", is_unknown=False)
    photo_with_known = GalleryPhoto(filename="known.jpg", sha256="a" * 64, object_key="gallery/known.jpg")
    photo_unknown_only = GalleryPhoto(filename="unknown.jpg", sha256="b" * 64, object_key="gallery/unknown.jpg")
    db_session.add_all([workspace, unknown, first, photo_with_known, photo_unknown_only])
    db_session.flush()
    unknown.workspace_id = workspace.id
    first.workspace_id = workspace.id
    photo_with_known.workspace_id = workspace.id
    photo_unknown_only.workspace_id = workspace.id
    db_session.flush()
    return workspace, unknown, first, photo_with_known, photo_unknown_only


def _person_ids_of(db_session, photo_id: int) -> set[int]:
    return set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo_id)
        ).all()
    )


def test_clear_unknown_tags_removes_only_when_known_tag_exists(db_session) -> None:
    workspace, unknown, first, photo_with_known, photo_unknown_only = _add_workspace_people_and_photos(db_session)
    db_session.add_all(
        [
            GalleryPhotoPersonTag(gallery_photo_id=photo_with_known.id, person_id=unknown.id, source="unknown"),
            GalleryPhotoPersonTag(gallery_photo_id=photo_with_known.id, person_id=first.id, source="manual"),
            GalleryPhotoPersonTag(gallery_photo_id=photo_unknown_only.id, person_id=unknown.id, source="unknown"),
        ]
    )
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.post("/api/gallery/photos/clear-unknown-tags")

    assert response.status_code == 200
    assert response.json() == {"total": 2, "cleared": 1, "kept": 1}
    assert _person_ids_of(db_session, photo_with_known.id) == {first.id}
    assert _person_ids_of(db_session, photo_unknown_only.id) == {unknown.id}


def test_clear_unknown_tags_without_unknown_links_is_noop(db_session) -> None:
    workspace, _, first, photo_with_known, _ = _add_workspace_people_and_photos(db_session)
    db_session.add(
        GalleryPhotoPersonTag(gallery_photo_id=photo_with_known.id, person_id=first.id, source="manual")
    )
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.post("/api/gallery/photos/clear-unknown-tags")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "cleared": 0, "kept": 0}
    assert _person_ids_of(db_session, photo_with_known.id) == {first.id}


def test_clear_unknown_tags_preserves_known_links_of_other_photos(db_session) -> None:
    workspace, unknown, first, photo_with_known, photo_unknown_only = _add_workspace_people_and_photos(db_session)
    db_session.add_all(
        [
            GalleryPhotoPersonTag(gallery_photo_id=photo_with_known.id, person_id=unknown.id, source="unknown"),
            GalleryPhotoPersonTag(gallery_photo_id=photo_with_known.id, person_id=first.id, source="auto"),
            GalleryPhotoPersonTag(gallery_photo_id=photo_unknown_only.id, person_id=unknown.id, source="unknown"),
            GalleryPhotoPersonTag(gallery_photo_id=photo_unknown_only.id, person_id=first.id, source="manual"),
        ]
    )
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.post("/api/gallery/photos/clear-unknown-tags")

    assert response.status_code == 200
    assert response.json() == {"total": 2, "cleared": 2, "kept": 0}
    assert _person_ids_of(db_session, photo_with_known.id) == {first.id}
    assert _person_ids_of(db_session, photo_unknown_only.id) == {first.id}
