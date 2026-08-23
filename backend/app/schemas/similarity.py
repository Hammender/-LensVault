from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime

from .gallery import GalleryPhotoListItem, TaskRead
from .people import PersonRead

class GallerySimilarityScanCreate(BaseModel):
    person_id: int | None = None
    include_cross_type: bool = False
    scan_type: Literal["normal", "mirror"] = "normal"
    auto_delete_exact_mirror: bool = False


class GallerySimilarityScanRead(BaseModel):
    id: str
    task_id: str | None
    person_id: int | None
    include_cross_type: bool
    scan_type: Literal["normal", "mirror"]
    auto_delete_exact_mirror: bool
    auto_deleted_count: int
    status: str
    is_stale: bool
    feature_version: str
    photo_count: int
    candidate_pair_count: int
    group_count: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    task: TaskRead | None = None


class GallerySimilarityScanOverview(BaseModel):
    active: GallerySimilarityScanRead | None = None
    results: list[GallerySimilarityScanRead]


class GallerySimilarityAutoDeleteResponse(BaseModel):
    deleted: int
    scan: GallerySimilarityScanRead


class GallerySimilarityAutoDeletePreviewMember(BaseModel):
    photo_id: int
    filename: str
    thumbnail_url: str
    size_bytes: int | None
    quality_score: float
    retained: bool


class GallerySimilarityAutoDeletePreviewCluster(BaseModel):
    status: Literal["ready", "skipped_overlap", "skipped_no_retention"]
    retained_photo_id: int | None
    delete_photo_ids: list[int]
    members: list[GallerySimilarityAutoDeletePreviewMember]


class GallerySimilarityAutoDeletePreviewResponse(BaseModel):
    scan_id: str
    deletable_count: int
    skipped_cluster_count: int
    clusters: list[GallerySimilarityAutoDeletePreviewCluster]


class GallerySimilarityMemberRead(BaseModel):
    photo: GalleryPhotoListItem
    score_to_representative: float
    overall_quality_score: float
    face_quality_score: float | None
    quality_score: float
    recommended_keep: bool
    auto_cluster_index: int | None = None


class GallerySimilarityClusterRead(BaseModel):
    index: int
    member_photo_ids: list[int]
    min_pair_score: float
    average_pair_score: float


class GallerySimilarityGroupRead(BaseModel):
    id: int
    ordinal: int
    tier: str
    review_status: Literal["pending", "dismissed"]
    min_score: float
    average_score: float
    face_quality_enabled: bool
    recommendation_status: Literal["recommended", "close_quality", "unavailable"]
    people: list[PersonRead]
    members: list[GallerySimilarityMemberRead]
    clusters: list[GallerySimilarityClusterRead] = []


class GallerySimilarityGroupUpdate(BaseModel):
    review_status: Literal["pending", "dismissed"]


class PaginatedGallerySimilarityGroups(BaseModel):
    items: list[GallerySimilarityGroupRead]
    total: int
    offset: int
    limit: int
