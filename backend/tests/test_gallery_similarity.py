from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GallerySimilarityFeature,
    GallerySimilarityGroup,
    GallerySimilarityGroupMember,
    GallerySimilarityScan,
    Person,
    Workspace,
)
from app.services.similarity import (
    DinoV2FeatureExtractor,
    GallerySimilarityScanner,
    SimilarityCandidate,
    cleanup_deleted_similarity_photos,
    complete_link_clusters,
    compute_mirrored_perceptual_hashes,
    compute_perceptual_features,
    cosine_similarity,
    hash_similarity,
    load_similarity_scan_overview,
    mark_similarity_scans_stale,
)
from tests.support.app_loader import load_test_main


def image_bytes(color: tuple[int, int, int], image_format: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format=image_format)
    return output.getvalue()


def asymmetric_image_bytes() -> bytes:
    image = Image.new("RGB", (96, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 8, 34, 55), fill="black")
    draw.ellipse((62, 13, 88, 39), fill="red")
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.calls: list[str] = []

    def get_bytes(self, object_key: str) -> bytes:
        self.calls.append(object_key)
        return self.objects[object_key]


class FakeVectorStore:
    def __init__(self) -> None:
        self.ensured = 0
        self.vectors: dict[str, np.ndarray] = {}
        self.deleted: list[str] = []

    def ensure_gallery_similarity_collection(self) -> None:
        self.ensured += 1

    def get_gallery_similarity_vectors(self, point_ids: list[str]) -> dict[str, np.ndarray]:
        assert self.ensured > 0
        return {point_id: self.vectors[point_id] for point_id in point_ids if point_id in self.vectors}

    def upsert_gallery_similarity_vector(self, *, photo_id: int, vector: np.ndarray, **_: object) -> str:
        point_id = f"photo-{photo_id}"
        self.vectors[point_id] = vector
        return point_id

    def delete_gallery_similarity_vectors(self, point_ids: list[str]) -> None:
        self.deleted.extend(point_ids)
        for point_id in point_ids:
            self.vectors.pop(point_id, None)


class FakeExtractor:
    device = "cuda"

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def encode(self, images: list[Image.Image]) -> list[np.ndarray]:
        self.batch_sizes.append(len(images))
        return [np.full(768, index + 1, dtype=np.float32) for index in range(len(images))]


def create_scope(db: Session, photo_count: int = 3) -> tuple[Workspace, Person, list[GalleryPhoto]]:
    workspace = Workspace(name="测试空间")
    db.add(workspace)
    db.flush()
    person = Person(workspace_id=workspace.id, name="person-a", display_name="人物甲")
    db.add(person)
    db.flush()
    photos: list[GalleryPhoto] = []
    for index in range(photo_count):
        photo = GalleryPhoto(
            workspace_id=workspace.id,
            filename=f"{index}.png",
            content_type="image/png",
            sha256=f"{index + 1:064x}",
            object_key=f"gallery/{index}.png",
            width=64,
            height=64,
            is_rich_text=index == photo_count - 1,
        )
        db.add(photo)
        db.flush()
        db.add(GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=person.id, source="manual"))
        photos.append(photo)
    db.commit()
    return workspace, person, photos


def test_similarity_math_and_complete_link_prevent_chain_merging() -> None:
    assert hash_similarity("ffff", "ffff") == 1.0
    assert hash_similarity("ffff", "0000") == 0.0
    assert cosine_similarity(np.array([1, 0]), np.array([1, 0])) == pytest.approx(1.0)
    clusters = complete_link_clusters(
        [1, 2, 3],
        [
            SimilarityCandidate(1, 2, 0.95),
            SimilarityCandidate(2, 3, 0.95),
            SimilarityCandidate(1, 3, 0.80),
        ],
        0.90,
    )
    assert [cluster.member_ids for cluster in clusters] == [(1, 2)]


def test_dinov2_reports_incomplete_local_model(tmp_path: Path) -> None:
    extractor = DinoV2FeatureExtractor(Settings(gallery_similarity_model_path=tmp_path))
    with pytest.raises(RuntimeError, match="本地模型文件不完整"):
        _ = extractor.device


