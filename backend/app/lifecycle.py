from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base
from app.models import Workspace
from app.services.container import ServiceContainer
from app.services.tasks import fail_incomplete_tasks


INCOMPLETE_TASK_TYPES = (
    "gallery_import",
    "gallery_rich_import",
    "gallery_zip_import",
    "person_import",
    "video_subtitle_generation",
)


def ensure_video_seek_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("video_items")}
    statements: list[str] = []
    if "seek_optimized" not in columns:
        statements.append("ALTER TABLE video_items ADD COLUMN seek_optimized BOOLEAN NOT NULL DEFAULT 0")
    if "seek_optimized_at" not in columns:
        statements.append("ALTER TABLE video_items ADD COLUMN seek_optimized_at DATETIME")
    if "seek_keyframe_interval_seconds" not in columns:
        statements.append("ALTER TABLE video_items ADD COLUMN seek_keyframe_interval_seconds FLOAT")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_face_recognition_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    additions = {
        "sample_photos": {
            "quality_status": "ALTER TABLE sample_photos ADD COLUMN quality_status VARCHAR(32)",
            "quality_warnings": "ALTER TABLE sample_photos ADD COLUMN quality_warnings TEXT",
            "source_type": "ALTER TABLE sample_photos ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'upload'",
            "source_gallery_photo_id": "ALTER TABLE sample_photos ADD COLUMN source_gallery_photo_id INTEGER",
        },
        "face_records": {
            "second_person_id": "ALTER TABLE face_records ADD COLUMN second_person_id INTEGER",
            "second_match_score": "ALTER TABLE face_records ADD COLUMN second_match_score FLOAT",
            "match_margin": "ALTER TABLE face_records ADD COLUMN match_margin FLOAT",
            "embedding_version": "ALTER TABLE face_records ADD COLUMN embedding_version VARCHAR(64)",
            "face_size": "ALTER TABLE face_records ADD COLUMN face_size FLOAT",
            "blur_score": "ALTER TABLE face_records ADD COLUMN blur_score FLOAT",
            "pose_yaw": "ALTER TABLE face_records ADD COLUMN pose_yaw FLOAT",
        },
    }
    statements: list[str] = []
    for table, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        statements.extend(statement for name, statement in columns.items() if name not in existing)
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_sample_person_source_gallery "
                "ON sample_photos (person_id, source_gallery_photo_id)"
            )
        )


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_video_seek_columns(engine)
    ensure_face_recognition_columns(engine)


def initialize_runtime(
    settings: Settings,
    services: ServiceContainer,
    session_factory: Callable[[], Session],
    logger: logging.Logger,
) -> None:
    logger.info("应用启动：开始检查存储、向量库、人脸识别和 OCR 依赖")
    services.storage.ensure_bucket()
    services.vector_store.ensure_collections()
    services.face.warmup()
    ocr_status = services.ocr.engine_status()
    logger.info(
        "OCR 引擎状态：rapidocr_ready=%s tesseract_ready=%s rapidocr_error=%s tesseract_error=%s",
        ocr_status["rapidocr_ready"],
        ocr_status["tesseract_ready"],
        ocr_status["rapidocr_error"] or "-",
        ocr_status["tesseract_error"] or "-",
    )

    db = session_factory()
    try:
        for workspace in db.scalars(select(Workspace)).all():
            services.pictures.ensure_system_tags(db, workspace.id)
        recovered = sum(fail_incomplete_tasks(db, task_type) for task_type in INCOMPLETE_TASK_TYPES)
        if recovered > 0:
            logger.warning("应用启动：已恢复未完成任务 count=%d", recovered)
    finally:
        db.close()

    logger.info(
        "应用启动完成：minio_bucket=%s qdrant_sample_collection=%s",
        settings.minio_bucket,
        settings.qdrant_known_collection,
    )
