from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from sqlalchemy import create_engine, inspect, text
from alembic import command
from alembic.config import Config
from pathlib import Path

from app.api.acquisition import _asset_read, _frame_asset, capture_asset_frame
from app.dependencies.context import ROUTE_PERMISSION_MATRIX
from app.models import AcquisitionAsset, AcquisitionImportBatch, AcquisitionImportBatchItem, GalleryPhoto
from app.schemas.acquisition import AcquisitionFrameLocate
from app.services.acquisition import AcquisitionService
from app.services.acquisition_frames import AcquisitionFrameService, _color_filter, _probe_frames, _source_color


class MemoryStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.reads = 0

    def put_bytes(self, key, payload, content_type=None):
        self.objects[key] = payload

    def get_stream(self, key):
        self.reads += 1
        return io.BytesIO(self.objects[key])

    def get_bytes(self, key):
        return self.objects[key]

    def remove_object(self, key):
        self.objects.pop(key, None)


@pytest.fixture
def settings():
    return SimpleNamespace(ffmpeg_path=shutil.which("ffmpeg"), ffprobe_path=shutil.which("ffprobe"),
                           acquisition_quality_min_pixels=1, acquisition_quality_max_aspect_ratio=10,
                           acquisition_quality_blur_threshold=0)


def run_video(command):
    subprocess.run(command, check=True, capture_output=True, timeout=30)


@pytest.fixture(params=["constant", "variable", "offset", "rotated"])
def sample_video(tmp_path, settings, request):
    if not settings.ffmpeg_path or not settings.ffprobe_path:
        pytest.skip("运行真实解码测试需要 FFmpeg 和 FFprobe")
    path = tmp_path / "source.mp4"
    args = [settings.ffmpeg_path, "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=96x64:rate=10:duration=1", "-c:v", "libx264", "-g", "3", "-bf", "2"]
    if request.param == "variable":
        args += ["-vf", "setpts=if(lt(N\\,5)\\,N\\,5+(N-5)*2)/(10*TB)", "-fps_mode", "vfr"]
    elif request.param == "offset":
        args += ["-vf", "setpts=PTS+5/TB", "-copyts"]
    run_video([*args, str(path)])
    if request.param == "rotated":
        rotated = tmp_path / "rotated.mp4"
        run_video([settings.ffmpeg_path, "-v", "error", "-y", "-display_rotation", "90", "-i", str(path),
                   "-c", "copy", str(rotated)])
        path = rotated
    return path, request.param


