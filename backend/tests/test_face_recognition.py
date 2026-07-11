from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base
from app.models import FaceRecord, GalleryPhoto, Person, SamplePhoto
from app.services.face import DetectedFace, FaceService
from app.services.face_index import build_face_index_health
from app.services.importer import PictureService
from app.services.qdrant import FaceIndexInspection, FaceSearchHit


class FakeVectorStore:
    def __init__(self, hits: list[FaceSearchHit]) -> None:
        self.hits = hits
        self.search_args: dict[str, object] = {}

    def search_candidates(self, collection: str, vector: np.ndarray, **kwargs: object) -> list[FaceSearchHit]:
        self.search_args = {"collection": collection, **kwargs}
        return self.hits


class FakeScalarSession:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)

    def scalar(self, _statement: object) -> int:
        return next(self.values)


class FakeInspectionStore:
    def __init__(self, inspection: FaceIndexInspection) -> None:
        self.inspection = inspection

    def inspect_collection(self, *_args: object, **_kwargs: object) -> FaceIndexInspection:
        return self.inspection


def test_face_detection_applies_exif_orientation_before_model_input() -> None:
    image = Image.new("RGB", (20, 10), "white")
    exif = image.getexif()
    exif[274] = 6
    source = BytesIO()
    image.save(source, format="JPEG", exif=exif)
    captured: dict[str, object] = {}

    class FakeFaceApp:
        def get(self, array: np.ndarray) -> list[object]:
            captured["shape"] = array.shape
            return []

    service = FaceService(Settings())
    service._app = FakeFaceApp()  # type: ignore[assignment]

    assert service.detect_faces(source.getvalue()) == []
    assert captured["shape"] == (20, 10, 3)


@pytest.mark.parametrize(
    ("searchable_samples", "covered_people", "expected_status"),
    [(37, 17, "degraded"), (293, 164, "ok")],
)
def test_face_index_health_detects_coverage_gap(
    searchable_samples: int,
    covered_people: int,
    expected_status: str,
) -> None:
    inspection = FaceIndexInspection(
        collection="faces",
        exists=True,
        vector_size=512,
        distance="Cosine",
        total_points=searchable_samples + covered_people,
        searchable_samples=searchable_samples,
        searchable_centroids=covered_people,
        covered_people=covered_people,
        invalid_payload_points=0,
        invalid_vector_points=0,
        vector_norm_min=None,
        vector_norm_max=None,
    )
    settings = Settings(
        qdrant_known_collection="faces",
        qdrant_vector_dimension=512,
        face_embedding_version="test-v2",
    )

    result = build_face_index_health(  # type: ignore[arg-type]
        FakeScalarSession([293, 164]),
        FakeInspectionStore(inspection),
        settings,
    )

    assert result["status"] == expected_status
    assert result["sample_coverage"] == pytest.approx(searchable_samples / 293)
    assert result["person_coverage"] == pytest.approx(covered_people / 164)


def test_person_level_matching_uses_best_sample_and_workspace_version_filters() -> None:
    store = FakeVectorStore([
        FaceSearchHit(1, 10, 0.61, "sample", 1),
        FaceSearchHit(2, 20, 0.72, "sample", 2),
        FaceSearchHit(3, 10, 0.81, "centroid", None),
    ])
    service = PictureService.__new__(PictureService)
    service.settings = Settings(face_search_limit=50, face_embedding_version="test-v1")
    service.vector_store = store
    detected = DetectedFace((0, 0, 100, 100), 0.9, np.ones(512, dtype=np.float32), 100, 90, 0)

    match = service._match_face(detected, workspace_id=7)

    assert (match.person_id, match.score) == (10, 0.81)
    assert (match.second_person_id, match.second_score) == (20, 0.72)
    assert round(match.margin or 0, 2) == 0.09
    assert store.search_args["workspace_id"] == 7
    assert store.search_args["embedding_version"] == "test-v1"
    assert store.search_args["limit"] == 50


