from __future__ import annotations

import logging
from pathlib import Path
import time

import numpy as np

from app.core.config import Settings, get_settings
from face_runtime import DetectedFace, FaceRuntime, decode_image_bytes
from face_runtime.providers import validate_configured_providers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FaceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._runtime: FaceRuntime | None = None

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
            )
            self._runtime.warmup()
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info("Face runtime initialized in %.1fms", elapsed_ms)
        return self._runtime

    def warmup(self) -> None:
        self._get_runtime()
        logger.info("FaceService warmup completed")

    def detect_faces(self, payload: bytes) -> list[DetectedFace]:
        logger.info("Start detect_faces payload_bytes=%d", len(payload))
        started_at = time.perf_counter()
        array = decode_image_bytes(payload)
        logger.info("Decoded image size=%sx%s", array.shape[1], array.shape[0])
        results = self._get_runtime().analyze_bgr(array)
        logger.info("Face detection finished detected_faces=%d", len(results))
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info("detect_faces completed in %.1fms", elapsed_ms)
        return results

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
