from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np

from app.services.qdrant import FaceSearchHit


@dataclass(frozen=True)
class ReferenceFace:
    vector: np.ndarray
    face_size: float | None = None
    detection_score: float | None = None
    blur_score: float | None = None
    pose_yaw: float | None = None


def unit_vector(vector: np.ndarray) -> np.ndarray:
    result = np.asarray(vector, dtype=np.float32)
    if result.ndim != 1 or not np.isfinite(result).all():
        raise ValueError("人脸向量必须是一维有限数值数组")
    norm = float(np.linalg.norm(result))
    if norm < 1e-8:
        raise ValueError("人脸向量不能为零向量")
    return result / norm


def quality_weight(face: ReferenceFace) -> float:
    def ratio(value: float | None, target: float) -> float:
        if value is None or not math.isfinite(value):
            return 1.0
        return float(np.clip(value / target, 0.25, 1.0))

    # 姿态仅小幅降权，保留侧脸对人物外观覆盖的贡献。
    pose = 1.0
    if face.pose_yaw is not None and math.isfinite(face.pose_yaw):
        pose = 1.0 - 0.15 * min(abs(face.pose_yaw) / 90.0, 1.0)
    return max(0.25, (ratio(face.face_size, 80) * ratio(face.detection_score, 0.9)
                     * ratio(face.blur_score, 45)) ** (1 / 3) * pose)


def build_centroid(
    faces: list[ReferenceFace], *, mode: str = "robust", quality_strength: float = 1.0,
    outlier_fraction: float = 0.2,
) -> np.ndarray | None:
    if not faces:
        return None
    vectors = np.stack([unit_vector(face.vector) for face in faces])
    weights = np.ones(len(faces), dtype=np.float64)
    if mode not in {"mean", "robust"}:
        raise ValueError("未知的人物中心算法")
    if mode == "robust" and len(faces) >= 3:
        weights = np.array([quality_weight(face) for face in faces]) ** quality_strength
        if len(faces) >= 5 and outlier_fraction > 0:
            distances = 1 - vectors @ vectors.T
            centrality = np.median(distances, axis=1)
            median = float(np.median(centrality))
            mad = float(np.median(np.abs(centrality - median)))
            limit = median + max(3 * mad, 0.15)
            candidates = np.flatnonzero(centrality > limit)
            count = min(len(candidates), int(len(faces) * outlier_fraction))
            if count:
                selected = candidates[np.argsort(centrality[candidates])[-count:]]
                weights[selected] *= 0.25
    combined = np.average(vectors, axis=0, weights=weights)
    if float(np.linalg.norm(combined)) < 1e-8:
        # 相互抵消时选实际样本，不能将零向量写入索引。
        return vectors[int(np.argmax(weights))]
    return unit_vector(combined)


def aggregate_hits(
    hits: list[FaceSearchHit], *, top_k: int, max_bonus: float, support_floor: float,
) -> list[FaceSearchHit]:
    people: dict[int, list[FaceSearchHit]] = {}
    for hit in hits:
        if math.isfinite(hit.score):
            people.setdefault(hit.person_id, []).append(hit)
    ranked: list[FaceSearchHit] = []
    for items in people.values():
        best = min(items, key=hit_sort_key)
        samples: dict[int | str, float] = {}
        centroids = []
        for hit in items:
            if hit.source_type == "sample":
                key = hit.sample_photo_id if hit.sample_photo_id is not None else hit.point_id
                samples[key] = max(samples.get(key, -1.0), hit.score)
            elif hit.source_type == "centroid":
                centroids.append(hit.score)
        scores = sorted(samples.values(), reverse=True)[:top_k]
        bonus = 0.0
        if len(scores) >= 2 and centroids and scores[1] >= support_floor:
            support = min(max(centroids), float(np.mean(scores)))
            bonus = max_bonus * float(np.clip((support - support_floor) / 0.05, 0, 1))
        ranked.append(replace(best, score=min(1.0, best.score + bonus)))
    return sorted(ranked, key=hit_sort_key)


def hit_sort_key(hit: FaceSearchHit) -> tuple[float, int, int, str]:
    return (-hit.score, 0 if hit.source_type == "sample" else 1,
            hit.sample_photo_id or 0, str(hit.point_id))
