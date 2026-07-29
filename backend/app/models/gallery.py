from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.core.timezones import shanghai_now
from .people import SamplePhoto
class GalleryPhoto(Base):
    __tablename__ = "gallery_photos"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", "is_rich_text", name="uq_gallery_photos_workspace_sha256_rich_text"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_rich_text: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    rich_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
        nullable=False,
    )

    faces: Mapped[list[FaceRecord]] = relationship(back_populates="gallery_photo", cascade="all, delete-orphan")
    person_tags: Mapped[list[GalleryPhotoPersonTag]] = relationship(
        back_populates="gallery_photo",
        cascade="all, delete-orphan",
    )
    tags: Mapped[list[GalleryPhotoTag]] = relationship(back_populates="gallery_photo", cascade="all, delete-orphan")
    promoted_samples: Mapped[list[SamplePhoto]] = relationship(
        back_populates="source_gallery_photo", foreign_keys=[SamplePhoto.source_gallery_photo_id], passive_deletes=True
    )
    similarity_feature: Mapped[GallerySimilarityFeature | None] = relationship(
        back_populates="gallery_photo", cascade="all, delete-orphan", uselist=False
    )
    similarity_memberships: Mapped[list[GallerySimilarityGroupMember]] = relationship(
        back_populates="gallery_photo", cascade="all, delete-orphan"
    )


class GallerySimilarityFeature(Base):
    __tablename__ = "gallery_similarity_features"

    gallery_photo_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_photos.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phash: Mapped[str] = mapped_column(String(64), nullable=False)
    dhash: Mapped[str] = mapped_column(String(64), nullable=False)
    blur_score: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    vector_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    vector_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now, nullable=False
    )

    gallery_photo: Mapped[GalleryPhoto] = relationship(back_populates="similarity_feature")


class GallerySimilarityScan(Base):
    __tablename__ = "gallery_similarity_scans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    person_id: Mapped[int | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    include_cross_type: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    photo_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_pair_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    groups: Mapped[list[GallerySimilarityGroup]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class GallerySimilarityGroup(Base):
    __tablename__ = "gallery_similarity_groups"
    __table_args__ = (UniqueConstraint("scan_id", "ordinal", name="uq_gallery_similarity_group_ordinal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        ForeignKey("gallery_similarity_scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    min_score: Mapped[float] = mapped_column(Float, nullable=False)
    average_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    scan: Mapped[GallerySimilarityScan] = relationship(back_populates="groups")
    members: Mapped[list[GallerySimilarityGroupMember]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    people: Mapped[list[GallerySimilarityGroupPerson]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GallerySimilarityGroupMember(Base):
    __tablename__ = "gallery_similarity_group_members"
    __table_args__ = (UniqueConstraint("group_id", "gallery_photo_id", name="uq_gallery_similarity_group_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_similarity_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gallery_photo_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score_to_representative: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_keep: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    group: Mapped[GallerySimilarityGroup] = relationship(back_populates="members")
    gallery_photo: Mapped[GalleryPhoto] = relationship(back_populates="similarity_memberships")


class GallerySimilarityGroupPerson(Base):
    __tablename__ = "gallery_similarity_group_people"
    __table_args__ = (UniqueConstraint("group_id", "person_id", name="uq_gallery_similarity_group_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_similarity_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    group: Mapped[GallerySimilarityGroup] = relationship(back_populates="people")


class FaceRecord(Base):
    __tablename__ = "face_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    sample_photo_id: Mapped[int | None] = mapped_column(ForeignKey("sample_photos.id", ondelete="CASCADE"), nullable=True)
    gallery_photo_id: Mapped[int | None] = mapped_column(
        ForeignKey("gallery_photos.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    bbox_left: Mapped[float] = mapped_column(Float)
    bbox_top: Mapped[float] = mapped_column(Float)
    bbox_right: Mapped[float] = mapped_column(Float)
    bbox_bottom: Mapped[float] = mapped_column(Float)
    detection_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_person_id: Mapped[int | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    second_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    face_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    vector_collection: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    sample_photo: Mapped[SamplePhoto | None] = relationship(back_populates="faces")
    gallery_photo: Mapped[GalleryPhoto | None] = relationship(back_populates="faces")
    matched_person: Mapped[Person | None] = relationship(back_populates="faces")


class FaceRecognitionCorrection(Base):
    __tablename__ = "face_recognition_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    gallery_photo_id: Mapped[int | None] = mapped_column(ForeignKey("gallery_photos.id", ondelete="SET NULL"), nullable=True, index=True)
    face_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    second_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected_person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    promoted_to_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False, index=True)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    gallery_links: Mapped[list[GalleryPhotoTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")
    person_links: Mapped[list[PersonTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class PersonTag(Base):
    __tablename__ = "person_tags"
    __table_args__ = (UniqueConstraint("person_id", "tag_id", name="uq_person_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    person: Mapped[Person] = relationship(back_populates="labels")
    tag: Mapped[Tag] = relationship(back_populates="person_links")


class GalleryPhotoPersonTag(Base):
    __tablename__ = "gallery_photo_person_tags"
    __table_args__ = (UniqueConstraint("gallery_photo_id", "person_id", name="uq_gallery_photo_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_photo_id: Mapped[int] = mapped_column(ForeignKey("gallery_photos.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    gallery_photo: Mapped[GalleryPhoto] = relationship(back_populates="person_tags")
    person: Mapped[Person] = relationship(back_populates="person_tags")


class GalleryPhotoTag(Base):
    __tablename__ = "gallery_photo_tags"
    __table_args__ = (UniqueConstraint("gallery_photo_id", "tag_id", name="uq_gallery_photo_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_photo_id: Mapped[int] = mapped_column(ForeignKey("gallery_photos.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    gallery_photo: Mapped[GalleryPhoto] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(back_populates="gallery_links")
