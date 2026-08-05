from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import csv
import json
from pathlib import Path
import platform
import shlex
import sys
from typing import Any

import numpy as np

from face_runtime import FaceDetection, FaceRuntime, load_image_path, resolve_provider_mode

from .cache import CacheStore, stable_cache_key
from .geometry import TARGET_SELECTION_POLICY, parse_bbox, select_target_detection, target_bbox_in_crop
from .store import connect_benchmark


@dataclass(frozen=True)
class Prediction:
    top1_person_id: int | None
    top1_score: float | None
    top2_person_id: int | None
    top2_score: float | None

    @property
    def margin(self) -> float | None:
        if self.top1_score is None or self.top2_score is None:
            return None
        return self.top1_score - self.top2_score


def predict(query: np.ndarray, prototypes: dict[int, list[np.ndarray]]) -> Prediction:
    scores = [
        (person_id, max(float(np.dot(query, vector)) for vector in vectors))
        for person_id, vectors in prototypes.items()
        if vectors
    ]
    scores.sort(key=lambda item: (-item[1], item[0]))
    if not scores:
        return Prediction(None, None, None, None)
    second = scores[1] if len(scores) > 1 else (None, None)
    return Prediction(scores[0][0], scores[0][1], second[0], second[1])


def acceptance_reason(prediction: Prediction, threshold: float, min_margin: float) -> str:
    if prediction.top1_person_id is None or prediction.top1_score is None:
        return "no_candidate"
    if prediction.top1_score < threshold:
        return "below_threshold"
    if prediction.margin is not None and prediction.margin < min_margin:
        return "below_margin"
    return "accepted"


def metrics(rows: list[dict[str, Any]], threshold: float, min_margin: float) -> dict[str, Any]:
    accepted = [row for row in rows if acceptance_reason(row["prediction"], threshold, min_margin) == "accepted"]
    wrong = [
        row
        for row in accepted
        if row["truth_is_unknown"] or row["prediction"].top1_person_id != row["truth_person_id"]
    ]
    known = [row for row in rows if not row["truth_is_unknown"]]
    known_rejected = [
        row for row in known if acceptance_reason(row["prediction"], threshold, min_margin) != "accepted"
    ]
    true_unknown = [row for row in rows if row["truth_is_unknown"]]
    false_accept = [
        row for row in true_unknown if acceptance_reason(row["prediction"], threshold, min_margin) == "accepted"
    ]
    failures = [row for row in rows if row.get("processing_error")]
    return {
        "labeled": len(rows),
        "accepted": len(accepted),
        "wrong_person": len(wrong),
        "known": len(known),
        "known_rejected": len(known_rejected),
        "known_reject_rate": round(len(known_rejected) / len(known), 6) if known else None,
        "true_unknown": len(true_unknown),
        "false_accept": len(false_accept),
        "false_accept_rate": round(len(false_accept) / len(true_unknown), 6) if true_unknown else None,
        "accepted_precision": round((len(accepted) - len(wrong)) / len(accepted), 6) if accepted else None,
        "processing_failures": len(failures),
    }


def _serialize_detection(detection: FaceDetection) -> dict[str, Any]:
    return {
        "bbox": list(detection.bbox),
        "keypoints": detection.keypoints.tolist(),
        "score": detection.score,
        "face_size": detection.face_size,
        "blur_score": detection.blur_score,
        "pose_yaw": detection.pose_yaw,
    }


def _deserialize_detection(payload: dict[str, Any]) -> FaceDetection:
    return FaceDetection(
        bbox=tuple(float(value) for value in payload["bbox"]),
        keypoints=np.asarray(payload["keypoints"], dtype=np.float32),
        score=float(payload["score"]) if payload.get("score") is not None else None,
        face_size=float(payload["face_size"]),
        blur_score=float(payload["blur_score"]) if payload.get("blur_score") is not None else None,
        pose_yaw=float(payload["pose_yaw"]) if payload.get("pose_yaw") is not None else None,
    )


