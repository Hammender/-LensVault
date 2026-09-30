from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db import Base
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

    def copy_object(self, target_key: str, source_key: str) -> None:
        self.files[target_key] = self.files[source_key]

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
    monkeypatch.setattr(service, "_extract_cover", lambda in_p, out_p, dur: out_p.write_bytes(b"generated-cover"))

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
    assert updated.cover_object_key is not None
    assert storage.files[updated.cover_object_key] == b"generated-cover"


def test_acquisition_video_import_runs_upload_processing(db_session: Session, monkeypatch) -> None:
    from app.models import AcquisitionAsset, AcquisitionImportBatchItem, Workspace
    from app.services.acquisition import AcquisitionService
    from app.services.video_processing import VideoProbeInfo
    from app.services.videos import VideoService

    workspace = Workspace(name="采集视频入库测试")
    db_session.add(workspace)
    db_session.commit()
    payload = b"acquired-video"
    sha256 = hashlib.sha256(payload).hexdigest()
    asset = AcquisitionAsset(
        id="acquired-video",
        workspace_id=workspace.id,
        sha256=sha256,
        filename="clip.mp4",
        content_type="video/mp4",
        object_key="acquisition/clip.mp4",
        media_type="video",
        size_bytes=len(payload),
        status="pending_review",
        duration_seconds=8.0,
    )
    db_session.add(asset)
    db_session.commit()
    storage = _FakeStorage()
    storage.put_bytes(asset.object_key, payload)
    video_service = VideoService(storage)
    monkeypatch.setattr(video_service, "_probe_object", lambda *_: VideoProbeInfo(8.0, 1920, 1080, "h264", "aac"))
    optimized_ids: list[int] = []
    monkeypatch.setattr(video_service, "optimize_video_faststart", optimized_ids.append)
    acquisition = AcquisitionService(storage, SimpleNamespace(), similarity_extractor=SimpleNamespace(), video_service=video_service)

    batch = acquisition.create_import_batch(db_session, workspace.id, [asset.id])
    acquisition.process_import_batch(db_session, batch.id)

    item = db_session.scalar(select(AcquisitionImportBatchItem).where(AcquisitionImportBatchItem.batch_id == batch.id))
    video = db_session.get(VideoItem, item.video_id)
    assert item.status == "imported"
    assert video is not None
    assert (video.sha256, video.status, video.video_type) == (sha256, "uploaded", "short")
    assert storage.files[video.object_key] == payload
    assert asset.object_key is None
    assert optimized_ids == [video.id]

    failed_payload = b"video-with-optimization-error"
    failed_asset = AcquisitionAsset(
        id="failed-optimization", workspace_id=workspace.id,
        sha256=hashlib.sha256(failed_payload).hexdigest(), filename="failed.mp4",
        content_type="video/mp4", object_key="acquisition/failed.mp4", media_type="video",
        size_bytes=len(failed_payload), status="pending_review",
    )
    db_session.add(failed_asset)
    db_session.commit()
    storage.put_bytes(failed_asset.object_key, failed_payload)

    def fail_optimization(_video_id: int) -> None:
        raise RuntimeError("模拟优化失败")

    monkeypatch.setattr(video_service, "optimize_video_faststart", fail_optimization)
    failed_batch = acquisition.create_import_batch(db_session, workspace.id, [failed_asset.id])
    acquisition.process_import_batch(db_session, failed_batch.id)
    failed_item = db_session.scalar(select(AcquisitionImportBatchItem).where(AcquisitionImportBatchItem.batch_id == failed_batch.id))
    db_session.expire_all()
    failed_video = db_session.get(VideoItem, failed_item.video_id)
    assert failed_item.status == "imported", failed_item.error_message
    assert failed_video.status == "processing_failed"
    assert failed_video.processing_error == "模拟优化失败"