def test_candidate_pairs_respect_cross_type_switch(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session)
    scanner = GallerySimilarityScanner(FakeStorage({}), FakeVectorStore(), Settings(), FakeExtractor())
    photo_map = {photo.id: photo for photo in photos}
    people = {photo.id: {person.id} for photo in photos}

    same_type = scanner._candidate_pairs(photo_map, people, include_cross_type=False)
    cross_type = scanner._candidate_pairs(photo_map, people, include_cross_type=True)

    assert same_type[person.id] == {(photos[0].id, photos[1].id)}
    assert len(cross_type[person.id]) == 3
    assert workspace.id is not None


def test_feature_generation_is_batched_and_reuses_qdrant_cache(db_session: Session) -> None:
    _, _, photos = create_scope(db_session)
    storage = FakeStorage({photo.object_key: image_bytes((photo.id * 30, 40, 50)) for photo in photos})
    vector_store = FakeVectorStore()
    extractor = FakeExtractor()
    scanner = GallerySimilarityScanner(
        storage,
        vector_store,
        Settings(gallery_similarity_batch_size=2, gallery_similarity_vector_dimension=768),
        extractor,
    )
    photo_map = {photo.id: photo for photo in photos}

    features, vectors = scanner._ensure_features(db_session, photo_map)
    first_storage_call_count = len(storage.calls)
    cached_features, cached_vectors = scanner._ensure_features(db_session, photo_map)

    assert extractor.batch_sizes == [2, 1]
    assert vector_store.ensured == 2
    assert len(features) == len(vectors) == 3
    assert len(cached_features) == len(cached_vectors) == 3
    assert all(feature.vector_ready for feature in features.values())
    assert len(storage.calls) == first_storage_call_count


def test_mirror_feature_uses_horizontal_flip_and_keeps_original_quality(db_session: Session) -> None:
    _, _, photos = create_scope(db_session, photo_count=1)
    payload = asymmetric_image_bytes()
    original = compute_perceptual_features(payload)
    image = Image.open(BytesIO(payload)).convert("RGB")
    mirrored = ImageOps.mirror(image)
    output = BytesIO()
    mirrored.save(output, format="PNG")
    expected_mirror = compute_perceptual_features(output.getvalue())
    image.close()
    mirrored.close()

    mirror_phash, mirror_dhash = compute_mirrored_perceptual_hashes(payload)
    scanner = GallerySimilarityScanner(
        FakeStorage({photos[0].object_key: payload}),
        FakeVectorStore(),
        Settings(),
        FakeExtractor(),
    )
    features, vectors = scanner._ensure_features(
        db_session,
        {photos[0].id: photos[0]},
        include_vectors=False,
    )
    feature = features[photos[0].id]

    assert (mirror_phash, mirror_dhash) == (expected_mirror.phash, expected_mirror.dhash)
    assert feature.quality_score == pytest.approx(original.quality_score)
    assert feature.blur_score == pytest.approx(original.blur_score)
    assert vectors == {}


def test_mirror_scan_requires_mirror_score_to_be_strictly_better(db_session: Session) -> None:
    _, person, photos = create_scope(db_session, photo_count=2)
    payload = image_bytes((120, 80, 40))
    scanner = GallerySimilarityScanner(
        FakeStorage({photo.object_key: payload for photo in photos}),
        FakeVectorStore(),
        Settings(gallery_similarity_near_threshold=0.92),
        FakeExtractor(),
    )
    pair = (photos[0].id, photos[1].id)
    features = {
        photos[0].id: GallerySimilarityFeature(
            gallery_photo_id=photos[0].id,
            phash="0" * 16,
            dhash="0" * 16,
            mirror_phash="f" * 16,
            mirror_dhash="f" * 16,
        ),
        photos[1].id: GallerySimilarityFeature(
            gallery_photo_id=photos[1].id,
            phash="f" * 16,
            dhash="f" * 16,
            mirror_phash="0" * 16,
            mirror_dhash="0" * 16,
        ),
    }

    near_scores, scene_scores = scanner._score_pairs(
        {person.id: {pair}},
        features,
        {},
        {photo.id: photo for photo in photos},
        None,
        "mirror",
    )
    assert near_scores[pair] == pytest.approx(1.0)
    assert scene_scores == {}

    features[photos[1].id].phash = "0" * 16
    features[photos[1].id].dhash = "0" * 16
    tied_scores, _ = scanner._score_pairs(
        {person.id: {pair}},
        features,
        {},
        {photo.id: photo for photo in photos},
        None,
        "mirror",
    )
    assert tied_scores == {}


