from __future__ import annotations

import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
from sqlalchemy import select

from app.core.config import Settings
from app.models import VideoExportJob, VideoItem, VideoSubtitleTrack
from app.services.provenance import attach_provenance, export_source
from app.services.video_transfer import export_video_package, import_video_package
from app.services.videos import VideoService
from tests.test_media_provenance import seed


class Storage:
    def __init__(self):
        self.objects = {}
    def put_bytes(self, key, payload, *_):
        self.objects[key] = payload
    def put_file(self, key, path, *_):
        self.objects[key] = path.read_bytes()
    def get_stream(self, key):
        stream = BytesIO(self.objects[key])
        stream.release_conn = lambda: None
        stream.stream = lambda size: iter(lambda: stream.read(size), b"")
        return stream
    def remove_object(self, key):
        self.objects.pop(key, None)


def setup_video(db, data_dir=None):
    seed(db)
    storage = Storage()
    service = VideoService(storage, Settings(data_dir=data_dir) if data_dir else Settings())
    service._probe_object = lambda *_: SimpleNamespace(video_codec="h264", audio_codec="aac", duration_seconds=5, width=32, height=32)
    service.playback_optimization_needed = lambda *_: False
    storage.objects["video"] = b"optimized-file-bytes"
    buf = BytesIO(); Image.new("RGB", (2, 2)).save(buf, "PNG")
    storage.objects["cover"] = buf.getvalue()
    video = VideoItem(workspace_id=1, title="原视频", filename="clip.mp4", description="简介", object_key="video", size_bytes=20,
                      sha256="original-ingest-hash", status="ready", cover_object_key="cover", cover_content_type="image/png")
    db.add(video); db.flush()
    attach_provenance(db, video, actor_id=1, source_type="acquisition", snapshot={"source_type": "acquisition", "site_name": "原站点"})
    db.add(VideoSubtitleTrack(video_id=video.id, language="zh-CN", label="中文字幕", status="ready", content_vtt="WEBVTT\n\n00:00.000 --> 00:01.000\n你好\n"))
    db.commit()
    job = VideoExportJob(id="job", workspace_id=1, selection_json=json.dumps([video.id]))
    db.add(job); db.commit()
    export_video_package(db, service, job)
    assert job.status == "ready"
    return service, storage, job, video


def test_video_roundtrip_actual_hash_source_cover_and_subtitle(db_session, tmp_path):
    service, storage, job, original = setup_video(db_session, tmp_path)
    path = tmp_path / "videos.zip"
    path.write_bytes(storage.objects[job.object_key])
    with ZipFile(path) as archive:
        entry = json.loads(archive.read("metadata.json"))["videos"][0]
        assert entry["sha256"] == hashlib.sha256(b"optimized-file-bytes").hexdigest()
        assert entry["sha256"] != original.sha256
    result = import_video_package(db_session, service, path, 2, 2)
    assert result["imported"] == 1 and not result["errors"] and not result["warnings"], result
    video = db_session.scalar(select(VideoItem).where(VideoItem.workspace_id == 2))
    assert video.created_by == 2
    assert video.status == "ready" and video.faststart_applied is False
    assert video.cover_object_key and video.subtitle_tracks[0].content_vtt.startswith("WEBVTT")
    assert export_source(video)["upstream"]["site_name"] == "原站点"
    assert export_source(video)["actor_name"] == "成员"
    assert import_video_package(db_session, service, path, 2, 1)["duplicates"] == 1
    assert video.created_by == 2


def test_legacy_optimized_video_is_duplicate_in_same_workspace(db_session, tmp_path):
    service, storage, job, original = setup_video(db_session, tmp_path)
    original.size_bytes = len(storage.objects["video"])
    db_session.commit()
    path = tmp_path / "videos.zip"; path.write_bytes(storage.objects[job.object_key])
    result = import_video_package(db_session, service, path, 1, 1)
    assert result["duplicates"] == 1, result
    assert original.content_sha256 == hashlib.sha256(storage.objects["video"]).hexdigest()