def test_sample_quality_has_human_readable_warnings() -> None:
    service = PictureService.__new__(PictureService)
    service.settings = Settings()
    detected = DetectedFace((0, 0, 50, 50), 0.2, np.ones(512, dtype=np.float32), 50, 5, 45)

    warnings = service._quality_warnings(detected)

    assert any("尺寸" in warning for warning in warnings)
    assert any("模糊" in warning for warning in warnings)
    assert any("侧脸" in warning for warning in warnings)


def test_gallery_sample_promotion_rejects_same_person_photo_twice() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        person = Person(name="测试人物", display_name="测试人物", is_unknown=False)
        photo = GalleryPhoto(
            filename="gallery.jpg",
            sha256="gallery-sha",
            object_key="gallery/object.jpg",
            is_rich_text=False,
        )
        db.add_all([person, photo])
        db.flush()
        db.add(
            SamplePhoto(
                person_id=person.id,
                filename="crop.jpg",
                sha256="sample-sha",
                object_key="samples/crop.jpg",
                status="ready",
                source_type="gallery_face",
                source_gallery_photo_id=photo.id,
            )
        )
        db.commit()
        face = FaceRecord(
            gallery_photo_id=photo.id,
            bbox_left=0,
            bbox_top=0,
            bbox_right=100,
            bbox_bottom=100,
            needs_review=False,
        )
        service = PictureService.__new__(PictureService)

        with pytest.raises(ValueError, match="已经加入过"):
            service.promote_gallery_face_to_sample(db, photo, face, person)


def test_gallery_face_crop_box_stays_square_at_image_edge() -> None:
    face = FaceRecord(bbox_left=0, bbox_top=5, bbox_right=40, bbox_bottom=45, needs_review=False)

    box = PictureService._square_face_crop_box(face, 100, 80, 2.0)

    assert box == (0, 0, 80, 80)


def test_gallery_face_crop_applies_exif_orientation_after_raw_coordinate_crop() -> None:
    image = Image.new("RGB", (120, 80), "red")
    exif = image.getexif()
    exif[274] = 6
    source = BytesIO()
    image.save(source, format="JPEG", exif=exif)
    face = FaceRecord(bbox_left=20, bbox_top=20, bbox_right=60, bbox_bottom=50, needs_review=False)
    service = PictureService.__new__(PictureService)

    crop = Image.open(BytesIO(service._gallery_face_crop(source.getvalue(), face, 2.0)))

    assert crop.size == (80, 80)


def test_gallery_sample_promotion_retries_larger_crop_and_reuses_detection() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    image = Image.new("RGB", (300, 300), "white")
    source = BytesIO()
    image.save(source, format="JPEG")
    detected = DetectedFace((20, 20, 100, 100), 0.9, np.ones(512, dtype=np.float32), 80, 90, 0)

    class FakeStorage:
        def get_bytes(self, _object_key: str) -> bytes:
            return source.getvalue()

    class FakeFaceService:
        def __init__(self) -> None:
            self.calls = 0

        def detect_faces(self, _payload: bytes) -> list[DetectedFace]:
            self.calls += 1
            return [] if self.calls == 1 else [detected]

    with Session(engine) as db:
        person = Person(name="测试人物", display_name="测试人物", is_unknown=False)
        photo = GalleryPhoto(filename="gallery.jpg", sha256="gallery-sha", object_key="gallery/object.jpg", is_rich_text=False)
        db.add_all([person, photo])
        db.flush()
        face = FaceRecord(
            gallery_photo_id=photo.id,
            bbox_left=100,
            bbox_top=100,
            bbox_right=140,
            bbox_bottom=140,
            needs_review=False,
        )
        db.add(face)
        db.commit()
        service = PictureService.__new__(PictureService)
        service.settings = Settings(face_sample_min_size=40)
        service.storage = FakeStorage()
        service.face_service = FakeFaceService()
        captured: dict[str, object] = {}

        def fake_add_person_samples(*args: object, **kwargs: object) -> list[SamplePhoto]:
            captured.update(kwargs)
            return [SamplePhoto(id=9, status="ready")]

        service.add_person_samples = fake_add_person_samples

        sample = service.promote_gallery_face_to_sample(db, photo, face, person)

        assert sample.id == 9
        assert service.face_service.calls == 2
        assert captured["prepared_faces"] == [[detected]]
