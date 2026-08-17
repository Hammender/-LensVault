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


class GallerySimilarityScanRead(BaseModel):
    id: str
    task_id: str | None
    person_id: int | None
    include_cross_type: bool
    scan_type: Literal["normal", "mirror"]
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


class GallerySimilarityMemberRead(BaseModel):
    photo: GalleryPhotoListItem
    score_to_representative: float
    overall_quality_score: float
    face_quality_score: float | None
    quality_score: float
    recommended_keep: bool


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


class GallerySimilarityGroupUpdate(BaseModel):
    review_status: Literal["pending", "dismissed"]


class PaginatedGallerySimilarityGroups(BaseModel):
    items: list[GallerySimilarityGroupRead]
    total: int
    offset: int
    limit: int
