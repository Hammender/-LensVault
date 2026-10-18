from __future__ import annotations

from datetime import datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.api.provenance import photo_source
from app.models import (AcquisitionAsset, AcquisitionCategory, AcquisitionRun, AcquisitionRunItem,
    AcquisitionSource, AcquisitionSourceItem, GalleryPhoto, MediaProvenance, User, VideoItem, Workspace)
from app.services.provenance import (acquisition_snapshot, asset_source, attach_provenance,
    export_source, imported_snapshot, normalize_snapshot, public_metadata, source_summary)
from app.tools.backfill_media_provenance import apply_report, build_report
from app.tools.reclassify_legacy_videos import reclassify


def seed(db):
    db.add_all([User(id=1, username="Hamender", display_name="Hamender", password_hash="test", is_admin=True),
                User(id=2, username="member", display_name="成员", password_hash="test")])
    db.flush()
    db.add_all([Workspace(id=1, name="一", kind="shared", owner_user_id=1), Workspace(id=2, name="二", kind="shared", owner_user_id=2)])
    db.commit()


def photo(db, suffix="one", workspace_id=1):
    row = GalleryPhoto(workspace_id=workspace_id, filename=f"{suffix}.jpg", sha256=suffix, object_key=suffix)
    db.add(row)
    db.flush()
    return row


def test_source_and_media_rollback_together(db_session):
    seed(db_session)
    item = photo(db_session)
    attach_provenance(db_session, item, actor_id=1)
    db_session.flush()
    db_session.rollback()
    assert db_session.scalar(select(GalleryPhoto)) is None
    assert db_session.scalar(select(MediaProvenance)) is None


def test_source_is_frozen_and_actor_name_survives_rename_and_delete(db_session):
    seed(db_session)
    item = photo(db_session)
    attach_provenance(db_session, item, actor_id=1, source_type="acquisition", snapshot={"source_type": "acquisition", "site_name": "站点", "category_path": "甲/乙", "telegram": {"message_id": 42}})
    db_session.commit()
    attach_provenance(db_session, item, actor_id=2, snapshot={"site_name": "后来"})
    db_session.get(User, 1).display_name = "新名称"
    db_session.commit()
    assert item.created_by == 1
    assert source_summary(item)["text"] == "站点 · 甲/乙"
    assert export_source(item)["actor_name"] == "Hamender"
    assert export_source(item)["telegram"]["message_id"] == 42
    # 删除账号只解除外键，不丢失历史名称。
    db_session.execute(User.__table__.delete().where(User.id == 1))
    db_session.commit()
    db_session.expire_all()
    assert item.created_by is None
    assert export_source(item)["actor_name"] == "Hamender"


