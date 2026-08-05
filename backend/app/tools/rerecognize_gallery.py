from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, select

from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person
from app.services.face import FaceService
from app.services.importer import PictureService
from app.services.ocr import OcrService
from app.services.qdrant import QdrantVectorStore
from app.services.storage import MinioStorage


REQUIRED_FACE_COLUMNS = {
    "predicted_person_id",
    "rejection_reason",
    "recognition_adapter_id",
    "decision_threshold",
    "decision_min_margin",
}


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


def _snapshot(db, photo_id: int) -> dict[str, object]:
    links = db.scalars(
        select(GalleryPhotoPersonTag)
        .where(GalleryPhotoPersonTag.gallery_photo_id == photo_id)
        .order_by(GalleryPhotoPersonTag.person_id)
    ).all()
    faces = db.scalars(
        select(FaceRecord).where(FaceRecord.gallery_photo_id == photo_id).order_by(FaceRecord.id)
    ).all()
    return {
        "person_tags": [{"person_id": link.person_id, "source": link.source} for link in links],
        "faces": [
            {
                "face_record_id": face.id,
                "bbox": [face.bbox_left, face.bbox_top, face.bbox_right, face.bbox_bottom],
                "detection_score": face.detection_score,
                "matched_person_id": face.matched_person_id,
                "predicted_person_id": face.predicted_person_id,
                "score": face.match_score,
                "second_person_id": face.second_person_id,
                "second_score": face.second_match_score,
                "margin": face.match_margin,
                "rejection_reason": face.rejection_reason,
                "recognition_adapter_id": face.recognition_adapter_id,
                "decision_threshold": face.decision_threshold,
                "decision_min_margin": face.decision_min_margin,
                "embedding_version": face.embedding_version,
                "face_size": face.face_size,
                "blur_score": face.blur_score,
                "pose_yaw": face.pose_yaw,
                "needs_review": face.needs_review,
                "vector_collection": face.vector_collection,
            }
            for face in faces
        ],
    }


def _append_audit(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="可预演、可恢复的全图库人脸重新识别工具。")
    parser.add_argument("--workspace-id", type=int, help="只处理指定工作区；默认处理全部工作区。")
    parser.add_argument("--start-after", type=int, default=0, help="只处理 ID 大于该值的照片。")
    parser.add_argument("--limit", type=int, help="本次最多处理多少张照片。")
    parser.add_argument("--audit-file", type=Path, help="审计 JSONL 路径。")
    parser.add_argument("--resume", action="store_true", help="跳过同一审计文件中已成功的照片。")
    parser.add_argument(
        "--preserve-existing-known-tags",
        action="store_true",
        help="把迁移前已有的非未知人物绑定视为导入绑定并保留；仅用于确认图库来自旧导入包的情况。",
    )
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演并回滚。")
    parser.add_argument("--confirm", action="store_true", help="确认正式写入，必须与 --apply 同时使用。")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式写入必须同时提供 --apply --confirm；预演时两个参数都不要提供。")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit 必须大于 0。")

    columns = {column["name"] for column in inspect(engine).get_columns("face_records")}
    missing = sorted(REQUIRED_FACE_COLUMNS - columns)
    if missing:
        raise SystemExit(
            "数据库尚未完成新版人脸字段迁移："
            + ", ".join(missing)
            + "。请先由使用者手动启动一次新版后端，确认启动成功后再关闭并运行本工具。"
        )

    settings = get_settings()
    mode = "apply" if args.apply else "dry-run"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    audit_path = args.audit_file or settings.data_dir / "face-rerecognition" / f"{timestamp}-{mode}.jsonl"
    completed = _load_completed(audit_path, mode) if args.resume else set()

    storage = MinioStorage(settings)
    face_service = FaceService(settings)
    vector_store = QdrantVectorStore(settings)
    service = PictureService(storage, face_service, vector_store, OcrService(), settings)
    with SessionLocal() as db:
        query = select(GalleryPhoto.id).where(GalleryPhoto.id > args.start_after).order_by(GalleryPhoto.id)
        if args.workspace_id is not None:
            query = query.where(GalleryPhoto.workspace_id == args.workspace_id)
        photo_ids = list(db.scalars(query).all())
    photo_ids = [photo_id for photo_id in photo_ids if photo_id not in completed]
    if args.limit is not None:
        photo_ids = photo_ids[: args.limit]

    succeeded = 0
    failed = 0
    for position, photo_id in enumerate(photo_ids, start=1):
        with SessionLocal() as db:
            photo = db.get(GalleryPhoto, photo_id)
            if photo is None:
                failed += 1
                _append_audit(audit_path, {
                    "mode": mode,
                    "status": "failed",
                    "gallery_photo_id": photo_id,
                    "error": "photo_not_found",
                })
                continue
            before = _snapshot(db, photo_id)
            if args.preserve_existing_known_tags:
                links = db.scalars(
                    select(GalleryPhotoPersonTag)
                    .join(Person, Person.id == GalleryPhotoPersonTag.person_id)
                    .where(
                        GalleryPhotoPersonTag.gallery_photo_id == photo_id,
                        Person.is_unknown.is_(False),
                    )
                ).all()
                for link in links:
                    if not service._is_preserved_person_tag_source(link.source):
                        link.source = "import"
                db.flush()
            base_row = {
                "mode": mode,
                "gallery_photo_id": photo_id,
                "workspace_id": photo.workspace_id,
                "position": position,
                "total": len(photo_ids),
                "collection": settings.qdrant_known_collection,
                "embedding_version": settings.face_embedding_version,
                "adapter_id": settings.face_adapter_id,
                "threshold": settings.face_recognition_threshold,
                "min_margin": settings.face_recognition_min_margin,
                "preserve_existing_known_tags": args.preserve_existing_known_tags,
                "before": before,
            }
            row_status = "failed"
            try:
                result = service.re_recognize_gallery_photo(db, photo, commit=args.apply)
                after = _snapshot(db, photo_id)
                summary = getattr(result, "recognition_summary", None)
                if not args.apply:
                    db.rollback()
                _append_audit(audit_path, {**base_row, "status": "success", "summary": summary, "after": after})
                succeeded += 1
                row_status = "success"
            except Exception as exc:
                db.rollback()
                _append_audit(audit_path, {
                    **base_row,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                failed += 1
        print(f"[{position}/{len(photo_ids)}] photo_id={photo_id} status={row_status}")

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