def test_mark_scans_stale_only_for_affected_person_scope(db_session: Session) -> None:
    workspace, person, _ = create_scope(db_session, photo_count=1)
    other = Person(workspace_id=workspace.id, name="person-b", display_name="人物乙")
    db_session.add(other)
    db_session.flush()
    scans = [
        GallerySimilarityScan(id="all", workspace_id=workspace.id, person_id=None, status="completed", feature_version="v1"),
        GallerySimilarityScan(id="affected", workspace_id=workspace.id, person_id=person.id, status="completed", feature_version="v1"),
        GallerySimilarityScan(id="other", workspace_id=workspace.id, person_id=other.id, status="completed", feature_version="v1"),
    ]
    db_session.add_all(scans)
    db_session.commit()

    assert mark_similarity_scans_stale(db_session, workspace.id, {person.id}) == 2
    db_session.commit()

    assert db_session.get(GallerySimilarityScan, "all").is_stale is True
    assert db_session.get(GallerySimilarityScan, "affected").is_stale is True
    assert db_session.get(GallerySimilarityScan, "other").is_stale is False


def test_scan_overview_returns_active_and_latest_completed_per_scope(db_session: Session) -> None:
    workspace, person, _ = create_scope(db_session, photo_count=1)
    other_workspace = Workspace(name="其他空间")
    db_session.add(other_workspace)
    db_session.flush()
    now = datetime.utcnow()
    scans = [
        GallerySimilarityScan(
            id="old-same-scope",
            workspace_id=workspace.id,
            person_id=None,
            include_cross_type=True,
            status="completed",
            feature_version="v1",
            completed_at=now - timedelta(hours=3),
            created_at=now - timedelta(hours=4),
        ),
        GallerySimilarityScan(
            id="latest-same-scope",
            workspace_id=workspace.id,
            person_id=None,
            include_cross_type=True,
            status="completed",
            is_stale=True,
            feature_version="v1",
            completed_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=2),
        ),
        GallerySimilarityScan(
            id="person-result",
            workspace_id=workspace.id,
            person_id=person.id,
            include_cross_type=False,
            status="completed",
            feature_version="v1",
            completed_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=3),
        ),
        GallerySimilarityScan(
            id="failed-newer",
            workspace_id=workspace.id,
            person_id=None,
            include_cross_type=True,
            status="failed",
            feature_version="v1",
            created_at=now,
        ),
        GallerySimilarityScan(
            id="active",
            workspace_id=workspace.id,
            person_id=person.id,
            include_cross_type=True,
            status="running",
            feature_version="v1",
            created_at=now,
        ),
        GallerySimilarityScan(
            id="other-workspace",
            workspace_id=other_workspace.id,
            person_id=None,
            include_cross_type=False,
            status="completed",
            feature_version="v1",
            completed_at=now + timedelta(hours=1),
            created_at=now,
        ),
    ]
    db_session.add_all(scans)
    db_session.commit()

    active, results = load_similarity_scan_overview(db_session, workspace.id)

    assert active is not None and active.id == "active"
    assert [scan.id for scan in results] == ["latest-same-scope", "person-result"]
    assert results[0].is_stale is True
    assert all(scan.workspace_id == workspace.id for scan in results)


def test_dismissed_similarity_group_is_filtered_from_scan_results(db_session: Session) -> None:
    module = load_test_main()
    workspace, person, _ = create_scope(db_session, photo_count=1)
    scan = GallerySimilarityScan(
        id="scan-review-status",
        workspace_id=workspace.id,
        person_id=person.id,
        status="completed",
        feature_version="v1",
    )
    db_session.add(scan)
    db_session.flush()
    pending_group = GallerySimilarityGroup(
        scan_id=scan.id,
        ordinal=1,
        tier="near_duplicate",
        min_score=0.95,
        average_score=0.97,
    )
    dismissed_group = GallerySimilarityGroup(
        scan_id=scan.id,
        ordinal=2,
        tier="near_duplicate",
        review_status="dismissed",
        min_score=0.94,
        average_score=0.96,
    )
    db_session.add_all([pending_group, dismissed_group])
    db_session.commit()
    current = SimpleNamespace(workspace_id=workspace.id)

    result = module.list_gallery_similarity_groups(
        scan_id=scan.id,
        tier="near_duplicate",
        offset=0,
        limit=20,
        db=db_session,
        current=current,
    )

    assert result.total == 1
    assert [group.id for group in result.items] == [pending_group.id]
    assert result.items[0].review_status == "pending"

    updated = module.update_gallery_similarity_group(
        scan_id=scan.id,
        group_id=pending_group.id,
        payload=module.GallerySimilarityGroupUpdate(review_status="dismissed"),
        db=db_session,
        current=current,
    )
    refreshed = module.list_gallery_similarity_groups(
        scan_id=scan.id,
        tier="near_duplicate",
        offset=0,
        limit=20,
        db=db_session,
        current=current,
    )

    assert updated.review_status == "dismissed"
    assert refreshed.total == 0
    assert refreshed.items == []