def test_corrupt_video_entry_does_not_create_media_or_source(db_session, tmp_path):
    service, storage, job, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "bad.zip"
    with ZipFile(BytesIO(storage.objects[job.object_key])) as source, ZipFile(path, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename.startswith("videos/"):
                payload = b"corrupted"
            target.writestr(info.filename, payload)
    result = import_video_package(db_session, service, path, 2, 2)
    assert len(result["errors"]) == 1 and result["imported"] == 0
    assert db_session.scalar(select(VideoItem).where(VideoItem.workspace_id == 2)) is None


def _bomb_package(tmp_path, *, compress=True):
    bomb = b"\0" * (5 * 1024 * 1024)
    entry = {"filename": "bomb.mp4", "path": "videos/bomb.mp4", "sha256": hashlib.sha256(bomb).hexdigest(),
             "size_bytes": len(bomb), "title": "炸弹", "video_type": "long"}
    path = tmp_path / "bomb.zip"
    with ZipFile(path, "w", ZIP_DEFLATED if compress else 0) as archive:
        archive.writestr("videos/bomb.mp4", bomb)
        archive.writestr("metadata.json", json.dumps({"kind": "video_export", "version": 1, "videos": [entry]}))
    return path, entry


def test_package_rejects_compression_bomb_entry_without_writing_disk(db_session, tmp_path, monkeypatch):
    opened: list[str] = []
    original = ZipFile.open

    def spy(self, name, *args, **kwargs):
        opened.append(getattr(name, "filename", name))
        return original(self, name, *args, **kwargs)

    service, _, _, _ = setup_video(db_session, tmp_path)
    path, _ = _bomb_package(tmp_path)
    monkeypatch.setattr(ZipFile, "open", spy)
    result = import_video_package(db_session, service, path, 2, 2)
    assert result["imported"] == 0 and len(result["errors"]) == 1
    assert "压缩比" in result["errors"][0]["message"]
    assert "videos/bomb.mp4" not in opened
    assert db_session.scalar(select(VideoItem).where(VideoItem.workspace_id == 2)) is None


def test_package_rejects_duplicate_manifest_paths(db_session, tmp_path):
    import pytest
    service, _, _, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "duplicate.zip"
    payload = b"video-bytes"
    entry = {"filename": f"{'a'}.mp4", "path": "videos/1.mp4", "sha256": hashlib.sha256(payload).hexdigest(),
             "size_bytes": len(payload), "title": "重复", "video_type": "long"}
    with ZipFile(path, "w") as archive:
        archive.writestr("videos/1.mp4", payload)
        archive.writestr("metadata.json", json.dumps({"kind": "video_export", "version": 1, "videos": [entry, dict(entry)]}))
    with pytest.raises(ValueError, match="重复引用"):
        import_video_package(db_session, service, path, 2, 2)


def test_package_rejects_declared_size_mismatch_before_extracting(db_session, tmp_path):
    service, _, _, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "size.zip"
    payload = b"video-bytes"
    entry = {"filename": "size.mp4", "path": "videos/1.mp4", "sha256": hashlib.sha256(payload).hexdigest(),
             "size_bytes": len(payload) + 10, "title": "大小不一致", "video_type": "long"}
    with ZipFile(path, "w") as archive:
        archive.writestr("videos/1.mp4", payload)
        archive.writestr("metadata.json", json.dumps({"kind": "video_export", "version": 1, "videos": [entry]}))
    result = import_video_package(db_session, service, path, 2, 2)
    assert result["imported"] == 0 and len(result["errors"]) == 1
    assert "大小" in result["errors"][0]["message"]


def test_spool_upload_rejects_oversized_package(tmp_path):
    import asyncio
    import pytest
    from app.services.import_spool import cleanup_import, spool_upload

    class Upload:
        filename = "package.zip"
        def __init__(self, payload: bytes) -> None:
            self.payload = payload
        async def read(self, size: int) -> bytes:
            chunk, self.payload = self.payload[:size], self.payload[size:]
            return chunk

    settings = Settings(data_dir=tmp_path)
    with pytest.raises(ValueError, match="上限"):
        asyncio.run(spool_upload(settings, "task-1", 0, Upload(b"x" * 4096), max_bytes=1024))
    cleanup_import(settings, "task-1")
    assert not (tmp_path / "tmp" / "imports" / "task-1").exists()


def test_export_start_rejects_concurrent_job_and_skips_unusable_videos(db_session, tmp_path):
    import pytest
    from fastapi import HTTPException
    from app.api.provenance import VideoExportRequest, create_video_export

    service, storage, _, _ = setup_video(db_session, tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        session_factory=None, services=SimpleNamespace(storage=storage, videos=service), settings=service.settings)))
    tasks = SimpleNamespace(add_task=lambda *args: None)
    current = SimpleNamespace(workspace_id=1)
    db_session.add(VideoExportJob(id="running", workspace_id=1, status="running", selection_json="[]"))
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create_video_export(VideoExportRequest(scope="all"), request, tasks, db_session, current)
    assert error.value.status_code == 409

    db_session.get(VideoExportJob, "running").status = "failed"
    broken = VideoItem(workspace_id=1, title="损坏", filename="broken.mp4", object_key="broken",
                       status="processing_failed", size_bytes=10)
    db_session.add(broken)
    db_session.commit()
    job = create_video_export(VideoExportRequest(scope="all"), request, tasks, db_session, current)
    stored = db_session.get(VideoExportJob, job.id)
    assert broken.id not in json.loads(stored.selection_json)
    stored.status = "failed"
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create_video_export(VideoExportRequest(scope="selected", video_ids=[broken.id]), request, tasks, db_session, current)
    assert error.value.status_code == 422