def test_acquisition_video_duplicate_does_not_reprocess(db_session: Session, monkeypatch) -> None:
    from app.models import AcquisitionAsset, AcquisitionImportBatchItem, Workspace
    from app.services.acquisition import AcquisitionService
    from app.services.videos import VideoService

    workspace = Workspace(name="采集视频去重测试")
    db_session.add(workspace)
    db_session.commit()
    payload = b"duplicate-video"
    sha256 = hashlib.sha256(payload).hexdigest()
    existing = VideoItem(
        workspace_id=workspace.id, title="已有视频", filename="original.mp4",
        sha256=sha256, object_key="videos/original.mp4", size_bytes=len(payload), status="ready",
    )
    asset = AcquisitionAsset(
        id="duplicate-video", workspace_id=workspace.id, sha256=sha256, filename="duplicate.mp4",
        object_key="acquisition/duplicate.mp4", media_type="video", size_bytes=len(payload), status="pending_review",
    )
    db_session.add_all([existing, asset])
    db_session.commit()
    storage = _FakeStorage()
    storage.put_bytes(existing.object_key, payload)
    storage.put_bytes(asset.object_key, payload)
    video_service = VideoService(storage)
    optimized_ids: list[int] = []
    monkeypatch.setattr(video_service, "optimize_video_faststart", optimized_ids.append)
    acquisition = AcquisitionService(storage, SimpleNamespace(), similarity_extractor=SimpleNamespace(), video_service=video_service)

    batch = acquisition.create_import_batch(db_session, workspace.id, [asset.id])
    acquisition.process_import_batch(db_session, batch.id)

    item = db_session.scalar(select(AcquisitionImportBatchItem).where(AcquisitionImportBatchItem.batch_id == batch.id))
    assert (item.status, item.video_id) == ("gallery_duplicate", existing.id)
    assert optimized_ids == []
    assert storage.files[existing.object_key] == payload


def test_acquisition_video_hash_mismatch_cleans_new_object(db_session: Session) -> None:
    from app.models import AcquisitionAsset
    from app.services.videos import VideoService

    payload = b"unexpected-video-content"
    storage = _FakeStorage()
    storage.put_bytes("acquisition/unexpected.mp4", payload)
    asset = AcquisitionAsset(
        id="unexpected-video", sha256="0" * 64, filename="unexpected.mp4",
        object_key="acquisition/unexpected.mp4", media_type="video", size_bytes=len(payload), status="pending_review",
    )

    with pytest.raises(ValueError, match="SHA256"):
        VideoService(storage).import_acquisition_asset(db_session, asset, None, None)

    assert list(storage.files) == [asset.object_key]
    assert db_session.scalar(select(VideoItem)) is None


def test_regular_upload_uses_shared_video_creation(db_session: Session, monkeypatch) -> None:
    from app.schemas.videos import VideoUploadCompleteRequest, VideoUploadSessionCreate
    from app.services.video_processing import VideoProbeInfo
    from app.services.videos import VideoService

    payload = b"regular-upload-video"
    storage = _FakeStorage()
    service = VideoService(storage)
    monkeypatch.setattr(service, "_probe_object", lambda *_: VideoProbeInfo(12.0, 1280, 720, "h264", "aac"))
    session = service.create_upload_session(
        db_session,
        VideoUploadSessionCreate(title="普通上传", filename="regular.mp4", size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()),
        workspace_id=None,
    )
    service.put_upload_part(db_session, session, 0, payload)

    video = service.complete_upload(db_session, session, VideoUploadCompleteRequest())

    assert (video.title, video.sha256, video.status, video.duration_seconds) == (
        "普通上传", hashlib.sha256(payload).hexdigest(), "uploaded", 12.0,
    )
    assert storage.files[video.object_key] == payload


def test_upload_cleanup_failure_keeps_committed_video(db_session: Session, monkeypatch) -> None:
    from app.schemas.videos import VideoUploadCompleteRequest, VideoUploadSessionCreate
    from app.services.video_processing import VideoProbeInfo
    from app.services.videos import VideoService

    payload = b"video-before-cleanup-error"
    storage = _FakeStorage()
    service = VideoService(storage)
    monkeypatch.setattr(service, "_probe_object", lambda *_: VideoProbeInfo(5.0, 640, 480, "h264", "aac"))
    session = service.create_upload_session(
        db_session, VideoUploadSessionCreate(title="清理失败测试", filename="cleanup.mp4", size_bytes=len(payload)), None,
    )
    service.put_upload_part(db_session, session, 0, payload)

    def fail_cleanup(_keys: list[str]) -> None:
        raise RuntimeError("模拟暂存分片清理失败")

    monkeypatch.setattr(storage, "remove_objects", fail_cleanup)
    with pytest.raises(RuntimeError, match="暂存分片清理失败"):
        service.complete_upload(db_session, session, VideoUploadCompleteRequest())

    video = db_session.scalar(select(VideoItem).where(VideoItem.title == "清理失败测试"))
    assert video is not None
    assert storage.files[video.object_key] == payload


