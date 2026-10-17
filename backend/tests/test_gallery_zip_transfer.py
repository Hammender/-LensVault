from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.api.gallery import _gallery_display_order, _resolve_gallery_export_photos, export_gallery_photos
from app.core.config import Settings
from app.db import Base
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, Tag
from app.schemas import GalleryPhotoExportRequest
from app.services.importer import PictureService
from app.tools.cleanup_gallery_zip_import import cleanup_gallery_zip_import


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, object_key: str, payload: bytes, _content_type: str | None = None) -> None:
        self.objects[object_key] = payload

    def get_bytes(self, object_key: str) -> bytes:
        return self.objects[object_key]

    def get_stream(self, object_key: str):
        payload = self.objects[object_key]

        class _Stream:
            def read(self, size: int = -1) -> bytes:
                nonlocal payload
                if size < 0:
                    chunk, payload = payload, b""
                    return chunk
                chunk, payload = payload[:size], payload[size:]
                return chunk

            def close(self) -> None:
                return None

            def release_conn(self) -> None:
                return None

        return _Stream()


class ForbiddenFaceService:
    def detect_faces(self, _payload: bytes) -> list[object]:
        raise AssertionError("展示图 ZIP 导入不得调用人脸识别")


class ForbiddenVectorStore:
    def __getattr__(self, _name: str) -> object:
        raise AssertionError("展示图 ZIP 导入不得访问向量库")


class NoopOcrService:
    def extract_text(self, _payload: bytes) -> str:
        raise AssertionError("展示图 ZIP 导入应信任清单中的富文本")


def make_service(storage: MemoryStorage | None = None) -> PictureService:
    return PictureService(  # type: ignore[arg-type]
        storage or MemoryStorage(),
        ForbiddenFaceService(),
        ForbiddenVectorStore(),
        NoopOcrService(),
        Settings(),
    )


def make_zip(entries: list[dict[str, object]], *, version: int = 2) -> bytes:
    manifest_entries: list[dict[str, object]] = []
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        for position, entry in enumerate(entries):
            payload = bytes(entry.get("payload", f"{entry.get('filename', position)}-{position}".encode()))
            path = f"gallery/{position}.jpg"
            archive.writestr(path, payload)
            manifest_entry = {
                "filename": entry.get("filename", f"{position}.jpg"),
                "content_type": "image/jpeg",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "width": 100,
                "height": 80,
                "taken_at": None,
                "is_rich_text": False,
                "rich_text": None,
                "ocr_status": None,
                "tags": entry.get("tags", []),
                "persons": entry.get("persons", []),
                "paths": [path],
            }
            if version == 2:
                manifest_entry["display_index"] = entry.get("display_index", position)
            manifest_entries.append(manifest_entry)
        archive.writestr(
            "metadata.json",
            json.dumps({"version": version, "kind": "gallery_export", "photos": manifest_entries}, ensure_ascii=False),
        )
    return source.getvalue()


def ordered_filenames(db: Session) -> list[str]:
    return list(db.scalars(select(GalleryPhoto.filename).order_by(*_gallery_display_order())).all())


def test_zip_import_skips_recognition_and_uses_v2_display_indexes(db_session: Session) -> None:
    service = make_service()
    archive = make_zip(
        [
            {"filename": "second.jpg", "display_index": 1},
            {"filename": "first.jpg", "display_index": 0},
        ]
    )

    result = service.import_gallery_from_zip(db_session, archive, None)

    assert result["added_photos"] == 2
    assert ordered_filenames(db_session) == ["first.jpg", "second.jpg"]
    assert db_session.scalar(select(FaceRecord)) is None


