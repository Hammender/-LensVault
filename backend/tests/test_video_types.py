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


class _FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def get_bytes(self, key: str) -> bytes:
        return self.files[key]

    def put_bytes(self, key: str, payload: bytes, content_type: str | None = None) -> None:
        self.files[key] = payload

    def put_stream(self, key: str, stream, length: int, content_type: str | None = None) -> None:
        self.files[key] = stream.read()

    def remove_object(self, key: str) -> None:
        self.files.pop(key, None)

    def remove_objects(self, keys: list[str]) -> None:
        for k in keys:
            self.files.pop(k, None)

    def compose_object(self, target_key: str, source_keys: list[str]) -> None:
        merged = b"".join(self.files[k] for k in source_keys)
        self.files[target_key] = merged

    def get_stream(self, key: str):
        import io

        class _StreamResponse:
            def __init__(self, data: bytes):
                self.data = data

            def stream(self, chunk_size: int = 1024 * 1024):
                stream = io.BytesIO(self.data)
                while chunk := stream.read(chunk_size):
                    yield chunk

            def close(self):
                pass

            def release_conn(self):
                pass

        return _StreamResponse(self.files[key])


def test_video_create_session_duplicate_sha256(db_session: Session) -> None:
    import hashlib
    from app.models import Workspace
    from app.schemas.videos import VideoUploadSessionCreate
    from app.services.videos import VideoService

    ws = Workspace(name="测试工作区1")
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    test_bytes = b"fake-video-content-for-sha256-test"
    sha = hashlib.sha256(test_bytes).hexdigest()

    existing_video = VideoItem(
        workspace_id=ws.id,
        title="已有视频",
        filename="existing.mp4",
        sha256=sha,
        object_key="videos/existing.mp4",
        size_bytes=len(test_bytes),
        status="ready",
    )
    db_session.add(existing_video)
    db_session.commit()

    service = VideoService(storage=_FakeStorage())
    # Same workspace, same sha256 provided
    try:
        service.create_upload_session(
            db_session,
            VideoUploadSessionCreate(
                filename="new_name.mp4",
                title="新视频",
                size_bytes=len(test_bytes),
                sha256=sha,
            ),
            workspace_id=ws.id,
        )
        assert False, "Should have raised ValueError for duplicate sha256"
    except ValueError as exc:
        assert "已存在内容相同的视频" in str(exc)
        assert "已有视频" in str(exc)


def test_video_complete_upload_duplicate_sha256_rejection(db_session: Session, monkeypatch) -> None:
    import hashlib
    from app.models import Workspace
    from app.schemas.videos import VideoUploadCompleteRequest, VideoUploadSessionCreate
    from app.services.videos import VideoService
    from app.services.video_processing import VideoProbeInfo

    ws = Workspace(name="测试工作区2")
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    test_bytes = b"fake-video-content-for-complete-dedup"
    sha = hashlib.sha256(test_bytes).hexdigest()

    existing_video = VideoItem(
        workspace_id=ws.id,
        title="已存在视频A",
        filename="video_a.mp4",
        sha256=sha,
        object_key="videos/video_a.mp4",
        size_bytes=len(test_bytes),
        status="ready",
    )
    db_session.add(existing_video)
    db_session.commit()

    storage = _FakeStorage()
    service = VideoService(storage=storage)
    monkeypatch.setattr(service, "_probe_object", lambda key, fn: VideoProbeInfo(duration_seconds=10.0, width=1920, height=1080, video_codec="h264", audio_codec="aac"))

    # Create session for a video with different filename and without providing sha256 upfront
    session = service.create_upload_session(
        db_session,
        VideoUploadSessionCreate(
            filename="video_b.mp4",
            title="视频B",
            size_bytes=len(test_bytes),
        ),
        workspace_id=ws.id,
    )
    # Put part
    service.put_upload_part(db_session, session, 0, test_bytes)

    # Complete upload should calculate sha256, detect duplication, and reject
    try:
        service.complete_upload(
            db_session,
            session,
            VideoUploadCompleteRequest(
                category_tag_ids=[],
                category_tag_names=[],
                person_ids=[],
                generate_zh_subtitles=False,
            ),
        )
        assert False, "Should have raised ValueError for duplicate SHA256 on complete"
    except ValueError as exc:
        assert "已存在内容相同的视频" in str(exc)
        assert "已存在视频A" in str(exc)


def test_process_video_preserves_original_sha256_and_updates_size(db_session: Session, monkeypatch) -> None:
    import hashlib
    from pathlib import Path
    from app.models import Workspace
    from app.services.videos import VideoService
    from app.services.video_processing import VideoProbeInfo

    ws = Workspace(name="测试工作区3")
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    raw_bytes = b"original-unoptimized-video-content"
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    raw_size = len(raw_bytes)

    video = VideoItem(
        workspace_id=ws.id,
        title="待优化视频",
        filename="unoptimized.mp4",
        sha256=raw_sha,
        object_key="workspaces/test/unoptimized.mp4",
        size_bytes=raw_size,
        status="uploaded",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    storage = _FakeStorage()
    storage.put_bytes("workspaces/test/unoptimized.mp4", raw_bytes)
    service = VideoService(storage=storage)
    from sqlalchemy.orm import sessionmaker
    test_session_factory = sessionmaker(bind=db_session.bind, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr("app.services.videos.SessionLocal", test_session_factory)

    # Mock _download_object_to_file, _probe_video, _estimate_keyframe_interval, _run_faststart
    monkeypatch.setattr(service, "_download_object_to_file", lambda key, path: path.write_bytes(raw_bytes))
    monkeypatch.setattr(service, "_probe_video", lambda path: VideoProbeInfo(duration_seconds=5.0, width=1280, height=720, video_codec="h264", audio_codec="aac"))
    monkeypatch.setattr(service, "_estimate_keyframe_interval", lambda path: 1.0)
    monkeypatch.setattr(service, "_extract_cover", lambda in_p, out_p, dur: None)

    transcoded_bytes = b"optimized-playback-bytes-with-smaller-or-different-size"
    def fake_faststart(in_p, out_p):
        out_p.write_bytes(transcoded_bytes)
    monkeypatch.setattr(service, "_run_faststart", fake_faststart)

    # Run playback process
    service.process_video_for_playback(video.id)

    db_session.expire_all()
    updated = db_session.get(VideoItem, video.id)
    assert updated is not None
    assert updated.status == "ready"
    assert updated.sha256 == raw_sha  # SHA256 must remain the original uploaded file's SHA256!
    assert updated.size_bytes == len(transcoded_bytes)  # size_bytes must be updated to the transcode output size!