def test_export_start_drops_newer_job_when_older_active_job_wins(db_session, tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.api import provenance as provenance_api
    from app.api.provenance import VideoExportRequest, create_video_export

    service, storage, _, _ = setup_video(db_session, tmp_path)
    added = []
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        session_factory=None, services=SimpleNamespace(storage=storage, videos=service), settings=service.settings)))
    tasks = SimpleNamespace(add_task=lambda *args: added.append(args))
    current = SimpleNamespace(workspace_id=1)
    db_session.add(VideoExportJob(id="older", workspace_id=1, status="queued", selection_json="[]"))
    db_session.commit()
    calls = {"n": 0}
    real = provenance_api._oldest_active_export_id

    def skip_precheck(db, workspace_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real(db, workspace_id)

    monkeypatch.setattr(provenance_api, "_oldest_active_export_id", skip_precheck)
    with pytest.raises(HTTPException) as error:
        create_video_export(VideoExportRequest(scope="all"), request, tasks, db_session, current)
    assert error.value.status_code == 409
    assert added == []
    assert db_session.get(VideoExportJob, "older") is not None
    leftovers = list(db_session.scalars(select(VideoExportJob.id).where(
        VideoExportJob.workspace_id == 1, VideoExportJob.status.in_(["queued", "running"]))))
    assert leftovers == ["older"]


def test_import_runs_playback_optimization_only_when_needed(db_session, tmp_path):
    service, storage, job, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "videos.zip"
    path.write_bytes(storage.objects[job.object_key])
    calls = []
    service.playback_optimization_needed = lambda *_: True
    service.optimize_video_faststart = lambda video_id, **kwargs: calls.append((video_id, kwargs))
    result = import_video_package(db_session, service, path, 2, 2)
    assert result["imported"] == 1 and calls and not result["warnings"], result
    assert calls[0][1].get("keep_existing_cover") is True


def test_import_records_playback_optimization_failure(db_session, tmp_path):
    service, storage, job, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "videos.zip"
    path.write_bytes(storage.objects[job.object_key])
    service.playback_optimization_needed = lambda *_: True

    def fail(video_id, **kwargs):
        raise RuntimeError("模拟优化失败")

    service.optimize_video_faststart = fail
    result = import_video_package(db_session, service, path, 2, 2)
    assert result["imported"] == 1 and not result["errors"], result
    assert result["warnings"] and "播放优化失败" in result["warnings"][0]["message"]
    video = db_session.scalar(select(VideoItem).where(VideoItem.workspace_id == 2))
    assert video.status == "processing_failed"
    assert "模拟优化失败" in video.processing_error


def test_import_skip_marks_faststart_from_moov(db_session, tmp_path):
    service, storage, job, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "videos.zip"
    path.write_bytes(storage.objects[job.object_key])
    service._has_faststart_moov = lambda *_: True
    result = import_video_package(db_session, service, path, 2, 2)
    video = db_session.scalar(select(VideoItem).where(VideoItem.workspace_id == 2))
    assert result["imported"] == 1 and video.status == "ready" and video.faststart_applied is True


def test_import_skip_leaves_faststart_false_without_moov(db_session, tmp_path):
    service, storage, job, _ = setup_video(db_session, tmp_path)
    path = tmp_path / "videos.zip"
    path.write_bytes(storage.objects[job.object_key])
    service._has_faststart_moov = lambda *_: False
    result = import_video_package(db_session, service, path, 2, 2)
    video = db_session.scalar(select(VideoItem).where(VideoItem.workspace_id == 2))
    assert result["imported"] == 1 and video.status == "ready" and video.faststart_applied is False
