from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageOps
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    FaceRecord,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GallerySimilarityFeature,
    GallerySimilarityGroup,
    GallerySimilarityGroupMember,
    GallerySimilarityGroupPair,
    GallerySimilarityScan,
    Person,
    Workspace,
)
from app.services.similarity import (
    DinoV2FeatureExtractor,
    GallerySimilarityScanner,
    SimilarityCandidate,
    assess_primary_face,
    build_normal_near_duplicate_auto_delete_plan,
    choose_quality_recommendation,
    cleanup_deleted_similarity_photos,
    complete_link_clusters,
    compose_group_quality_scores,
    compute_mirrored_perceptual_hashes,
    compute_perceptual_features,
    cosine_similarity,
    derive_group_auto_clusters,
    hash_similarity,
    load_similarity_scan_overview,
    mark_similarity_scans_stale,
    select_exact_mirror_auto_delete_photo_ids,
    select_normal_near_duplicate_auto_delete_photo_ids,
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

    def remove_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


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


def test_quality_score_does_not_depend_on_encoded_file_size() -> None:
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    for offset in range(0, 256, 16):
        draw.line((0, offset, 255, 255 - offset), fill=(offset, 60, 180), width=3)
    compact = BytesIO()
    large = BytesIO()
    image.save(compact, format="PNG", compress_level=9)
    image.save(large, format="PNG", compress_level=0)
    image.close()

    compact_features = compute_perceptual_features(compact.getvalue())
    large_features = compute_perceptual_features(large.getvalue())

    assert len(compact.getvalue()) < len(large.getvalue())
    assert compact_features.quality_score == large_features.quality_score


def test_quality_recommendation_requires_minimum_margin() -> None:
    close = choose_quality_recommendation({"small": 78.0, "large": 80.999}, 3.0)
    clear = choose_quality_recommendation({"small": 78.0, "large": 81.0}, 3.0)

    assert close.recommended_id is None
    assert close.status == "close_quality"
    assert clear.recommended_id == "large"
    assert clear.status == "recommended"


def test_group_quality_uses_faces_only_for_same_dominant_face() -> None:
    face_a = np.array([1.0, 0.0], dtype=np.float32).tobytes()
    face_a_near = np.array([0.99, 0.01], dtype=np.float32).tobytes()
    face_b = np.array([0.0, 1.0], dtype=np.float32).tobytes()

    weighted, enabled = compose_group_quality_scores(
        {1: (70.0, 90.0, face_a, True), 2: (80.0, 60.0, face_a_near, True)},
        0.5,
    )
    fallback, fallback_enabled = compose_group_quality_scores(
        {1: (70.0, 90.0, face_a, True), 2: (80.0, 60.0, face_b, True)},
        0.5,
    )

    assert enabled is True
    assert weighted == pytest.approx({1: 79.0, 2: 71.0})
    assert fallback_enabled is False
    assert fallback == {1: 70.0, 2: 80.0}


def test_primary_face_rejects_ambiguous_crowd() -> None:
    payload = image_bytes((120, 100, 80))
    detections = [
        SimpleNamespace(score=0.9, bbox=(4, 4, 44, 54), face_size=40, embedding=np.array([1.0, 0.0])),
        SimpleNamespace(score=0.9, bbox=(20, 8, 60, 56), face_size=40, embedding=np.array([0.0, 1.0])),
    ]

    assessment = assess_primary_face(payload, detections, Settings())

    assert assessment.dominant is False
    assert assessment.quality_score is None
    assert assessment.embedding is None


def test_gallery_quality_uses_only_the_single_confirmed_group_person(db_session: Session) -> None:
    _, person, photos = create_scope(db_session, photo_count=2)
    for photo in photos:
        db_session.add(
            FaceRecord(
                gallery_photo_id=photo.id,
                matched_person_id=person.id,
                bbox_left=0,
                bbox_top=0,
                bbox_right=64,
                bbox_bottom=64,
                detection_score=0.9,
                face_size=64,
                needs_review=False,
            )
        )
    db_session.flush()
    scanner = GallerySimilarityScanner(
        FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos}),
        FakeVectorStore(),
        Settings(),
        FakeExtractor(),
    )
    features = {
        photos[0].id: GallerySimilarityFeature(gallery_photo_id=photos[0].id, quality_score=60.0),
        photos[1].id: GallerySimilarityFeature(gallery_photo_id=photos[1].id, quality_score=70.0),
    }

    weighted, face_scores, enabled = scanner._group_quality_scores(
        db_session,
        {photo.id: photo for photo in photos},
        features,
        tuple(photo.id for photo in photos),
        [person.id],
    )
    fallback, fallback_face_scores, fallback_enabled = scanner._group_quality_scores(
        db_session,
        {photo.id: photo for photo in photos},
        features,
        tuple(photo.id for photo in photos),
        [person.id, person.id + 1],
    )

    assert enabled is True
    assert all(score is not None for score in face_scores.values())
    assert weighted != {photos[0].id: 60.0, photos[1].id: 70.0}
    assert fallback_enabled is False
    assert fallback_face_scores == {photos[0].id: None, photos[1].id: None}
    assert fallback == {photos[0].id: 60.0, photos[1].id: 70.0}


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


