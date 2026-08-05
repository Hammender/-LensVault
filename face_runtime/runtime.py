from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageOps

from .adapters import OnnxFaceAdapter, create_adapter, model_sha256


@dataclass(frozen=True)
class FaceDetection:
    bbox: tuple[float, float, float, float]
    keypoints: np.ndarray
    score: float | None
    face_size: float
    blur_score: float | None
    pose_yaw: float | None


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[float, float, float, float]
    score: float | None
    embedding: np.ndarray
    face_size: float
    blur_score: float | None
    pose_yaw: float | None
    keypoints: np.ndarray | None = None


def decode_image_bytes(payload: bytes) -> np.ndarray:
    with Image.open(BytesIO(payload)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return np.ascontiguousarray(np.asarray(image)[:, :, ::-1])


def load_image_path(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return np.ascontiguousarray(np.asarray(image)[:, :, ::-1])


class FaceRuntime:
    def __init__(
        self,
        *,
        detector_pack: str,
        adapter_id: str,
        model_path: Path | None,
        providers: list[str],
        detection_size: int,
        flip_tta: bool,
        detector: object | None = None,
        adapter: OnnxFaceAdapter | None = None,
    ) -> None:
        if detection_size <= 0:
            raise RuntimeError("检测尺寸必须大于 0。")
        self.detector_pack = detector_pack
        self.adapter_id = adapter_id
        self.model_path = model_path
        self.providers = providers
        self.detection_size = detection_size
        self.flip_tta = flip_tta
        self._detector = detector
        self._adapter = adapter

    @property
    def adapter(self) -> OnnxFaceAdapter:
        if self._adapter is None:
            self._adapter = create_adapter(
                self.adapter_id,
                model_path=self.model_path,
                detector_pack=self.detector_pack,
                providers=self.providers,
            )
        return self._adapter

    @property
    def detector(self) -> object:
        if self._detector is None:
            try:
                from insightface.app import FaceAnalysis
            except Exception as exc:
                raise RuntimeError("InsightFace 未安装或加载失败。") from exc
            self._detector = FaceAnalysis(
                name=self.detector_pack,
                providers=self.providers,
                allowed_modules=["detection"],
            )
            self._detector.prepare(ctx_id=0, det_size=(self.detection_size, self.detection_size))
        return self._detector

    def detector_metadata(self) -> dict[str, object]:
        detector_app = self.detector
        detector = getattr(detector_app, "models", {}).get("detection", detector_app)
        model_file = getattr(detector, "model_file", None)
        model_path = Path(str(model_file)).expanduser().resolve() if model_file else None
        session = getattr(detector, "session", None)
        actual_providers = list(session.get_providers()) if session is not None else list(self.providers)
        return {
            "detector_pack": self.detector_pack,
            "detection_size": self.detection_size,
            "model_path": str(model_path) if model_path else None,
            "model_sha256": model_sha256(model_path) if model_path and model_path.is_file() else None,
            "providers": actual_providers,
        }

    def warmup(self) -> None:
        _ = self.detector
        _ = self.adapter

    def detect_bgr(self, image_bgr: np.ndarray) -> tuple[list[FaceDetection], float]:
        started_at = time.perf_counter()
        faces = self.detector.get(image_bgr)  # type: ignore[attr-defined]
        detections: list[FaceDetection] = []
        for face in faces:
            keypoints = np.asarray(getattr(face, "kps", None), dtype=np.float32)
            if keypoints.shape != (5, 2):
                continue
            bbox = tuple(float(value) for value in np.asarray(face.bbox).reshape(-1).tolist())
            if len(bbox) != 4:
                continue
            left, top, right, bottom = bbox
            x1, y1 = max(0, int(left)), max(0, int(top))
            x2, y2 = min(image_bgr.shape[1], int(right)), min(image_bgr.shape[0], int(bottom))
            crop = image_bgr[y1:y2, x1:x2]
            score_value = getattr(face, "det_score", None)
            detections.append(
                FaceDetection(
                    bbox=bbox,
                    keypoints=keypoints,
                    score=float(score_value) if score_value is not None else None,
                    face_size=max(0.0, min(right - left, bottom - top)),
                    blur_score=self.blur_score(crop),
                    pose_yaw=self.pose_yaw(keypoints),
                )
            )
        detections.sort(
            key=lambda face: (
                -((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])),
                face.bbox,
            )
        )
        return detections, (time.perf_counter() - started_at) * 1000

    def embed_detection(self, image_bgr: np.ndarray, detection: FaceDetection) -> tuple[np.ndarray, float]:
        try:
            from insightface.utils import face_align
        except Exception as exc:
            raise RuntimeError("InsightFace 人脸对齐组件加载失败。") from exc
        started_at = time.perf_counter()
        aligned = face_align.norm_crop(
            image_bgr,
            landmark=detection.keypoints,
            image_size=self.adapter.manifest.input_width,
        )
        embedding = self.adapter.embed_aligned(aligned, flip_tta=self.flip_tta)
        return embedding, (time.perf_counter() - started_at) * 1000

    def analyze_bgr(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        detections, _ = self.detect_bgr(image_bgr)
        results: list[DetectedFace] = []
        for detection in detections:
            embedding, _ = self.embed_detection(image_bgr, detection)
            results.append(
                DetectedFace(
                    bbox=detection.bbox,
                    score=detection.score,
                    embedding=embedding,
                    face_size=detection.face_size,
                    blur_score=detection.blur_score,
                    pose_yaw=detection.pose_yaw,
                    keypoints=detection.keypoints,
                )
            )
        return results

    @staticmethod
    def blur_score(crop: np.ndarray) -> float | None:
        if crop.size == 0 or min(crop.shape[:2]) < 3:
            return None
        gray = crop.astype(np.float32).mean(axis=2)
        laplacian = (
            -4 * gray[1:-1, 1:-1]
            + gray[:-2, 1:-1]
            + gray[2:, 1:-1]
            + gray[1:-1, :-2]
            + gray[1:-1, 2:]
        )
        return float(np.var(laplacian))

    @staticmethod
    def pose_yaw(keypoints: object) -> float | None:
        points = np.asarray(keypoints, dtype=np.float32)
        if points.shape[0] < 3:
            return None
        left_eye, right_eye, nose = points[0], points[1], points[2]
        eye_span = float(np.linalg.norm(right_eye - left_eye))
        if eye_span <= 0:
            return None
        midpoint = (left_eye + right_eye) / 2
        return float((nose[0] - midpoint[0]) / eye_span * 90.0)
