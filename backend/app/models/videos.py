from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.core.timezones import shanghai_now


class VideoItem(Base):
    __tablename__ = "video_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_video_items_workspace_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    cover_object_key: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    cover_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_audio_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    video_type: Mapped[str] = mapped_column(String(16), default="short", nullable=False, index=True)
    faststart_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seek_optimized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seek_optimized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seek_keyframe_interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
        nullable=False,
    )

    category_links: Mapped[list[VideoItemCategoryTag]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
    )
    person_links: Mapped[list[VideoItemPerson]] = relationship(back_populates="video", cascade="all, delete-orphan")
    subtitle_tracks: Mapped[list[VideoSubtitleTrack]] = relationship(back_populates="video", cascade="all, delete-orphan")


class VideoCategoryTag(Base):
    __tablename__ = "video_category_tags"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_video_category_tags_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    video_links: Mapped[list[VideoItemCategoryTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class VideoPerson(Base):
    __tablename__ = "video_people"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_video_people_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_object_key: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    avatar_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
        nullable=False,
    )

    video_links: Mapped[list[VideoItemPerson]] = relationship(back_populates="person", cascade="all, delete-orphan")


class VideoItemCategoryTag(Base):
    __tablename__ = "video_item_category_tags"
    __table_args__ = (UniqueConstraint("video_id", "tag_id", name="uq_video_item_category_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video_items.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("video_category_tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    video: Mapped[VideoItem] = relationship(back_populates="category_links")
    tag: Mapped[VideoCategoryTag] = relationship(back_populates="video_links")


class VideoItemPerson(Base):
    __tablename__ = "video_item_people"
    __table_args__ = (UniqueConstraint("video_id", "person_id", name="uq_video_item_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video_items.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("video_people.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    video: Mapped[VideoItem] = relationship(back_populates="person_links")
    person: Mapped[VideoPerson] = relationship(back_populates="video_links")


class VideoSubtitleTrack(Base):
    __tablename__ = "video_subtitle_tracks"
    __table_args__ = (UniqueConstraint("video_id", "language", name="uq_video_subtitle_track_language"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video_items.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), default="中文字幕", nullable=False)
    source_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="local_hymt2", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    content_vtt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
        nullable=False,
    )

    video: Mapped[VideoItem] = relationship(back_populates="subtitle_tracks")


class VideoUploadSession(Base):
    __tablename__ = "video_upload_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_parts: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploading", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
        nullable=False,
    )

    parts: Mapped[list[VideoUploadPart]] = relationship(back_populates="session", cascade="all, delete-orphan")


class VideoUploadPart(Base):
    __tablename__ = "video_upload_parts"
    __table_args__ = (UniqueConstraint("session_id", "part_index", name="uq_video_upload_part"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("video_upload_sessions.id", ondelete="CASCADE"), index=True)
    part_index: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    session: Mapped[VideoUploadSession] = relationship(back_populates="parts")