def test_later_zip_batch_is_entirely_before_earlier_batch(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter([datetime(2026, 8, 5, 10, 0), datetime(2026, 8, 5, 11, 0)])
    monkeypatch.setattr("app.services.importer.shanghai_now", lambda: next(moments))
    service = make_service()

    service.import_gallery_from_zip(
        db_session,
        make_zip([{"filename": "old-1.jpg"}, {"filename": "old-2.jpg"}]),
        None,
    )
    service.import_gallery_from_zip(
        db_session,
        make_zip([{"filename": "new-1.jpg"}, {"filename": "new-2.jpg"}]),
        None,
    )

    assert ordered_filenames(db_session) == ["new-1.jpg", "new-2.jpg", "old-1.jpg", "old-2.jpg"]


def test_version_1_zip_preserves_manifest_array_order(db_session: Session) -> None:
    service = make_service()

    service.import_gallery_from_zip(
        db_session,
        make_zip([{"filename": "one.jpg"}, {"filename": "two.jpg"}], version=1),
        None,
    )

    assert ordered_filenames(db_session) == ["one.jpg", "two.jpg"]


def test_version_2_rejects_invalid_display_indexes(db_session: Session) -> None:
    service = make_service()
    archive = make_zip(
        [
            {"filename": "one.jpg", "display_index": 0},
            {"filename": "two.jpg", "display_index": 0},
        ]
    )

    with pytest.raises(ValueError, match="display_index"):
        service.import_gallery_from_zip(db_session, archive, None)


def test_duplicate_zip_photo_is_exactly_replaced_from_manifest(db_session: Session) -> None:
    payload = b"same-image"
    sha256 = hashlib.sha256(payload).hexdigest()
    storage = MemoryStorage()
    service = make_service(storage)
    old_person = Person(name="old", display_name="旧人物", is_unknown=False)
    unknown = Person(name="unknown", display_name="未知人物", is_unknown=True, unknown_serial=1)
    old_tag = Tag(name="旧标签", is_system=False)
    photo = GalleryPhoto(
        filename="old.jpg",
        content_type="image/jpeg",
        sha256=sha256,
        object_key="gallery/old.jpg",
        is_rich_text=False,
    )
    db_session.add_all([old_person, unknown, old_tag, photo])
    db_session.flush()
    db_session.add_all(
        [
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=old_person.id, source="manual"),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=unknown.id, source="unknown"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=old_tag.id, source="manual"),
            FaceRecord(
                gallery_photo_id=photo.id,
                matched_person_id=unknown.id,
                bbox_left=0,
                bbox_top=0,
                bbox_right=10,
                bbox_bottom=10,
                needs_review=True,
            ),
        ]
    )
    db_session.commit()

    archive = make_zip(
        [
            {
                "filename": "new.jpg",
                "payload": payload,
                "tags": ["新标签"],
                "persons": [{"name": "new", "display_name": "新人物", "is_unknown": False}],
            }
        ]
    )
    result = service.import_gallery_from_zip(db_session, archive, None)
    db_session.expire_all()
    restored = db_session.scalar(select(GalleryPhoto).where(GalleryPhoto.id == photo.id))

    assert result["updated_existing"] == 1
    assert restored is not None
    assert restored.filename == "new.jpg"
    assert [link.tag.name for link in restored.tags] == ["新标签"]
    assert [(link.person.name, link.source) for link in restored.person_tags] == [("new", "import")]
    assert restored.faces == []


def test_export_v3_uses_the_same_stable_display_order(db_session: Session) -> None:
    storage = MemoryStorage()
    photos = [
        GalleryPhoto(
            filename="older.jpg",
            content_type="image/jpeg",
            sha256="1" * 64,
            object_key="gallery/older.jpg",
            is_rich_text=False,
            display_batch_at=datetime(2026, 8, 5, 10, 0),
            display_index=0,
        ),
        GalleryPhoto(
            filename="new-second.jpg",
            content_type="image/jpeg",
            sha256="2" * 64,
            object_key="gallery/new-second.jpg",
            is_rich_text=False,
            display_batch_at=datetime(2026, 8, 5, 11, 0),
            display_index=1,
        ),
        GalleryPhoto(
            filename="new-first.jpg",
            content_type="image/jpeg",
            sha256="3" * 64,
            object_key="gallery/new-first.jpg",
            is_rich_text=False,
            display_batch_at=datetime(2026, 8, 5, 11, 0),
            display_index=0,
        ),
    ]
    db_session.add_all(photos)
    db_session.commit()
    for photo in photos:
        storage.put_bytes(photo.object_key, photo.filename.encode())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(storage=storage))))
    current = SimpleNamespace(workspace_id=None)

    response = export_gallery_photos(
        request,  # type: ignore[arg-type]
        scope="all",
        person_ids=[],
        tag_ids=[],
        exclude_person_ids=[],
        exclude_tag_ids=[],
        db=db_session,
        current=current,  # type: ignore[arg-type]
    )

    async def read_response() -> bytes:
        return b"".join([chunk async for chunk in response.body_iterator])

    with ZipFile(BytesIO(asyncio.run(read_response()))) as archive:
        manifest = json.loads(archive.read("metadata.json"))
    assert manifest["version"] == 3
    assert [item["filename"] for item in manifest["photos"]] == [
        "new-first.jpg",
        "new-second.jpg",
        "older.jpg",
    ]
    assert [item["display_index"] for item in manifest["photos"]] == [0, 1, 2]


def test_selected_export_uses_gallery_order_and_rejects_unknown_ids(db_session: Session) -> None:
    photos = [
        GalleryPhoto(
            filename=f"{name}.jpg",
            content_type="image/jpeg",
            sha256=str(index) * 64,
            object_key=f"gallery/{name}.jpg",
            is_rich_text=False,
            display_batch_at=datetime(2026, 8, 5, hour),
            display_index=0,
        )
        for index, (name, hour) in enumerate(
            [("older", 10), ("newer", 11), ("newest", 12)],
            start=1,
        )
    ]
    db_session.add_all(photos)
    db_session.commit()

    selected = _resolve_gallery_export_photos(
        db_session,
        None,  # type: ignore[arg-type]
        GalleryPhotoExportRequest(scope="selected", photo_ids=[photos[0].id, photos[2].id]),
    )

    assert [photo.filename for photo in selected] == ["newest.jpg", "older.jpg"]
    with pytest.raises(HTTPException) as exc_info:
        _resolve_gallery_export_photos(
            db_session,
            None,  # type: ignore[arg-type]
            GalleryPhotoExportRequest(scope="selected", photo_ids=[photos[0].id, 999999]),
        )
    assert exc_info.value.detail == "所选图片不存在或不属于当前空间。"


