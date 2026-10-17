from __future__ import annotations

import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

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


def setup_video(db):
    seed(db)
    storage = Storage()
    service = VideoService(storage, Settings())
    service._probe_object = lambda *_: SimpleNamespace(video_codec="h264", audio_codec="aac", duration_seconds=5, width=32, height=32)
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
    service, storage, job, original = setup_video(db_session)
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
    assert video.cover_object_key and video.subtitle_tracks[0].content_vtt.startswith("WEBVTT")
    assert export_source(video)["upstream"]["site_name"] == "原站点"
    assert export_source(video)["actor_name"] == "成员"
    assert import_video_package(db_session, service, path, 2, 1)["duplicates"] == 1
    assert video.created_by == 2


def test_legacy_optimized_video_is_duplicate_in_same_workspace(db_session, tmp_path):
    service, storage, job, original = setup_video(db_session)
    original.size_bytes = len(storage.objects["video"])
    db_session.commit()
    path = tmp_path / "videos.zip"; path.write_bytes(storage.objects[job.object_key])
    result = import_video_package(db_session, service, path, 1, 1)
    assert result["duplicates"] == 1, result
    assert original.content_sha256 == hashlib.sha256(storage.objects["video"]).hexdigest()


def test_corrupt_video_entry_does_not_create_media_or_source(db_session, tmp_path):
    service, storage, job, _ = setup_video(db_session)
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