def test_database_rejects_orphan_source_and_two_media_targets(db_session):
    seed(db_session)
    db_session.add(MediaProvenance(workspace_id=1, source_type="unknown", snapshot_json="{}"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_summary_queries_batch_and_defer_large_snapshot(db_session):
    seed(db_session)
    for number in range(4):
        attach_provenance(db_session, photo(db_session, str(number)), actor_id=1)
    db_session.commit()
    db_session.expunge_all()
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        items = db_session.scalars(select(GalleryPhoto)).all()
        assert all(source_summary(item)["text"] == "手动上传 · Hamender" for item in items)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    assert not any("snapshot_json" in sql for sql in statements)


def test_source_read_denies_other_workspace(db_session):
    seed(db_session)
    item = photo(db_session)
    attach_provenance(db_session, item, actor_id=1)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        photo_source(item.id, db_session, SimpleNamespace(workspace_id=2))
    assert error.value.status_code == 404
    assert photo_source(item.id, db_session, SimpleNamespace(workspace_id=1))["actor_name"] == "Hamender"


def test_redaction_caption_limit_and_metadata_limit():
    data = normalize_snapshot({"source_type": "acquisition", "collected_at": datetime(2026, 1, 1),
        "original_url": "https://user:pass@example.test/post?id=42&token=secret",
        "telegram": {"caption_excerpt": "文" * 60, "message_url": "https://t.me/test/42?comment=5&token=x"},
        "public_metadata": {"title": "正常", "nested": {"Cookie": "secret", "text": "Bearer abc"}}})
    assert data["original_url"] == "https://example.test/post?id=42"
    assert len(data["telegram"]["caption_excerpt"]) == 50
    assert data["telegram"]["caption_truncated"]
    assert data["public_metadata"]["nested"] == {"text": "[已脱敏]"}
    assert public_metadata({str(i): "大" * 2000 for i in range(30)}) == {"metadata_truncated": True}
    with pytest.raises(ValueError):
        normalize_snapshot({"source_type": "invalid"})


def test_repeated_transfer_keeps_root_without_nested_history():
    original = {"source_type": "acquisition", "site_name": "原站点", "actor_name": "原入库人"}
    first = imported_snapshot(original)
    second = imported_snapshot({**first, "actor_name": "中间人"})
    assert second["upstream"]["site_name"] == "原站点"
    assert second["upstream"]["actor_name"] == "原入库人"
    assert "upstream" not in second["upstream"]


def test_first_capture_snapshot_survives_upstream_deletion(db_session):
    seed(db_session)
    db = db_session
    source = AcquisitionSource(workspace_id=1, name="站点")
    db.add(source); db.flush()
    category = AcquisitionCategory(source_id=source.id, name="分类", path="原路径", crawl_url="https://example.test")
    db.add(category); db.flush()
    asset = AcquisitionAsset(id="asset", workspace_id=1, sha256="hash", filename="a.jpg")
    db.add(asset)
    for index in [1, 2]:
        run = AcquisitionRun(id=f"run{index}", workspace_id=1, source_id=source.id, category_id=category.id,
                             source_name_snapshot=f"站点{index}", category_name_snapshot="分类")
        item = AcquisitionSourceItem(source_id=source.id, category_id=category.id, external_key=str(index), source_url=f"https://example.test/{index}")
        db.add_all([run, item]); db.flush()
        data = acquisition_snapshot(db, run, category, url=item.source_url)
        db.add(AcquisitionRunItem(run_id=run.id, source_item_id=item.id, asset_id=asset.id,
               created_at=datetime(2026, 1, index), source_snapshot_json=json.dumps(data)))
    db.commit()
    category.path = "改名后"
    db.commit()
    data = asset_source(db, asset)
    assert data["site_name"] == "站点1"
    assert data["category_path"] == "原路径"
    result = photo(db)
    attach_provenance(db, result, actor_id=1, source_type="acquisition", snapshot=data)
    db.commit()
    db.delete(source); db.commit()
    assert export_source(result)["original_url"] == "https://example.test/1"


def test_asset_source_survives_category_deletion(db_session):
    """待审核期间删掉分类后，素材仍能取到首次采集的站点与分类。"""
    from app.services.acquisition import AcquisitionService
    seed(db_session)
    db = db_session
    source = AcquisitionSource(workspace_id=1, name="站点")
    db.add(source); db.flush()
    category = AcquisitionCategory(source_id=source.id, name="分类", path="甲/乙", crawl_url="https://example.test")
    db.add(category); db.flush()
    run = AcquisitionRun(id="run", workspace_id=1, source_id=source.id, category_id=category.id,
                         source_name_snapshot="站点快照", category_name_snapshot="分类")
    item = AcquisitionSourceItem(source_id=source.id, category_id=category.id, external_key="1", source_url="https://example.test/1")
    db.add_all([run, item]); db.flush()
    asset = AcquisitionAsset(id="asset", workspace_id=1, sha256="hash", filename="a.jpg")
    db.add(asset)
    data = acquisition_snapshot(db, run, category, url=item.source_url)
    run_item = AcquisitionRunItem(run_id=run.id, source_item_id=item.id, asset_id=asset.id,
                                  source_snapshot_json=json.dumps(data))
    db.add(run_item); db.flush()
    AcquisitionService._freeze_asset_source(asset, run_item)
    db.commit()
    assert asset.source_snapshot_json
    db.delete(category); db.commit()
    assert db.scalar(select(AcquisitionRunItem)) is None
    result = asset_source(db, asset)
    assert result["source_type"] == "acquisition"
    assert result["site_name"] == "站点快照" and result["category_path"] == "甲/乙"
    assert result["original_url"] == "https://example.test/1"


def test_screenshot_source_does_not_need_video_or_run(db_session):
    seed(db_session)
    asset = AcquisitionAsset(id="frame", workspace_id=1, sha256="frame", filename="frame.png",
        capture_metadata_json=json.dumps({"video_asset_id": "removed", "video_filename": "clip.mp4", "time_seconds": 12.345,
            "frame_index": 123, "video_sha256": "hash", "provenance": {"source_type": "acquisition", "site_name": "上游"}}))
    data = asset_source(db_session, asset)
    assert data["source_type"] == "video_capture"
    assert data["capture"]["time_seconds"] == 12.345
    assert data["site_name"] == "上游"


def test_backfill_dry_run_and_idempotent_apply_cross_workspace(db_session):
    seed(db_session)
    one = photo(db_session)
    two = photo(db_session, "two", 2)
    db_session.commit()
    report = build_report(db_session, 1)
    assert report["统计"]["图片"] == 2
    assert one.provenance is None and two.created_by is None
    assert apply_report(db_session, report) == 2
    assert one.created_by == two.created_by == 1
    assert apply_report(db_session, report) == 0
    assert one.provenance.record_method == "backfilled"
    assert build_report(db_session, 1)["items"] == []


def test_telegram_forum_topic_transport_and_private_message_link():
    from app.services.telegram import TelegramService
    message = SimpleNamespace(id=12, grouped_id=None, date=datetime(2026, 1, 1), edit_date=None,
        photo=None, document=SimpleNamespace(attributes=[SimpleNamespace(file_name="original.png")]),
        reply_to=SimpleNamespace(forum_topic=True, reply_to_top_id=None, reply_to_msg_id=7))
    channel = SimpleNamespace(id=99, username=None, title="论坛", forum=True)
    result = TelegramService._record(message, channel, "image", "文案", [], None, False)
    assert result["topic_id"] == 7
    assert result["media_type"] == "image" and result["transport_type"] == "document"
    assert result["original_filename"] == "original.png"
    assert result["source_url"] == "https://t.me/c/99/12"
    channel.forum = False
    message.reply_to = SimpleNamespace(forum_topic=False, reply_to_top_id=7)
    assert TelegramService._record(message, channel, "image", "", [], None, False)["topic_id"] is None


def test_picture_v3_roundtrip_preserves_root_and_new_actor(db_session):
    import asyncio
    from io import BytesIO
    from app.api.gallery import _build_gallery_export_response
    from tests.test_gallery_zip_transfer import MemoryStorage, make_service
    seed(db_session)
    storage = MemoryStorage()
    original = photo(db_session)
    payload = b"test-image"
    import hashlib
    original.sha256 = hashlib.sha256(payload).hexdigest()
    storage.put_bytes(original.object_key, payload)
    attach_provenance(db_session, original, actor_id=1, source_type="acquisition", snapshot={"source_type": "acquisition", "site_name": "原站点"})
    db_session.commit()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(storage=storage))))
    response = _build_gallery_export_response(request, [original], "all")
    async def read():
        return b"".join([chunk async for chunk in response.body_iterator])
    package = asyncio.run(read())
    result = make_service(storage).import_gallery_from_zip(db_session, package, 2, actor_id=2)
    assert result["added_photos"] == 1
    copied = db_session.scalar(select(GalleryPhoto).where(GalleryPhoto.workspace_id == 2))
    assert copied.created_by == 2
    assert export_source(copied)["upstream"]["site_name"] == "原站点"
    make_service(storage).import_gallery_from_zip(db_session, package, 2, actor_id=1)
    assert copied.created_by == 2