def test_exact_mirror_auto_delete_prefers_recommendation_then_unique_largest_file(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session, photo_count=9)
    for photo, size_bytes in zip(photos, [900, 700, 500, 400, 200, 100, 100, 80, 60], strict=True):
        photo.size_bytes = size_bytes
    scan = GallerySimilarityScan(
        id="scan-exact-mirror-auto-delete",
        workspace_id=workspace.id,
        person_id=person.id,
        scan_type="mirror",
        status="completed",
        feature_version="v1",
    )
    db_session.add(scan)
    db_session.flush()
    groups = [
        GallerySimilarityGroup(scan_id=scan.id, ordinal=1, tier="near_duplicate", min_score=1.0, average_score=1.0),
        GallerySimilarityGroup(scan_id=scan.id, ordinal=2, tier="near_duplicate", min_score=1.0, average_score=1.0),
        GallerySimilarityGroup(scan_id=scan.id, ordinal=3, tier="near_duplicate", min_score=1.0, average_score=1.0),
        GallerySimilarityGroup(scan_id=scan.id, ordinal=4, tier="near_duplicate", min_score=0.99, average_score=0.99),
    ]
    db_session.add_all(groups)
    db_session.flush()
    memberships = [
        (groups[0], photos[0], True),
        (groups[0], photos[1], False),
        (groups[0], photos[2], False),
        (groups[1], photos[3], False),
        (groups[1], photos[4], False),
        (groups[2], photos[5], False),
        (groups[2], photos[6], False),
        (groups[3], photos[7], False),
        (groups[3], photos[8], False),
    ]
    db_session.add_all(
        GallerySimilarityGroupMember(
            group_id=group.id,
            gallery_photo_id=photo.id,
            score_to_representative=group.min_score,
            quality_score=1.0,
            recommended_keep=recommended_keep,
        )
        for group, photo, recommended_keep in memberships
    )
    db_session.commit()

    deleted_ids = select_exact_mirror_auto_delete_photo_ids(db_session, scan)

    assert deleted_ids == [photos[1].id, photos[2].id, photos[4].id]


FULL_HASH = "f" * 16
LOOSE_HASH = "0ff0" + "f" * 12  # 与全 1 哈希相差 8 位，平均感知相似度约 0.9375，低于自动整理阈值


def add_normal_scan(db_session: Session, workspace: Workspace, person: Person) -> GallerySimilarityScan:
    scan = GallerySimilarityScan(
        id="scan-normal-auto-delete",
        workspace_id=workspace.id,
        person_id=person.id,
        scan_type="normal",
        status="completed",
        feature_version="v1",
    )
    db_session.add(scan)
    db_session.flush()
    return scan