def test_real_selected_frame_matches_full_decode(sample_video, settings):
    path, kind = sample_video
    storage = MemoryStorage()
    payload = path.read_bytes()
    storage.objects["source"] = payload
    asset = SimpleNamespace(id="video", workspace_id=7, sha256=hashlib.sha256(payload).hexdigest(),
                            object_key="source", filename=path.name, size_bytes=len(payload))
    frames = AcquisitionFrameService(storage, settings)
    try:
        # 不同 FFmpeg 版本可能通过 MP4 编辑列表丢弃末帧，以独立全量解码的可播放帧数为准。
        decoded = subprocess.run([
            settings.ffmpeg_path, "-v", "error", "-i", str(path), "-map", "0:v:0",
            "-fps_mode", "passthrough", "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ], capture_output=True, check=True, timeout=30).stdout
        frame_count, remainder = divmod(len(decoded), 96 * 64 * 3)
        assert remainder == 0
        assert frame_count >= 8
        for index in (0, 4, 7, frame_count - 1):
            located, image = frames.extract(asset, index=index)
            expected = subprocess.run([
                settings.ffmpeg_path, "-v", "error", "-i", str(path), "-map", "0:v:0",
                "-vf", f"select=eq(n\\,{index}),{_color_filter(located['color_conversion'])}",
                "-fps_mode", "passthrough", "-frames:v", "1",
                "-c:v", "png", "-f", "image2pipe", "-",
            ], capture_output=True, check=True, timeout=30).stdout
            with Image.open(io.BytesIO(image)) as actual, Image.open(io.BytesIO(expected)) as reference:
                assert actual.size == ((64, 96) if kind == "rotated" else (96, 64))
                assert actual.tobytes() == reference.tobytes()
                assert actual.format == "PNG"
                assert actual.info.get("icc_profile")
            assert located["color_conversion"]["output"] == "sRGB"
            assert located["frame_index"] == index
            assert located["total_frames"] == frame_count
            assert frames.locate(asset, located["time_seconds"])["frame_index"] == index
        assert frames.locate(asset, index=0, direction=-1)["frame_index"] == 0
        assert frames.locate(asset, index=frame_count - 1, direction=1)["frame_index"] == frame_count - 1
        assert storage.reads == 1
        if kind == "variable":
            assert frames.locate(asset, index=7)["time_seconds"] == pytest.approx(.9)
        if kind == "offset":
            assert frames.locate(asset, index=0)["time_seconds"] == pytest.approx(0)
        cached = next(iter(frames._videos.values()))
        cached.used_at = time.monotonic() - 301
        frames._prune()
        assert not cached.path.exists()
    finally:
        frames.close()


def test_untagged_sdr_uses_bt709_and_hdr_is_rejected():
    color = _source_color({})
    assert color["source"] == {"matrix": "bt709", "transfer": "bt709", "primaries": "bt709", "range": "tv"}
    assert color["assumed"] == ["matrix", "transfer", "primaries", "range"]
    tagged = _source_color({"color_space": "smpte170m", "color_transfer": "smpte170m",
                            "color_primaries": "smpte170m", "color_range": "pc"})
    assert tagged["source"]["matrix"] == "smpte170m"
    assert tagged["source"]["range"] == "pc"
    assert tagged["assumed"] == []
    with pytest.raises(ValueError, match="HDR"):
        _source_color({"color_transfer": "smpte2084"})


@pytest.fixture
def capture_context(db_session, settings):
    video = AcquisitionAsset(id="video", workspace_id=None, sha256="a" * 64, filename="原视频.mp4",
                             media_type="video", object_key="source", size_bytes=100, quality_warnings="[]")
    db_session.add(video)
    db_session.commit()
    output = io.BytesIO()
    Image.new("RGB", (1600, 900), "#237b75").save(output, format="PNG")
    storage = MemoryStorage()
    storage.objects["source"] = b"original-video"
    service = AcquisitionService(storage, SimpleNamespace(), settings)
    metadata = dict(source_caption="原始文案", source_hashtags=["来源标签"],
                    source_published_at="2026-10-04T12:00:00+08:00", source_message_url="https://example.test/1",
                    source_channel_title="来源频道")
    return video, service, output.getvalue(), metadata


def test_probe_skips_invalid_timestamps_and_rejects_empty():
    frames = _probe_frames({"frames": [
        {"best_effort_timestamp": "N/A", "best_effort_timestamp_time": "N/A"},
        {"best_effort_timestamp": 1, "best_effort_timestamp_time": "0.1", "key_frame": 1},
        {"best_effort_timestamp_time": "0.2"},
        {"best_effort_timestamp": 3, "best_effort_timestamp_time": "0.2", "key_frame": 0},
    ]})
    assert [(frame.pts, frame.seconds) for frame in frames] == [(1, 0.1), (3, 0.2)]
    with pytest.raises(ValueError, match="没有可定位"):
        _probe_frames({"frames": [{"best_effort_timestamp": "N/A", "best_effort_timestamp_time": "N/A"}]})


def test_preparing_one_video_does_not_block_another(settings, monkeypatch):
    class SlowStorage(MemoryStorage):
        def get_stream(self, key):
            time.sleep(0.25)
            return super().get_stream(key)

    storage = SlowStorage()
    storage.objects["a"] = b"aaaa"
    storage.objects["b"] = b"bbbb"
    probe = json.dumps({
        "frames": [{"best_effort_timestamp": 0, "best_effort_timestamp_time": "0", "key_frame": 1}],
        "format": {"start_time": "0"},
        "streams": [{}],
    }).encode()
    monkeypatch.setattr(
        AcquisitionFrameService,
        "_run",
        staticmethod(lambda command: SimpleNamespace(returncode=0, stdout=probe, stderr=b"")),
    )
    frames = AcquisitionFrameService(storage, settings)
    assets = [
        SimpleNamespace(workspace_id=None, id="va", sha256="a" * 64, object_key="a", filename="a.mp4", size_bytes=4),
        SimpleNamespace(workspace_id=None, id="vb", sha256="b" * 64, object_key="b", filename="b.mp4", size_bytes=4),
    ]
    errors: list[BaseException] = []

    def locate(asset):
        try:
            frames.locate(asset)
        except BaseException as exc:
            errors.append(exc)

    started = time.monotonic()
    workers = [threading.Thread(target=locate, args=(asset,)) for asset in assets]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    elapsed = time.monotonic() - started
    frames.close()
    assert errors == []
    assert elapsed < 0.4


def test_capture_is_independent_deduplicated_and_restorable(db_session, capture_context):
    video, service, payload, metadata = capture_context
    frame = {"frame_index": 12, "time_seconds": 1.2, "color_conversion": _source_color({})}
    asset, outcome = service.capture_frame(db_session, video, frame, payload, metadata)
    assert outcome == "created"
    assert (asset.width, asset.height, asset.status) == (1600, 900, "pending_review")
    assert video.status == "pending_review"
    read = _asset_read(db_session, asset)
    assert read.source_caption == metadata["source_caption"]
    assert read.source_hashtags == ["来源标签"]
    assert read.source_message_url == metadata["source_message_url"]
    assert read.capture_metadata.video_filename == "原视频.mp4"
    assert read.capture_metadata.time_seconds == 1.2
    assert read.capture_metadata.color_conversion.version == "srgb-v1"
    assert asset.filename == "原视频_截图_00-01-200_sRGB.png"
    second, outcome = service.capture_frame(db_session, video, frame, payload, metadata)
    assert second.id == asset.id and outcome == "existing"
    service.reject_assets(db_session, None, [asset.id])
    assert asset.object_key is None
    restored, outcome = service.capture_frame(db_session, video, frame, payload, metadata)
    assert restored.id == asset.id and outcome == "restored"
    service.reject_assets(db_session, None, [video.id])
    assert video.object_key is None
    assert service.storage.get_bytes(restored.object_key) == payload
    assert _asset_read(db_session, restored).source_caption == "原始文案"


def test_capture_blocks_in_flight_import_and_restores_failed(db_session, capture_context):
    video, service, payload, metadata = capture_context
    frame = {"frame_index": 1, "time_seconds": 0.1, "color_conversion": _source_color({})}
    asset, _ = service.capture_frame(db_session, video, frame, payload, metadata)
    asset.status = "importing"
    db_session.commit()
    same, outcome = service.capture_frame(db_session, video, frame, payload, metadata)
    assert same.id == asset.id and outcome == "existing" and same.status == "importing"
    asset.status = "import_queued"
    db_session.commit()
    queued, outcome = service.capture_frame(db_session, video, frame, payload, metadata)
    assert queued.id == asset.id and outcome == "existing" and queued.status == "import_queued"
    asset.status = "import_failed"
    asset.error_message = "入库失败"
    db_session.commit()
    restored, outcome = service.capture_frame(db_session, video, frame, payload, metadata)
    assert restored.id == asset.id and outcome == "restored"
    assert restored.status == "pending_review" and restored.error_message is None


def test_capture_write_failure_cleans_object(db_session, capture_context, monkeypatch):
    video, service, payload, metadata = capture_context
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("写入失败")))
    with pytest.raises(RuntimeError, match="写入失败"):
        service.capture_frame(db_session, video, {"frame_index": 0, "time_seconds": 0}, payload, metadata)
    assert set(service.storage.objects) == {"source"}
    assert len(db_session.scalars(select(AcquisitionAsset)).all()) == 1


