from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image

from app.core.config import Settings, get_settings

try:
    from insightface.app import FaceAnalysis
except Exception:
    FaceAnalysis = None  # type: ignore[assignment]


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
            raise RuntimeError("InsightFace is not installed or failed to load.")
        if self._app is None:
            self._app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            self._app.prepare(ctx_id=0, det_size=(640, 640))
        return self._app

    def detect_faces(self, payload: bytes) -> list[DetectedFace]:
        image = Image.open(BytesIO(payload)).convert("RGB")
        array = np.asarray(image)[:, :, ::-1]
        faces = self._get_app().get(array)
        results: list[DetectedFace] = []
        for face in faces:
            bbox = tuple(float(v) for v in face.bbox.tolist())
            embedding = np.asarray(face.embedding, dtype=np.float32)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            results.append(
                DetectedFace(
                    bbox=bbox,
                    score=float(getattr(face, "det_score", 0.0)) if getattr(face, "det_score", None) is not None else None,
                    embedding=embedding,
                )
            )
        return results

    @staticmethod
    def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
        return float(np.dot(left, right))

    def match_embedding(self, embedding: np.ndarray, candidates: list[tuple[int, np.ndarray]]) -> tuple[int | None, float | None]:
        best_person_id: int | None = None
        best_score: float | None = None
        for person_id, candidate in candidates:
            score = self.cosine_similarity(embedding, candidate)
            if best_score is None or score > best_score:
                best_person_id = person_id
                best_score = score
        if best_score is None or best_score < self.settings.face_recognition_threshold:
            return None, best_score
        return best_person_id, best_score

    def cluster_unknown_embeddings(self, embeddings: list[tuple[int, np.ndarray]]) -> dict[int, str]:
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
        return assignments


def vector_to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def bytes_to_vector(payload: bytes) -> np.ndarray:
    vector = np.frombuffer(payload, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector
