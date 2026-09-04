from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person, Workspace

IGNORED_GALLERY_FACE_CLEANUP_KEY = "2026_08_08_delete_ignored_gallery_face_records"
ALEMBIC_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def _face(workspace_id: int, photo_id: int, **overrides) -> FaceRecord:
    values = {
        "workspace_id": workspace_id,
        "gallery_photo_id": photo_id,
        "bbox_left": 1,
        "bbox_top": 2,
        "bbox_right": 30,
        "bbox_bottom": 40,
        "matched_person_id": None,
        "needs_review": False,
        "vector_collection": None,
    }
    values.update(overrides)
    return FaceRecord(**values)


def test_face_cleanup_runs_via_alembic_0003(tmp_path) -> None:
    """升级到 0002 后插入遗留数据，再升级 head 触发 0003 清理。"""
    db_path = tmp_path / "cleanup.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url)
    config = _alembic_config(url)

    # 先升级到 0002（结构对齐完成，数据迁移未执行）
    command.upgrade(config, "0002")

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with SessionLocal() as db:
        workspace = Workspace(name="迁移测试空间", kind="private")
        unknown = Person(name="__system_unknown_person__:1", display_name="未知人物", is_unknown=True)
        known = Person(name="known", display_name="已知人物", is_unknown=False)
        photos = [
            GalleryPhoto(
                filename=f"photo-{index}.jpg",
                sha256=str(index) * 64,
                object_key=f"gallery/{index}.jpg",
                is_rich_text=False,
            )
            for index in range(1, 5)
        ]
        db.add_all([workspace, unknown, known, *photos])
        db.flush()
        unknown.workspace_id = workspace.id
        known.workspace_id = workspace.id
        for photo in photos:
            photo.workspace_id = workspace.id
        db.flush()

        ignored = _face(workspace.id, photos[0].id)
        still_unknown = _face(workspace.id, photos[1].id)
        known_face = _face(workspace.id, photos[2].id, matched_person_id=known.id)
        pending_review = _face(workspace.id, photos[3].id, needs_review=True)
        db.add_all(
            [
                ignored,
                still_unknown,
                known_face,
                pending_review,
                GalleryPhotoPersonTag(
                    gallery_photo_id=photos[1].id,
                    person_id=unknown.id,
                    source="unknown",
                ),
            ]
        )
        db.commit()
        ignored_id = ignored.id
        retained_ids = {still_unknown.id, known_face.id, pending_review.id}

    # 升级到 head，触发 0003 清理
    command.upgrade(config, "head")

    with SessionLocal() as db:
        remaining_ids = set(db.scalars(select(FaceRecord.id)).all())
        assert ignored_id not in remaining_ids
        assert retained_ids.issubset(remaining_ids)

    with engine.connect() as connection:
        marker_count = connection.scalar(
            text("SELECT COUNT(*) FROM app_schema_migrations WHERE migration_key=:key"),
            {"key": IGNORED_GALLERY_FACE_CLEANUP_KEY},
        )
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert marker_count == 1
    assert version == "0003"
    engine.dispose()
