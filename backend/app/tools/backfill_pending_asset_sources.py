"""补齐升级前待审核素材的来源快照；默认试跑，审核报告后再写入。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AcquisitionAsset
from app.services.provenance import asset_source, normalize_snapshot


STATUSES = ("pending_review", "import_failed")


def build_report(db: Session) -> dict:
    report = {"version": 1, "items": [], "unresolved": []}
    assets = db.scalars(select(AcquisitionAsset).where(
        AcquisitionAsset.status.in_(STATUSES), AcquisitionAsset.source_snapshot_json.is_(None),
    ).order_by(AcquisitionAsset.created_at, AcquisitionAsset.id)).yield_per(200)
    for asset in assets:
        snapshot = normalize_snapshot(asset_source(db, asset))
        if not snapshot.get("site_name") and not snapshot.get("category_path"):
            report["unresolved"].append({"id": asset.id, "原因": "原采集记录已缺失，无法恢复站点和分类"})
            continue
        report["items"].append({
            "id": asset.id, "workspace_id": asset.workspace_id, "sha256": asset.sha256,
            "created_at": asset.created_at.isoformat(), "snapshot": snapshot,
        })
    return report


def apply_report(db: Session, report: dict) -> int:
    if report.get("version") != 1:
        raise ValueError("回填报告版本不支持")
    changed = 0
    try:
        for entry in report["items"]:
            asset = db.get(AcquisitionAsset, entry["id"])
            if (asset is None or asset.workspace_id != entry["workspace_id"]
                    or asset.sha256 != entry["sha256"] or asset.created_at.isoformat() != entry["created_at"]):
                raise ValueError(f"素材已变化，请重新试跑：{entry['id']}")
            snapshot = json.dumps(normalize_snapshot(entry["snapshot"]), ensure_ascii=False)
            # 条件更新保证试跑后新采集写入的快照及已经入库的素材不会被覆盖。
            result = db.execute(update(AcquisitionAsset).where(
                AcquisitionAsset.id == asset.id, AcquisitionAsset.status.in_(STATUSES),
                AcquisitionAsset.source_snapshot_json.is_(None),
            ).values(source_snapshot_json=snapshot))
            changed += result.rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", type=Path, help="试跑报告路径，不写数据库")
    mode.add_argument("--apply-report", type=Path, help="审核后的试跑报告，显式写入数据库")
    args = parser.parse_args()
    engine = create_engine(get_settings().database_url)
    try:
        with Session(engine) as db:
            if args.apply_report:
                report = json.loads(args.apply_report.read_text(encoding="utf-8"))
                print(json.dumps({"写入数量": apply_report(db, report)}, ensure_ascii=False))
            else:
                report = build_report(db)
                args.report.parent.mkdir(parents=True, exist_ok=True)
                with args.report.open("x", encoding="utf-8") as output:
                    json.dump(report, output, ensure_ascii=False, indent=2)
                db.rollback()
                print(json.dumps({"可回填": len(report["items"]), "无法恢复": len(report["unresolved"])}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
