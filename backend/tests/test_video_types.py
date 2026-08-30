from __future__ import annotations

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db import Base
from app.lifecycle import ensure_video_type_columns
from app.mappers.videos import video_to_list_item
from app.models.videos import VideoCategoryTag, VideoItem, VideoItemCategoryTag


def test_video_item_default_video_type(db_session: Session) -> None:
    video = VideoItem(
        title="测试短视频",
        filename="short_test.mp4",
        object_key="videos/short_test.mp4",
        size_bytes=1024 * 1024,
        duration_seconds=45.0,
        status="ready",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    assert video.video_type == "short"
    item_read = video_to_list_item(video)
    assert item_read.video_type == "short"


def test_video_item_explicit_long_type(db_session: Session) -> None:
    video = VideoItem(
        title="测试长视频",
        filename="long_test.mp4",
        object_key="videos/long_test.mp4",
        size_bytes=1024 * 1024 * 50,
        duration_seconds=1800.0,
        status="ready",
        video_type="long",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    assert video.video_type == "long"
    item_read = video_to_list_item(video)
    assert item_read.video_type == "long"


def test_ensure_video_type_columns_backfill(tmp_path) -> None:
    db_file = tmp_path / "legacy_video.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")

    with engine.begin() as conn:
        # Create legacy table without video_type column
        conn.execute(
            text(
                """
                CREATE TABLE video_items (
                    id INTEGER PRIMARY KEY,
                    workspace_id INTEGER,
                    title VARCHAR(256) NOT NULL,
                    description TEXT,
                    filename VARCHAR(512) NOT NULL,
                    content_type VARCHAR(128),
                    sha256 VARCHAR(64),
                    object_key VARCHAR(512) NOT NULL UNIQUE,
                    cover_object_key VARCHAR(512),
                    cover_content_type VARCHAR(128),
                    size_bytes BIGINT NOT NULL,
                    duration_seconds FLOAT,
                    width INTEGER,
                    height INTEGER,
                    original_video_codec VARCHAR(64),
                    original_audio_codec VARCHAR(64),
                    video_codec VARCHAR(64),
                    audio_codec VARCHAR(64),
                    status VARCHAR(32) NOT NULL,
                    faststart_applied BOOLEAN NOT NULL DEFAULT 0,
                    seek_optimized BOOLEAN NOT NULL DEFAULT 0,
                    seek_optimized_at DATETIME,
                    seek_keyframe_interval_seconds FLOAT,
                    processed_at DATETIME,
                    processing_error TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO video_items (id, title, filename, object_key, size_bytes, duration_seconds, status)
                VALUES (1, '3分钟视频', 'v1.mp4', 'v1.mp4', 1000, 180.0, 'ready'),
                       (2, '10分钟视频', 'v2.mp4', 'v2.mp4', 2000, 600.0, 'ready'),
                       (3, '未知时长视频', 'v3.mp4', 'v3.mp4', 3000, NULL, 'ready')
                """
            )
        )

    # Run migration
    ensure_video_type_columns(engine)

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, video_type FROM video_items ORDER BY id")).fetchall()
        assert rows[0] == (1, "short")  # 180s <= 300s -> short
        assert rows[1] == (2, "long")   # 600s > 300s -> long
        assert rows[2] == (3, "short")  # NULL -> default short

    engine.dispose()