class CachedRuntime:
    def __init__(
        self,
        runtime: FaceRuntime,
        cache: CacheStore,
        *,
        snapshot_sha256: str,
        file_checksums: dict[str, str],
    ) -> None:
        self.runtime = runtime
        self.cache = cache
        self.snapshot_sha256 = snapshot_sha256
        self.file_checksums = file_checksums
        self.detector = runtime.detector_metadata()
        self.adapter = runtime.adapter.report_metadata()
        self.cache_hits = {"detection": 0, "embedding": 0}
        self.cache_misses = {"detection": 0, "embedding": 0}

    def process(self, snapshot_dir: Path, relative_path: str) -> dict[str, Any]:
        image_checksum = self.file_checksums.get(relative_path)
        if image_checksum is None:
            raise RuntimeError(f"图片不在快照校验清单中：{relative_path}")
        detection_key = stable_cache_key({
            "kind": "detection-v1",
            "snapshot_sha256": self.snapshot_sha256,
            "image_path": relative_path,
            "image_sha256": image_checksum,
            "detector_pack": self.detector["detector_pack"],
            "detector_model_sha256": self.detector["model_sha256"],
            "detection_size": self.detector["detection_size"],
            "providers": self.detector["providers"],
        })
        detection_cache = self.cache.load("detections", detection_key)
        image: np.ndarray | None = None
        if detection_cache is None:
            self.cache_misses["detection"] += 1
            image = load_image_path(snapshot_dir / relative_path)
            detections, detection_ms = self.runtime.detect_bgr(image)
            self.cache.save("detections", detection_key, {
                "detections": [_serialize_detection(item) for item in detections],
                "detection_ms": detection_ms,
            })
            detection_hit = False
        else:
            self.cache_hits["detection"] += 1
            detections = [_deserialize_detection(item) for item in detection_cache["detections"]]
            detection_ms = float(detection_cache["detection_ms"])
            detection_hit = True

        embedding_key = stable_cache_key({
            "kind": "embedding-v1",
            "detection_key": detection_key,
            "adapter_id": self.adapter["adapter_id"],
            "adapter_version": self.adapter["version"],
            "model_sha256": self.adapter["model_sha256"],
            "alignment": self.adapter["alignment"],
            "flip_tta": self.runtime.flip_tta,
            "providers": self.adapter["providers"],
        })
        embedding_cache = self.cache.load("embeddings", embedding_key)
        if embedding_cache is None:
            self.cache_misses["embedding"] += 1
            if image is None:
                image = load_image_path(snapshot_dir / relative_path)
            vectors: list[np.ndarray] = []
            embedding_ms = 0.0
            for detection in detections:
                vector, elapsed = self.runtime.embed_detection(image, detection)
                vectors.append(vector)
                embedding_ms += elapsed
            self.cache.save("embeddings", embedding_key, {
                "vectors": [vector.tolist() for vector in vectors],
                "embedding_ms": embedding_ms,
            })
            embedding_hit = False
        else:
            self.cache_hits["embedding"] += 1
            vectors = [np.asarray(vector, dtype=np.float32) for vector in embedding_cache["vectors"]]
            embedding_ms = float(embedding_cache["embedding_ms"])
            embedding_hit = True
        if len(vectors) != len(detections):
            raise RuntimeError(f"缓存中的检测数和嵌入数不一致：{relative_path}")
        return {
            "detections": detections,
            "vectors": vectors,
            "detection_ms": detection_ms,
            "embedding_ms": embedding_ms,
            "detection_cache_hit": detection_hit,
            "embedding_cache_hit": embedding_hit,
        }


def _verify_snapshot(snapshot_dir: Path) -> tuple[dict[str, Any], dict[str, str], str]:
    meta_path = snapshot_dir / "snapshot.json"
    selection_path = snapshot_dir / "selection.jsonl"
    checksums_path = snapshot_dir / "file-checksums.json"
    if not meta_path.is_file() or not selection_path.is_file() or not checksums_path.is_file():
        raise RuntimeError("快照缺少完整性文件，请重新创建。")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if sha256(selection_path.read_bytes()).hexdigest() != meta.get("selection_sha256"):
        raise RuntimeError("selection.jsonl 校验失败，快照抽样清单已被修改。")
    checksum_payload = checksums_path.read_text(encoding="utf-8")
    if sha256(checksum_payload.encode()).hexdigest() != meta.get("file_checksums_sha256"):
        raise RuntimeError("file-checksums.json 校验失败。")
    checksums = json.loads(checksum_payload)
    for relative, expected in checksums.items():
        path = snapshot_dir / relative
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"快照文件校验失败：{relative}")
    return meta, checksums, sha256(meta_path.read_bytes()).hexdigest()