def add_normal_group(
    db_session: Session,
    scan: GallerySimilarityScan,
    ordinal: int,
    entries: list[tuple[GalleryPhoto, float]],
) -> GallerySimilarityGroup:
    group = GallerySimilarityGroup(scan_id=scan.id, ordinal=ordinal, tier="near_duplicate", min_score=1.0, average_score=1.0)
    db_session.add(group)
    db_session.flush()
    for photo, quality_score in entries:
        db_session.add(
            GallerySimilarityGroupMember(
                group_id=group.id,
                gallery_photo_id=photo.id,
                score_to_representative=1.0,
                quality_score=quality_score,
            )
        )
    return group


def add_normal_feature(db_session: Session, photo: GalleryPhoto, phash: str, dhash: str) -> None:
    db_session.add(
        GallerySimilarityFeature(
            gallery_photo_id=photo.id,
            workspace_id=photo.workspace_id,
            sha256=photo.sha256,
            feature_version="v1",
            phash=phash,
            dhash=dhash,
            blur_score=0.0,
            quality_score=70.0,
        )
    )


def test_normal_auto_delete_targets_identical_cluster_and_keeps_scattered_photo(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session, photo_count=5)
    for photo in photos:
        photo.size_bytes = 100
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    # 组 1：photo0 与 photo1 指纹完全一致（簇内删到剩一张），photo2 仅松散相似，作为散图保留。
    add_normal_group(db_session, scan, 1, [(photos[0], 90.0), (photos[1], 70.0), (photos[2], 80.0)])
    add_normal_feature(db_session, photos[0], FULL_HASH, FULL_HASH)
    add_normal_feature(db_session, photos[1], FULL_HASH, FULL_HASH)
    add_normal_feature(db_session, photos[2], FULL_HASH, LOOSE_HASH)
    # 组 2：两两感知相似度低于阈值，不产生簇。
    add_normal_group(db_session, scan, 2, [(photos[3], 85.0), (photos[4], 75.0)])
    add_normal_feature(db_session, photos[3], FULL_HASH, LOOSE_HASH)
    add_normal_feature(db_session, photos[4], LOOSE_HASH, LOOSE_HASH)
    db_session.commit()

    deleted_ids = select_normal_near_duplicate_auto_delete_photo_ids(db_session, scan, storage, Settings())

    assert deleted_ids == [photos[1].id]


def test_normal_auto_delete_falls_back_to_unique_largest_file_on_close_quality(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session, photo_count=2)
    photos[0].size_bytes = 500
    photos[1].size_bytes = 900
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    # 质量分差小于阈值，触发 close_quality：回退到保留唯一体积最大者。
    add_normal_group(db_session, scan, 1, [(photos[0], 80.0), (photos[1], 78.0)])
    for photo in photos:
        add_normal_feature(db_session, photo, FULL_HASH, FULL_HASH)
    db_session.commit()

    deleted_ids = select_normal_near_duplicate_auto_delete_photo_ids(db_session, scan, storage, Settings())

    assert deleted_ids == [photos[0].id]


def test_normal_auto_delete_skips_clusters_sharing_a_photo(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session, photo_count=3)
    for photo in photos:
        photo.size_bytes = 100
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    # 照片 1 同时属于两个组的不同簇（跨组重叠），相关簇全部跳过。
    add_normal_group(db_session, scan, 1, [(photos[0], 90.0), (photos[1], 70.0)])
    add_normal_group(db_session, scan, 2, [(photos[1], 70.0), (photos[2], 60.0)])
    for photo in photos:
        add_normal_feature(db_session, photo, FULL_HASH, FULL_HASH)
    db_session.commit()

    deleted_ids = select_normal_near_duplicate_auto_delete_photo_ids(db_session, scan, storage, Settings())

    assert deleted_ids == []

    plans = build_normal_near_duplicate_auto_delete_plan(db_session, scan, storage, Settings())
    assert [plan.skip_reason for plan in plans] == ["overlap", "overlap"]
    assert all(plan.retained_photo_id is None and plan.delete_photo_ids == () for plan in plans)


def test_derive_group_auto_clusters_threshold_ordering_and_scattered() -> None:
    clusters = derive_group_auto_clusters(
        [(1, 2, 0.99), (3, 4, 0.986), (5, 6, 0.985), (7, 8, 0.9849), (9, 9, 0.999)],
        0.985,
    )

    assert [(cluster.member_ids, cluster.min_score) for cluster in clusters] == [
        ((1, 2), 0.99),
        ((3, 4), 0.986),
        ((5, 6), 0.985),
    ]


