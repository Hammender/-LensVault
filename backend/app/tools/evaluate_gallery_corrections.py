from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, FaceRecognitionCorrection, GalleryPhoto, Person
from app.services.face import FaceRuntime, FaceService
from app.services.importer import PictureService
from app.services.ocr import OcrService
from app.services.qdrant import QdrantVectorStore
from app.services.storage import MinioStorage


def _is_better_correction(candidate: FaceRecognitionCorrection, current: FaceRecognitionCorrection) -> bool:
    # 同一人脸多次纠正时只保留最后一条事件，避免重复计数。
    return candidate.id > current.id


def _load_corrections(limit: int | None) -> list[tuple[FaceRecognitionCorrection, GalleryPhoto, FaceRecord, bool]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(FaceRecognitionCorrection)
            .where(FaceRecognitionCorrection.gallery_photo_id.is_not(None))
            .order_by(FaceRecognitionCorrection.id)
        ).all()
        latest: dict[tuple[int, int], FaceRecognitionCorrection] = {}
        for row in rows:
            if row.gallery_photo_id is None or row.face_record_id is None:
                continue
            key = (row.gallery_photo_id, row.face_record_id)
            previous = latest.get(key)
            if previous is None or _is_better_correction(row, previous):
                latest[key] = row
        selected = list(latest.values())
        selected.sort(key=lambda row: row.id)
        if limit is not None:
            selected = selected[:limit]
        person_ids = {row.predicted_person_id for row in selected if row.predicted_person_id is not None}
        unknown_person_ids = {
            person.id for person in db.scalars(select(Person).where(Person.id.in_(person_ids))).all()
            if person.is_unknown
        }
        result = []
        for correction in selected:
            photo = db.get(GalleryPhoto, correction.gallery_photo_id)
            face = db.get(FaceRecord, correction.face_record_id)
            if photo is not None and face is not None:
                result.append((correction, photo, face, correction.predicted_person_id in unknown_person_ids or correction.predicted_person_id is None))
        return result


def _evaluate_config(
    name: str,
    detection_size: int,
    flip_augmentation: bool,
    corrections: list[tuple[FaceRecognitionCorrection, GalleryPhoto, FaceRecord, bool]],
) -> dict[str, object]:
    base = get_settings()
    settings = base.model_copy(update={
        "face_detection_size": detection_size,
        "face_flip_augmentation": flip_augmentation,
    })
    storage = MinioStorage(settings)
    face_service = FaceService(settings)
    vector_store = QdrantVectorStore(settings)
    service = PictureService(storage, face_service, vector_store, OcrService(), settings)
    detected_by_photo: dict[int, list[object]] = {}
    rows: list[dict[str, object]] = []
    started = time.perf_counter()
    failures: list[dict[str, object]] = []
    for index, (correction, photo, old_face, old_prediction_was_unknown) in enumerate(corrections, start=1):
        try:
            detected = detected_by_photo.get(photo.id)
            if detected is None:
                detected = face_service.detect_faces(storage.get_bytes(photo.object_key))
                detected_by_photo[photo.id] = detected
            target_bbox = (old_face.bbox_left, old_face.bbox_top, old_face.bbox_right, old_face.bbox_bottom)
            selected = max(
                detected,
                key=lambda item: FaceRuntime.bbox_iou(item.bbox, target_bbox),
                default=None,
            )
            if selected is None or FaceRuntime.bbox_iou(selected.bbox, target_bbox) < 0.3:
                raise RuntimeError("无法在重新检测结果中定位原纠正人脸")
            match = service._match_face(selected, photo.workspace_id)
            predicted = match.person_id
            accepted = (
                predicted is not None
                and match.score is not None
                and match.score >= settings.face_recognition_threshold
                and (match.margin is None or match.margin >= settings.face_recognition_min_margin)
            )
            rows.append({
                "correction_id": correction.id,
                "gallery_photo_id": photo.id,
                "face_record_id": old_face.id,
                "corrected_person_id": correction.corrected_person_id,
                "old_predicted_person_id": correction.predicted_person_id,
                "old_predicted_score": correction.predicted_score,
                "predicted_person_id": predicted,
                "score": match.score,
                "margin": match.margin,
                "accepted": accepted,
                "old_prediction_was_unknown": old_prediction_was_unknown,
                "recovered_unknown": old_prediction_was_unknown and accepted and predicted == correction.corrected_person_id,
                "correct": accepted and predicted == correction.corrected_person_id,
                "wrong_identity": accepted and predicted != correction.corrected_person_id,
            })
        except Exception as exc:
            failures.append({"correction_id": correction.id, "gallery_photo_id": photo.id, "error": f"{type(exc).__name__}: {exc}"})
        if index % 25 == 0:
            print(f"{name}: {index}/{len(corrections)}", flush=True)
    elapsed = time.perf_counter() - started
    unknown_rows = [row for row in rows if row["old_prediction_was_unknown"]]
    summary = {
        "name": name,
        "detection_size": detection_size,
        "flip_augmentation": flip_augmentation,
        "corrections": len(rows),
        "old_unknown_corrections": len(unknown_rows),
        "recovered_unknown": sum(bool(row["recovered_unknown"]) for row in rows),
        "correct_after_redetect": sum(bool(row["correct"]) for row in rows),
        "wrong_identity_after_redetect": sum(bool(row["wrong_identity"]) for row in rows),
        "rejected_after_redetect": sum(not bool(row["accepted"]) for row in rows),
        "detection_failures": len(failures),
        "elapsed_seconds": round(elapsed, 2),
        "photos_detected": len(detected_by_photo),
    }
    return {"summary": summary, "rows": rows, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description="只读评估真实图库人工纠正样本的人脸检测配置。")
    parser.add_argument("--output", type=Path, default=Path("data/gallery-correction-evaluation"))
    parser.add_argument("--limit", type=int, help="限制纠正样本数量；默认处理全部最新纠正样本。")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit 必须大于 0")
    corrections = _load_corrections(args.limit)
    if not corrections:
        raise SystemExit("没有可用的图库人工纠正样本")
    configs = [
        ("baseline_640_no_flip", 640, False),
        ("flip_640", 640, True),
        ("large_1024", 1024, False),
        ("large_1024_flip", 1024, True),
    ]
    reports = []
    for name, size, flip in configs:
        reports.append(_evaluate_config(name, size, flip, corrections))
    report = {
        "sample_source": "face_recognition_corrections latest per gallery face",
        "input_corrections": len(corrections),
        "configs": [item["summary"] for item in reports],
        "details": reports,
        "limitation": "该基准只覆盖发生过人工纠正的图库人脸；其中原预测为未知的人数由数据决定，不能推断未纠正图库的未知召回率。",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 真实图库人工纠正样本评估", "", report["limitation"], "", "| 配置 | 纠正样本 | 原预测未知 | 找回未知 | 重检正确 | 重检错认 | 重检拒绝 | 用时(秒) |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for item in report["configs"]:
        lines.append(f"| {item['name']} | {item['corrections']} | {item['old_unknown_corrections']} | {item['recovered_unknown']} | {item['correct_after_redetect']} | {item['wrong_identity_after_redetect']} | {item['rejected_after_redetect']} | {item['elapsed_seconds']} |")
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"input_corrections": len(corrections), "configs": report["configs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
