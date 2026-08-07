from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base
from app.models import Person
from app.services.face import FaceService
from app.services.importer import PictureService
from app.services.qdrant import FaceSearchHit
from face_runtime import DetectedFace, FaceRuntime


NORMAL_KEYPOINTS = np.asarray(
    [[30, 30], [70, 30], [50, 50], [35, 70], [65, 70]],
    dtype=np.float32,
)


def rotated_keypoints(angle: float) -> np.ndarray:
    matrix = cv2.getRotationMatrix2D((50, 50), angle, 1.0)
    return FaceRuntime.transform_points(NORMAL_KEYPOINTS, matrix)


def make_payload() -> bytes:
    image = Image.new("RGB", (100, 100), "white")
    source = BytesIO()
    image.save(source, format="PNG")
    return source.getvalue()


@pytest.mark.parametrize(
    ("image_rotation", "expected_roll"),
    [(0, 0), (20, -20), (90, -90), (-90, 90), (180, -180)],
)
def test_roll_angle_uses_exact_landmark_rotation(image_rotation: float, expected_roll: float) -> None:
    assert FaceRuntime.estimate_roll_angle(rotated_keypoints(image_rotation)) == pytest.approx(expected_roll)


def test_roll_angle_uses_mouth_position_to_detect_upside_down_face() -> None:
    points = rotated_keypoints(180)
    points[[0, 1]] = points[[1, 0]]
    points[[3, 4]] = points[[4, 3]]

    assert FaceRuntime.estimate_roll_angle(points) == pytest.approx(-180)


@pytest.mark.parametrize(
    "keypoints",
    [
        np.zeros((4, 2), dtype=np.float32),
        np.full((5, 2), np.nan, dtype=np.float32),
        np.asarray([[1, 1], [1, 1], [2, 2], [3, 3], [4, 4]], dtype=np.float32),
    ],
)
def test_roll_angle_rejects_invalid_landmarks(keypoints: np.ndarray) -> None:
    assert FaceRuntime.estimate_roll_angle(keypoints) is None


@dataclass
class FakeModelFace:
    bbox: np.ndarray
    kps: np.ndarray
    det_score: float = 0.9