def test_untracked_legacy_video_requires_explicit_manual_inference(db_session):
    seed(db_session)
    video = VideoItem(workspace_id=1, title="旧视频", filename="old.mp4", sha256="old", object_key="old", size_bytes=3)
    db_session.add(video)
    db_session.commit()
    normal = build_report(db_session, 1)
    assumed = build_report(db_session, 1, assume_untracked_videos_manual=True)
    assert normal["items"][0]["snapshot"]["source_type"] == "unknown"
    assert assumed["items"][0]["snapshot"]["source_type"] == "manual_upload"
    assert video.created_by is None and video.provenance is None


def test_reclassifying_legacy_unknown_video_preserves_other_sources(db_session):
    seed(db_session)
    video = VideoItem(workspace_id=1, title="旧视频", filename="old.mp4", sha256="old", object_key="old", size_bytes=3)
    db_session.add(video)
    db_session.flush()
    attach_provenance(db_session, video, actor_id=1, source_type="unknown", record_method="backfilled")
    image = photo(db_session)
    attach_provenance(db_session, image, actor_id=1, source_type="unknown", record_method="backfilled")
    db_session.commit()
    with pytest.raises(ValueError, match="数量已变化"):
        reclassify(db_session, user_id=1, expected_count=2)
    assert video.provenance.source_type == "unknown"
    assert reclassify(db_session, user_id=1, expected_count=1) == 1
    assert video.created_by == 1 and video.actor_name == "Hamender"
    assert video.provenance.source_type == "manual_upload"
    assert export_source(video)["source_type"] == "manual_upload"
    assert video.provenance.record_method == "backfilled"
    assert image.provenance.source_type == "unknown"
    assert reclassify(db_session, user_id=1, expected_count=0) == 0


