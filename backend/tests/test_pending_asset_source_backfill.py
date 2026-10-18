from __future__ import annotations

from datetime import datetime
import json

import pytest
from sqlalchemy import select

from app.models import (AcquisitionAsset, AcquisitionCategory, AcquisitionRun, AcquisitionRunItem,
    AcquisitionSource, AcquisitionSourceItem, AcquisitionTelegramHashtag, AcquisitionTelegramMessage)
from app.services.acquisition import AcquisitionService
from app.services.provenance import acquisition_snapshot, asset_source, export_source
from app.tools.backfill_pending_asset_sources import apply_report, build_report
from tests.test_media_provenance import seed, photo


def legacy_asset(db, *, frozen_run=False):
    seed(db)
    source = AcquisitionSource(workspace_id=1, name="站点")
    db.add(source); db.flush()
    category = AcquisitionCategory(source_id=source.id, name="分类", path="甲/乙", crawl_url="https://example.test")
    db.add(category); db.flush()
    run = AcquisitionRun(id="run", workspace_id=1, source_id=source.id, category_id=category.id,
                         source_name_snapshot="站点快照", category_name_snapshot="分类")
    item = AcquisitionSourceItem(source_id=source.id, category_id=category.id, external_key="1", source_url="https://example.test/1")
    asset = AcquisitionAsset(id="legacy", workspace_id=1, sha256="hash", filename="a.jpg", status="pending_review")
    db.add_all([run, item, asset]); db.flush()
    message = AcquisitionTelegramMessage(workspace_id=1, source_item_id=item.id, channel_id="99",
        channel_title="频道名", message_id=42, media_type="image", caption="文" * 60,
        topic_id=7, topic_title="话题名", message_url="https://t.me/c/99/42", published_at=datetime(2026, 1, 1))
    db.add(message); db.flush()
    db.add(AcquisitionTelegramHashtag(telegram_message_id=message.id, tag_raw="#标签", tag_normalized="标签"))
    snapshot = acquisition_snapshot(db, run, category, url=item.source_url,
        telegram={"channel_title": "频道名", "message_id": 42, "caption": "文" * 60,
                  "topic_title": "话题名", "hashtags": ["#标签"]}) if frozen_run else None
    db.add(AcquisitionRunItem(run_id=run.id, source_item_id=item.id, asset_id=asset.id,
        source_snapshot_json=json.dumps(snapshot) if snapshot else None))
    db.commit()
    return asset, category


@pytest.mark.parametrize("frozen_run", [False, True])
def test_legacy_pending_asset_backfill_survives_category_delete_and_import(db_session, frozen_run):
    db = db_session
    asset, category = legacy_asset(db, frozen_run=frozen_run)
    report = build_report(db)
    assert len(report["items"]) == 1 and report["unresolved"] == []
    assert asset.source_snapshot_json is None
    db.expire_all()
    assert asset.source_snapshot_json is None  # 试跑没有隐式写入。
    assert apply_report(db, report) == 1
    frozen = asset.source_snapshot_json
    assert apply_report(db, report) == 0
    assert build_report(db)["items"] == []
    db.delete(category); db.commit()
    assert db.scalar(select(AcquisitionRunItem)) is None
    result = photo(db)
    AcquisitionService._finish_imported(AcquisitionService.__new__(AcquisitionService), db, None, asset, result)
    db.commit()
    snapshot = export_source(result)
    assert snapshot["site_name"] == "站点快照" and snapshot["category_path"] == "甲/乙"
    assert snapshot["original_url"] == "https://example.test/1"
    tg = snapshot["telegram"]
    assert tg["channel_title"] == "频道名" and tg["topic_title"] == "话题名"
    assert tg["caption_excerpt"] == "文" * 50 and tg["caption_truncated"]
    assert tg["hashtags"] == ["#标签"]
    assert asset.source_snapshot_json == frozen


def test_backfill_preserves_existing_snapshot_and_lists_missing_evidence(db_session):
    asset, _ = legacy_asset(db_session)
    asset.source_snapshot_json = '{"source_type":"acquisition","site_name":"首次来源"}'
    orphan = AcquisitionAsset(id="orphan", workspace_id=1, sha256="orphan", filename="old.jpg")
    ignored = AcquisitionAsset(id="rejected", workspace_id=1, sha256="rejected", filename="r.jpg", status="rejected")
    db_session.add_all([orphan, ignored]); db_session.commit()
    report = build_report(db_session)
    assert report["items"] == []
    assert [row["id"] for row in report["unresolved"]] == ["orphan"]
    assert json.loads(asset.source_snapshot_json)["site_name"] == "首次来源"


def test_apply_rejects_changed_asset_and_rolls_back_all_entries(db_session):
    asset, _ = legacy_asset(db_session)
    report = build_report(db_session)
    report["items"].append({**report["items"][0], "sha256": "changed"})
    with pytest.raises(ValueError, match="素材已变化"):
        apply_report(db_session, report)
    db_session.expire_all()
    assert asset.source_snapshot_json is None


def test_apply_does_not_overwrite_snapshot_created_since_dry_run(db_session):
    asset, _ = legacy_asset(db_session)
    report = build_report(db_session)
    asset.source_snapshot_json = '{"source_type":"acquisition","site_name":"已冻结"}'
    db_session.commit()
    assert apply_report(db_session, report) == 0
    assert json.loads(asset.source_snapshot_json)["site_name"] == "已冻结"


def test_backfilled_first_source_wins_over_remaining_later_run(db_session):
    db = db_session
    asset, original = legacy_asset(db)
    apply_report(db, build_report(db))
    category = AcquisitionCategory(source_id=original.source_id, name="后来分类", path="后来", crawl_url="https://example.test/later")
    db.add(category); db.flush()
    run = AcquisitionRun(id="later-run", workspace_id=1, source_id=original.source_id, category_id=category.id,
                         source_name_snapshot="后来站点", category_name_snapshot="后来分类")
    item = AcquisitionSourceItem(source_id=original.source_id, category_id=category.id,
                                  external_key="later", source_url="https://example.test/later")
    db.add_all([run, item]); db.flush()
    db.add(AcquisitionRunItem(run_id=run.id, source_item_id=item.id, asset_id=asset.id,
        source_snapshot_json=json.dumps(acquisition_snapshot(db, run, category))))
    db.commit()
    db.delete(original); db.commit()
    assert db.scalar(select(AcquisitionRunItem)).run_id == "later-run"
    snapshot = asset_source(db, asset)
    assert snapshot["site_name"] == "站点快照" and snapshot["category_path"] == "甲/乙"


def test_apply_skips_asset_imported_since_dry_run(db_session):
    asset, _ = legacy_asset(db_session)
    report = build_report(db_session)
    asset.status = "imported"
    db_session.commit()
    assert apply_report(db_session, report) == 0
    assert asset.source_snapshot_json is None
