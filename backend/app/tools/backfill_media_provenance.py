"""历史来源回填：默认只读试跑；审核报告后使用 --apply-report 写入。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (AcquisitionAsset, AcquisitionImportBatch, AcquisitionImportBatchItem,
    AcquisitionImportedPhoto, AcquisitionImportedVideo, GalleryPhoto, User, VideoItem, Workspace, WorkspaceMember)
from app.services.provenance import actor_snapshot, asset_source, attach_provenance


def _asset(db, media):
    is_photo = isinstance(media, GalleryPhoto)
    history = AcquisitionImportedPhoto if is_photo else AcquisitionImportedVideo
    target = history.gallery_photo_id if is_photo else history.video_id
    ids = list(db.scalars(select(history.asset_id).where(target == media.id).order_by(history.created_at, history.id)))
    batch_target = AcquisitionImportBatchItem.gallery_photo_id if is_photo else AcquisitionImportBatchItem.video_id
    ids.extend(db.scalars(select(AcquisitionImportBatchItem.asset_id).join(AcquisitionImportBatch).where(
        batch_target == media.id, AcquisitionImportBatchItem.status == "imported",
        AcquisitionImportBatch.workspace_id == media.workspace_id).order_by(AcquisitionImportBatchItem.created_at)))
    for asset_id in dict.fromkeys(ids):
        asset = db.get(AcquisitionAsset, asset_id)
        if asset and asset.workspace_id == media.workspace_id:
            return asset
    return None


def build_report(db, photo_user_id: int, *, assume_untracked_videos_manual: bool = False):
    user = db.get(User, photo_user_id)
    if user is None:
        raise ValueError("指定的图片历史入库用户不存在")
    report = {"说明": "只补缺失来源和入库人；请审核后使用本报告执行回填", "图片入库人": {"id": user.id, "name": actor_snapshot(db, user.id)},
              "统计": {"图片": 0, "视频": 0, "未知来源": 0, "可追溯采集": 0, "来源类型推断": 0, "待确认": 0}, "items": [], "conflicts": []}
    for model in (GalleryPhoto, VideoItem):
        for media in db.scalars(select(model).order_by(model.id)).yield_per(200):
            if media.provenance is not None and (media.created_by is not None or media.provenance.record_method != "backfilled"):
                continue
            photo = isinstance(media, GalleryPhoto)
            actor_id = media.created_by
            if actor_id is None:
                if photo:
                    actor_id = photo_user_id
                else:
                    workspace = db.get(Workspace, media.workspace_id) if media.workspace_id else None
                    members = select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == media.workspace_id)
                    admins = list(db.scalars(select(User.id).where(User.is_admin.is_(True), or_(User.id.in_(members), User.id == (workspace.owner_user_id if workspace else -1)))))
                    if len(admins) != 1:
                        report["conflicts"].append({"media_type": "video", "id": media.id, "原因": "工作区管理员无法唯一确定"})
                        report["统计"]["待确认"] += 1
                        continue
                    actor_id = admins[0]
            source = None
            if media.provenance is None:
                asset = _asset(db, media)
                if asset:
                    report["统计"]["可追溯采集"] += 1
                    source = asset_source(db, asset)
                else:
                    kind = ("manual_upload" if not photo and assume_untracked_videos_manual else
                            {"manual": "manual_upload", "manual_upload": "manual_upload", "gallery_zip": "import", "acquisition": "acquisition"}.get(getattr(media, "ingest_source", ""), "unknown"))
                    source = {"source_type": kind}
                    if kind != "unknown":
                        report["统计"]["来源类型推断"] += 1
                source["record_method"] = "backfilled"
                if source["source_type"] == "unknown":
                    report["统计"]["未知来源"] += 1
            report["统计"]["图片" if photo else "视频"] += 1
            report["items"].append({"media_type": "photo" if photo else "video", "id": media.id,
                "workspace_id": media.workspace_id, "sha256": media.sha256, "created_at": media.created_at.isoformat(),
                "actor_id": actor_id, "actor_name": media.actor_name or actor_snapshot(db, actor_id), "snapshot": source,
                "fill_actor": media.created_by is None})
    return report


def apply_report(db, report):
    changed = 0
    for entry in report["items"]:
        model = GalleryPhoto if entry["media_type"] == "photo" else VideoItem
        media = db.get(model, entry["id"])
        if not media or media.workspace_id != entry["workspace_id"] or media.sha256 != entry["sha256"] or media.created_at.isoformat() != entry["created_at"]:
            raise ValueError(f"素材已变化，请重新试跑：{entry['media_type']} {entry['id']}")
        if db.get(User, entry["actor_id"]) is None:
            raise ValueError("报告中的入库用户已不存在")
        if media.provenance is not None and media.provenance.record_method != "backfilled":
            continue
        modified = False
        if media.provenance is None and entry["snapshot"]:
            attach_provenance(db, media, source_type=entry["snapshot"]["source_type"],
                actor_id=media.created_by or entry["actor_id"], actor_name=media.actor_name or entry["actor_name"],
                snapshot=entry["snapshot"], record_method="backfilled")
            modified = True
        if media.created_by is None and entry["fill_actor"]:
            media.created_by, media.actor_name = entry["actor_id"], entry["actor_name"]
            if media.provenance and not media.provenance.actor_name:
                media.provenance.actor_name = entry["actor_name"]
                data = json.loads(media.provenance.snapshot_json)
                data.update(actor_name=entry["actor_name"], record_method="backfilled")
                media.provenance.snapshot_json = json.dumps(data, ensure_ascii=False)
            modified = True
        changed += int(modified)
    db.commit()
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo-user-id", type=int)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply-report", type=Path)
    parser.add_argument("--assume-untracked-videos-manual", action="store_true", help="仅在已核实旧视频无采集记录者均为手动上传时使用")
    args = parser.parse_args()
    if not args.apply_report and (args.photo_user_id is None or args.report is None):
        parser.error("试跑需要 --photo-user-id 和 --report")
    engine = create_engine(get_settings().database_url)
    try:
        with Session(engine) as db:
            if args.apply_report:
                report = json.loads(args.apply_report.read_text(encoding="utf-8"))
                print(json.dumps({"写入数量": apply_report(db, report)}, ensure_ascii=False))
            else:
                report = build_report(db, args.photo_user_id, assume_untracked_videos_manual=args.assume_untracked_videos_manual)
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report["统计"], ensure_ascii=False))
                db.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
