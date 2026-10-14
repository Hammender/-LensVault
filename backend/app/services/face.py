from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore, local
import time

import numpy as np

from app.core.config import Settings, get_settings
from app.native_runtime import create_onnx_inference_session, insightface_session_options
from face_runtime import DetectedFace, FaceRuntime, decode_image_bytes
from face_runtime.providers import validate_configured_providers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FaceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._runtime: FaceRuntime | None = None
        # 同一份 ONNX Session 同时只跑一路，避免两路推理把内存池叠高。
        # 解码和向量检索仍可由 gallery_recognition_workers 并行。
        self._detect_slots = BoundedSemaphore(1)
        self._detect_depth = local()

    @contextmanager
    def _hold_detect_slot(self):
        depth = getattr(self._detect_depth, "value", 0)
        if depth == 0:
            self._detect_slots.acquire()
        self._detect_depth.value = depth + 1
        try:
            yield
        finally:
            self._detect_depth.value = depth
            if depth == 0:
                self._detect_slots.release()

    def _get_runtime(self) -> FaceRuntime:
        if self._runtime is None:
            configured = self.settings.face_execution_providers.split(",")
            providers = validate_configured_providers(
                configured,
                require_primary=self.settings.face_require_primary_provider,
            )
            logger.info(
                "Initializing face runtime: detector=%s adapter=%s det_size=%s providers=%s",
                self.settings.face_model_name,
                self.settings.face_adapter_id,
                self.settings.face_detection_size,
                providers,
            )
            started_at = time.perf_counter()
            self._runtime = FaceRuntime(
                detector_pack=self.settings.face_model_name,
                adapter_id=self.settings.face_adapter_id,
                model_path=(
                    Path(self.settings.face_recognition_model_path)
                    if self.settings.face_recognition_model_path.strip()
                    else None
                ),
                providers=providers,
                detection_size=self.settings.face_detection_size,
                flip_tta=self.settings.face_flip_augmentation,
                roll_correction_enabled=self.settings.face_roll_correction_enabled,
                roll_correction_min_angle=self.settings.face_roll_correction_min_angle,
                create_session=create_onnx_inference_session,
                detector_session_guard=insightface_session_options,
            )
            self._runtime.warmup()
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info("Face runtime initialized in %.1fms", elapsed_ms)
        return self._runtime

    def warmup(self) -> None:
        self._get_runtime()
        logger.info("FaceService warmup completed")

    def detect_faces(self, payload: bytes) -> list[DetectedFace]:
        logger.debug("Start detect_faces payload_bytes=%d", len(payload))
        array = decode_image_bytes(payload)
        logger.debug("Decoded image size=%sx%s", array.shape[1], array.shape[0])
        return self.detect_faces_bgr(array)

    def detect_faces_bgr(self, array: np.ndarray) -> list[DetectedFace]:
        started_at = time.perf_counter()
        with self._hold_detect_slot():
            runtime = self._get_runtime()
            results = runtime.analyze_bgr(array)
            if not results and self.settings.face_rotation_fallback_enabled:
                results = self._rotate_detections(runtime, array)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.debug("Face detection finished detected_faces=%d elapsed_ms=%.1f", len(results), elapsed_ms)
        return results

    def detect_rotations(self, payload: bytes) -> list[DetectedFace]:
        return self.detect_rotations_bgr(decode_image_bytes(payload))

    def detect_rotations_bgr(self, array: np.ndarray) -> list[DetectedFace]:
        """只跑旋转备选，不再重复正放检测。"""
        if not self.settings.face_rotation_fallback_enabled:
            return []
        with self._hold_detect_slot():
            runtime = self._get_runtime()
            return self._rotate_detections(runtime, array)

    def detect_faces_with_rotation_fallback(self, payload: bytes) -> list[DetectedFace]:
        logger.debug("Start detect_faces_with_rotation_fallback payload_bytes=%d", len(payload))
        return self.detect_faces_with_rotation_fallback_bgr(decode_image_bytes(payload))

    def detect_faces_with_rotation_fallback_bgr(
        self,
        array: np.ndarray,
        primary_faces: list[DetectedFace] | None = None,
    ) -> list[DetectedFace]:
        with self._hold_detect_slot():
            runtime = self._get_runtime()
            if primary_faces is None:
                primary_faces = runtime.analyze_bgr(array)
            if not self.settings.face_rotation_fallback_enabled:
                return primary_faces
            rotated_faces = self._rotate_detections(runtime, array)
            results = runtime.prefer_rotated_faces(primary_faces, rotated_faces)
        logger.debug(
            "Rotation fallback finished primary_faces=%d rotated_faces=%d merged_faces=%d",
            len(primary_faces),
            len(rotated_faces),
            len(results),
        )
        return results

    def _rotate_detections(self, runtime: FaceRuntime, array: np.ndarray) -> list[DetectedFace]:
        analyze_rotations = getattr(runtime, "analyze_rotations_bgr", None)
        if not callable(analyze_rotations):
            return []
        return analyze_rotations(array, self._rotation_fallback_angles())

    def _rotation_fallback_angles(self) -> tuple[float, ...]:
        angles: list[float] = []
        for raw_angle in self.settings.face_rotation_fallback_angles.split(","):
            value = raw_angle.strip()
            if not value:
                continue
            try:
                angle = FaceRuntime.normalize_angle(float(value))
            except ValueError as exc:
                raise RuntimeError(f"无效的人脸旋转备选角度：{value}") from exc
            if not math.isfinite(angle):
                raise RuntimeError(f"无效的人脸旋转备选角度：{value}")
            if abs(angle) >= 1e-6 and angle not in angles:
                angles.append(angle)
        if not angles:
            raise RuntimeError("人脸旋转备选角度不能为空。")
        return tuple(angles)

    @staticmethod
    def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
        return float(np.dot(left, right))

    def match_embedding(self, embedding: np.ndarray, candidates: list[tuple[int, np.ndarray]]) -> tuple[int | None, float | None]:
        logger.debug("Start match_embedding candidates=%d", len(candidates))
        best_person_id: int | None = None
        best_score: float | None = None
        for person_id, candidate in candidates:
            score = self.cosine_similarity(embedding, candidate)
            if best_score is None or score > best_score:
                best_person_id = person_id
                best_score = score
        if best_score is None or best_score < self.settings.face_recognition_threshold:
            logger.debug(
                "match_embedding no match threshold=%.4f best_score=%s",
                self.settings.face_recognition_threshold,
                f"{best_score:.4f}" if best_score is not None else "None",
            )
            return None, best_score
        logger.debug(
            "match_embedding matched person_id=%s score=%.4f threshold=%.4f",
            best_person_id,
            best_score,
            self.settings.face_recognition_threshold,
        )
        return best_person_id, best_score

    def cluster_unknown_embeddings(self, embeddings: list[tuple[int, np.ndarray]]) -> dict[int, str]:
        logger.debug("Start cluster_unknown_embeddings faces=%d", len(embeddings))
        assignments: dict[int, str] = {}
        clusters: list[tuple[str, np.ndarray, int]] = []
        for face_id, embedding in embeddings:
            assigned = False
            for index, (cluster_key, centroid, count) in enumerate(clusters):
                score = self.cosine_similarity(embedding, centroid)
                if score >= self.settings.face_cluster_threshold:
                    new_count = count + 1
                    new_centroid = (centroid * count + embedding) / new_count
                    norm = np.linalg.norm(new_centroid)
                    if norm > 0:
                        new_centroid = new_centroid / norm
                    clusters[index] = (cluster_key, new_centroid, new_count)
                    assignments[face_id] = cluster_key
                    assigned = True
                    break
            if not assigned:
                cluster_key = f"cluster-{len(clusters) + 1:04d}"
                clusters.append((cluster_key, embedding, 1))
                assignments[face_id] = cluster_key
        logger.info(
            "cluster_unknown_embeddings completed faces=%d clusters=%d",
            len(embeddings),
            len(clusters),
        )
        return assignments


def vector_to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def bytes_to_vector(payload: bytes) -> np.ndarray:
    vector = np.frombuffer(payload, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector
