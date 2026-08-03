from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import logging
import time

import numpy as np
from PIL import Image, ImageOps

from app.core.config import Settings, get_settings

try:
    from insightface.app import FaceAnalysis
    from insightface.utils import face_align
except Exception:
    FaceAnalysis = None  # type: ignore[assignment]
    face_align = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]
    score: float | None
    embedding: np.ndarray
    face_size: float
    blur_score: float | None
    pose_yaw: float | None


class FaceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._app: FaceAnalysis | None = None  # type: ignore[type-arg]

    def _get_app(self) -> FaceAnalysis:
        if FaceAnalysis is None:
            logger.error("InsightFace load failed, FaceAnalysis is unavailable")
            raise RuntimeError("InsightFace is not installed or failed to load.")
        if self._app is None:
            providers = [item.strip() for item in self.settings.face_execution_providers.split(",") if item.strip()]
            if not providers:
                raise RuntimeError("FACE_EXECUTION_PROVIDERS must contain at least one provider.")
            try:
                import onnxruntime as ort

                available = set(ort.get_available_providers())
            except Exception as exc:
                raise RuntimeError("ONNX Runtime is not installed or failed to load.") from exc
            if self.settings.face_require_primary_provider and providers[0] not in available:
                raise RuntimeError(
                    f"Required ONNX Runtime provider is unavailable: {providers[0]}; "
                    f"available={sorted(available)}"
                )
            usable_providers = [provider for provider in providers if provider in available]
            if not usable_providers:
                raise RuntimeError(
                    f"None of the configured ONNX Runtime providers are available: {providers}; "
                    f"available={sorted(available)}"
                )
            logger.info(
                "Initializing InsightFace model: name=%s det_size=%s providers=%s",
                self.settings.face_model_name,
                self.settings.face_detection_size,
                usable_providers,
            )
            started_at = time.perf_counter()
            self._app = FaceAnalysis(name=self.settings.face_model_name, providers=usable_providers)
            size = self.settings.face_detection_size
            self._app.prepare(ctx_id=0, det_size=(size, size))
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info("InsightFace model initialized in %.1fms", elapsed_ms)
        return self._app

    def warmup(self) -> None:
        self._get_app()
        logger.info("FaceService warmup completed")

    def detect_faces(self, payload: bytes) -> list[DetectedFace]:
        logger.info("Start detect_faces payload_bytes=%d", len(payload))
        started_at = time.perf_counter()
        with Image.open(BytesIO(payload)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
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
            left, top, right, bottom = bbox
            face_size = max(0.0, min(right - left, bottom - top))
            x1 = max(0, int(left))
            y1 = max(0, int(top))
            x2 = min(array.shape[1], int(right))
            y2 = min(array.shape[0], int(bottom))
            crop = array[y1:y2, x1:x2]
            blur_score = self._blur_score(crop)
            pose_yaw = self._pose_yaw(getattr(face, "kps", None))
            if self.settings.face_flip_augmentation:
                augmented = self._embedding_with_aligned_flip(array, getattr(face, "kps", None))
                if augmented is not None:
                    embedding = augmented
            results.append(
                DetectedFace(
                    bbox=bbox,
                    score=score,
                    embedding=embedding,
                    face_size=face_size,
                    blur_score=blur_score,
                    pose_yaw=pose_yaw,
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

    def _embedding_with_aligned_flip(self, image: np.ndarray, keypoints: object) -> np.ndarray | None:
        if face_align is None or keypoints is None:
            return None
        recognition = getattr(self._get_app(), "models", {}).get("recognition")
        if recognition is None or not hasattr(recognition, "get_feat"):
            return None
        aligned = face_align.norm_crop(image, landmark=np.asarray(keypoints, dtype=np.float32))
        features = np.asarray(recognition.get_feat([aligned, np.ascontiguousarray(aligned[:, ::-1])]), dtype=np.float32)
        if features.ndim != 2 or features.shape[0] != 2:
            return None
        embedding = features.sum(axis=0)
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 0 else None

    @staticmethod
    def _blur_score(crop: np.ndarray) -> float | None:
        if crop.size == 0 or min(crop.shape[:2]) < 3:
            return None
        gray = crop.astype(np.float32).mean(axis=2)
        laplacian = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
        return float(np.var(laplacian))

    @staticmethod
    def _pose_yaw(keypoints: object) -> float | None:
        if keypoints is None:
            return None
        points = np.asarray(keypoints, dtype=np.float32)
        if points.shape[0] < 3:
            return None
        left_eye, right_eye, nose = points[0], points[1], points[2]
        eye_span = float(np.linalg.norm(right_eye - left_eye))
        if eye_span <= 0:
            return None
        midpoint = (left_eye + right_eye) / 2
        return float((nose[0] - midpoint[0]) / eye_span * 90.0)

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