def _safe_process(cached: CachedRuntime, snapshot_dir: Path, path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return cached.process(snapshot_dir, path), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def evaluate_snapshot(
    snapshot_dir: Path,
    *,
    adapter_id: str,
    model_path: Path | None,
    detector_pack: str,
    provider: str,
    detection_size: int,
    flip_tta: bool,
    threshold: float,
    min_margin: float,
    final_holdout: bool,
    use_cache: bool = True,
) -> Path:
    snapshot_dir = snapshot_dir.resolve()
    snapshot_meta, file_checksums, snapshot_sha256 = _verify_snapshot(snapshot_dir)
    split = "holdout" if final_holdout else "calibration"
    with connect_benchmark(snapshot_dir / "benchmark.db") as db:
        samples = [dict(row) for row in db.execute("SELECT * FROM samples ORDER BY source_sample_id")]
        items = [dict(row) for row in db.execute(
            "SELECT * FROM items WHERE status = 'labeled' AND split = ? ORDER BY id", (split,)
        )]
        people = {
            int(row["source_person_id"]): str(row["display_name"])
            for row in db.execute("SELECT source_person_id, display_name FROM persons")
        }
    if not items:
        raise RuntimeError(f"{split} 没有已标注项目。")

    providers = resolve_provider_mode(provider)
    runtime = FaceRuntime(
        detector_pack=detector_pack,
        adapter_id=adapter_id,
        model_path=model_path,
        providers=providers,
        detection_size=detection_size,
        flip_tta=flip_tta,
    )
    runtime.warmup()
    cached = CachedRuntime(
        runtime,
        CacheStore(snapshot_dir / "cache", enabled=use_cache),
        snapshot_sha256=snapshot_sha256,
        file_checksums=file_checksums,
    )

    prototypes: dict[int, list[np.ndarray]] = defaultdict(list)
    sample_skips: list[dict[str, Any]] = []
    for sample in samples:
        result, error = _safe_process(cached, snapshot_dir, str(sample["image_path"]))
        if error or result is None or not result["vectors"]:
            sample_skips.append({"source_sample_id": int(sample["source_sample_id"]), "error": error or "no_face"})
            continue
        prototypes[int(sample["source_person_id"])].append(result["vectors"][0])
    for person_vectors in prototypes.values():
        centroid = np.mean(np.stack(person_vectors), axis=0)
        centroid /= max(float(np.linalg.norm(centroid)), 1e-12)
        person_vectors.append(np.asarray(centroid, dtype=np.float32))

    face_rows: list[dict[str, Any]] = []
    detection_rows: list[dict[str, Any]] = []
    for item in items:
        result, error = _safe_process(cached, snapshot_dir, str(item["image_path"]))
        vectors = result["vectors"] if result is not None else []
        detections = result["detections"] if result is not None else []
        timing = {
            "detection_ms": result["detection_ms"] if result else None,
            "embedding_ms": result["embedding_ms"] if result else None,
            "processing_ms": result["detection_ms"] + result["embedding_ms"] if result else None,
            "detection_cache_hit": result["detection_cache_hit"] if result else False,
            "embedding_cache_hit": result["embedding_cache_hit"] if result else False,
        }
        if item["kind"] == "detection":
            truth = int(item["true_face_count"])
            detected = len(detections)
            detection_rows.append({
                "item_id": int(item["id"]),
                "true_faces": truth,
                "detected_faces": detected,
                "matched_faces": min(truth, detected),
                "exact_count": truth == detected,
                "processing_error": error,
                **timing,
            })
            continue
        target_bbox = target_bbox_in_crop(parse_bbox(item["bbox_json"]))
        selection = select_target_detection(detections, target_bbox)
        selected_detection = (
            detections[selection.index]
            if selection.index is not None and selection.index < len(detections)
            else None
        )
        selected_vector = (
            vectors[selection.index]
            if selection.index is not None and selection.index < len(vectors)
            else None
        )
        prediction = (
            predict(selected_vector, prototypes)
            if selected_vector is not None
            else Prediction(None, None, None, None)
        )
        face_rows.append({
            "item_id": int(item["id"]),
            "sample_bucket": str(item["sample_bucket"]),
            "truth_person_id": int(item["truth_person_id"]) if item["truth_person_id"] is not None else None,
            "truth_person_name": people.get(int(item["truth_person_id"])) if item["truth_person_id"] is not None else None,
            "truth_is_unknown": bool(item["truth_is_unknown"]),
            "prediction": prediction,
            "detected_face_count": len(detections),
            "target_bbox_crop": list(target_bbox),
            "target_detection_bbox": list(selected_detection.bbox) if selected_detection is not None else None,
            "target_detection_iou": round(selection.iou, 6) if selection.iou is not None else None,
            "target_selection_method": selection.method,
            "processing_error": error,
            **timing,
        })

    report_metrics = metrics(face_rows, threshold, min_margin)
    by_bucket = {
        bucket: metrics([row for row in face_rows if row["sample_bucket"] == bucket], threshold, min_margin)
        for bucket in sorted({row["sample_bucket"] for row in face_rows})
    }
    threshold_grid = [
        {"threshold": candidate_threshold, "min_margin": candidate_margin, **metrics(face_rows, candidate_threshold, candidate_margin)}
        for candidate_threshold in [round(value / 100, 2) for value in range(20, 81)]
        for candidate_margin in [round(value / 100, 2) for value in range(0, 21)]
    ]
    truth_faces = sum(row["true_faces"] for row in detection_rows)
    detection_metrics = {
        "images": len(detection_rows),
        "true_faces": truth_faces,
        "detected_faces": sum(row["detected_faces"] for row in detection_rows),
        "count_recall_proxy": (
            round(sum(row["matched_faces"] for row in detection_rows) / truth_faces, 6) if truth_faces else None
        ),
        "exact_count_images": sum(row["exact_count"] for row in detection_rows),
        "processing_failures": sum(bool(row["processing_error"]) for row in detection_rows),
    }
    adapter_meta = cached.adapter
    model_key = f"{adapter_id}-{str(adapter_meta['model_sha256'])[:12]}"
    result_dir = snapshot_dir / "results" / f"{model_key}-{split}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    result_dir.mkdir(parents=True)

    serializable_rows: list[dict[str, Any]] = []
    for row in face_rows:
        prediction = row["prediction"]
        reason = acceptance_reason(prediction, threshold, min_margin)
        serializable_rows.append({
            **{key: value for key, value in row.items() if key != "prediction"},
            "top1_person_id": prediction.top1_person_id,
            "top1_person_name": people.get(prediction.top1_person_id) if prediction.top1_person_id is not None else None,
            "top1_score": prediction.top1_score,
            "top2_person_id": prediction.top2_person_id,
            "top2_person_name": people.get(prediction.top2_person_id) if prediction.top2_person_id is not None else None,
            "top2_score": prediction.top2_score,
            "margin": prediction.margin,
            "accepted": reason == "accepted",
            "decision_reason": reason,
        })
    with (result_dir / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in serializable_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (result_dir / "detections.jsonl").open("w", encoding="utf-8") as handle:
        for row in detection_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (result_dir / "thresholds.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(threshold_grid[0]))
        writer.writeheader()
        writer.writerows(threshold_grid)

    timings = [row["processing_ms"] for row in face_rows if row["processing_ms"] is not None]
    report = {
        "report_version": 3,
        "snapshot": {
            "snapshot_id": snapshot_meta.get("snapshot_id"),
            "snapshot_sha256": snapshot_sha256,
            "selection_sha256": snapshot_meta.get("selection_sha256"),
            "file_checksums_sha256": snapshot_meta.get("file_checksums_sha256"),
        },
        "command": " ".join(shlex.quote(argument) for argument in sys.argv),
        "created_at": datetime.now().astimezone().isoformat(),
        "system": platform.platform(),
        "split": split,
        "adapter": adapter_meta,
        "detector": cached.detector,
        "target_selection_policy": TARGET_SELECTION_POLICY,
        "flip_tta": flip_tta,
        "threshold": threshold,
        "min_margin": min_margin,
        "sample_photos": len(samples),
        "sample_skips": sample_skips,
        "covered_people": len(prototypes),
        "latency_ms_average": round(float(np.mean(timings)), 3) if timings else None,
        "cache": {
            "enabled": use_cache,
            "hits": cached.cache_hits,
            "misses": cached.cache_misses,
        },
        "face_metrics": report_metrics,
        "face_metrics_by_bucket": by_bucket,
        "detection_metrics": detection_metrics,
    }
    (result_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 人脸识别评测报告",
        "",
        f"- 模型适配器：`{adapter_id}`",
        f"- 模型 SHA-256：`{adapter_meta['model_sha256']}`",
        f"- 数据分区：`{split}`",
        f"- 目标脸选择策略：`{TARGET_SELECTION_POLICY}`",
        f"- Provider：`{', '.join(adapter_meta['providers'])}`",
        f"- 人脸标注数：{report_metrics['labeled']}",
        f"- 错误自动绑定：{report_metrics['wrong_person']}",
        f"- 已知人物拒识率：{report_metrics['known_reject_rate']}",
        f"- 未知人物误接纳率：{report_metrics['false_accept_rate']}",
        f"- 解析/推理失败：{report_metrics['processing_failures']}",
        f"- 平均单图推理耗时：{report['latency_ms_average']} ms",
        f"- 检测计数召回代理值：{detection_metrics['count_recall_proxy']}",
        "",
        "`holdout` 结果只用于最终候选确认，不用于阈值调参。",
        "",
    ]
    (result_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result_dir
