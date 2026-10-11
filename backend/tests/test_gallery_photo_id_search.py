from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.gallery import _resolve_gallery_export_photos, list_gallery_photos
from app.models import GalleryPhoto, GalleryPhotoTag, Tag, Workspace
from app.schemas import GalleryPhotoExportRequest


def _seed(db: Session) -> tuple[Workspace, Workspace, list[GalleryPhoto], GalleryPhoto, Tag]:
    workspace = Workspace(name="主空间")
    other_workspace = Workspace(name="其他空间")
    db.add_all([workspace, other_workspace])
    db.flush()
    photos = [
        GalleryPhoto(
            workspace_id=workspace.id,
            filename=f"photo-{index}.jpg",
            content_type="image/jpeg",
            sha256=str(index) * 64,
            object_key=f"gallery/photo-{index}.jpg",
            is_rich_text=False,
            display_batch_at=datetime(2026, 10, 1, 10 + index),
            display_index=0,
        )
        for index in range(1, 4)
    ]
    foreign_photo = GalleryPhoto(
        workspace_id=other_workspace.id,
        filename="foreign.jpg",
        content_type="image/jpeg",
        sha256="f" * 64,
        object_key="gallery/foreign.jpg",
        is_rich_text=False,
        display_batch_at=datetime(2026, 10, 1, 9),
        display_index=0,
    )
    tag = Tag(name="风景", workspace_id=workspace.id)
    db.add_all([*photos, foreign_photo, tag])
    db.flush()
    db.add(GalleryPhotoTag(gallery_photo_id=photos[0].id, tag_id=tag.id))
    db.commit()
    return workspace, other_workspace, photos, foreign_photo, tag


def _list(db: Session, workspace_id: int, **kwargs):
    params = {
        "person_ids": [],
        "tag_ids": [],
        "exclude_person_ids": [],
        "exclude_tag_ids": [],
        "photo_id": None,
        "offset": 0,
        "limit": 24,
    }
    params.update(kwargs)
    return list_gallery_photos(db=db, current=SimpleNamespace(workspace_id=workspace_id), **params)  # type: ignore[arg-type]


def test_photo_id_search_returns_exact_match(db_session: Session) -> None:
    workspace, _, photos, _, _ = _seed(db_session)

    result = _list(db_session, workspace.id, photo_id=photos[1].id)

    assert result.total == 1
    assert [item.id for item in result.items] == [photos[1].id]


def test_photo_id_search_without_match_returns_empty_page(db_session: Session) -> None:
    workspace, _, _, _, _ = _seed(db_session)

    result = _list(db_session, workspace.id, photo_id=999999)

    assert result.total == 0
    assert result.items == []


def test_photo_id_search_is_scoped_to_current_workspace(db_session: Session) -> None:
    workspace, _, _, foreign_photo, _ = _seed(db_session)

    result = _list(db_session, workspace.id, photo_id=foreign_photo.id)

    assert result.total == 0


def test_photo_id_search_combines_with_filters_on_backend(db_session: Session) -> None:
    workspace, _, photos, _, tag = _seed(db_session)

    assert _list(db_session, workspace.id, photo_id=photos[0].id, tag_ids=[tag.id]).total == 1
    assert _list(db_session, workspace.id, photo_id=photos[1].id, tag_ids=[tag.id]).total == 0


def test_list_without_photo_id_is_unchanged(db_session: Session) -> None:
    workspace, _, _, _, _ = _seed(db_session)

    assert _list(db_session, workspace.id).total == 3


def test_filtered_export_honours_photo_id(db_session: Session) -> None:
    workspace, _, photos, _, _ = _seed(db_session)

    exported = _resolve_gallery_export_photos(
        db_session,
        workspace.id,
        GalleryPhotoExportRequest(scope="filtered", photo_id=photos[2].id),
    )

    assert [photo.id for photo in exported] == [photos[2].id]


@pytest.mark.parametrize("value", [0, -1])
def test_export_request_rejects_non_positive_photo_id(value: int) -> None:
    with pytest.raises(ValidationError):
        GalleryPhotoExportRequest(scope="filtered", photo_id=value)