def test_from_start_export_includes_newer_filtered_photos_and_start(db_session: Session) -> None:
    included_tag = Tag(name="保留", is_system=False)
    excluded_tag = Tag(name="排除", is_system=False)
    photos = [
        GalleryPhoto(
            filename=f"{name}.jpg",
            content_type="image/jpeg",
            sha256=str(index) * 64,
            object_key=f"gallery/{name}.jpg",
            is_rich_text=False,
            display_batch_at=datetime(2026, 8, 5, hour),
            display_index=0,
        )
        for index, (name, hour) in enumerate(
            [("old", 9), ("start", 10), ("hidden", 11), ("new", 12)],
            start=1,
        )
    ]
    db_session.add_all([included_tag, excluded_tag, *photos])
    db_session.flush()
    db_session.add_all(
        [
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=included_tag.id, source="manual")
            for photo in photos
        ]
        + [
            GalleryPhotoTag(gallery_photo_id=photos[2].id, tag_id=excluded_tag.id, source="manual"),
        ]
    )
    db_session.commit()

    result = _resolve_gallery_export_photos(
        db_session,
        None,  # type: ignore[arg-type]
        GalleryPhotoExportRequest(
            scope="from_start",
            start_photo_id=photos[1].id,
            tag_ids=[included_tag.id],
            exclude_tag_ids=[excluded_tag.id],
        ),
    )

    assert [photo.filename for photo in result] == ["new.jpg", "start.jpg"]
    with pytest.raises(HTTPException) as exc_info:
        _resolve_gallery_export_photos(
            db_session,
            None,  # type: ignore[arg-type]
            GalleryPhotoExportRequest(
                scope="from_start",
                start_photo_id=photos[2].id,
                exclude_tag_ids=[excluded_tag.id],
            ),
        )
    assert exc_info.value.detail == "起点图片不在当前筛选结果中。"


def test_cleanup_command_is_dry_run_by_default_and_scoped_to_manifest(db_session: Session) -> None:
    known = Person(name="known", display_name="已知", is_unknown=False)
    unknown = Person(name="unknown", display_name="未知", is_unknown=True, unknown_serial=1)
    target = GalleryPhoto(
        filename="target.jpg",
        sha256="a" * 64,
        object_key="gallery/target.jpg",
        is_rich_text=False,
    )
    outside = GalleryPhoto(
        filename="outside.jpg",
        sha256="b" * 64,
        object_key="gallery/outside.jpg",
        is_rich_text=False,
    )
    db_session.add_all([known, unknown, target, outside])
    db_session.flush()
    db_session.add_all(
        [
            GalleryPhotoPersonTag(gallery_photo_id=target.id, person_id=known.id, source="auto"),
            GalleryPhotoPersonTag(gallery_photo_id=target.id, person_id=unknown.id, source="unknown"),
            GalleryPhotoPersonTag(gallery_photo_id=outside.id, person_id=unknown.id, source="unknown"),
            FaceRecord(
                gallery_photo_id=target.id,
                matched_person_id=unknown.id,
                bbox_left=0,
                bbox_top=0,
                bbox_right=10,
                bbox_bottom=10,
                needs_review=True,
            ),
        ]
    )
    db_session.commit()
    manifest = {"a" * 64: {"known"}}

    write_statements: list[str] = []

    def capture_writes(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            write_statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture_writes)
    try:
        preview = cleanup_gallery_zip_import(db_session, manifest)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture_writes)
    assert preview == {
        "manifest_photos": 1,
        "manifest_unique_sha256": 1,
        "matched_photos": 1,
        "matched_unique_sha256": 1,
        "affected_photos": 1,
        "unknown_tags_deleted": 1,
        "unknown_faces_deleted": 1,
        "known_sources_changed": 1,
        "applied": False,
    }
    assert write_statements == []
    assert db_session.scalar(select(FaceRecord).where(FaceRecord.gallery_photo_id == target.id)) is not None

    applied = cleanup_gallery_zip_import(db_session, manifest, apply=True)
    assert applied["applied"] is True
    remaining_target_links = db_session.scalars(
        select(GalleryPhotoPersonTag).where(GalleryPhotoPersonTag.gallery_photo_id == target.id)
    ).all()
    remaining_outside_links = db_session.scalars(
        select(GalleryPhotoPersonTag).where(GalleryPhotoPersonTag.gallery_photo_id == outside.id)
    ).all()
    assert [(link.person_id, link.source) for link in remaining_target_links] == [(known.id, "import")]
    assert len(remaining_outside_links) == 1
    assert db_session.scalar(select(FaceRecord).where(FaceRecord.gallery_photo_id == target.id)) is None
