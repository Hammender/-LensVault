from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, select

# Support direct execution from the repository root as well as module execution.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.models import GalleryPhoto
from app.services.storage import MinioStorage


def _append_audit(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def _load_completed(path: Path, mode: str) -> set[int]:
    if not path.is_file():
        return set()
    completed: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("mode") == mode and row.get("status") == "success":
            completed.add(int(row["gallery_photo_id"]))
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description="可预演、可恢复的展示图库文件大小回填工具。")
    parser.add_argument("--workspace-id", type=int, help="只处理指定工作区；默认处理全部工作区。")
    parser.add_argument("--start-after", type=int, default=0, help="只处理 ID 大于该值的图片。")
    parser.add_argument("--limit", type=int, help="本次最多处理多少张图片。")
    parser.add_argument("--audit-file", type=Path, help="审计 JSONL 路径。")
    parser.add_argument("--resume", action="store_true", help="跳过同一审计文件中已成功的图片。")
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演。")
    parser.add_argument("--confirm", action="store_true", help="确认正式写入，必须与 --apply 同时使用。")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式写入必须同时提供 --apply --confirm；预演时两个参数都不要提供。")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit 必须大于 0。")

    columns = {column["name"] for column in inspect(engine).get_columns("gallery_photos")}
    if "size_bytes" not in columns:
        raise SystemExit("数据库尚未完成图库文件大小字段迁移，请先手工启动一次新版后端后再运行本工具。")

    settings = get_settings()
    mode = "apply" if args.apply else "dry-run"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    audit_path = args.audit_file or settings.data_dir / "gallery-photo-size-backfill" / f"{timestamp}-{mode}.jsonl"
    completed = _load_completed(audit_path, mode) if args.resume else set()
    storage = MinioStorage(settings)

    with SessionLocal() as db:
        query = (
            select(GalleryPhoto.id)
            .where(GalleryPhoto.id > args.start_after, GalleryPhoto.size_bytes.is_(None))
            .order_by(GalleryPhoto.id)
        )
        if args.workspace_id is not None:
            query = query.where(GalleryPhoto.workspace_id == args.workspace_id)
        photo_ids = [photo_id for photo_id in db.scalars(query).all() if photo_id not in completed]
    if args.limit is not None:
        photo_ids = photo_ids[: args.limit]

    succeeded = 0
    failed = 0
    for position, photo_id in enumerate(photo_ids, start=1):
        with SessionLocal() as db:
            photo = db.get(GalleryPhoto, photo_id)
            if photo is None or photo.size_bytes is not None:
                continue
            base_row = {
                "mode": mode,
                "gallery_photo_id": photo.id,
                "workspace_id": photo.workspace_id,
                "object_key": photo.object_key,
                "position": position,
                "total": len(photo_ids),
            }
            try:
                size_bytes = int(storage.stat_object(photo.object_key).size)
                if args.apply:
                    photo.size_bytes = size_bytes
                    db.commit()
                _append_audit(audit_path, {**base_row, "status": "success", "size_bytes": size_bytes})
                succeeded += 1
                status = "success"
            except Exception as exc:
                db.rollback()
                _append_audit(audit_path, {
                    **base_row,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                failed += 1
                status = "failed"
        print(f"[{position}/{len(photo_ids)}] photo_id={photo_id} status={status}")

    print(json.dumps({
        "mode": mode,
        "total": len(photo_ids),
        "succeeded": succeeded,
        "failed": failed,
        "audit_file": str(audit_path),
    }, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