def test_derive_group_auto_clusters_rejects_transitive_chain() -> None:
    # A~B、B~C 达阈值而 A~C 不达：严格完全连接下 C 不得经由 B 混入同簇。
    clusters = derive_group_auto_clusters(
        [(1, 2, 0.99), (2, 3, 0.99), (1, 3, 0.80)],
        0.985,
    )

    assert [(cluster.member_ids, cluster.min_score) for cluster in clusters] == [((1, 2), 0.99)]


def test_run_scan_persists_intra_group_pair_scores(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session, photo_count=3)
    storage = FakeStorage(
        {
            photos[0].object_key: image_bytes((10, 20, 30)),
            photos[1].object_key: image_bytes((10, 20, 30)),
            photos[2].object_key: image_bytes((200, 100, 50)),
        }
    )
    settings = Settings(gallery_similarity_vector_dimension=768)
    scanner = GallerySimilarityScanner(storage, FakeVectorStore(), settings, FakeExtractor())
    scan = GallerySimilarityScan(
        id="scan-pair-scores",
        workspace_id=workspace.id,
        person_id=person.id,
        include_cross_type=True,
        status="running",
        feature_version=settings.gallery_similarity_model_version,
    )
    db_session.add(scan)
    identical_hash = "f" * 16
    distinct_hash = "0f0f" * 4  # 与全 1 哈希相差 16 位，感知相似度 0.75，低于近重复阈值
    for photo, crafted_hash in (
        (photos[0], identical_hash),
        (photos[1], identical_hash),
        (photos[2], distinct_hash),
    ):
        db_session.add(
            GallerySimilarityFeature(
                gallery_photo_id=photo.id,
                workspace_id=workspace.id,
                sha256=photo.sha256,
                feature_version=settings.gallery_similarity_model_version,
                quality_version=settings.gallery_similarity_quality_version,
                phash=crafted_hash,
                dhash=crafted_hash,
                mirror_phash=crafted_hash,
                mirror_dhash=crafted_hash,
                blur_score=0.0,
                quality_score=70.0,
            )
        )
    db_session.commit()

    scanner.run_scan(db_session, scan, None)
    db_session.commit()

    near_groups = db_session.scalars(
        select(GallerySimilarityGroup).where(
            GallerySimilarityGroup.scan_id == scan.id,
            GallerySimilarityGroup.tier == "near_duplicate",
        )
    ).all()
    assert len(near_groups) == 1
    pair_rows = db_session.scalars(
        select(GallerySimilarityGroupPair).where(GallerySimilarityGroupPair.group_id == near_groups[0].id)
    ).all()
    expected_pair = tuple(sorted((photos[0].id, photos[1].id)))
    assert {(row.left_gallery_photo_id, row.right_gallery_photo_id): row.score for row in pair_rows} == {
        expected_pair: pytest.approx(1.0)
    }

    clusters = derive_group_auto_clusters(
        [(row.left_gallery_photo_id, row.right_gallery_photo_id, row.score) for row in pair_rows],
        settings.gallery_similarity_auto_delete_threshold,
    )
    assert [cluster.member_ids for cluster in clusters] == [expected_pair]

    # 回归防护：带成员、特征与两两分数的组列表读取必须走通。
    # 曾因 api 层漏导入 GallerySimilarityFeature 在此崩溃，而成员为空的旧测试无法暴露。
    module = load_test_main()
    read_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    page = module.list_gallery_similarity_groups(
        scan_id=scan.id,
        request=read_request,
        tier="near_duplicate",
        offset=0,
        limit=20,
        db=db_session,
        current=SimpleNamespace(workspace_id=workspace.id),
    )
    assert page.total == 1
    group_read = page.items[0]
    assert len(group_read.clusters) == 1
    assert group_read.clusters[0].member_photo_ids == list(expected_pair)
    cluster_index_by_photo = {member.photo.id: member.auto_cluster_index for member in group_read.members}
    assert all(cluster_index_by_photo[photo_id] == 1 for photo_id in expected_pair)


