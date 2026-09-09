from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, Person
from app.services.face import FaceRuntime, FaceService
from app.services.importer import PictureService
from app.services.ocr import OcrService
from app.services.qdrant import QdrantVectorStore
from app.services.storage import MinioStorage


def _load_photo_ids(workspace_id: int | None) -> list[int]:
    with SessionLocal() as db:
        statement = (
            select(GalleryPhoto.id)
            .join(FaceRecord, FaceRecord.gallery_photo_id == GalleryPhoto.id)
            .outerjoin(Person, Person.id == FaceRecord.matched_person_id)
            .where(FaceRecord.needs_review.is_(True),
                   (FaceRecord.matched_person_id.is_(None)) | Person.is_unknown.is_(True))
            .distinct()
            .order_by(GalleryPhoto.id)
        )
        if workspace_id is not None:
            statement = statement.where(GalleryPhoto.workspace_id == workspace_id)
        return list(db.scalars(statement).all())


def _evaluate(
    *, name: str, settings, photo_ids: list[int], storage: MinioStorage,
    vector_store: QdrantVectorStore,
) -> dict[str, object]:
    face_service = FaceService(settings)
    service = PictureService(storage, face_service, vector_store, OcrService(), settings)
    started = time.perf_counter()
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    processed_photos = 0
    old_unknown_faces = 0
    with SessionLocal() as db:
        for index, photo_id in enumerate(photo_ids, start=1):
            photo = db.get(GalleryPhoto, photo_id)
            if photo is None:
                continue
            unknown_faces = db.scalars(
                select(FaceRecord).where(
                    FaceRecord.gallery_photo_id == photo.id,
                    FaceRecord.needs_review.is_(True),
                    FaceRecord.matched_person_id.is_not(None),
                    FaceRecord.matched_person.has(Person.is_unknown.is_(True)),
                ).order_by(FaceRecord.id)
            ).all()
            if not unknown_faces:
                continue
            old_unknown_faces += len(unknown_faces)
            try:
                detected = face_service.detect_faces(storage.get_bytes(photo.object_key))
                used: set[int] = set()
                for old_face in unknown_faces:
                    target_bbox = (old_face.bbox_left, old_face.bbox_top, old_face.bbox_right, old_face.bbox_bottom)
                    candidates = [
                        (FaceRuntime.bbox_iou(item.bbox, target_bbox), item_index, item)
                        for item_index, item in enumerate(detected)
                        if item_index not in used
                    ]
                    if not candidates:
                        raise RuntimeError("重新检测没有可匹配的人脸")
                    overlap, item_index, selected = max(candidates, key=lambda item: item[0])
                    if overlap < 0.3:
                        raise RuntimeError(f"重新检测人脸框无法对应旧未知人脸，IoU={overlap:.3f}")
                    used.add(item_index)
                    match = service._match_face(selected, photo.workspace_id)
                    accepted = (
                        match.person_id is not None
                        and match.score is not None
                        and match.score >= settings.face_recognition_threshold
                        and (match.margin is None or match.margin >= settings.face_recognition_min_margin)
                    )
                    rows.append({
                        "gallery_photo_id": photo.id,
                        "old_face_record_id": old_face.id,
                        "old_score": old_face.match_score,
                        "old_rejection_reason": old_face.rejection_reason,
                        "predicted_person_id": match.person_id,
                        "score": match.score,
                        "margin": match.margin,
                        "accepted": accepted,
                    })
                processed_photos += 1
            except Exception as exc:
                failures.append({"gallery_photo_id": photo.id, "error": f"{type(exc).__name__}: {exc}"})
            if index % 25 == 0:
                print(f"{name}: {index}/{len(photo_ids)}", flush=True)
    accepted = [row for row in rows if row["accepted"]]
    summary = {
        "name": name,
        "photos": len(photo_ids),
        "processed_photos": processed_photos,
        "old_unknown_faces": old_unknown_faces,
        "candidate_rows": len(rows),
        "accepted_known_candidates": len(accepted),
        "rejected_candidates": len(rows) - len(accepted),
        "detection_or_matching_failures": len(failures),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    return {"summary": summary, "rows": rows, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description="只读评估现有未知图库人脸在新识别配置下的候选结果。")
    parser.add_argument("--output", type=Path, default=Path("data/unknown-gallery-evaluation"))
    parser.add_argument("--workspace-id", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--flip-augmentation", action="store_true")
    parser.add_argument("--model-name", default=None, help="实验检测模型包，例如 antelopev2。")
    parser.add_argument("--adapter-id", default=None, help="实验识别适配器 ID。")
    parser.add_argument("--model-path", type=Path, default=None, help="实验识别 ONNX 文件路径。")
    parser.add_argument("--collection", default=None, help="实验 Qdrant 集合名称。")
    parser.add_argument("--embedding-version", default=None, help="实验向量版本。")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit 必须大于 0")
    base = get_settings()
    updates: dict[str, object] = {"face_flip_augmentation": args.flip_augmentation}
    if args.threshold is not None:
        if not 0 <= args.threshold <= 1:
            raise SystemExit("--threshold 必须在 0 到 1 之间")
        updates["face_recognition_threshold"] = args.threshold
    if args.model_name is not None:
        updates["face_model_name"] = args.model_name
    if args.adapter_id is not None:
        updates["face_adapter_id"] = args.adapter_id
    if args.model_path is not None:
        updates["face_recognition_model_path"] = str(args.model_path)
    if args.collection is not None:
        updates["qdrant_known_collection"] = args.collection
    if args.embedding_version is not None:
        updates["face_embedding_version"] = args.embedding_version
    settings = base.model_copy(update=updates)
    photo_ids = _load_photo_ids(args.workspace_id)
    if args.limit is not None:
        photo_ids = photo_ids[:args.limit]
    if not photo_ids:
        raise SystemExit("没有可评估的未知人脸照片")
    storage = MinioStorage(settings)
    vector_store = QdrantVectorStore(settings)
    configs = [
        ("flip640_t" + str(settings.face_recognition_threshold), True),
    ]
    reports = []
    for name, flip in configs:
        run_settings = settings.model_copy(update={"face_flip_augmentation": flip})
        reports.append(_evaluate(name=name, settings=run_settings, photo_ids=photo_ids,
                                 storage=storage, vector_store=vector_store))
    report = {
        "input_photos": len(photo_ids),
        "threshold": settings.face_recognition_threshold,
        "min_margin": settings.face_recognition_min_margin,
        "flip_augmentation": settings.face_flip_augmentation,
        "model": {"name": settings.face_model_name, "adapter_id": settings.face_adapter_id,
                  "model_path": settings.face_recognition_model_path or None,
                  "collection": settings.qdrant_known_collection,
                  "embedding_version": settings.face_embedding_version},
        "configs": [item["summary"] for item in reports],
        "details": reports,
        "limitation": "没有人工真值时，accepted_known_candidates 代表可疑的已知候选，不等于确认正确；本工具全程只读。",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 未知图库人脸只读评估", "", report["limitation"], "", "| 配置 | 照片 | 候选人脸 | 接受为已知候选 | 拒绝 | 检测/匹配失败 | 用时(秒) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for item in report["configs"]:
        lines.append(f"| {item['name']} | {item['photos']} | {item['candidate_rows']} | {item['accepted_known_candidates']} | {item['rejected_candidates']} | {item['detection_or_matching_failures']} | {item['elapsed_seconds']} |")
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"input_photos": len(photo_ids), "configs": report["configs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