def test_cleanup_deleted_photo_recommends_best_remaining_member(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session)
    scan = GallerySimilarityScan(
        id="scan-cleanup",
        workspace_id=workspace.id,
        person_id=person.id,
        status="completed",
        feature_version="v1",
    )
    db_session.add(scan)
    db_session.flush()
    group = GallerySimilarityGroup(scan_id=scan.id, ordinal=1, tier="near_duplicate", min_score=0.95, average_score=0.97)
    db_session.add(group)
    db_session.flush()
    for index, photo in enumerate(photos):
        db_session.add(
            GallerySimilarityFeature(
                gallery_photo_id=photo.id,
                workspace_id=workspace.id,
                sha256=photo.sha256,
                feature_version="v1",
                phash="ffff",
                dhash="ffff",
                blur_score=10,
                quality_score=float(index + 1),
                vector_point_id=f"photo-{photo.id}",
                vector_ready=True,
            )
        )
        db_session.add(
            GallerySimilarityGroupMember(
                group_id=group.id,
                gallery_photo_id=photo.id,
                score_to_representative=0.95,
                quality_score=float(index + 1),
                recommended_keep=index == 2,
            )
        )
    db_session.commit()
    vector_store = FakeVectorStore()

    cleanup_deleted_similarity_photos(db_session, vector_store, [photos[2].id])
    db_session.flush()
    members = db_session.scalars(
        select(GallerySimilarityGroupMember)
        .where(GallerySimilarityGroupMember.group_id == group.id)
        .order_by(GallerySimilarityGroupMember.quality_score.desc())
    ).all()

    assert vector_store.deleted == [f"photo-{photos[2].id}"]
    assert [member.gallery_photo_id for member in members] == [photos[1].id, photos[0].id]
    assert [member.recommended_keep for member in members] == [True, False]
    assert db_session.get(GallerySimilarityScan, scan.id).group_count == 1

    cleanup_deleted_similarity_photos(db_session, vector_store, [photos[1].id])
    db_session.flush()
    assert db_session.scalar(select(GallerySimilarityGroup).where(GallerySimilarityGroup.id == group.id)) is None
    assert db_session.get(GallerySimilarityScan, scan.id).group_count == 0


def test_scan_skips_photo_deleted_before_result_publish(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session)
    storage = FakeStorage({photo.object_key: image_bytes((40, 50, 60)) for photo in photos})
    scanner = GallerySimilarityScanner(
        storage,
        FakeVectorStore(),
        Settings(gallery_similarity_vector_dimension=768),
        FakeExtractor(),
    )
    scan = GallerySimilarityScan(
        id="scan-delete-during-publish",
        workspace_id=workspace.id,
        person_id=person.id,
        include_cross_type=True,
        status="running",
        feature_version="v1",
    )
    db_session.add(scan)
    db_session.commit()
    deleted = False

    def progress(value: float, _: str) -> None:
        nonlocal deleted
        if value < 0.91 or deleted:
            return
        db_session.execute(delete(GalleryPhoto).where(GalleryPhoto.id == photos[2].id))
        db_session.commit()
        deleted = True

    scanner.run_scan(db_session, scan, progress)
    db_session.commit()

    groups = db_session.scalars(
        select(GallerySimilarityGroup).where(GallerySimilarityGroup.scan_id == scan.id)
    ).all()
    member_photo_ids = {
        member.gallery_photo_id
        for group in groups
        for member in group.members
    }
    assert deleted is True
    assert scan.photo_count == 2
    assert scan.group_count == 1
    assert photos[2].id not in member_photo_ids
    assert member_photo_ids == {photos[0].id, photos[1].id}
