from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class UserRead(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool

    model_config = {"from_attributes": True}


class WorkspaceRead(BaseModel):
    id: int
    name: str
    kind: str
    role: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    can_leave: bool = False


class AuthSession(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    workspace: WorkspaceRead
    workspaces: list[WorkspaceRead]


class BootstrapStatus(BaseModel):
    required: bool


class BootstrapCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    workspace_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    is_admin: bool = False
    can_add_gallery: bool = False
    can_delete_gallery: bool = False
    can_edit_gallery: bool = False
    can_add_samples: bool = False
    can_delete_samples: bool = False
    can_edit_samples: bool = False
    can_add_videos: bool = False
    can_delete_videos: bool = False
    can_edit_videos: bool = False


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class WorkspacePermissionUpdate(BaseModel):
    can_add_gallery: bool = False
    can_delete_gallery: bool = False
    can_edit_gallery: bool = False
    can_add_samples: bool = False
    can_delete_samples: bool = False
    can_edit_samples: bool = False
    can_add_videos: bool = False
    can_delete_videos: bool = False
    can_edit_videos: bool = False


class WorkspaceMemberRead(BaseModel):
    id: int
    user: UserRead
    role: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime


class WorkspaceInvitationCreate(WorkspacePermissionUpdate):
    username: str = Field(min_length=1, max_length=128)


class WorkspaceInvitationRead(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    inviter_username: str
    invitee_username: str
    status: str
    role: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    note: str | None = None


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    note: str | None = None


class PersonRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class PersonBatchDeleteRequest(BaseModel):
    person_ids: list[int] = Field(min_length=1)


class PersonRead(BaseModel):
    id: int
    name: str
    display_name: str
    note: str | None
    is_unknown: bool
    unknown_serial: int | None
    sample_count: int = 0
    gallery_photo_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class SamplePhotoRead(BaseModel):
    id: int
    filename: str
    width: int | None
    height: int | None
    taken_at: datetime | None
    status: str
    error_message: str | None
    quality_status: str | None = None
    quality_warnings: str | None = None
    source_type: str = "upload"
    source_gallery_photo_id: int | None = None
    thumbnail_url: str
    original_url: str
    created_at: datetime


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class TagRead(BaseModel):
    id: int
    name: str
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonTagCreate(BaseModel):
    tag_id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "PersonTagCreate":
        if bool(self.tag_id) == bool(self.name and self.name.strip()):
            raise ValueError("Provide either tag_id or name.")
        if self.name is not None:
            self.name = self.name.strip()
        return self


class GalleryPersonTagRead(BaseModel):
    person_id: int
    person_name: str
    is_unknown: bool
    source: str
    promoted_sample_id: int | None = None


class GalleryTagRead(BaseModel):
    id: int
    name: str
    is_system: bool


class FaceRead(BaseModel):
    id: int
    bbox_left: float
    bbox_top: float
    bbox_right: float
    bbox_bottom: float
    matched_person_id: int | None
    match_score: float | None
    second_person_id: int | None = None
    second_match_score: float | None = None
    match_margin: float | None = None
    embedding_version: str | None = None
    face_size: float | None = None
    blur_score: float | None = None
    pose_yaw: float | None = None
    needs_review: bool
    vector_collection: str | None


class GalleryPhotoListItem(BaseModel):
    id: int
    filename: str
    width: int | None
    height: int | None
    taken_at: datetime | None
    is_rich_text: bool
    rich_text: str | None
    ocr_status: str | None
    persons: list[GalleryPersonTagRead]
    tags: list[GalleryTagRead]
    thumbnail_url: str
    original_url: str


class GalleryPhotoDetail(GalleryPhotoListItem):
    faces: list[FaceRead]
    created_at: datetime
    content_type: str | None
    recognition_summary: dict[str, int] | None = None


class PaginatedGalleryPhotos(BaseModel):
    items: list[GalleryPhotoListItem]
    total: int
    offset: int
    limit: int


class TaskRead(BaseModel):
    id: str
    kind: str
    status: str
    message: str | None
    progress: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GalleryPhotoPersonTagCreate(BaseModel):
    person_id: int


class GalleryPhotoTagCreate(BaseModel):
    tag_id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "GalleryPhotoTagCreate":
        if bool(self.tag_id) == bool(self.name and self.name.strip()):
            raise ValueError("Provide either tag_id or name.")
        if self.name is not None:
            self.name = self.name.strip()
        return self


class GalleryPhotoRichTextUpdate(BaseModel):
    rich_text: str | None = None


class GalleryPhotoBatchDeleteRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1)


class TagStatistics(BaseModel):
    tag_id: int
    tag_name: str
    is_system: bool
    photo_count: int


class UploadHistoryRead(BaseModel):
    id: int
    upload_type: str
    total_count: int
    success_count: int
    duplicate_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonStatistics(BaseModel):
    person_id: int
    person_name: str
    display_name: str
    is_unknown: bool
    photo_count: int
    sample_count: int


class ExportSamplePhoto(BaseModel):
    filename: str
    sha256: str
    content_type: str | None = None
    object_key: str
    width: int | None = None
    height: int | None = None
    taken_at: datetime | None = None


class ExportPerson(BaseModel):
    name: str
    display_name: str
    note: str | None = None
    is_unknown: bool
    tags: list[str]
    samples: list[ExportSamplePhoto]


class ExportManifest(BaseModel):
    version: int
    exported_at: datetime
    persons: list[ExportPerson]


class ImportResult(BaseModel):
    created_persons: int = 0
    existing_persons: int = 0
    added_samples: int = 0
    skipped_samples: int = 0
    tags_added: int = 0


class VideoCategoryTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class VideoCategoryTagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class VideoCategoryTagRead(BaseModel):
    id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VideoPersonRead(BaseModel):
    id: int
    name: str
    note: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


class VideoPersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    note: str | None = None


class VideoTagBindCreate(BaseModel):
    tag_id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "VideoTagBindCreate":
        if bool(self.tag_id) == bool(self.name and self.name.strip()):
            raise ValueError("Provide either tag_id or name.")
        if self.name is not None:
            self.name = self.name.strip()
        return self


class VideoPersonBindCreate(BaseModel):
    person_id: int


class VideoSubtitleTrackRead(BaseModel):
    id: int
    video_id: int
    language: str
    label: str
    source_language: str | None
    provider: str
    status: str
    error_message: str | None
    task_id: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    vtt_url: str | None = None
    srt_url: str | None = None

    model_config = {"from_attributes": True}


class GallerySimilarityScanCreate(BaseModel):
    person_id: int | None = None
    include_cross_type: bool = False


class GallerySimilarityScanRead(BaseModel):
    id: str
    task_id: str | None
    person_id: int | None
    include_cross_type: bool
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
    quality_score: float
    recommended_keep: bool


class GallerySimilarityGroupRead(BaseModel):
    id: int
    ordinal: int
    tier: str
    min_score: float
    average_score: float
    people: list[PersonRead]
    members: list[GallerySimilarityMemberRead]


class PaginatedGallerySimilarityGroups(BaseModel):
    items: list[GallerySimilarityGroupRead]
    total: int
    offset: int
    limit: int


class SubtitleAsrStatus(BaseModel):
    status: str
    loaded: bool
    model_path: str
    device: str
    compute_type: str
    current_video_id: int | None
    current_task_id: str | None
    message: str | None
    last_duration_seconds: float | None
    last_language: str | None
    last_segment_count: int | None
    last_error: str | None


class SubtitleServiceStatus(BaseModel):
    status: str
    healthy: bool
    managed: bool
    pid: int | None
    endpoint: str
    model: str
    model_path: str
    server_path: str | None
    log_path: str | None
    message: str | None
    asr: SubtitleAsrStatus


class SubtitleServiceLogs(BaseModel):
    log_path: str | None
    exists: bool
    content: str


class SubtitleJobRead(BaseModel):
    video_id: int
    video_title: str
    video_filename: str
    track: VideoSubtitleTrackRead
    task: TaskRead | None


class VideoSubtitleTrackUpdate(BaseModel):
    content_vtt: str


class VideoItemListItem(BaseModel):
    id: int
    title: str
    description: str | None
    filename: str
    content_type: str | None
    size_bytes: int
    duration_seconds: float | None
    width: int | None
    height: int | None
    original_video_codec: str | None
    original_audio_codec: str | None
    video_codec: str | None
    audio_codec: str | None
    status: str
    category_tags: list[VideoCategoryTagRead]
    people: list[VideoPersonRead]
    stream_url: str
    play_url: str
    cover_url: str | None
    faststart_applied: bool
    seek_optimized: bool
    seek_optimized_at: datetime | None
    seek_keyframe_interval_seconds: float | None
    processed_at: datetime | None
    processing_error: str | None
    created_at: datetime
    updated_at: datetime
    subtitle_tracks: list[VideoSubtitleTrackRead] = Field(default_factory=list)


class VideoItemDetail(VideoItemListItem):
    sha256: str | None


class PaginatedVideos(BaseModel):
    items: list[VideoItemListItem]
    total: int
    offset: int
    limit: int


class VideoMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None


class VideoUploadSessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    filename: str = Field(min_length=1, max_length=512)
    content_type: str | None = None
    size_bytes: int = Field(gt=0)
    part_size: int | None = Field(default=None, gt=0)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class VideoUploadSessionRead(BaseModel):
    id: str
    filename: str
    title: str
    description: str | None
    content_type: str | None
    size_bytes: int
    part_size: int
    total_parts: int
    uploaded_parts: list[int]
    status: str
    created_at: datetime
    updated_at: datetime


class VideoUploadPartRead(BaseModel):
    session_id: str
    part_index: int
    size_bytes: int
    sha256: str | None


class VideoUploadCompleteRequest(BaseModel):
    category_tag_ids: list[int] = Field(default_factory=list)
    category_tag_names: list[str] = Field(default_factory=list)
    person_ids: list[int] = Field(default_factory=list)
    generate_zh_subtitles: bool = False

    @model_validator(mode="after")
    def normalize_names(self) -> "VideoUploadCompleteRequest":
        self.category_tag_names = list(
            dict.fromkeys(name.strip() for name in self.category_tag_names if name.strip())
        )
        return self
