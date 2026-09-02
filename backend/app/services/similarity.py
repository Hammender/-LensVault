from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.core.config import Settings
from app.models import (
    FaceRecord,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GallerySimilarityFeature,
    GallerySimilarityGroup,
    GallerySimilarityGroupMember,
    GallerySimilarityGroupPair,
    GallerySimilarityGroupPerson,
    GallerySimilarityScan,
    Person,
)
from app.services.qdrant import QdrantVectorStore
from app.services.storage import MinioStorage
from sqlalchemy import delete, func, insert, literal, select, text, update
from sqlalchemy.orm import Session


_dino_encode_lock = Lock()


@dataclass(frozen=True)
class PerceptualFeatures:
    phash: str
    dhash: str
    blur_score: float
    quality_score: float
    resolution_score: float
    sharpness_score: float
    artifact_score: float
    exposure_score: float


@dataclass(frozen=True)
class QualityRecommendation:
    recommended_id: int | str | None
    status: str


@dataclass(frozen=True)
class ImageQualityAssessment:
    overall_score: float
    resolution_score: float
    sharpness_score: float
    artifact_score: float
    exposure_score: float
    blur_score: float


@dataclass(frozen=True)
class PrimaryFaceAssessment:
    quality_score: float | None
    embedding: bytes | None
    dominant: bool


@dataclass(frozen=True)
class SimilarityCandidate:
    left_id: int
    right_id: int
    score: float


def load_similarity_scan_overview(
    db: Session,
    workspace_id: int,
) -> tuple[GallerySimilarityScan | None, list[GallerySimilarityScan]]:
    active = db.scalar(
        select(GallerySimilarityScan)
        .where(
            GallerySimilarityScan.workspace_id == workspace_id,
            GallerySimilarityScan.status.in_(("pending", "running")),
        )
        .order_by(GallerySimilarityScan.created_at.desc())
        .limit(1)
    )
    completed = db.scalars(
        select(GallerySimilarityScan)
        .where(
            GallerySimilarityScan.workspace_id == workspace_id,
            GallerySimilarityScan.status == "completed",
        )
        .order_by(
            GallerySimilarityScan.completed_at.desc(),
            GallerySimilarityScan.created_at.desc(),
        )
    ).all()
    latest_by_scope: dict[tuple[int | None, bool, str], GallerySimilarityScan] = {}
    for scan in completed:
        latest_by_scope.setdefault((scan.person_id, scan.include_cross_type, scan.scan_type), scan)
    return active, list(latest_by_scope.values())


@dataclass(frozen=True)
class SimilarityCluster:
    member_ids: tuple[int, ...]
    min_score: float
    average_score: float


@dataclass(frozen=True)
class OrbFeatures:
    keypoint_count: int
    descriptors: np.ndarray | None


