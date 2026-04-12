from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import logging
import time

import numpy as np
from PIL import Image

from app.core.config import Settings, get_settings

try:
    from insightface.app import FaceAnalysis
except Exception:
    FaceAnalysis = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]
    score: float | None
    embedding: np.ndarray


class FaceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._app: FaceAnalysis | None = None  # type: ignore[type-arg]

    def _get_app(self) -> FaceAnalysis:
        if FaceAnalysis is None:
            logger.error("InsightFace load failed, FaceAnalysis is unavailable")
            raise RuntimeError("InsightFace is not installed or failed to load.")
        if self._app is None:
            logger.info("Initializing InsightFace model: name=buffalo_l providers=CPUExecutionProvider")
            started_at = time.perf_counter()
            self._app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            self._app.prepare(ctx_id=0, det_size=(640, 640))
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info("InsightFace model initialized in %.1fms", elapsed_ms)
        return self._app

    def warmup(self) -> None:
        self._get_app()
        logger.info("FaceService warmup completed")

    def detect_faces(self, payload: bytes) -> list[DetectedFace]:
        logger.info("Start detect_faces payload_bytes=%d", len(payload))
        started_at = time.perf_counter()
        image = Image.open(BytesIO(payload)).convert("RGB")
        logger.info("Decoded image size=%sx%s mode=%s", image.width, image.height, image.mode)
        array = np.asarray(image)[:, :, ::-1]
        faces = self._get_app().get(array)
        logger.info("Face detection finished detected_faces=%d", len(faces))
        results: list[DetectedFace] = []
        for index, face in enumerate(faces, start=1):
            bbox = tuple(float(v) for v in face.bbox.tolist())
            embedding = np.asarray(face.embedding, dtype=np.float32)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            score = float(getattr(face, "det_score", 0.0)) if getattr(face, "det_score", None) is not None else None
            results.append(
                DetectedFace(
                    bbox=bbox,
                    score=score,
                    embedding=embedding,
                )
            )
            logger.debug(
                "Detected face index=%d score=%s bbox=(%.1f,%.1f,%.1f,%.1f)",
                index,
                f"{score:.4f}" if score is not None else "None",
                bbox[0],
                bbox[1],
                bbox[2],
                bbox[3],
            )
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