class SequenceDetector:
    def __init__(self, responses: list[list[FakeModelFace]]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    def get(self, _image: np.ndarray) -> list[FakeModelFace]:
        self.calls += 1
        return next(self.responses)


def make_runtime(detector: SequenceDetector, *, min_angle: float = 30) -> FaceRuntime:
    return FaceRuntime(
        detector_pack="test",
        adapter_id="buffalo_l",
        model_path=None,
        providers=["CPUExecutionProvider"],
        detection_size=640,
        flip_tta=False,
        roll_correction_enabled=True,
        roll_correction_min_angle=min_angle,
        detector=detector,
    )


def model_face(keypoints: np.ndarray) -> FakeModelFace:
    return FakeModelFace(np.asarray([20, 20, 80, 80], dtype=np.float32), keypoints)


def test_high_roll_face_is_rotated_and_redetected_before_embedding() -> None:
    detector = SequenceDetector([[model_face(rotated_keypoints(90))], [model_face(NORMAL_KEYPOINTS)]])
    runtime = make_runtime(detector)
    embedded_landmarks: list[np.ndarray] = []

    def fake_embed(_image: np.ndarray, detection: object) -> tuple[np.ndarray, float]:
        embedded_landmarks.append(detection.keypoints.copy())
        return np.asarray([1.0, 0.0], dtype=np.float32), 1.0

    runtime.embed_detection = fake_embed  # type: ignore[method-assign]

    result = runtime.analyze_bgr(np.zeros((100, 100, 3), dtype=np.uint8))

    assert detector.calls == 2
    assert len(result) == 1
    assert result[0].orientation_corrected is True
    assert result[0].roll_angle == pytest.approx(-90)
    assert np.array_equal(embedded_landmarks[0], NORMAL_KEYPOINTS)


def test_small_roll_does_not_trigger_redetection() -> None:
    points = rotated_keypoints(20)
    detector = SequenceDetector([[model_face(points)]])
    runtime = make_runtime(detector)
    runtime.embed_detection = lambda _image, _detection: (np.asarray([1.0]), 1.0)  # type: ignore[method-assign]

    result = runtime.analyze_bgr(np.zeros((100, 100, 3), dtype=np.uint8))

    assert detector.calls == 1
    assert result[0].orientation_corrected is False


def test_failed_roll_redetection_uses_original_landmarks() -> None:
    original = rotated_keypoints(90)
    detector = SequenceDetector([[model_face(original)], []])
    runtime = make_runtime(detector)
    embedded_landmarks: list[np.ndarray] = []

    def fake_embed(_image: np.ndarray, detection: object) -> tuple[np.ndarray, float]:
        embedded_landmarks.append(detection.keypoints.copy())
        return np.asarray([1.0]), 1.0

    runtime.embed_detection = fake_embed  # type: ignore[method-assign]

    result = runtime.analyze_bgr(np.zeros((100, 100, 3), dtype=np.uint8))

    assert result[0].orientation_corrected is False
    assert np.array_equal(embedded_landmarks[0], original)


def test_rotated_bbox_maps_back_to_original_coordinates() -> None:
    image = np.zeros((60, 100, 3), dtype=np.uint8)
    _, forward = FaceRuntime.rotate_bound(image, 90)
    original_bbox = (20.0, 10.0, 60.0, 40.0)
    rotated_bbox = FaceRuntime.transform_bbox(original_bbox, forward, 60, 100)

    assert rotated_bbox is not None
    mapped_bbox = FaceRuntime.transform_bbox(
        rotated_bbox,
        FaceRuntime._invert_affine(forward),
        100,
        60,
    )

    assert mapped_bbox == pytest.approx(original_bbox, abs=1e-4)


def detected_face(
    value: float,
    *,
    variants: tuple[float, ...] = (),
    bbox: tuple[float, float, float, float] = (10, 10, 80, 80),
) -> DetectedFace:
    return DetectedFace(
        bbox,
        0.9,
        np.asarray([value], dtype=np.float32),
        70,
        90,
        0,
        embedding_variants=tuple(np.asarray([item], dtype=np.float32) for item in variants),
    )


def test_rotation_candidates_are_deduplicated_and_preserved_as_variants() -> None:
    faces = FaceRuntime.deduplicate_faces([detected_face(1), detected_face(2), detected_face(3)])

    assert len(faces) == 1
    assert [float(vector[0]) for vector in faces[0].embedding_variants] == [2, 3]


def test_multi_face_rotation_candidates_are_deduplicated_per_face() -> None:
    faces = FaceRuntime.deduplicate_faces(
        [
            detected_face(1, bbox=(10, 10, 50, 50)),
            detected_face(2, bbox=(12, 11, 52, 51)),
            detected_face(3, bbox=(100, 20, 150, 70)),
            detected_face(4, bbox=(98, 19, 148, 69)),
        ]
    )

    assert len(faces) == 2
    assert [float(vector[0]) for vector in faces[0].embedding_variants] == [2]
    assert [float(vector[0]) for vector in faces[1].embedding_variants] == [4]


class VectorStoreByValue:
    def search_candidates(self, _collection: str, vector: np.ndarray, **_kwargs: object) -> list[FaceSearchHit]:
        value = int(vector[0])
        scores = {
            1: [FaceSearchHit(1, 10, 0.44, "sample", 1), FaceSearchHit(2, 20, 0.42, "sample", 2)],
            2: [FaceSearchHit(3, 10, 0.72, "sample", 3), FaceSearchHit(4, 20, 0.55, "sample", 4)],
        }
        return scores.get(value, [])


def test_person_matching_aggregates_best_score_across_rotation_variants() -> None:
    service = PictureService.__new__(PictureService)
    service.settings = Settings()
    service.vector_store = VectorStoreByValue()

    match = service._match_face(detected_face(1, variants=(2,)), workspace_id=1)

    assert (match.person_id, match.score) == (10, 0.72)
    assert (match.second_person_id, match.second_score) == (20, 0.55)
    assert match.margin == pytest.approx(0.17)


class FallbackFaceService:
    def __init__(self, primary: list[DetectedFace], fallback: list[DetectedFace]) -> None:
        self.primary = primary
        self.fallback = fallback
        self.fallback_calls = 0

    def detect_faces(self, _payload: bytes) -> list[DetectedFace]:
        return self.primary

    def detect_faces_with_rotation_fallback(self, _payload: bytes) -> list[DetectedFace]:
        self.fallback_calls += 1
        return self.fallback


class RecognitionVectorStore:
    def search_candidates(self, _collection: str, vector: np.ndarray, **_kwargs: object) -> list[FaceSearchHit]:
        value = int(vector[0])
        hit = {
            1: FaceSearchHit(1, 1, 0.20, "sample", 1),
            2: FaceSearchHit(2, 1, 0.70, "sample", 2),
            3: FaceSearchHit(3, 2, 0.75, "sample", 3),
        }.get(value)
        return [hit] if hit is not None else []


def make_recognition_service(face_service: FallbackFaceService) -> PictureService:
    service = PictureService.__new__(PictureService)
    service.settings = Settings(face_recognition_threshold=0.43, face_recognition_min_margin=0.04)
    service.face_service = face_service
    service.vector_store = RecognitionVectorStore()
    return service


def test_all_failed_matches_trigger_rotation_fallback() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    face_service = FallbackFaceService([detected_face(1)], [detected_face(2)])
    service = make_recognition_service(face_service)
    with Session(engine) as db:
        db.add(Person(id=1, name="person-1", display_name="人物一", is_unknown=False))
        db.commit()

        plan = service._recognition_plan(db, make_payload(), workspace_id=None)

    assert face_service.fallback_calls == 1
    assert plan[0][1].score == pytest.approx(0.70)


def test_any_accepted_match_skips_rotation_fallback() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    face_service = FallbackFaceService([detected_face(3), detected_face(1)], [detected_face(2)])
    service = make_recognition_service(face_service)
    with Session(engine) as db:
        db.add_all([
            Person(id=1, name="person-1", display_name="人物一", is_unknown=False),
            Person(id=2, name="person-2", display_name="人物二", is_unknown=False),
        ])
        db.commit()

        plan = service._recognition_plan(db, make_payload(), workspace_id=None)

    assert face_service.fallback_calls == 0
    assert len(plan) == 2


class EmptyRuntime:
    def __init__(self) -> None:
        self.fallback_calls = 0

    def analyze_bgr(self, _array: np.ndarray) -> list[DetectedFace]:
        return []

    def analyze_rotations_bgr(self, _array: np.ndarray, angles: tuple[float, ...]) -> list[DetectedFace]:
        self.fallback_calls += 1
        assert angles == (90.0, -90.0, -180.0)
        return [detected_face(2)]


def test_no_face_detection_uses_configured_rotation_fallback() -> None:
    runtime = EmptyRuntime()
    service = FaceService(Settings())
    service._runtime = runtime  # type: ignore[assignment]

    result = service.detect_faces(make_payload())

    assert runtime.fallback_calls == 1
    assert len(result) == 1
