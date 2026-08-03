from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import csv
import json
from pathlib import Path
import time
from typing import Any

import numpy as np

from .store import connect_benchmark


@dataclass(frozen=True)
class Prediction:
    person_id: int | None
    score: float | None
    second_score: float | None

    @property
    def margin(self) -> float | None:
        if self.score is None or self.second_score is None:
            return None
        return self.score - self.second_score


class InsightFaceAdapter:
    def __init__(
        self,
        *,
        model_name: str,
        recognition_onnx: Path | None,
        provider_mode: str,
        detection_size: int,
        flip_tta: bool,
    ) -> None:
        try:
            import onnxruntime as ort
            from insightface.app import FaceAnalysis
            from insightface import model_zoo
            from insightface.utils import face_align
        except Exception as exc:
            raise RuntimeError("运行候选模型需要安装 InsightFace 和 ONNX Runtime。") from exc
        available = set(ort.get_available_providers())
        if provider_mode == "cuda":
            if "CUDAExecutionProvider" not in available:
                raise RuntimeError(f"CUDAExecutionProvider 不可用，实际 Provider：{sorted(available)}")
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif provider_mode == "cpu":
            providers = ["CPUExecutionProvider"]
        else:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if "CUDAExecutionProvider" in available else ["CPUExecutionProvider"]
        self.providers = providers
        self.face_align = face_align
        self.app = FaceAnalysis(name=model_name, providers=providers, allowed_modules=["detection", "recognition"])
        self.app.prepare(ctx_id=0, det_size=(detection_size, detection_size))
        self.recognizer = self.app.models.get("recognition")
        if recognition_onnx is not None:
            if not recognition_onnx.is_file():
                raise RuntimeError(f"候选识别模型不存在：{recognition_onnx}")
            self.recognizer = model_zoo.get_model(str(recognition_onnx), providers=providers)
            if self.recognizer is None or not hasattr(self.recognizer, "get_feat"):
                raise RuntimeError("ONNX 文件不是 InsightFace 兼容的人脸识别模型。")
        if self.recognizer is None:
            raise RuntimeError(f"模型包不包含识别模型：{model_name}")
        self.flip_tta = flip_tta

    def detect_embeddings(self, path: Path) -> tuple[list[np.ndarray], float]:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError(f"无法读取图片：{path}")
        started_at = time.perf_counter()
        faces = self.app.get(image)
        faces = sorted(
            faces,
            key=lambda face: float((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])),
            reverse=True,
        )
        embeddings: list[np.ndarray] = []
        for face in faces:
            if self.flip_tta:
                aligned = self.face_align.norm_crop(image, landmark=np.asarray(face.kps, dtype=np.float32))
                features = np.asarray(
                    self.recognizer.get_feat([aligned, np.ascontiguousarray(aligned[:, ::-1])]),
                    dtype=np.float32,
                )
                vector = features.sum(axis=0)
            elif self.recognizer is self.app.models.get("recognition"):
                vector = np.asarray(face.embedding, dtype=np.float32)
            else:
                aligned = self.face_align.norm_crop(image, landmark=np.asarray(face.kps, dtype=np.float32))
                vector = np.asarray(self.recognizer.get_feat(aligned), dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                embeddings.append(vector / norm)
        return embeddings, (time.perf_counter() - started_at) * 1000


def _best_face(vectors: list[np.ndarray]) -> np.ndarray | None:
    return vectors[0] if vectors else None


def _predict(query: np.ndarray, prototypes: dict[int, list[np.ndarray]]) -> Prediction:
    scores: list[tuple[int, float]] = []
    for person_id, vectors in prototypes.items():
        person_scores = [float(np.dot(query, vector)) for vector in vectors]
        scores.append((person_id, max(person_scores)))
    scores.sort(key=lambda item: item[1], reverse=True)
    if not scores:
        return Prediction(None, None, None)
    return Prediction(scores[0][0], scores[0][1], scores[1][1] if len(scores) > 1 else None)


def _accepted(prediction: Prediction, threshold: float, min_margin: float) -> bool:
    return bool(
        prediction.person_id is not None
        and prediction.score is not None
        and prediction.score >= threshold
        and (prediction.margin is None or prediction.margin >= min_margin)
    )


def _metrics(rows: list[dict[str, Any]], threshold: float, min_margin: float) -> dict[str, Any]:
    labeled = [row for row in rows if row["status"] == "labeled"]
    accepted = [row for row in labeled if _accepted(row["prediction"], threshold, min_margin)]
    wrong = [row for row in accepted if row["truth_is_unknown"] or row["prediction"].person_id != row["truth_person_id"]]
    known = [row for row in labeled if not row["truth_is_unknown"]]
    known_unknown = [row for row in known if not _accepted(row["prediction"], threshold, min_margin)]
    true_unknown = [row for row in labeled if row["truth_is_unknown"]]
    false_accept = [row for row in true_unknown if _accepted(row["prediction"], threshold, min_margin)]
    return {
        "labeled": len(labeled),
        "accepted": len(accepted),
        "wrong_person": len(wrong),
        "known": len(known),
        "known_rejected": len(known_unknown),
        "known_reject_rate": round(len(known_unknown) / len(known), 6) if known else None,
        "true_unknown": len(true_unknown),
        "false_accept": len(false_accept),
        "false_accept_rate": round(len(false_accept) / len(true_unknown), 6) if true_unknown else None,
        "accepted_precision": round((len(accepted) - len(wrong)) / len(accepted), 6) if accepted else None,
    }


def evaluate_snapshot(
    snapshot_dir: Path,
    *,
    model_name: str,
    recognition_onnx: Path | None,
    provider: str,
    detection_size: int,
    flip_tta: bool,
    threshold: float,
    min_margin: float,
    final_holdout: bool,
) -> Path:
    snapshot_dir = snapshot_dir.resolve()
    _verify_snapshot(snapshot_dir)
    split = "holdout" if final_holdout else "calibration"
    with connect_benchmark(snapshot_dir / "benchmark.db") as db:
        samples = [dict(row) for row in db.execute("SELECT * FROM samples ORDER BY source_sample_id")]
        items = [dict(row) for row in db.execute("SELECT * FROM items WHERE status = 'labeled' AND split = ? ORDER BY id", (split,))]
    if not items:
        raise RuntimeError(f"{split} 没有已标注项目。")
    adapter = InsightFaceAdapter(
        model_name=model_name,
        recognition_onnx=recognition_onnx,
        provider_mode=provider,
        detection_size=detection_size,
        flip_tta=flip_tta,
    )
    prototypes: dict[int, list[np.ndarray]] = defaultdict(list)
    latencies: list[float] = []
    sample_skips: list[int] = []
    for sample in samples:
        vectors, elapsed = adapter.detect_embeddings(snapshot_dir / sample["image_path"])
        latencies.append(elapsed)
        vector = _best_face(vectors)
        if vector is None:
            sample_skips.append(int(sample["source_sample_id"]))
            continue
        prototypes[int(sample["source_person_id"])].append(vector)
    for person_vectors in prototypes.values():
        centroid = np.mean(np.stack(person_vectors), axis=0)
        centroid /= max(float(np.linalg.norm(centroid)), 1e-12)
        person_vectors.append(centroid)

    face_results: list[dict[str, Any]] = []
    detection_results: list[dict[str, Any]] = []
    for item in items:
        vectors, elapsed = adapter.detect_embeddings(snapshot_dir / item["image_path"])
        latencies.append(elapsed)
        if item["kind"] == "detection":
            truth = int(item["true_face_count"])
            detected = len(vectors)
            detection_results.append({
                "item_id": item["id"], "true_faces": truth, "detected_faces": detected,
                "matched_faces": min(truth, detected), "exact_count": truth == detected,
            })
            continue
        query = _best_face(vectors)
        prediction = _predict(query, prototypes) if query is not None else Prediction(None, None, None)
        face_results.append({
            "item_id": item["id"], "sample_bucket": item["sample_bucket"], "status": item["status"],
            "truth_person_id": item["truth_person_id"], "truth_is_unknown": bool(item["truth_is_unknown"]),
            "prediction": prediction,
        })

    report_metrics = _metrics(face_results, threshold, min_margin)
    by_bucket = {
        bucket: _metrics([row for row in face_results if row["sample_bucket"] == bucket], threshold, min_margin)
        for bucket in sorted({str(row["sample_bucket"]) for row in face_results})
    }
    threshold_grid = []
    for candidate_threshold in [round(value / 100, 2) for value in range(30, 71, 2)]:
        for candidate_margin in (0.0, 0.04, 0.06, 0.08, 0.10, 0.12):
            threshold_grid.append({
                "threshold": candidate_threshold,
                "min_margin": candidate_margin,
                **_metrics(face_results, candidate_threshold, candidate_margin),
            })
    truth_faces = sum(row["true_faces"] for row in detection_results)
    detection = {
        "images": len(detection_results),
        "true_faces": truth_faces,
        "detected_faces": sum(row["detected_faces"] for row in detection_results),
        "count_recall_proxy": round(sum(row["matched_faces"] for row in detection_results) / truth_faces, 6) if truth_faces else None,
        "exact_count_images": sum(row["exact_count"] for row in detection_results),
    }
    model_key = recognition_onnx.stem if recognition_onnx else model_name
    result_dir = snapshot_dir / "results" / f"{model_key}-{split}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    result_dir.mkdir(parents=True)
    report = {
        "model": model_key,
        "detector_pack": model_name,
        "recognition_onnx": str(recognition_onnx) if recognition_onnx else None,
        "providers": adapter.providers,
        "split": split,
        "flip_tta": flip_tta,
        "threshold": threshold,
        "min_margin": min_margin,
        "sample_photos": len(samples),
        "sample_skips": sample_skips,
        "covered_people": len(prototypes),
        "latency_ms_average": round(float(np.mean(latencies)), 3) if latencies else None,
        "face_metrics": report_metrics,
        "face_metrics_by_bucket": by_bucket,
        "detection_metrics": detection,
    }
    (result_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (result_dir / "thresholds.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(threshold_grid[0]) if threshold_grid else ["threshold", "min_margin"])
        writer.writeheader()
        writer.writerows(threshold_grid)
    lines = [
        "# 人脸识别评测报告", "", f"- 模型：`{model_key}`", f"- 数据分区：`{split}`",
        f"- Provider：`{', '.join(adapter.providers)}`", f"- 人脸标注数：{report_metrics['labeled']}",
        f"- 错误自动绑定：{report_metrics['wrong_person']}", f"- 已知人物拒识率：{report_metrics['known_reject_rate']}",
        f"- 未知人物误接纳率：{report_metrics['false_accept_rate']}", f"- 平均单图耗时：{report['latency_ms_average']} ms",
        f"- 检测计数召回代理值：{detection['count_recall_proxy']}", "",
        "`holdout` 结果只应用于最终候选确认，不应用于阈值调参。", "",
    ]
    (result_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result_dir


def _verify_snapshot(snapshot_dir: Path) -> None:
    from hashlib import sha256

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
    for relative, expected in json.loads(checksum_payload).items():
        path = snapshot_dir / relative
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"快照文件校验失败：{relative}")