def test_frame_access_rejects_other_workspace_changed_source_and_cleared_file(db_session, capture_context):
    video, _, _, _ = capture_context
    with pytest.raises(HTTPException) as error:
        _frame_asset(db_session, SimpleNamespace(workspace_id=2), video.id, video.sha256)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        _frame_asset(db_session, SimpleNamespace(workspace_id=None), video.id, "b" * 64)
    assert error.value.status_code == 409
    video.status = "rejected"
    with pytest.raises(HTTPException) as error:
        _frame_asset(db_session, SimpleNamespace(workspace_id=None), video.id, video.sha256)
    assert error.value.status_code == 409
    assert ROUTE_PERMISSION_MATRIX[("POST", "/api/acquisition/assets/{asset_id}/captures")] == "can_add_gallery"


def test_capture_does_not_duplicate_gallery_and_snapshot_survives_import_link(db_session, capture_context):
    video, service, payload, metadata = capture_context
    asset, _ = service.capture_frame(db_session, video, {"frame_index": 1, "time_seconds": .1}, payload, metadata)
    def import_photo(db, filename, image, content_type, **kwargs):
        assert image == payload and content_type == "image/png"
        photo = GalleryPhoto(filename=filename, sha256=hashlib.sha256(image).hexdigest(),
                             object_key="gallery/frame.png", ingest_source=kwargs["ingest_source"])
        db.add(photo)
        db.flush()
        return photo, SimpleNamespace(duplicated=False)
    service.pictures = SimpleNamespace(import_gallery_photo=import_photo)
    batch = service.create_import_batch(db_session, None, [asset.id])
    service.process_import_batch(db_session, batch.id)
    item = db_session.scalar(select(AcquisitionImportBatchItem).where(AcquisitionImportBatchItem.batch_id == batch.id))
    assert item.status == "imported"
    assert asset.status == "imported" and asset.object_key is None
    assert video.status == "pending_review" and video.object_key == "source"
    same, outcome = service.capture_frame(db_session, video, {"frame_index": 1, "time_seconds": .1}, payload, metadata)
    assert same.id == asset.id and outcome == "imported"
    linked = db_session.scalar(select(AcquisitionAsset).join(AcquisitionImportBatchItem).where(
        AcquisitionImportBatchItem.gallery_photo_id == item.gallery_photo_id))
    assert _asset_read(db_session, linked).capture_metadata.video_asset_id == video.id
    assert "capture_metadata_json" not in GalleryPhoto.__table__.columns


