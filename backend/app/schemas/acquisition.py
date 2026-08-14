from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime

from .gallery import GalleryPhotoListItem, TaskRead


class AcquisitionSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=1024)
    notes: str | None = Field(default=None, max_length=2000)


class AcquisitionSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    notes: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


class AcquisitionSourceRead(BaseModel):
    id: int
    name: str
    base_url: str
    notes: str | None
    page_format_key: str | None
    script_keys: list[str] = Field(default_factory=list)
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcquisitionCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    crawl_url: str = Field(min_length=1, max_length=2048)
    notes: str | None = Field(default=None, max_length=2000)


class AcquisitionCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    crawl_url: str | None = Field(default=None, min_length=1, max_length=2048)
    notes: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


class AcquisitionCategoryRead(BaseModel):
    id: int
    source_id: int
    name: str
    crawl_url: str
    notes: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcquisitionRunCreate(BaseModel):
    script_key: str = Field(min_length=1, max_length=128)
    mode: Literal["incremental", "full", "verify"] = "incremental"
    parameters: dict[str, object] = Field(default_factory=dict)


class AcquisitionRunRead(BaseModel):
    id: str
    source_id: int
    category_id: int
    script_key: str | None
    script_name: str
    script_version: str
    source_name: str
    category_name: str
    category_url: str
    parameters: dict[str, object]
    mode: str
    status: str
    total_count: int
    downloaded_count: int
    skipped_count: int
    download_success_count: int
    candidate_count: int
    content_duplicate_count: int
    gallery_duplicate_count: int
    resolution_duplicate_count: int
    resolution_upgrade_count: int
    ignored_count: int
    invalid_count: int
    error_count: int
    imported_count: int
    error_message: str | None
    scan_start_page: int | None
    scan_end_page: int | None
    reached_collection_end: bool
    stop_reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcquisitionScriptParameterOption(BaseModel):
    value: str
    label: str


class AcquisitionScriptParameterRead(BaseModel):
    key: str
    label: str
    type: Literal["string", "integer", "number", "boolean", "select"]
    required: bool = False
    default: object | None = None
    description: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    options: list[AcquisitionScriptParameterOption] = Field(default_factory=list)


class AcquisitionScriptRead(BaseModel):
    key: str
    name: str
    version: str
    page_format_key: str
    description: str
    parameters: list[AcquisitionScriptParameterRead] = Field(default_factory=list)


class AcquisitionSourceScriptBind(BaseModel):
    script_key: str = Field(min_length=1, max_length=128)
    default_parameters: dict[str, object] = Field(default_factory=dict)


class AcquisitionAssetRead(BaseModel):
    id: str
    filename: str
    content_type: str | None
    sha256: str
    size_bytes: int
    width: int | None
    height: int | None
    blur_score: float | None
    quality_warnings: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime
    preview_url: str | None = None
    original_url: str | None = None


class PaginatedAcquisitionAssets(BaseModel):
    items: list[AcquisitionAssetRead]
    total: int
    offset: int
    limit: int


class AcquisitionSimilarityGroupRead(BaseModel):
    id: str
    max_score: float
    average_score: float
    members: list[AcquisitionAssetRead]
    gallery_members: list["AcquisitionSimilarityGalleryMemberRead"] = Field(default_factory=list)


class AcquisitionSimilarityGalleryMemberRead(BaseModel):
    photo: GalleryPhotoListItem
    score: float
    quality_score: float
    recommended_keep: bool = False


class AcquisitionSimilarityScanCreate(BaseModel):
    scan_type: Literal["normal", "mirror"] = "normal"
    scope: Literal["pending_only", "pending_to_gallery"] = "pending_only"


class AcquisitionSimilarityResultRead(BaseModel):
    scan_type: Literal["normal", "mirror"] = "normal"
    scope: Literal["pending_only", "pending_to_gallery"] = "pending_only"
    task: TaskRead | None
    generated_at: datetime | None
    is_stale: bool
    groups: list[AcquisitionSimilarityGroupRead]
    total: int
    offset: int
    limit: int


class AcquisitionAssetAction(BaseModel):
    asset_ids: list[str] = Field(min_length=1)


class AcquisitionAssetSummary(BaseModel):
    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)


class AcquisitionImportBatchItemRead(BaseModel):
    id: int
    asset_id: str
    ordinal: int
    status: str
    gallery_photo_id: int | None
    attempt_count: int
    error_message: str | None

    model_config = {"from_attributes": True}


class AcquisitionImportBatchRead(BaseModel):
    id: str
    status: str
    total_count: int
    processed_count: int
    imported_count: int
    duplicate_count: int
    failed_count: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[AcquisitionImportBatchItemRead] = Field(default_factory=list)


class PaginatedAcquisitionImportBatches(BaseModel):
    items: list[AcquisitionImportBatchRead]
    total: int
    offset: int
    limit: int
    unassigned_imported_count: int


class AcquisitionImportOriginRead(BaseModel):
    run_id: str
    source_name: str
    category_name: str
    run_created_at: datetime


class AcquisitionImportBatchItemDetailRead(BaseModel):
    id: int | None
    asset_id: str
    ordinal: int
    status: str
    gallery_photo_id: int | None
    gallery_photo_snapshot_id: int | None
    gallery_available: bool
    attempt_count: int
    error_message: str | None
    filename: str
    sha256: str
    imported_at: datetime | None
    origins: list[AcquisitionImportOriginRead] = Field(default_factory=list)


class PaginatedAcquisitionImportBatchItems(BaseModel):
    items: list[AcquisitionImportBatchItemDetailRead]
    total: int
    offset: int
    limit: int


class AcquisitionExportCreate(BaseModel):
    run_id: str | None = None
    source_id: int | None = None
    category_id: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class AcquisitionExportRead(BaseModel):
    id: str
    status: str
    filename: str | None
    item_count: int
    missing_count: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    download_url: str | None = None