def test_normal_auto_delete_does_not_merge_transitive_pairs(db_session: Session, monkeypatch) -> None:
    import app.services.similarity as similarity_module

    workspace, person, photos = create_scope(db_session, photo_count=3)
    for photo in photos:
        photo.size_bytes = 100
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    add_normal_group(db_session, scan, 1, [(photos[0], 90.0), (photos[1], 70.0), (photos[2], 60.0)])
    for photo in photos:
        add_normal_feature(db_session, photo, FULL_HASH, FULL_HASH)
    db_session.commit()

    scores_by_pair = {
        tuple(sorted((photos[0].id, photos[1].id))): 0.99,
        tuple(sorted((photos[1].id, photos[2].id))): 0.99,
        tuple(sorted((photos[0].id, photos[2].id))): 0.90,
    }

    def fake_pair_score(left, right, *, load_orb_features):
        return scores_by_pair[tuple(sorted((left.gallery_photo_id, right.gallery_photo_id)))]

    monkeypatch.setattr(similarity_module, "near_duplicate_pair_score", fake_pair_score)

    plans = build_normal_near_duplicate_auto_delete_plan(db_session, scan, storage, Settings())

    # 只有 {photo0, photo1} 构成簇；photo2 与二者的直接分数不达阈值，不得经由传递混入，也不能被删。
    assert len(plans) == 1
    assert plans[0].member_ids == tuple(sorted((photos[0].id, photos[1].id)))
    assert plans[0].retained_photo_id == photos[0].id
    assert plans[0].delete_photo_ids == (photos[1].id,)
    assert select_normal_near_duplicate_auto_delete_photo_ids(db_session, scan, storage, Settings()) == [photos[1].id]


def test_normal_auto_delete_requires_perceptual_hash_floor(db_session: Session, monkeypatch) -> None:
    import app.services.similarity as similarity_module

    workspace, person, photos = create_scope(db_session, photo_count=2)
    for photo in photos:
        photo.size_bytes = 100
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    add_normal_group(db_session, scan, 1, [(photos[0], 90.0), (photos[1], 70.0)])
    # 纯哈希相似度约 0.875，低于门槛 0.96：即使 ORB 加成把综合分抬到 0.99，也不得视为肉眼相同。
    add_normal_feature(db_session, photos[0], FULL_HASH, FULL_HASH)
    add_normal_feature(db_session, photos[1], LOOSE_HASH, LOOSE_HASH)
    db_session.commit()

    monkeypatch.setattr(
        similarity_module,
        "near_duplicate_pair_score",
        lambda left, right, *, load_orb_features: 0.99,
    )

    plans = build_normal_near_duplicate_auto_delete_plan(db_session, scan, storage, Settings())

    assert plans == []
    assert select_normal_near_duplicate_auto_delete_photo_ids(db_session, scan, storage, Settings()) == []


def test_preview_normal_auto_delete_endpoint_returns_plan(db_session: Session) -> None:
    workspace, person, photos = create_scope(db_session, photo_count=2)
    for photo, size_bytes in zip(photos, [500, 900], strict=True):
        photo.size_bytes = size_bytes
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    add_normal_group(db_session, scan, 1, [(photos[0], 90.0), (photos[1], 70.0)])
    for photo in photos:
        add_normal_feature(db_session, photo, FULL_HASH, FULL_HASH)
    db_session.commit()

    module = load_test_main()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(),
                services=SimpleNamespace(similarity=SimpleNamespace(storage=storage)),
            )
        )
    )
    permissions = {field: False for field in module.PERMISSION_FIELDS}
    permissions["can_delete_gallery"] = True
    current = SimpleNamespace(workspace_id=workspace.id, role="member", membership=SimpleNamespace(**permissions))

    response = module.preview_normal_near_duplicate_auto_delete(scan.id, request, db=db_session, current=current)

    assert response.scan_id == scan.id
    assert response.deletable_count == 1
    assert response.skipped_cluster_count == 0
    assert len(response.clusters) == 1
    cluster = response.clusters[0]
    assert cluster.status == "ready"
    retained = [member for member in cluster.members if member.retained]
    dropped = [member for member in cluster.members if not member.retained]
    assert [member.photo_id for member in retained] == [photos[0].id]
    assert [member.photo_id for member in dropped] == [photos[1].id]
    assert dropped[0].thumbnail_url.startswith("/api/gallery/photos/")
    assert dropped[0].original_url.startswith("/api/gallery/photos/")