def test_save_rechecks_source_after_decode(db_session, capture_context):
    video, service, image, metadata = capture_context
    def extract(*args):
        video.status = "rejected"
        db_session.commit()
        return {"frame_index": 0, "time_seconds": 0}, image
    service._frames = SimpleNamespace(extract=extract)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(acquisition=service))))
    with pytest.raises(HTTPException) as error:
        capture_asset_frame(video.id, AcquisitionFrameLocate(source_sha256=video.sha256), request, db_session,
                            SimpleNamespace(workspace_id=None))
    assert error.value.status_code == 409
    assert len(db_session.scalars(select(AcquisitionAsset)).all()) == 1


def test_capture_migration_preserves_existing_rows_indexes_and_foreign_keys(tmp_path):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    command.upgrade(config, "bc12196435fb")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO acquisition_assets (id, sha256, filename, size_bytes, status, created_at, updated_at) "
                                "VALUES ('old', :hash, '旧图片.jpg', 100, 'pending_review', '2026-10-01', '2026-10-01')"), {"hash": "b" * 64})
    indexes = inspect(engine).get_indexes("acquisition_assets")
    foreign_keys = inspect(engine).get_foreign_keys("acquisition_assets")
    constraints = inspect(engine).get_unique_constraints("acquisition_assets")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT filename, capture_metadata_json FROM acquisition_assets WHERE id='old'")).one() == ("旧图片.jpg", None)
    command.downgrade(config, "bc12196435fb")
    assert "capture_metadata_json" not in {c["name"] for c in inspect(engine).get_columns("acquisition_assets")}
    assert inspect(engine).get_indexes("acquisition_assets") == indexes
    assert inspect(engine).get_foreign_keys("acquisition_assets") == foreign_keys
    assert sorted(inspect(engine).get_unique_constraints("acquisition_assets"), key=lambda c: json.dumps(c, sort_keys=True)) == sorted(constraints, key=lambda c: json.dumps(c, sort_keys=True))
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT filename FROM acquisition_assets WHERE id='old'")) == "旧图片.jpg"
    engine.dispose()