def _tg_message(**overrides):
    base = dict(id=12, grouped_id=None, date=datetime(2026, 1, 1), edit_date=None,
                photo=None, video=None, gif=None, document=None, file=None,
                peer_id=SimpleNamespace(channel_id=99), is_comment=False,
                reply_to=None, sender=None, message="", protected=False)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_transport_type_uses_message_form_not_mime():
    from app.services.telegram import TelegramService
    channel = SimpleNamespace(id=99, username="chan", title="频道", forum=False)
    document = SimpleNamespace(attributes=[SimpleNamespace(file_name="clip.mp4")], mime_type="video/mp4")
    assert TelegramService._record(_tg_message(photo=object()), channel, "image", "", [], None, False)["transport_type"] == "photo"
    assert TelegramService._record(_tg_message(video=document, document=document), channel, "video", "", [], None, False)["transport_type"] == "video"
    assert TelegramService._record(_tg_message(gif=document, document=document), channel, "video", "", [], None, False)["transport_type"] == "animation"
    assert TelegramService._record(_tg_message(video=document, gif=document, document=document), channel, "video", "", [], None, False)["transport_type"] == "animation"
    assert TelegramService._record(_tg_message(document=document), channel, "video", "", [], None, False)["transport_type"] == "document"


def test_comment_keeps_channel_key_and_records_discussion_peer():
    from app.services.telegram import TelegramService
    channel = SimpleNamespace(id=99, username="chan", title="频道", forum=False)
    message = _tg_message(id=7, peer_id=SimpleNamespace(channel_id=555), is_comment=True, photo=object())
    record = TelegramService._record(message, channel, "image", "", [], None, False)
    assert record["external_key"] == "99:7:1"
    assert record["channel_id"] == "99" and record["channel_title"] == "频道"
    assert record["discussion_peer_id"] == "555" and record["peer_id"] == "555"
    normal = TelegramService._record(_tg_message(photo=object()), channel, "image", "", [], None, False)
    assert normal["discussion_peer_id"] is None and normal["peer_id"] == "99"


def test_oversized_snapshot_is_trimmed_instead_of_failing():
    snapshot = {"source_type": "acquisition", "site_name": "站点",
                "telegram": {"hashtags": ["#标签" * 200 for _ in range(100)], "channel_title": "深" * 2000},
                "public_metadata": {str(i): "值" * 500 for i in range(30)}}
    data = normalize_snapshot(snapshot)
    assert len(json.dumps(data, ensure_ascii=False).encode("utf-8")) <= 65536
    assert data["public_metadata"] == {"metadata_truncated": True}
    assert len(data["telegram"]["hashtags"]) <= 32
    nested = normalize_snapshot({"source_type": "import", "upstream": snapshot})
    assert len(json.dumps(nested, ensure_ascii=False).encode("utf-8")) <= 65536


def test_invalid_public_metadata_is_dropped_instead_of_failing():
    assert public_metadata("不是对象") == {}
    assert public_metadata(["列表"]) == {}
    data = normalize_snapshot({"source_type": "acquisition", "public_metadata": ["列表"]})
    assert data["public_metadata"] == {}


def test_legacy_screenshot_inherits_video_asset_source(db_session):
    seed(db_session)
    video = AcquisitionAsset(id="video-asset", workspace_id=1, sha256="v", filename="clip.mp4",
        source_snapshot_json=json.dumps({"version": 1, "source_type": "acquisition", "site_name": "站点", "category_path": "分类"}))
    frame = AcquisitionAsset(id="frame-asset", workspace_id=1, sha256="f", filename="frame.png",
        capture_metadata_json=json.dumps({"video_asset_id": "video-asset", "video_filename": "clip.mp4", "time_seconds": 3.0}))
    db_session.add_all([video, frame]); db_session.commit()
    data = asset_source(db_session, frame)
    assert data["source_type"] == "video_capture"
    assert data["site_name"] == "站点" and data["category_path"] == "分类"
    assert data["capture"]["time_seconds"] == 3.0