def open_normalized_image(payload: bytes, max_edge: int | None = None) -> Image.Image:
    with Image.open(BytesIO(payload)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if max_edge is not None and max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return image


def ensure_perceptual_feature_dependencies() -> None:
    unavailable: list[str] = []
    for module_name, package_name in (("cv2", "opencv-python-headless"), ("imagehash", "ImageHash")):
        try:
            __import__(module_name)
        except Exception:
            unavailable.append(package_name)
    if unavailable:
        packages = "、".join(unavailable)
        raise RuntimeError(f"图片分析依赖不可用：{packages}。请在后端运行环境重新安装 requirements.txt。")


def assess_image_quality(image: Image.Image) -> ImageQualityAssessment:
    """计算有界技术质量分；文件体积不参与评分。"""
    ensure_perceptual_feature_dependencies()
    import cv2

    pixels = max(image.width * image.height, 1)
    analysis = image.copy()
    if max(analysis.size) > 1600:
        analysis.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    gray = cv2.cvtColor(np.asarray(analysis), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    analysis.close()

    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(sobel_x, sobel_y)
    mean_gradient = float(np.mean(gradient))
    sharpness = 1.0 - math.exp(-18.0 * mean_gradient)

    smoothed = cv2.GaussianBlur(gray, (0, 0), 1.0)
    residual = np.abs(gray - smoothed)
    low_detail = gradient <= float(np.percentile(gradient, 60))
    noise = float(np.mean(residual[low_detail])) if np.any(low_detail) else float(np.mean(residual))
    noise_quality = math.exp(-22.0 * noise)

    horizontal = np.abs(np.diff(gray, axis=1))
    vertical = np.abs(np.diff(gray, axis=0))
    boundary_parts = [horizontal[:, 7::8].ravel(), vertical[7::8, :].ravel()]
    interior_parts = [horizontal[:, 3::8].ravel(), vertical[3::8, :].ravel()]
    boundary = float(np.mean(np.concatenate([part for part in boundary_parts if part.size]))) if any(
        part.size for part in boundary_parts
    ) else 0.0
    interior = float(np.mean(np.concatenate([part for part in interior_parts if part.size]))) if any(
        part.size for part in interior_parts
    ) else boundary
    block_excess = max(0.0, boundary - interior)
    block_quality = math.exp(-24.0 * block_excess)
    artifact_quality = math.sqrt(noise_quality * block_quality)

    clipped_ratio = float(np.mean((gray <= 0.01) | (gray >= 0.99)))
    contrast = float(np.percentile(gray, 95) - np.percentile(gray, 5))
    exposure_quality = max(0.0, min(1.0, 0.65 * (1.0 - clipped_ratio) + 0.35 * min(1.0, contrast / 0.55)))
    resolution_quality = max(0.0, min(1.0, (math.log2(pixels) - 16.0) / 8.0))
    effective_detail = sharpness * artifact_quality
    overall = 100.0 * (
        0.25 * resolution_quality
        + 0.40 * effective_detail
        + 0.20 * artifact_quality
        + 0.15 * exposure_quality
    )
    blur_score = float(cv2.Laplacian(gray, cv2.CV_32F).var() * 255.0 * 255.0)
    return ImageQualityAssessment(
        overall_score=round(max(0.0, min(100.0, overall)), 3),
        resolution_score=round(100.0 * resolution_quality, 3),
        sharpness_score=round(100.0 * effective_detail, 3),
        artifact_score=round(100.0 * artifact_quality, 3),
        exposure_score=round(100.0 * exposure_quality, 3),
        blur_score=blur_score,
    )


def choose_quality_recommendation(
    scores: dict[int | str, float], minimum_margin: float
) -> QualityRecommendation:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
    if not ordered:
        return QualityRecommendation(None, "unavailable")
    if len(ordered) == 1:
        return QualityRecommendation(ordered[0][0], "recommended")
    if ordered[0][1] - ordered[1][1] < minimum_margin:
        return QualityRecommendation(None, "close_quality")
    return QualityRecommendation(ordered[0][0], "recommended")


def compose_group_quality_scores(
    entries: dict[int | str, tuple[float, float | None, bytes | None, bool]],
    face_threshold: float,
) -> tuple[dict[int | str, float], bool]:
    if not entries:
        return {}, False
    face_enabled = all(face_score is not None and embedding and dominant for _, face_score, embedding, dominant in entries.values())
    if face_enabled:
        vectors = {
            member_id: np.frombuffer(embedding or b"", dtype=np.float32)
            for member_id, (_, _, embedding, _) in entries.items()
        }
        vector_list = list(vectors.values())
        reference = vector_list[0]
        face_enabled = bool(reference.size) and all(
            left.shape == right.shape and cosine_similarity(left, right) >= face_threshold
            for index, left in enumerate(vector_list)
            for right in vector_list[index + 1 :]
        )
    scores = {
        member_id: (
            0.55 * overall_score + 0.45 * float(face_score)
            if face_enabled and face_score is not None
            else overall_score
        )
        for member_id, (overall_score, face_score, _embedding, _dominant) in entries.items()
    }
    return scores, face_enabled


def assess_primary_face(
    payload: bytes,
    detections: list[Any],
    settings: Settings,
) -> PrimaryFaceAssessment:
    image = open_normalized_image(payload)
    try:
        eligible: list[tuple[float, Any]] = []
        image_area = max(1.0, float(image.width * image.height))
        for face in detections:
            score = getattr(face, "score", None)
            bbox = getattr(face, "bbox", None)
            face_size = float(getattr(face, "face_size", 0.0) or 0.0)
            embedding = getattr(face, "embedding", None)
            if (
                bbox is None
                or embedding is None
                or score is None
                or float(score) < settings.face_sample_min_detection_score
                or face_size < settings.face_sample_min_size
            ):
                continue
            area = max(0.0, float(bbox[2] - bbox[0])) * max(0.0, float(bbox[3] - bbox[1]))
            if area / image_area >= 0.01:
                eligible.append((area, face))
        eligible.sort(key=lambda item: item[0], reverse=True)
        if not eligible or (len(eligible) > 1 and eligible[0][0] < eligible[1][0] * 1.5):
            return PrimaryFaceAssessment(None, None, False)
        face = eligible[0][1]
        bbox = face.bbox
        left = max(0, min(image.width - 1, int(math.floor(float(bbox[0])))))
        top = max(0, min(image.height - 1, int(math.floor(float(bbox[1])))))
        right = max(left + 1, min(image.width, int(math.ceil(float(bbox[2])))))
        bottom = max(top + 1, min(image.height, int(math.ceil(float(bbox[3])))))
        crop = image.crop((left, top, right, bottom))
        try:
            quality_score = assess_image_quality(crop).overall_score
        finally:
            crop.close()
        embedding = np.asarray(face.embedding, dtype=np.float32)
        norm = float(np.linalg.norm(embedding))
        if not norm:
            return PrimaryFaceAssessment(None, None, False)
        return PrimaryFaceAssessment(quality_score, (embedding / norm).astype(np.float32).tobytes(), True)
    finally:
        image.close()


def compute_perceptual_features_from_image(image: Image.Image) -> PerceptualFeatures:
    ensure_perceptual_feature_dependencies()
    import imagehash

    phash = str(imagehash.phash(image))
    dhash = str(imagehash.dhash(image))
    assessment = assess_image_quality(image)
    return PerceptualFeatures(
        phash=phash,
        dhash=dhash,
        blur_score=assessment.blur_score,
        quality_score=assessment.overall_score,
        resolution_score=assessment.resolution_score,
        sharpness_score=assessment.sharpness_score,
        artifact_score=assessment.artifact_score,
        exposure_score=assessment.exposure_score,
    )


def compute_perceptual_features(payload: bytes) -> PerceptualFeatures:
    image = open_normalized_image(payload)
    try:
        return compute_perceptual_features_from_image(image)
    finally:
        image.close()


def compute_mirrored_perceptual_hashes(payload: bytes) -> tuple[str, str]:
    ensure_perceptual_feature_dependencies()
    import imagehash

    image = open_normalized_image(payload)
    try:
        mirrored = ImageOps.mirror(image)
        try:
            return str(imagehash.phash(mirrored)), str(imagehash.dhash(mirrored))
        finally:
            mirrored.close()
    finally:
        image.close()


def hash_similarity(left: str, right: str) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    bit_count = len(left) * 4
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return max(0.0, 1.0 - distance / bit_count)


def compute_orb_features(payload: bytes, *, mirrored: bool = False) -> OrbFeatures:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV 未安装，无法执行近重复确认") from exc
    image = open_normalized_image(payload, max_edge=1024)
    if mirrored:
        mirrored_image = ImageOps.mirror(image)
        image.close()
        image = mirrored_image
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    image.close()
    orb = cv2.ORB_create(nfeatures=800)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    return OrbFeatures(keypoint_count=len(keypoints), descriptors=descriptors)


def orb_feature_similarity(left: OrbFeatures, right: OrbFeatures) -> float:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV 未安装，无法执行近重复确认") from exc
    if left.descriptors is None or right.descriptors is None or not left.keypoint_count or not right.keypoint_count:
        return 0.0
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(left.descriptors, right.descriptors)
    good = [match for match in matches if match.distance <= 48]
    denominator = max(1, min(left.keypoint_count, right.keypoint_count))
    return min(1.0, len(good) / denominator)


def orb_similarity(left_payload: bytes, right_payload: bytes) -> float:
    return orb_feature_similarity(compute_orb_features(left_payload), compute_orb_features(right_payload))


def near_duplicate_pair_score(
    left: GallerySimilarityFeature,
    right: GallerySimilarityFeature,
    *,
    load_orb_features: Any,
    mirrored: bool = False,
) -> float:
    """计算一对图片的近重复分数，扫描与自动整理共用同一打分口径。"""
    right_phash = right.mirror_phash if mirrored else right.phash
    right_dhash = right.mirror_dhash if mirrored else right.dhash
    if not right_phash or not right_dhash:
        return 0.0
    perceptual = (
        hash_similarity(left.phash, right_phash) + hash_similarity(left.dhash, right_dhash)
    ) / 2
    if perceptual < 0.82:
        return perceptual
    local_score = orb_feature_similarity(
        load_orb_features(left.gallery_photo_id, False),
        load_orb_features(right.gallery_photo_id, mirrored),
    )
    return max(perceptual, min(1.0, 0.85 + local_score * 0.15))


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left = np.asarray(left, dtype=np.float32)
    right = np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else 0.0


class DinoV2FeatureExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._processor: Any | None = None
        self._torch: Any | None = None
        self._device = "cpu"

    @property
    def device(self) -> str:
        self._ensure_loaded()
        return self._device

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        model_path = Path(self.settings.gallery_similarity_model_path)
        if not model_path.is_dir():
            raise RuntimeError(f"DINOv2 本地模型目录不存在：{model_path}")
        required_files = ("config.json", "preprocessor_config.json")
        missing_files = [filename for filename in required_files if not (model_path / filename).is_file()]
        has_weights = (model_path / "model.safetensors").is_file() or (model_path / "pytorch_model.bin").is_file()
        if missing_files or not has_weights:
            missing_description = "、".join(missing_files + ([] if has_weights else ["模型权重文件"]))
            raise RuntimeError(f"DINOv2 本地模型文件不完整，缺少：{missing_description}")
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel
        except ImportError as exc:
            raise RuntimeError("DINOv2 推理依赖缺失，请安装 CUDA 和 Transformers 依赖") from exc
        requested_device = self.settings.gallery_similarity_device.lower()
        self._device = "cuda" if requested_device.startswith("cuda") and torch.cuda.is_available() else "cpu"
        self._processor = AutoImageProcessor.from_pretrained(model_path, local_files_only=True)
        self._model = AutoModel.from_pretrained(model_path, local_files_only=True).eval().to(self._device)
        self._torch = torch

    def encode(self, images: list[Image.Image]) -> list[np.ndarray]:
        if not images:
            return []
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None and self._torch is not None
        batch_size = max(1, self.settings.gallery_similarity_batch_size)
        output: list[np.ndarray] = []
        offset = 0
        with _dino_encode_lock:
            while offset < len(images):
                current_size = min(batch_size, len(images) - offset)
                while True:
                    try:
                        batch = self._processor(images=images[offset : offset + current_size], return_tensors="pt")
                        batch = {key: value.to(self._device) for key, value in batch.items()}
                        with self._torch.inference_mode():
                            autocast_enabled = self._device == "cuda"
                            with self._torch.autocast(device_type=self._device, dtype=self._torch.float16, enabled=autocast_enabled):
                                vectors = self._model(**batch).last_hidden_state[:, 0, :]
                            vectors = self._torch.nn.functional.normalize(vectors.float(), dim=1).cpu().numpy()
                        if vectors.shape[1] != self.settings.gallery_similarity_vector_dimension:
                            raise RuntimeError(
                                f"DINOv2 输出维度为 {vectors.shape[1]}，预期 "
                                f"{self.settings.gallery_similarity_vector_dimension}"
                            )
                        output.extend(np.asarray(vector, dtype=np.float32) for vector in vectors)
                        offset += current_size
                        break
                    except self._torch.cuda.OutOfMemoryError:
                        if self._device != "cuda" or current_size == 1:
                            raise
                        self._torch.cuda.empty_cache()
                        current_size = max(1, current_size // 2)
        return output


def complete_link_clusters(
    member_ids: Iterable[int], candidates: Iterable[SimilarityCandidate], threshold: float
) -> list[SimilarityCluster]:
    scores: dict[tuple[int, int], float] = {}
    for candidate in candidates:
        pair = tuple(sorted((candidate.left_id, candidate.right_id)))
        scores[pair] = max(scores.get(pair, 0.0), candidate.score)

    ordered_ids = sorted(set(member_ids))
    clusters: list[list[int]] = []
    for member_id in ordered_ids:
        eligible: list[tuple[float, list[int]]] = []
        for cluster in clusters:
            member_scores = [scores.get(tuple(sorted((member_id, other_id))), 0.0) for other_id in cluster]
            if member_scores and min(member_scores) >= threshold:
                eligible.append((sum(member_scores) / len(member_scores), cluster))
        if not eligible:
            clusters.append([member_id])
        else:
            max(eligible, key=lambda item: item[0])[1].append(member_id)

    result: list[SimilarityCluster] = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        pair_scores = [
            scores[tuple(sorted((cluster[left], cluster[right])))]
            for left in range(len(cluster))
            for right in range(left + 1, len(cluster))
        ]
        result.append(
            SimilarityCluster(
                member_ids=tuple(cluster),
                min_score=min(pair_scores),
                average_score=sum(pair_scores) / len(pair_scores),
            )
        )
    return result


class GallerySimilarityScanner:
    def __init__(
        self,
        storage: MinioStorage,
        vector_store: QdrantVectorStore,
        settings: Settings,
        extractor: DinoV2FeatureExtractor | None = None,
        face_service: Any | None = None,
    ) -> None:
        self.storage = storage
        self.vector_store = vector_store
        self.settings = settings
        self.extractor = extractor or DinoV2FeatureExtractor(settings)
        self.face_service = face_service

    def _load_scope(
        self, db: Session, workspace_id: int, person_id: int | None
    ) -> tuple[dict[int, GalleryPhoto], dict[int, set[int]]]:
        query = (
            select(GalleryPhoto, GalleryPhotoPersonTag.person_id)
            .join(GalleryPhotoPersonTag, GalleryPhotoPersonTag.gallery_photo_id == GalleryPhoto.id)
            .where(GalleryPhoto.workspace_id == workspace_id)
        )
        if person_id is not None:
            query = query.where(GalleryPhotoPersonTag.person_id == person_id)
        photos: dict[int, GalleryPhoto] = {}
        people_by_photo: dict[int, set[int]] = {}
        for photo, linked_person_id in db.execute(query).all():
            photos[photo.id] = photo
            people_by_photo.setdefault(photo.id, set()).add(int(linked_person_id))
        return photos, people_by_photo

    def _ensure_features(
        self,
        db: Session,
        photos: dict[int, GalleryPhoto],
        progress: Any | None = None,
        *,
        include_vectors: bool = True,
    ) -> tuple[dict[int, GallerySimilarityFeature], dict[int, np.ndarray]]:
        version = self.settings.gallery_similarity_model_version
        quality_version = self.settings.gallery_similarity_quality_version
        cached = {
            feature.gallery_photo_id: feature
            for feature in db.scalars(
                select(GallerySimilarityFeature).where(GallerySimilarityFeature.gallery_photo_id.in_(photos))
            ).all()
        }
        features: dict[int, GallerySimilarityFeature] = {}
        vectors: dict[int, np.ndarray] = {}
        vector_ids: list[str] = []
        for photo_id, photo in photos.items():
            feature = cached.get(photo_id)
            base_changed = feature is None or feature.sha256 != photo.sha256 or feature.feature_version != version
            quality_changed = feature is None or feature.sha256 != photo.sha256 or feature.quality_version != quality_version
            if base_changed or quality_changed or not feature.mirror_phash or not feature.mirror_dhash:
                payload = self.storage.get_bytes(photo.object_key)
                perceptual = compute_perceptual_features(payload)
                mirror_phash, mirror_dhash = compute_mirrored_perceptual_hashes(payload)
                if feature is None:
                    feature = GallerySimilarityFeature(gallery_photo_id=photo_id)
                feature.workspace_id = photo.workspace_id
                feature.sha256 = photo.sha256
                feature.feature_version = version
                feature.phash = perceptual.phash
                feature.dhash = perceptual.dhash
                feature.mirror_phash = mirror_phash
                feature.mirror_dhash = mirror_dhash
                feature.blur_score = perceptual.blur_score
                feature.quality_score = perceptual.quality_score
                feature.quality_version = quality_version
                feature.resolution_score = perceptual.resolution_score
                feature.sharpness_score = perceptual.sharpness_score
                feature.artifact_score = perceptual.artifact_score
                feature.exposure_score = perceptual.exposure_score
                if quality_changed and self.face_service is not None:
                    try:
                        primary_face = assess_primary_face(
                            payload,
                            self.face_service.detect_faces(payload),
                            self.settings,
                        )
                    except Exception:
                        primary_face = PrimaryFaceAssessment(None, None, False)
                    feature.primary_face_quality_score = primary_face.quality_score
                    feature.primary_face_embedding = primary_face.embedding
                    feature.primary_face_dominant = primary_face.dominant
                if base_changed:
                    feature.vector_point_id = None
                    feature.vector_ready = False
                db.add(feature)
            features[photo_id] = feature
            if include_vectors and feature.vector_ready and feature.vector_point_id:
                vector_ids.append(feature.vector_point_id)
        db.flush()
        if not include_vectors:
            return features, vectors
        if photos:
            self.vector_store.ensure_gallery_similarity_collection()
        existing_vectors = self.vector_store.get_gallery_similarity_vectors(vector_ids)
        missing_ids: list[int] = []
        for photo_id, photo in photos.items():
            feature = features[photo_id]
            if feature.vector_point_id and feature.vector_point_id in existing_vectors:
                vectors[photo_id] = existing_vectors[feature.vector_point_id]
                continue
            missing_ids.append(photo_id)
        if missing_ids:
            device = self.extractor.device
            if progress is not None:
                message = "CUDA 不可用，已回退 CPU，扫描速度会明显降低" if device == "cpu" else "正在使用 CUDA 生成视觉特征"
                progress(0.08, message)
        batch_size = max(1, self.settings.gallery_similarity_batch_size)
        processed = 0
        for offset in range(0, len(missing_ids), batch_size):
            batch_ids = missing_ids[offset : offset + batch_size]
            images = [
                open_normalized_image(self.storage.get_bytes(photos[photo_id].object_key), max_edge=1024)
                for photo_id in batch_ids
            ]
            try:
                batch_vectors = self.extractor.encode(images)
            finally:
                for image in images:
                    image.close()
            for photo_id, vector in zip(batch_ids, batch_vectors, strict=True):
                photo = photos[photo_id]
                point_id = self.vector_store.upsert_gallery_similarity_vector(
                    workspace_id=photo.workspace_id,
                    photo_id=photo.id,
                    sha256=photo.sha256,
                    is_rich_text=photo.is_rich_text,
                    feature_version=version,
                    vector=vector,
                )
                feature = features[photo_id]
                feature.vector_point_id = point_id
                feature.vector_ready = True
                vectors[photo_id] = vector
                db.add(feature)
                processed += 1
            if progress is not None:
                progress(0.1 + 0.45 * (processed / len(missing_ids)), f"正在生成视觉特征 {processed}/{len(missing_ids)}")
        db.flush()
        return features, vectors

    def ensure_features(
        self,
        db: Session,
        photos: dict[int, GalleryPhoto],
        progress: Any | None = None,
        *,
        include_vectors: bool = True,
    ) -> tuple[dict[int, GallerySimilarityFeature], dict[int, np.ndarray]]:
        """为其他受控工作流复用图库相似特征缓存和 Qdrant 向量。"""
        return self._ensure_features(db, photos, progress, include_vectors=include_vectors)

    def _group_quality_scores(
        self,
        db: Session,
        photos: dict[int, GalleryPhoto],
        features: dict[int, GallerySimilarityFeature],
        member_ids: tuple[int, ...],
        person_ids: list[int],
    ) -> tuple[dict[int, float], dict[int, float | None], bool]:
        overall_scores = {photo_id: float(features[photo_id].quality_score) for photo_id in member_ids}
        if len(person_ids) != 1:
            return overall_scores, {photo_id: None for photo_id in member_ids}, False
        person_id = person_ids[0]
        faces = db.scalars(
            select(FaceRecord).where(
                FaceRecord.gallery_photo_id.in_(member_ids),
                FaceRecord.matched_person_id == person_id,
                FaceRecord.needs_review.is_(False),
                FaceRecord.detection_score >= self.settings.face_sample_min_detection_score,
                FaceRecord.face_size >= self.settings.face_sample_min_size,
            )
        ).all()
        faces_by_photo: dict[int, list[FaceRecord]] = {}
        for face in faces:
            if face.gallery_photo_id is not None:
                faces_by_photo.setdefault(face.gallery_photo_id, []).append(face)
        if any(photo_id not in faces_by_photo for photo_id in member_ids):
            return overall_scores, {photo_id: None for photo_id in member_ids}, False

        face_scores: dict[int, float | None] = {}
        for photo_id in member_ids:
            face = max(
                faces_by_photo[photo_id],
                key=lambda item: (item.face_size or 0.0, item.detection_score or 0.0),
            )
            image = open_normalized_image(self.storage.get_bytes(photos[photo_id].object_key))
            try:
                left = max(0, min(image.width - 1, int(math.floor(face.bbox_left))))
                top = max(0, min(image.height - 1, int(math.floor(face.bbox_top))))
                right = max(left + 1, min(image.width, int(math.ceil(face.bbox_right))))
                bottom = max(top + 1, min(image.height, int(math.ceil(face.bbox_bottom))))
                crop = image.crop((left, top, right, bottom))
                try:
                    face_scores[photo_id] = assess_image_quality(crop).overall_score
                finally:
                    crop.close()
            finally:
                image.close()
        combined = {
            photo_id: 0.55 * overall_scores[photo_id] + 0.45 * float(face_scores[photo_id])
            for photo_id in member_ids
        }
        return combined, face_scores, True

    def _candidate_pairs(
        self,
        photos: dict[int, GalleryPhoto],
        people_by_photo: dict[int, set[int]],
        include_cross_type: bool,
    ) -> dict[int, set[tuple[int, int]]]:
        photos_by_person: dict[int, list[int]] = {}
        for photo_id, person_ids in people_by_photo.items():
            for person_id in person_ids:
                photos_by_person.setdefault(person_id, []).append(photo_id)
        result: dict[int, set[tuple[int, int]]] = {}
        for person_id, photo_ids in photos_by_person.items():
            pairs: set[tuple[int, int]] = set()
            for left_index, left_id in enumerate(sorted(set(photo_ids))):
                for right_id in sorted(set(photo_ids))[left_index + 1 :]:
                    if not include_cross_type and photos[left_id].is_rich_text != photos[right_id].is_rich_text:
                        continue
                    pairs.add((left_id, right_id))
            result[person_id] = pairs
        return result

    def _score_pairs(
        self,
        pairs_by_person: dict[int, set[tuple[int, int]]],
        features: dict[int, GallerySimilarityFeature],
        vectors: dict[int, np.ndarray],
        photos: dict[int, GalleryPhoto],
        progress: Any | None,
        scan_type: str = "normal",
    ) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
        unique_pairs = sorted(set().union(*pairs_by_person.values()) if pairs_by_person else set())
        near_scores: dict[tuple[int, int], float] = {}
        scene_scores: dict[tuple[int, int], float] = {}
        orb_cache: OrderedDict[tuple[int, bool], OrbFeatures] = OrderedDict()

        def get_orb_features(photo_id: int, *, mirrored: bool = False) -> OrbFeatures:
            cache_key = (photo_id, mirrored)
            cached = orb_cache.pop(cache_key, None)
            if cached is not None:
                orb_cache[cache_key] = cached
                return cached
            feature = compute_orb_features(
                self.storage.get_bytes(photos[photo_id].object_key),
                mirrored=mirrored,
            )
            orb_cache[cache_key] = feature
            if len(orb_cache) > 256:
                orb_cache.popitem(last=False)
            return feature

        def near_score(left_id: int, right_id: int, *, mirrored: bool = False) -> float:
            def orb_loader(photo_id: int, use_mirrored: bool) -> OrbFeatures:
                return get_orb_features(photo_id, mirrored=use_mirrored)

            return near_duplicate_pair_score(
                features[left_id],
                features[right_id],
                load_orb_features=orb_loader,
                mirrored=mirrored,
            )

        for index, pair in enumerate(unique_pairs):
            left_id, right_id = pair
            direct_score = near_score(left_id, right_id)
            if scan_type == "mirror":
                mirrored_score = near_score(left_id, right_id, mirrored=True)
                if (
                    mirrored_score >= self.settings.gallery_similarity_near_threshold
                    and mirrored_score > direct_score
                ):
                    near_scores[pair] = mirrored_score
            elif direct_score >= self.settings.gallery_similarity_near_threshold:
                near_scores[pair] = direct_score
            else:
                scene_score = cosine_similarity(vectors[left_id], vectors[right_id])
                if scene_score >= self.settings.gallery_similarity_scene_threshold:
                    scene_scores[pair] = scene_score
            if progress is not None and unique_pairs and (index % 100 == 0 or index + 1 == len(unique_pairs)):
                progress(0.55 + 0.35 * ((index + 1) / len(unique_pairs)), f"正在匹配候选 {index + 1}/{len(unique_pairs)}")
        return near_scores, scene_scores

    def run_scan(self, db: Session, scan: GallerySimilarityScan, progress: Any | None = None) -> None:
        photos, people_by_photo = self._load_scope(db, int(scan.workspace_id), scan.person_id)
        scan.photo_count = len(photos)
        if progress is not None:
            progress(0.05, f"找到 {len(photos)} 张带人物标签的图片")
        features, vectors = self._ensure_features(
            db,
            photos,
            progress,
            include_vectors=scan.scan_type == "normal",
        )
        pairs_by_person = self._candidate_pairs(photos, people_by_photo, scan.include_cross_type)
        unique_pairs = set().union(*pairs_by_person.values()) if pairs_by_person else set()
        scan.candidate_pair_count = len(unique_pairs)
        near_scores, scene_scores = self._score_pairs(
            pairs_by_person,
            features,
            vectors,
            photos,
            progress,
            scan.scan_type,
        )

        group_specs: dict[tuple[str, tuple[int, ...]], tuple[SimilarityCluster, set[int]]] = {}
        score_tiers = [("near_duplicate", near_scores, self.settings.gallery_similarity_near_threshold)]
        if scan.scan_type == "normal":
            score_tiers.append(("same_scene", scene_scores, self.settings.gallery_similarity_scene_threshold))
        for tier, scores, threshold in score_tiers:
            for person_id, pairs in pairs_by_person.items():
                candidates = [
                    SimilarityCandidate(left, right, scores[(left, right)])
                    for left, right in pairs
                    if (left, right) in scores
                ]
                if not candidates:
                    continue
                member_ids = {item.left_id for item in candidates} | {item.right_id for item in candidates}
                for cluster in complete_link_clusters(member_ids, candidates, threshold):
                    key = (tier, cluster.member_ids)
                    if key in group_specs:
                        group_specs[key][1].add(person_id)
                    else:
                        group_specs[key] = (cluster, {person_id})

        if progress is not None:
            progress(0.91, f"正在发布 {len(group_specs)} 个相似组")

        # 特征计算阶段可能耗时数分钟。发布前先结束此前的读取事务，再用很短的
        # SQLite 写事务锁住“重新校验 -> 写入结果”窗口，避免已删除图片触发外键失败。
        if db.in_transaction():
            db.commit()
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

        scoped_photo_ids = set(photos)
        live_photo_ids = set(
            db.scalars(
                select(GalleryPhoto.id).where(
                    GalleryPhoto.workspace_id == scan.workspace_id,
                    GalleryPhoto.id.in_(scoped_photo_ids),
                )
            ).all()
        )
        live_person_ids = set(
            db.scalars(
                select(Person.id).where(
                    Person.workspace_id == scan.workspace_id,
                    Person.id.in_({person_id for _, person_ids in group_specs.values() for person_id in person_ids}),
                )
            ).all()
        )
        scan.photo_count = len(live_photo_ids)
        scan.candidate_pair_count = sum(
            left_id in live_photo_ids and right_id in live_photo_ids
            for left_id, right_id in unique_pairs
        )

        old_scans = db.scalars(
            select(GallerySimilarityScan).where(
                GallerySimilarityScan.workspace_id == scan.workspace_id,
                GallerySimilarityScan.person_id.is_(None) if scan.person_id is None else GallerySimilarityScan.person_id == scan.person_id,
                GallerySimilarityScan.include_cross_type == scan.include_cross_type,
                GallerySimilarityScan.scan_type == scan.scan_type,
                GallerySimilarityScan.status == "completed",
                GallerySimilarityScan.id != scan.id,
            )
        ).all()
        for old_scan in old_scans:
            db.delete(old_scan)
        db.execute(delete(GallerySimilarityGroup).where(GallerySimilarityGroup.scan_id == scan.id))
        published_group_count = 0
        for (tier, member_ids), (cluster, person_ids) in sorted(
            group_specs.items(), key=lambda item: (item[0][0], -len(item[0][1]), item[0][1])
        ):
            live_member_ids = tuple(photo_id for photo_id in member_ids if photo_id in live_photo_ids)
            live_group_person_ids = sorted(person_id for person_id in person_ids if person_id in live_person_ids)
            if len(live_member_ids) < 2 or not live_group_person_ids:
                continue
            quality_scores, face_scores, face_quality_enabled = self._group_quality_scores(
                db,
                photos,
                features,
                live_member_ids,
                live_group_person_ids,
            )
            recommendation = choose_quality_recommendation(
                quality_scores,
                self.settings.gallery_similarity_quality_min_margin,
            )
            group = GallerySimilarityGroup(
                scan_id=scan.id,
                ordinal=published_group_count + 1,
                tier=tier,
                min_score=cluster.min_score,
                average_score=cluster.average_score,
                face_quality_enabled=face_quality_enabled,
                recommendation_status=recommendation.status,
            )
            db.add(group)
            db.flush()
            representative_id = max(live_member_ids, key=lambda photo_id: quality_scores[photo_id])
            score_map = near_scores if tier == "near_duplicate" else scene_scores
            for photo_id in live_member_ids:
                score = 1.0 if photo_id == representative_id else score_map.get(tuple(sorted((photo_id, representative_id))), cluster.min_score)
                db.execute(
                    insert(GallerySimilarityGroupMember).from_select(
                        [
                            "group_id",
                            "gallery_photo_id",
                            "score_to_representative",
                            "overall_quality_score",
                            "face_quality_score",
                            "quality_score",
                            "recommended_keep",
                        ],
                        select(
                            literal(group.id),
                            GalleryPhoto.id,
                            literal(score),
                            literal(features[photo_id].quality_score),
                            literal(face_scores[photo_id]),
                            literal(quality_scores[photo_id]),
                            literal(photo_id == recommendation.recommended_id),
                        ).where(
                            GalleryPhoto.id == photo_id,
                            GalleryPhoto.workspace_id == scan.workspace_id,
                        ),
                    )
                )
            for person_id in live_group_person_ids:
                db.add(GallerySimilarityGroupPerson(group_id=group.id, person_id=person_id))
            ordered_member_ids = tuple(sorted(live_member_ids))
            for left_index, left_id in enumerate(ordered_member_ids):
                for right_id in ordered_member_ids[left_index + 1 :]:
                    pair_score = score_map.get((left_id, right_id))
                    if pair_score is None:
                        continue
                    db.add(
                        GallerySimilarityGroupPair(
                            group_id=group.id,
                            left_gallery_photo_id=left_id,
                            right_gallery_photo_id=right_id,
                            score=pair_score,
                        )
                    )
            published_group_count += 1
        scan.group_count = published_group_count
        db.add(scan)
        db.flush()


def mark_similarity_scans_stale(db: Session, workspace_id: int, person_ids: set[int] | None = None) -> int:
    condition = [
        GallerySimilarityScan.workspace_id == workspace_id,
        GallerySimilarityScan.status == "completed",
        GallerySimilarityScan.is_stale.is_(False),
    ]
    if person_ids:
        condition.append(
            (GallerySimilarityScan.person_id.is_(None)) | (GallerySimilarityScan.person_id.in_(person_ids))
        )
    result = db.execute(update(GallerySimilarityScan).where(*condition).values(is_stale=True))
    return int(result.rowcount or 0)


def select_exact_mirror_auto_delete_photo_ids(db: Session, scan: GallerySimilarityScan) -> list[int]:
    """返回可按镜像自动整理规则删除的图片标识，不执行删除。"""
    if scan.scan_type != "mirror":
        return []
    groups = [
        group
        for group in db.scalars(
            select(GallerySimilarityGroup)
            .where(
                GallerySimilarityGroup.scan_id == scan.id,
                GallerySimilarityGroup.tier == "near_duplicate",
                GallerySimilarityGroup.review_status == "pending",
                GallerySimilarityGroup.min_score == 1.0,
            )
            .order_by(GallerySimilarityGroup.ordinal.asc())
        ).all()
        if len(group.members) >= 2
    ]
    group_ids_by_photo: dict[int, set[int]] = {}
    for group in groups:
        for member in group.members:
            group_ids_by_photo.setdefault(member.gallery_photo_id, set()).add(group.id)
    overlapping_group_ids = {
        group_id
        for group_ids in group_ids_by_photo.values()
        if len(group_ids) > 1
        for group_id in group_ids
    }

    photo_ids: list[int] = []
    for group in groups:
        if group.id in overlapping_group_ids:
            continue
        recommended = [member for member in group.members if member.recommended_keep]
        if len(recommended) == 1:
            retained_photo_id = recommended[0].gallery_photo_id
        elif recommended:
            continue
        else:
            sizes = [member.gallery_photo.size_bytes for member in group.members]
            if any(size is None for size in sizes):
                continue
            largest_size = max(size for size in sizes if size is not None)
            largest = [member for member in group.members if member.gallery_photo.size_bytes == largest_size]
            if len(largest) != 1:
                continue
            retained_photo_id = largest[0].gallery_photo_id
        photo_ids.extend(member.gallery_photo_id for member in group.members if member.gallery_photo_id != retained_photo_id)
    return photo_ids


def perceptual_component(
    left: GallerySimilarityFeature | None,
    right: GallerySimilarityFeature | None,
) -> float:
    """两图 pHash/dHash 相似度均值；缺少特征时返回 0。"""
    if left is None or right is None:
        return 0.0
    return (hash_similarity(left.phash, right.phash) + hash_similarity(left.dhash, right.dhash)) / 2


def derive_group_auto_clusters(
    pair_scores: Iterable[tuple[int, int, float]], threshold: float
) -> list[SimilarityCluster]:
    """按自动整理阈值推导组内的“几乎完全相同簇”。

    采用严格完全连接：簇内每一对图片的两两分数都必须达到阈值，
    避免传递链（A~B、B~C 达标而 A~C 不达标）把明显不同的图混入同一簇。
    返回结果按规模降序、最低分降序排列，未进入任何簇的散图不出现在结果中。
    """
    candidates = [
        SimilarityCandidate(left_id, right_id, score)
        for left_id, right_id, score in pair_scores
        if left_id != right_id and score >= threshold
    ]
    member_ids = {
        photo_id
        for candidate in candidates
        for photo_id in (candidate.left_id, candidate.right_id)
    }
    clusters = complete_link_clusters(sorted(member_ids), candidates, threshold)
    return sorted(clusters, key=lambda item: (-len(item.member_ids), -item.min_score))


@dataclass(frozen=True)
class AutoDeleteClusterPlan:
    """单个“几乎完全相同簇”的自动整理预案。"""

    member_ids: tuple[int, ...]
    retained_photo_id: int | None
    delete_photo_ids: tuple[int, ...]
    skip_reason: str | None


def build_normal_near_duplicate_auto_delete_plan(
    db: Session,
    scan: GallerySimilarityScan,
    storage: MinioStorage,
    settings: Settings,
) -> list[AutoDeleteClusterPlan]:
    """构建普通相似扫描近重复组的自动整理预案，不执行删除。"""
    if scan.scan_type != "normal":
        return []
    groups = [
        group
        for group in db.scalars(
            select(GallerySimilarityGroup)
            .where(
                GallerySimilarityGroup.scan_id == scan.id,
                GallerySimilarityGroup.tier == "near_duplicate",
                GallerySimilarityGroup.review_status == "pending",
            )
            .order_by(GallerySimilarityGroup.ordinal.asc())
        ).all()
        if len(group.members) >= 2
    ]
    if not groups:
        return []

    threshold = max(0.0, min(1.0, float(settings.gallery_similarity_auto_delete_threshold)))
    member_ids = sorted({member.gallery_photo_id for group in groups for member in group.members})
    photos = {
        photo.id: photo
        for photo in db.scalars(
            select(GalleryPhoto).where(
                GalleryPhoto.workspace_id == scan.workspace_id,
                GalleryPhoto.id.in_(member_ids),
            )
        ).all()
    }
    features = {
        feature.gallery_photo_id: feature
        for feature in db.scalars(
            select(GallerySimilarityFeature).where(
                GallerySimilarityFeature.gallery_photo_id.in_(member_ids)
            )
        ).all()
    }
    if not photos or not features:
        return []

    orb_cache: OrderedDict[tuple[int, bool], OrbFeatures] = OrderedDict()

    def get_orb_features(photo_id: int, *, mirrored: bool = False) -> OrbFeatures:
        cache_key = (photo_id, mirrored)
        cached = orb_cache.pop(cache_key, None)
        if cached is not None:
            orb_cache[cache_key] = cached
            return cached
        feature = compute_orb_features(
            storage.get_bytes(photos[photo_id].object_key),
            mirrored=mirrored,
        )
        orb_cache[cache_key] = feature
        if len(orb_cache) > 256:
            orb_cache.popitem(last=False)
        return feature

    def orb_loader(photo_id: int, use_mirrored: bool) -> OrbFeatures:
        return get_orb_features(photo_id, mirrored=use_mirrored)

    def pair_score(left_id: int, right_id: int) -> float:
        left_feature = features.get(left_id)
        right_feature = features.get(right_id)
        if left_feature is None or right_feature is None:
            return 0.0
        try:
            score = near_duplicate_pair_score(left_feature, right_feature, load_orb_features=orb_loader)
        except Exception:
            return 0.0
        # 纯哈希门槛：同机位不同瞬间的图片会被 ORB 背景匹配抬分，但哈希相似度上不去。
        if score >= threshold and perceptual_component(left_feature, right_feature) < settings.gallery_similarity_auto_delete_perceptual_min:
            return 0.0
        return score

    # 每个组内独立做高阈值子聚类：严格完全连接——簇内每一对分数都须达阈值，避免传递链误成簇。
    cluster_to_group: dict[tuple[int, ...], GallerySimilarityGroup] = {}
    for group in groups:
        group_member_ids = sorted({member.gallery_photo_id for member in group.members})
        candidates: list[SimilarityCandidate] = []
        for left_index, left_id in enumerate(group_member_ids):
            for right_id in group_member_ids[left_index + 1 :]:
                if left_id not in photos or right_id not in photos:
                    continue
                score = pair_score(left_id, right_id)
                if score >= threshold:
                    candidates.append(SimilarityCandidate(left_id, right_id, score))
        for cluster in complete_link_clusters(group_member_ids, candidates, threshold):
            if cluster.member_ids not in cluster_to_group:
                cluster_to_group[cluster.member_ids] = group
    if not cluster_to_group:
        return []

    # 护栏：同一张图片出现在多个簇（跨组重叠）时，相关簇全部跳过。
    cluster_ids = list(cluster_to_group)
    overlap_photo_ids = {
        photo_id
        for photo_id in member_ids
        if sum(photo_id in cluster for cluster in cluster_ids) > 1
    }
    minimum_margin = float(settings.gallery_similarity_quality_min_margin)
    plans: list[AutoDeleteClusterPlan] = []
    for cluster in cluster_ids:
        if any(photo_id in overlap_photo_ids for photo_id in cluster):
            plans.append(AutoDeleteClusterPlan(cluster, None, (), "overlap"))
            continue
        group = cluster_to_group[cluster]
        quality_scores = {
            member.gallery_photo_id: member.quality_score
            for member in group.members
            if member.gallery_photo_id in cluster
        }
        recommendation = choose_quality_recommendation(quality_scores, minimum_margin)
        retained_photo_id: int | None = None
        if recommendation.status == "recommended" and recommendation.recommended_id is not None:
            retained_photo_id = int(recommendation.recommended_id)
        else:
            sizes = [photos[photo_id].size_bytes for photo_id in cluster]
            if all(size is not None for size in sizes):
                largest_size = max(size for size in sizes if size is not None)
                largest = [photo_id for photo_id, size in zip(cluster, sizes, strict=True) if size == largest_size]
                if len(largest) == 1:
                    retained_photo_id = largest[0]
        if retained_photo_id is None:
            plans.append(AutoDeleteClusterPlan(cluster, None, (), "no_retention"))
            continue
        plans.append(
            AutoDeleteClusterPlan(
                cluster,
                retained_photo_id,
                tuple(photo_id for photo_id in cluster if photo_id != retained_photo_id),
                None,
            )
        )
    return plans


def select_normal_near_duplicate_auto_delete_photo_ids(
    db: Session,
    scan: GallerySimilarityScan,
    storage: MinioStorage,
    settings: Settings,
) -> list[int]:
    """返回普通相似扫描中可按近重复自动整理规则删除的图片标识，不执行删除。"""
    return [
        photo_id
        for plan in build_normal_near_duplicate_auto_delete_plan(db, scan, storage, settings)
        for photo_id in plan.delete_photo_ids
    ]


def cleanup_deleted_similarity_photos(
    db: Session,
    vector_store: QdrantVectorStore,
    photo_ids: list[int],
    minimum_quality_margin: float = 3.0,
) -> None:
    if not photo_ids:
        return
    point_ids = [
        point_id
        for point_id in db.scalars(
            select(GallerySimilarityFeature.vector_point_id).where(
                GallerySimilarityFeature.gallery_photo_id.in_(photo_ids)
            )
        ).all()
        if point_id
    ]
    vector_store.delete_gallery_similarity_vectors(point_ids)
    group_ids = set(
        db.scalars(
            select(GallerySimilarityGroupMember.group_id).where(
                GallerySimilarityGroupMember.gallery_photo_id.in_(photo_ids)
            )
        ).all()
    )
    affected_scan_ids = set(
        db.scalars(
            select(GallerySimilarityGroup.scan_id).where(GallerySimilarityGroup.id.in_(group_ids))
        ).all()
    )
    db.execute(
        delete(GallerySimilarityGroupMember).where(GallerySimilarityGroupMember.gallery_photo_id.in_(photo_ids))
    )
    for group_id in group_ids:
        members = db.scalars(
            select(GallerySimilarityGroupMember)
            .where(GallerySimilarityGroupMember.group_id == group_id)
            .order_by(GallerySimilarityGroupMember.quality_score.desc())
        ).all()
        if len(members) < 2:
            db.execute(delete(GallerySimilarityGroup).where(GallerySimilarityGroup.id == group_id))
            continue
        recommendation = choose_quality_recommendation(
            {member.gallery_photo_id: member.quality_score for member in members},
            minimum_quality_margin,
        )
        group = db.get(GallerySimilarityGroup, group_id)
        if group is not None:
            group.recommendation_status = recommendation.status
            db.add(group)
        for member in members:
            member.recommended_keep = member.gallery_photo_id == recommendation.recommended_id
            db.add(member)
    db.flush()
    for scan_id in affected_scan_ids:
        scan = db.get(GallerySimilarityScan, scan_id)
        if scan is None:
            continue
        scan.group_count = int(
            db.scalar(
                select(func.count(GallerySimilarityGroup.id)).where(
                    GallerySimilarityGroup.scan_id == scan_id
                )
            )
            or 0
        )
        db.add(scan)
