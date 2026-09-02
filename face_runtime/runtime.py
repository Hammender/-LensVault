from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
import logging
import math
import time
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .adapters import OnnxFaceAdapter, create_adapter, model_sha256


logger = logging.getLogger(__name__)


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
    roll_angle: float | None = None
    orientation_corrected: bool = False
    embedding_variants: tuple[np.ndarray, ...] = ()


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
        roll_correction_enabled: bool = True,
        roll_correction_min_angle: float = 30.0,
        detector: object | None = None,
        adapter: OnnxFaceAdapter | None = None,
        create_session: Callable[..., Any] | None = None,
        detector_session_guard: Callable[[], AbstractContextManager[Any]] | None = None,
    ) -> None:
        if detection_size <= 0:
            raise RuntimeError("检测尺寸必须大于 0。")
        if not 0 <= roll_correction_min_angle <= 180:
            raise RuntimeError("人脸滚转校正角度阈值必须在 0 到 180 之间。")
        self.detector_pack = detector_pack
        self.adapter_id = adapter_id
        self.model_path = model_path
        self.providers = providers
        self.detection_size = detection_size
        self.flip_tta = flip_tta
        self.roll_correction_enabled = roll_correction_enabled
        self.roll_correction_min_angle = roll_correction_min_angle
        self._detector = detector
        self._adapter = adapter
        self._create_session = create_session
        self._detector_session_guard = detector_session_guard

    @property
    def adapter(self) -> OnnxFaceAdapter:
        if self._adapter is None:
            self._adapter = create_adapter(
                self.adapter_id,
                model_path=self.model_path,
                detector_pack=self.detector_pack,
                providers=self.providers,
                create_session=self._create_session,
            )
        return self._adapter

    @property
    def detector(self) -> object:
        if self._detector is None:
            try:
                from insightface.app import FaceAnalysis
            except Exception as exc:
                raise RuntimeError("InsightFace 未安装或加载失败。") from exc
            guard = self._detector_session_guard() if self._detector_session_guard is not None else nullcontext()
            with guard:
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
            if keypoints.shape != (5, 2) or not np.isfinite(keypoints).all():
                continue
            bbox_values = np.asarray(face.bbox, dtype=np.float32).reshape(-1)
            if bbox_values.shape != (4,) or not np.isfinite(bbox_values).all():
                continue
            bbox = tuple(float(value) for value in bbox_values.tolist())
            left, top, right, bottom = bbox
            if right <= left or bottom <= top:
                continue
            x1, y1 = max(0, int(left)), max(0, int(top))
            x2, y2 = min(image_bgr.shape[1], int(right)), min(image_bgr.shape[0], int(bottom))
            if x2 <= x1 or y2 <= y1:
                continue
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
            roll_angle = self.estimate_roll_angle(detection.keypoints)
            correction_triggered = (
                self.roll_correction_enabled
                and roll_angle is not None
                and abs(roll_angle) >= self.roll_correction_min_angle
            )
            logger.info(
                "Face orientation evaluated bbox=%s roll=%s correction_triggered=%s",
                detection.bbox,
                f"{roll_angle:.2f}" if roll_angle is not None else "unknown",
                correction_triggered,
            )
            corrected: tuple[np.ndarray, FaceDetection] | None = None
            if correction_triggered:
                try:
                    corrected = self._correct_rolled_detection(image_bgr, detection, roll_angle)
                except Exception:
                    logger.warning(
                        "Rolled face correction failed; use original landmarks bbox=%s roll=%.1f",
                        detection.bbox,
                        roll_angle,
                        exc_info=True,
                    )
            original_embedding: np.ndarray | None = None
            try:
                original_embedding, _ = self.embed_detection(image_bgr, detection)
            except Exception:
                if corrected is None:
                    raise
                logger.warning(
                    "Original face embedding failed; keep corrected candidate bbox=%s roll=%.1f",
                    detection.bbox,
                    roll_angle,
                    exc_info=True,
                )
            if corrected is None:
                assert original_embedding is not None
                embedding = original_embedding
                embedding_variants: tuple[np.ndarray, ...] = ()
                pose_yaw = detection.pose_yaw
            else:
                embedding, corrected_detection = corrected
                embedding_variants = (original_embedding,) if original_embedding is not None else ()
                pose_yaw = corrected_detection.pose_yaw
            results.append(
                DetectedFace(
                    bbox=detection.bbox,
                    score=detection.score,
                    embedding=embedding,
                    face_size=detection.face_size,
                    blur_score=detection.blur_score,
                    pose_yaw=pose_yaw,
                    keypoints=detection.keypoints,
                    roll_angle=roll_angle,
                    orientation_corrected=corrected is not None,
                    embedding_variants=embedding_variants,
                )
            )
        return results

    def analyze_rotations_bgr(self, image_bgr: np.ndarray, angles: tuple[float, ...]) -> list[DetectedFace]:
        candidates: list[DetectedFace] = []
        for angle in angles:
            normalized_angle = self.normalize_angle(angle) if math.isfinite(angle) else 0.0
            if not math.isfinite(angle) or abs(normalized_angle) < 1e-6:
                continue
            try:
                rotated, forward_matrix = self.rotate_bound(image_bgr, normalized_angle)
                inverse_matrix = self._invert_affine(forward_matrix)
                detections, _ = self.detect_bgr(rotated)
            except Exception:
                logger.warning(
                    "Rotation fallback angle failed angle=%.1f",
                    normalized_angle,
                    exc_info=True,
                )
                continue
            logger.info(
                "Rotation fallback detection angle=%.1f detected_faces=%d",
                normalized_angle,
                len(detections),
            )
            retained_before = len(candidates)
            for detection_index, detection in enumerate(detections):
                try:
                    detected_roll = self.estimate_roll_angle(detection.keypoints)
                    bbox = self.transform_bbox(
                        detection.bbox,
                        inverse_matrix,
                        image_bgr.shape[1],
                        image_bgr.shape[0],
                    )
                    if bbox is None:
                        logger.info(
                            "Rotation fallback candidate skipped angle=%.1f face_index=%d reason=invalid_bbox",
                            normalized_angle,
                            detection_index,
                        )
                        continue
                    mapped_keypoints = self.transform_points(detection.keypoints, inverse_matrix)
                    if not np.isfinite(mapped_keypoints).all():
                        logger.info(
                            "Rotation fallback candidate skipped angle=%.1f face_index=%d reason=invalid_keypoints",
                            normalized_angle,
                            detection_index,
                        )
                        continue
                    embedding, _ = self.embed_detection(rotated, detection)
                    left, top, right, bottom = bbox
                    crop = image_bgr[
                        max(0, int(top)):min(image_bgr.shape[0], int(bottom)),
                        max(0, int(left)):min(image_bgr.shape[1], int(right)),
                    ]
                    candidates.append(
                        DetectedFace(
                            bbox=bbox,
                            score=detection.score,
                            embedding=embedding,
                            face_size=max(0.0, min(right - left, bottom - top)),
                            blur_score=self.blur_score(crop),
                            pose_yaw=detection.pose_yaw,
                            keypoints=mapped_keypoints,
                            roll_angle=self.estimate_roll_angle(mapped_keypoints),
                            orientation_corrected=True,
                        )
                    )
                    logger.info(
                        "Rotation fallback candidate retained angle=%.1f face_index=%d residual_roll=%s",
                        normalized_angle,
                        detection_index,
                        f"{detected_roll:.2f}" if detected_roll is not None else "unknown",
                    )
                except Exception:
                    logger.warning(
                        "Rotation fallback face failed angle=%.1f face_index=%d",
                        normalized_angle,
                        detection_index,
                        exc_info=True,
                    )
            logger.info(
                "Rotation fallback angle completed angle=%.1f retained_candidates=%d",
                normalized_angle,
                len(candidates) - retained_before,
            )
        deduplicated = self.deduplicate_faces(candidates)
        logger.info(
            "Rotation fallback candidates merged retained_candidates=%d merged_faces=%d",
            len(candidates),
            len(deduplicated),
        )
        return deduplicated

    def _correct_rolled_detection(
        self,
        image_bgr: np.ndarray,
        detection: FaceDetection,
        roll_angle: float,
    ) -> tuple[np.ndarray, FaceDetection] | None:
        crop = self._padded_square_crop(image_bgr, detection.bbox, scale=1.5)
        rotated = self.rotate_same_size(crop, roll_angle)
        detections, _ = self.detect_bgr(rotated)
        logger.info(
            "Roll correction redetection bbox=%s input_roll=%.2f detected_faces=%d",
            detection.bbox,
            roll_angle,
            len(detections),
        )
        if not detections:
            return None
        center = np.asarray([rotated.shape[1] / 2.0, rotated.shape[0] / 2.0], dtype=np.float32)
        corrected_detection = min(
            detections,
            key=lambda item: float(
                np.linalg.norm(
                    np.asarray(
                        [
                            (item.bbox[0] + item.bbox[2]) / 2.0,
                            (item.bbox[1] + item.bbox[3]) / 2.0,
                        ],
                        dtype=np.float32,
                    )
                    - center
                )
            ),
        )
        corrected_roll = self.estimate_roll_angle(corrected_detection.keypoints)
        embedding, _ = self.embed_detection(rotated, corrected_detection)
        logger.info(
            "Roll correction candidate retained bbox=%s residual_roll=%s",
            detection.bbox,
            f"{corrected_roll:.2f}" if corrected_roll is not None else "unknown",
        )
        return embedding, corrected_detection

    @staticmethod
    def normalize_angle(angle: float) -> float:
        normalized = (float(angle) + 180.0) % 360.0 - 180.0
        return 0.0 if abs(normalized) < 1e-6 else normalized

    @classmethod
    def estimate_roll_angle(cls, keypoints: object) -> float | None:
        points = np.asarray(keypoints, dtype=np.float32)
        if points.shape != (5, 2) or not np.isfinite(points).all():
            return None
        left_eye, right_eye = points[0], points[1]
        eye_vector = right_eye - left_eye
        eye_span = float(np.linalg.norm(eye_vector))
        if eye_span <= 1.0:
            return None
        eye_midpoint = (left_eye + right_eye) / 2.0
        mouth_midpoint = (points[3] + points[4]) / 2.0
        mouth_vector = mouth_midpoint - eye_midpoint
        if float(np.linalg.norm(mouth_vector)) <= 1.0:
            return None
        angle = math.degrees(math.atan2(float(eye_vector[1]), float(eye_vector[0])))
        radians = math.radians(angle)
        rotated_mouth_y = -math.sin(radians) * float(mouth_vector[0]) + math.cos(radians) * float(mouth_vector[1])
        if rotated_mouth_y < 0:
            angle += 180.0
        return cls.normalize_angle(angle)

    @staticmethod
    def _padded_square_crop(
        image_bgr: np.ndarray,
        bbox: tuple[float, float, float, float],
        *,
        scale: float,
    ) -> np.ndarray:
        import cv2

        left, top, right, bottom = bbox
        side = max(2, int(math.ceil(max(right - left, bottom - top) * scale)))
        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        raw_left = int(math.floor(center_x - side / 2.0))
        raw_top = int(math.floor(center_y - side / 2.0))
        raw_right = raw_left + side
        raw_bottom = raw_top + side
        x1, y1 = max(0, raw_left), max(0, raw_top)
        x2, y2 = min(image_bgr.shape[1], raw_right), min(image_bgr.shape[0], raw_bottom)
        crop = image_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return np.empty((0, 0, 3), dtype=image_bgr.dtype)
        return cv2.copyMakeBorder(
            crop,
            y1 - raw_top,
            raw_bottom - y2,
            x1 - raw_left,
            raw_right - x2,
            cv2.BORDER_REPLICATE,
        )

    @staticmethod
    def rotate_same_size(image_bgr: np.ndarray, angle: float) -> np.ndarray:
        import cv2

        if image_bgr.size == 0:
            return image_bgr
        height, width = image_bgr.shape[:2]
        center = ((width - 1) / 2.0, (height - 1) / 2.0)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(
            image_bgr,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

    @staticmethod
    def rotate_bound(image_bgr: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
        import cv2

        height, width = image_bgr.shape[:2]
        center = (width / 2.0, height / 2.0)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        cosine, sine = abs(float(matrix[0, 0])), abs(float(matrix[0, 1]))
        target_width = max(1, int(math.ceil(height * sine + width * cosine)))
        target_height = max(1, int(math.ceil(height * cosine + width * sine)))
        matrix[0, 2] += target_width / 2.0 - center[0]
        matrix[1, 2] += target_height / 2.0 - center[1]
        rotated = cv2.warpAffine(
            image_bgr,
            matrix,
            (target_width, target_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated, np.asarray(matrix, dtype=np.float32)

    @staticmethod
    def _invert_affine(matrix: np.ndarray) -> np.ndarray:
        import cv2

        return np.asarray(cv2.invertAffineTransform(matrix), dtype=np.float32)

    @staticmethod
    def transform_points(points: object, matrix: np.ndarray) -> np.ndarray:
        array = np.asarray(points, dtype=np.float32)
        homogeneous = np.concatenate([array, np.ones((array.shape[0], 1), dtype=np.float32)], axis=1)
        return np.asarray(homogeneous @ matrix.T, dtype=np.float32)

    @classmethod
    def transform_bbox(
        cls,
        bbox: tuple[float, float, float, float],
        matrix: np.ndarray,
        image_width: int,
        image_height: int,
    ) -> tuple[float, float, float, float] | None:
        left, top, right, bottom = bbox
        corners = cls.transform_points(
            np.asarray([[left, top], [right, top], [right, bottom], [left, bottom]], dtype=np.float32),
            matrix,
        )
        mapped_left = max(0.0, float(np.min(corners[:, 0])))
        mapped_top = max(0.0, float(np.min(corners[:, 1])))
        mapped_right = min(float(image_width), float(np.max(corners[:, 0])))
        mapped_bottom = min(float(image_height), float(np.max(corners[:, 1])))
        if mapped_right <= mapped_left or mapped_bottom <= mapped_top:
            return None
        return mapped_left, mapped_top, mapped_right, mapped_bottom

    @staticmethod
    def bbox_iou(
        left_bbox: tuple[float, float, float, float],
        right_bbox: tuple[float, float, float, float],
    ) -> float:
        intersection_left = max(left_bbox[0], right_bbox[0])
        intersection_top = max(left_bbox[1], right_bbox[1])
        intersection_right = min(left_bbox[2], right_bbox[2])
        intersection_bottom = min(left_bbox[3], right_bbox[3])
        intersection = max(0.0, intersection_right - intersection_left) * max(
            0.0, intersection_bottom - intersection_top
        )
        left_area = max(0.0, left_bbox[2] - left_bbox[0]) * max(0.0, left_bbox[3] - left_bbox[1])
        right_area = max(0.0, right_bbox[2] - right_bbox[0]) * max(0.0, right_bbox[3] - right_bbox[1])
        union = left_area + right_area - intersection
        return intersection / union if union > 0 else 0.0

    @classmethod
    def deduplicate_faces(cls, faces: list[DetectedFace], *, iou_threshold: float = 0.5) -> list[DetectedFace]:
        deduplicated: list[DetectedFace] = []
        for face in faces:
            best_index: int | None = None
            best_iou = iou_threshold
            for index, existing in enumerate(deduplicated):
                overlap = cls.bbox_iou(face.bbox, existing.bbox)
                if overlap >= best_iou:
                    best_index = index
                    best_iou = overlap
            if best_index is None:
                deduplicated.append(face)
                continue
            existing = deduplicated[best_index]
            deduplicated[best_index] = replace(
                existing,
                embedding_variants=existing.embedding_variants + (face.embedding,) + face.embedding_variants,
            )
        return deduplicated

    @classmethod
    def prefer_rotated_faces(
        cls,
        primary_faces: list[DetectedFace],
        rotated_faces: list[DetectedFace],
    ) -> list[DetectedFace]:
        if not rotated_faces:
            return primary_faces
        merged: list[DetectedFace] = []
        unused_rotated = set(range(len(rotated_faces)))
        for primary in primary_faces:
            overlaps = [
                (cls.bbox_iou(primary.bbox, rotated.bbox), index)
                for index, rotated in enumerate(rotated_faces)
                if index in unused_rotated
            ]
            best_overlap, best_index = max(overlaps, default=(0.0, -1))
            if best_overlap < 0.3:
                merged.append(primary)
                continue
            rotated = rotated_faces[best_index]
            unused_rotated.remove(best_index)
            merged.append(
                replace(
                    primary,
                    embedding=rotated.embedding,
                    embedding_variants=(
                        rotated.embedding_variants
                        + (primary.embedding,)
                        + primary.embedding_variants
                    ),
                    pose_yaw=rotated.pose_yaw,
                    roll_angle=primary.roll_angle if primary.roll_angle is not None else rotated.roll_angle,
                    orientation_corrected=True,
                )
            )
        merged.extend(rotated_faces[index] for index in sorted(unused_rotated))
        return merged

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
