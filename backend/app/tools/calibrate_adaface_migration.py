from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, SamplePhoto
from app.services.face_profiles import ReferenceFace
from app.services.qdrant import QdrantVectorStore
from app.tools.evaluate_face_profiles import EvaluationSample, predict, reference_split


SEED = "pictureshow-adaface-20260908"


def _flip_rows(path: Path) -> list[dict[str, object]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    details = next(item for item in report["details"] if item["summary"]["name"] == "flip_640")
    return list(details["rows"])


def _metrics(rows: list[dict[str, object]], threshold: float, margin: float) -> dict[str, int | float]:
    accepted = [
        row for row in rows
        if row.get("score") is not None
        and float(row["score"]) >= threshold
        and (row.get("margin") is None or float(row["margin"]) >= margin)
    ]
    correct = [row for row in accepted if row["predicted_person_id"] == row["corrected_person_id"]]
    wrong = [row for row in accepted if row["predicted_person_id"] != row["corrected_person_id"]]
    recovered = [row for row in correct if row["old_prediction_was_unknown"]]
    return {
        "rows": len(rows),
        "accepted": len(accepted),
        "correct": len(correct),
        "wrong_identity": len(wrong),
        "rejected": len(rows) - len(accepted),
        "recovered_unknown": len(recovered),
        "wrong_identity_rate": len(wrong) / len(rows) if rows else 0.0,
    }


def _split_photo_ids(rows: list[dict[str, object]], faces: dict[int, FaceRecord]) -> tuple[set[int], set[int]]:
    by_photo: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_photo[int(row["gallery_photo_id"])].append(row)
    strata: dict[tuple[bool, bool, bool, bool], list[int]] = defaultdict(list)
    for photo_id, items in by_photo.items():
        item_faces = [faces.get(int(item["face_record_id"])) for item in items]
        key = (
            any(bool(item["old_prediction_was_unknown"]) for item in items),
            any(face is not None and face.face_size is not None and face.face_size < 80 for face in item_faces),
            any(face is not None and face.blur_score is not None and face.blur_score < 45 for face in item_faces),
            any(face is not None and face.pose_yaw is not None and abs(face.pose_yaw) >= 45 for face in item_faces),
        )
        strata[key].append(photo_id)
    holdout: set[int] = set()
    for photo_ids in strata.values():
        ordered = sorted(
            photo_ids,
            key=lambda photo_id: sha256(f"{SEED}:{photo_id}".encode()).hexdigest(),
        )
        count = round(len(ordered) * 0.3)
        if len(ordered) >= 2:
            count = max(1, min(count, len(ordered) - 1))
        holdout.update(ordered[:count])
    calibration = set(by_photo) - holdout
    return calibration, holdout


def _load_samples(collection: str, embedding_version: str) -> list[EvaluationSample]:
    settings = get_settings()
    store = QdrantVectorStore(settings)
    samples: list[EvaluationSample] = []
    with SessionLocal() as db:
        for sample in db.scalars(
            select(SamplePhoto).where(SamplePhoto.status == "ready").order_by(SamplePhoto.id)
        ):
            faces = db.scalars(
                select(FaceRecord).where(FaceRecord.sample_photo_id == sample.id)
            ).all()
            if len(faces) != 1:
                raise RuntimeError(f"样本 {sample.id} 人脸记录数量异常")
            face = faces[0]
            vector = store.get_reference_vector(
                collection,
                face.id,
                workspace_id=sample.workspace_id,
                person_id=sample.person_id,
                embedding_version=embedding_version,
            )
            samples.append(EvaluationSample(
                sample.id,
                sample.workspace_id,
                sample.person_id,
                sample.sha256,
                sample.source_gallery_photo_id,
                ReferenceFace(vector, face.face_size, face.detection_score, face.blur_score, face.pose_yaw),
            ))
    return samples


def _unknown_scores(collection: str, embedding_version: str) -> list[dict[str, object]]:
    settings = get_settings().model_copy(update={
        "face_recognition_threshold": -1.0,
        "face_recognition_min_margin": -1.0,
    })
    samples = _load_samples(collection, embedding_version)
    rows: list[dict[str, object]] = []
    for query in samples:
        references = [
            item for item in reference_split(query, samples) if item.person_id != query.person_id
        ]
        predicted, score, margin = predict(query, references, settings, "mean", 0.0)
        rows.append({"predicted": predicted, "score": score, "margin": margin})
    return rows


def _false_accepts(rows: list[dict[str, object]], threshold: float, margin: float) -> int:
    return sum(
        row["predicted"] is not None
        and row["score"] is not None
        and float(row["score"]) >= threshold
        and (row["margin"] is None or float(row["margin"]) >= margin)
        for row in rows
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="独立校准 AdaFace 迁移阈值并验证错认不增加门槛。")
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--baseline-collection", required=True)
    parser.add_argument("--baseline-version", required=True)
    parser.add_argument("--candidate-collection", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline_by_face = {int(row["face_record_id"]): row for row in _flip_rows(args.baseline_report)}
    candidate_by_face = {int(row["face_record_id"]): row for row in _flip_rows(args.candidate_report)}
    common_ids = sorted(set(baseline_by_face) & set(candidate_by_face))
    baseline_rows = [baseline_by_face[face_id] for face_id in common_ids]
    candidate_rows = [candidate_by_face[face_id] for face_id in common_ids]
    with SessionLocal() as db:
        faces = {
            face.id: face for face in db.scalars(
                select(FaceRecord).where(FaceRecord.id.in_(common_ids))
            ).all()
        }
    calibration_photos, holdout_photos = _split_photo_ids(baseline_rows, faces)
    baseline_calibration = [row for row in baseline_rows if int(row["gallery_photo_id"]) in calibration_photos]
    baseline_holdout = [row for row in baseline_rows if int(row["gallery_photo_id"]) in holdout_photos]
    candidate_calibration = [row for row in candidate_rows if int(row["gallery_photo_id"]) in calibration_photos]
    candidate_holdout = [row for row in candidate_rows if int(row["gallery_photo_id"]) in holdout_photos]
    baseline_calibration_metrics = _metrics(baseline_calibration, 0.41, 0.039)
    baseline_holdout_metrics = _metrics(baseline_holdout, 0.41, 0.039)
    baseline_unknown = _unknown_scores(args.baseline_collection, args.baseline_version)
    candidate_unknown = _unknown_scores(args.candidate_collection, args.candidate_version)
    baseline_false_accepts = _false_accepts(baseline_unknown, 0.41, 0.039)

    scan: list[dict[str, object]] = []
    for threshold_int in range(350, 501, 5):
        threshold = threshold_int / 1000
        for margin_int in range(0, 81, 5):
            margin = margin_int / 1000
            metrics = _metrics(candidate_calibration, threshold, margin)
            false_accepts = _false_accepts(candidate_unknown, threshold, margin)
            eligible = (
                int(metrics["wrong_identity"]) <= int(baseline_calibration_metrics["wrong_identity"])
                and false_accepts <= baseline_false_accepts
            )
            scan.append({
                "threshold": threshold,
                "margin": margin,
                **metrics,
                "unknown_false_accepts": false_accepts,
                "eligible": eligible,
            })
    eligible = [row for row in scan if row["eligible"]]
    primary_selected = max(
        eligible,
        key=lambda row: (
            int(row["correct"]),
            int(row["recovered_unknown"]),
            float(row["threshold"]),
            float(row["margin"]),
        ),
        default=None,
    )
    primary_holdout = (
        _metrics(
            candidate_holdout,
            float(primary_selected["threshold"]),
            float(primary_selected["margin"]),
        )
        if primary_selected is not None else None
    )
    validated: list[tuple[dict[str, object], dict[str, int | float]]] = []
    for row in eligible:
        holdout_metrics = _metrics(
            candidate_holdout, float(row["threshold"]), float(row["margin"])
        )
        if (
            int(holdout_metrics["wrong_identity"]) <= int(baseline_holdout_metrics["wrong_identity"])
            and int(holdout_metrics["correct"]) >= int(baseline_holdout_metrics["correct"])
            and int(holdout_metrics["recovered_unknown"]) >= int(baseline_holdout_metrics["recovered_unknown"])
        ):
            validated.append((row, holdout_metrics))
    selected_pair = max(
        validated,
        key=lambda item: (
            int(item[0]["correct"]),
            int(item[0]["recovered_unknown"]),
            float(item[0]["threshold"]),
            float(item[0]["margin"]),
        ),
        default=None,
    )
    selected = selected_pair[0] if selected_pair else None
    candidate_holdout_metrics = selected_pair[1] if selected_pair else None
    migration_ready = selected_pair is not None
    result = {
        "seed": SEED,
        "common_rows": len(common_ids),
        "calibration_photos": len(calibration_photos),
        "holdout_photos": len(holdout_photos),
        "calibration_rows": len(candidate_calibration),
        "holdout_rows": len(candidate_holdout),
        "baseline_operating_point": {"threshold": 0.41, "margin": 0.039},
        "baseline_calibration": baseline_calibration_metrics,
        "baseline_holdout": baseline_holdout_metrics,
        "baseline_unknown_false_accepts": baseline_false_accepts,
        "primary_selected": primary_selected,
        "primary_holdout": primary_holdout,
        "selected": selected,
        "candidate_holdout": candidate_holdout_metrics,
        "migration_ready": migration_ready,
        "scan": scan,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "calibration.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AdaFace 独立阈值校准",
        "",
        f"- 校准图片：{len(calibration_photos)}；锁定验证图片：{len(holdout_photos)}。",
        f"- 校准人脸：{len(candidate_calibration)}；锁定验证人脸：{len(candidate_holdout)}。",
        f"- 迁移门槛通过：{'是' if migration_ready else '否'}。",
        "",
        "| 模型/集合 | 正确 | 错认 | 拒绝 | 找回未知 |",
        "|---|---:|---:|---:|---:|",
        f"| buffalo_l 锁定验证 | {baseline_holdout_metrics['correct']} | {baseline_holdout_metrics['wrong_identity']} | {baseline_holdout_metrics['rejected']} | {baseline_holdout_metrics['recovered_unknown']} |",
    ]
    if selected is not None and candidate_holdout_metrics is not None:
        lines.append(
            f"| AdaFace 锁定验证（{selected['threshold']:.3f}/{selected['margin']:.3f}） | "
            f"{candidate_holdout_metrics['correct']} | {candidate_holdout_metrics['wrong_identity']} | "
            f"{candidate_holdout_metrics['rejected']} | {candidate_holdout_metrics['recovered_unknown']} |"
        )
    (args.output / "calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "scan"}, ensure_ascii=False, indent=2))
    if not migration_ready:
        raise SystemExit("AdaFace 未通过锁定验证门槛，停止生产迁移。")


if __name__ == "__main__":
    main()