def test_auto_delete_endpoint_validates_explicit_photo_ids(db_session: Session) -> None:
    import app.api.gallery as gallery_api
    from app.schemas import GallerySimilarityAutoDeleteExecuteRequest
    from app.services.importer import PictureService

    workspace, person, photos = create_scope(db_session, photo_count=3)
    for photo in photos:
        photo.size_bytes = 100
    storage = FakeStorage({photo.object_key: image_bytes((120, 100, 80)) for photo in photos})
    scan = add_normal_scan(db_session, workspace, person)
    # 仅簇 {photo0, photo1}；photo2 为散图。
    add_normal_group(db_session, scan, 1, [(photos[0], 90.0), (photos[1], 70.0)])
    add_normal_feature(db_session, photos[0], FULL_HASH, FULL_HASH)
    add_normal_feature(db_session, photos[1], FULL_HASH, FULL_HASH)
    add_normal_feature(db_session, photos[2], FULL_HASH, LOOSE_HASH)
    db_session.commit()

    module = load_test_main()
    picture_service = PictureService(storage, None, FakeVectorStore(), None, Settings())
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(),
                services=SimpleNamespace(
                    similarity=SimpleNamespace(storage=storage),
                    pictures=picture_service,
                    storage=storage,
                ),
            )
        )
    )
    permissions = {field: False for field in module.PERMISSION_FIELDS}
    permissions["can_delete_gallery"] = True
    current = SimpleNamespace(workspace_id=workspace.id, role="member", membership=SimpleNamespace(**permissions))

    def call(payload):
        token = gallery_api._services_context.set(request.app.state.services)
        try:
            return gallery_api.auto_delete_exact_mirror_groups(
                scan.id,
                request,
                payload=payload,
                db=db_session,
                current=current,
            )
        finally:
            gallery_api._services_context.reset(token)

    # 越界：不属于任何 ready 簇的图片拒绝删除。
    with pytest.raises(HTTPException) as unknown_error:
        call(GallerySimilarityAutoDeleteExecuteRequest(delete_photo_ids=[987654]))
    assert unknown_error.value.status_code == 422

    # 整簇清空拒绝。
    with pytest.raises(HTTPException) as empty_error:
        call(GallerySimilarityAutoDeleteExecuteRequest(delete_photo_ids=[photos[0].id, photos[1].id]))
    assert empty_error.value.status_code == 422

    # 合法子集：只删簇内指定的图片，散图不受影响。
    response = call(GallerySimilarityAutoDeleteExecuteRequest(delete_photo_ids=[photos[1].id]))

    assert response.deleted == 1
    assert response.scan.auto_deleted_count == 1
    remaining_ids = set(
        db_session.scalars(select(GalleryPhoto.id).where(GalleryPhoto.workspace_id == workspace.id)).all()
    )
    assert remaining_ids == {photos[0].id, photos[2].id}


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
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=Settings())))

    result = module.list_gallery_similarity_groups(
        scan_id=scan.id,
        request=request,
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
        request=request,
        db=db_session,
        current=current,
    )
    refreshed = module.list_gallery_similarity_groups(
        scan_id=scan.id,
        request=request,
        tier="near_duplicate",
        offset=0,
        limit=20,
        db=db_session,
        current=current,
    )

    assert updated.review_status == "dismissed"
    assert refreshed.total == 0
    assert refreshed.items == []


def test_cleanup_deleted_photo_does_not_recommend_when_remaining_quality_is_close(db_session: Session) -> None:
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
    assert [member.recommended_keep for member in members] == [False, False]
    assert db_session.get(GallerySimilarityGroup, group.id).recommendation_status == "close_quality"
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
