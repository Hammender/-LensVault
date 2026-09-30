from __future__ import annotations

from datetime import datetime
import json

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.core.timezones import shanghai_now
class AcquisitionSource(Base):
    __tablename__ = "acquisition_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_acquisition_source_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_format_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_telegram_account_workspace"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    api_id: Mapped[int] = mapped_column(Integer, nullable=False)
    api_hash_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    session_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_login_state_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="unconfigured", nullable=False, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionScript(Base):
    __tablename__ = "acquisition_scripts"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    page_format_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameter_schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionPluginVersion(Base):
    __tablename__ = "acquisition_plugin_versions"
    __table_args__ = (UniqueConstraint("script_key", "version", name="uq_acquisition_plugin_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_key: Mapped[str] = mapped_column(ForeignKey("acquisition_scripts.key", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)


class AcquisitionPluginCredential(Base):
    __tablename__ = "acquisition_plugin_credentials"
    __table_args__ = (UniqueConstraint("workspace_id", "script_key", "name", name="uq_acquisition_plugin_credential"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    script_key: Mapped[str] = mapped_column(ForeignKey("acquisition_scripts.key", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="untested", nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionSourceScript(Base):
    __tablename__ = "acquisition_source_scripts"
    __table_args__ = (UniqueConstraint("source_id", "script_key", name="uq_acquisition_source_script"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("acquisition_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    script_key: Mapped[str] = mapped_column(ForeignKey("acquisition_scripts.key", ondelete="CASCADE"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    default_parameters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionCategory(Base):
    __tablename__ = "acquisition_categories"
    __table_args__ = (UniqueConstraint("source_id", "path", name="uq_acquisition_category_source_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("acquisition_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("acquisition_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    crawl_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    telegram_peer_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    telegram_entity_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    telegram_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    telegram_topic_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    telegram_source_mode: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)

class AcquisitionRun(Base):
    __tablename__ = "acquisition_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("acquisition_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("acquisition_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    script_key: Mapped[str | None] = mapped_column(ForeignKey("acquisition_scripts.key", ondelete="SET NULL"), nullable=True, index=True)
    credential_id: Mapped[int | None] = mapped_column(ForeignKey("acquisition_plugin_credentials.id", ondelete="SET NULL", name="fk_acquisition_runs_credential_id"), nullable=True)
    script_name_snapshot: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    script_version_snapshot: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_name_snapshot: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    category_name_snapshot: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    category_url_snapshot: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="incremental", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    downloaded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    download_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gallery_duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolution_duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolution_upgrade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ignored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reached_collection_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionSourceItem(Base):
    __tablename__ = "acquisition_source_items"
    __table_args__ = (UniqueConstraint("source_id", "external_key", name="uq_acquisition_source_item_external_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("acquisition_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("acquisition_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    script_key: Mapped[str | None] = mapped_column(ForeignKey("acquisition_scripts.key", ondelete="SET NULL"), nullable=True, index=True)
    external_key: Mapped[str] = mapped_column(String(256), nullable=False)
    remote_external_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    preview_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionAsset(Base):
    __tablename__ = "acquisition_assets"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256", name="uq_acquisition_asset_workspace_sha256"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_type: Mapped[str] = mapped_column(String(16), default="image", server_default="image", nullable=False, index=True)
    object_key: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    preview_object_key: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    perceptual_phash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    perceptual_dhash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_version: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resolution_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    artifact_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    exposure_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_face_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_face_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    primary_face_dominant: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    quality_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionRunItem(Base):
    __tablename__ = "acquisition_run_items"
    __table_args__ = (UniqueConstraint("run_id", "source_item_id", name="uq_acquisition_run_source_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("acquisition_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("acquisition_source_items.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("acquisition_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    collection_outcome: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    resolved_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    resolved_candidate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionTelegramMessage(Base):
    __tablename__ = "acquisition_telegram_messages"
    __table_args__ = (UniqueConstraint("workspace_id", "channel_id", "message_id", "media_index", name="uq_telegram_message_media"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("acquisition_source_items.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    channel_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    media_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grouped_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    protected_content: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    peer_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    sender_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sender_is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    topic_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_comment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False, index=True)
    root_channel_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionTelegramHashtag(Base):
    __tablename__ = "acquisition_telegram_hashtags"
    __table_args__ = (UniqueConstraint("telegram_message_id", "tag_normalized", name="uq_telegram_message_hashtag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(ForeignKey("acquisition_telegram_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_raw: Mapped[str] = mapped_column(String(256), nullable=False)
    tag_normalized: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)


class AcquisitionImportedPhoto(Base):
    __tablename__ = "acquisition_imported_photos"
    __table_args__ = (UniqueConstraint("run_id", "asset_id", name="uq_acquisition_imported_run_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("acquisition_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("acquisition_assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    gallery_photo_id: Mapped[int | None] = mapped_column(ForeignKey("gallery_photos.id", ondelete="SET NULL"), nullable=True, index=True)
    gallery_photo_snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    filename_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    category_path_snapshot: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)


class AcquisitionImportBatch(Base):
    __tablename__ = "acquisition_import_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    is_rich_text: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionImportBatchItem(Base):
    __tablename__ = "acquisition_import_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "asset_id", name="uq_acquisition_import_batch_asset"),
        UniqueConstraint("batch_id", "ordinal", name="uq_acquisition_import_batch_ordinal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("acquisition_import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("acquisition_assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    promotion_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gallery_photo_id: Mapped[int | None] = mapped_column(ForeignKey("gallery_photos.id", ondelete="SET NULL"), nullable=True, index=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("video_items.id", ondelete="SET NULL"), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(16), default="image", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False)


class AcquisitionImportedVideo(Base):
    __tablename__ = "acquisition_imported_videos"
    __table_args__ = (UniqueConstraint("run_id", "asset_id", name="uq_acquisition_imported_run_video"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("acquisition_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("acquisition_assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("video_items.id", ondelete="SET NULL"), nullable=True, index=True)
    video_id_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    filename_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    category_path_snapshot: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)


class AcquisitionSimilarityCandidate(Base):
    __tablename__ = "acquisition_similarity_candidates"
    __table_args__ = (UniqueConstraint("asset_id", "other_asset_id", "gallery_photo_id", name="uq_acquisition_similarity_candidate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    scan_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("acquisition_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    other_asset_id: Mapped[str | None] = mapped_column(ForeignKey("acquisition_assets.id", ondelete="CASCADE"), nullable=True, index=True)
    gallery_photo_id: Mapped[int | None] = mapped_column(ForeignKey("gallery_photos.id", ondelete="CASCADE"), nullable=True, index=True)
    scan_type: Mapped[str] = mapped_column(String(32), default="normal", nullable=False, index=True)
    scan_scope: Mapped[str] = mapped_column(String(32), default="pending_only", nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(32), default="near_duplicate", nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)


class AcquisitionExportJob(Base):
    __tablename__ = "acquisition_export_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True, unique=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
