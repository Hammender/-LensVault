from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    memberships: Mapped[list[WorkspaceMember]] = relationship(back_populates="user", cascade="all, delete-orphan")
    owned_workspaces: Mapped[list[Workspace]] = relationship(back_populates="owner", foreign_keys="Workspace.owner_user_id")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="private", nullable=False, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    owner: Mapped[User | None] = relationship(back_populates="owned_workspaces", foreign_keys=[owner_user_id])
    invitations: Mapped[list[WorkspaceInvitation]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    can_add_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_add_samples: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete_samples: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_samples: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_add_videos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete_videos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_videos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    inviter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    invitee_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    can_add_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_add_samples: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete_samples: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_samples: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_add_videos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete_videos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_videos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="invitations")
    inviter: Mapped[User] = relationship(foreign_keys=[inviter_user_id])
    invitee: Mapped[User] = relationship(foreign_keys=[invitee_user_id])


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_persons_workspace_name"),
        UniqueConstraint("workspace_id", "unknown_serial", name="uq_persons_workspace_unknown_serial"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    display_name: Mapped[str] = mapped_column(String(256), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_unknown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    unknown_serial: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    sample_photos: Mapped[list[SamplePhoto]] = relationship(back_populates="person", cascade="all, delete-orphan")
    person_tags: Mapped[list[GalleryPhotoPersonTag]] = relationship(back_populates="person", cascade="all, delete-orphan")
    labels: Mapped[list[PersonTag]] = relationship(back_populates="person", cascade="all, delete-orphan")
    faces: Mapped[list[FaceRecord]] = relationship(back_populates="matched_person")


class SamplePhoto(Base):
    __tablename__ = "sample_photos"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_sample_photos_workspace_sha256"),
        UniqueConstraint("person_id", "source_gallery_photo_id", name="uq_sample_person_source_gallery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    quality_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="upload", nullable=False, index=True)
    source_gallery_photo_id: Mapped[int | None] = mapped_column(
        ForeignKey("gallery_photos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    person: Mapped[Person] = relationship(back_populates="sample_photos")
    faces: Mapped[list[FaceRecord]] = relationship(back_populates="sample_photo", cascade="all, delete-orphan")
    source_gallery_photo: Mapped[GalleryPhoto | None] = relationship(
        back_populates="promoted_samples", foreign_keys=[source_gallery_photo_id]
    )


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    gallery_links: Mapped[list[GalleryPhotoTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")
    person_links: Mapped[list[PersonTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class PersonTag(Base):
    __tablename__ = "person_tags"
    __table_args__ = (UniqueConstraint("person_id", "tag_id", name="uq_person_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    person: Mapped[Person] = relationship(back_populates="labels")
    tag: Mapped[Tag] = relationship(back_populates="person_links")


class GalleryPhotoPersonTag(Base):
    __tablename__ = "gallery_photo_person_tags"
    __table_args__ = (UniqueConstraint("gallery_photo_id", "person_id", name="uq_gallery_photo_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_photo_id: Mapped[int] = mapped_column(ForeignKey("gallery_photos.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    gallery_photo: Mapped[GalleryPhoto] = relationship(back_populates="person_tags")
    person: Mapped[Person] = relationship(back_populates="person_tags")


class GalleryPhotoTag(Base):
    __tablename__ = "gallery_photo_tags"
    __table_args__ = (UniqueConstraint("gallery_photo_id", "tag_id", name="uq_gallery_photo_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_photo_id: Mapped[int] = mapped_column(ForeignKey("gallery_photos.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    gallery_photo: Mapped[GalleryPhoto] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(back_populates="gallery_links")


class VideoItem(Base):
    __tablename__ = "video_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "filename", "size_bytes", name="uq_video_items_workspace_filename_size"),
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
    faststart_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seek_optimized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seek_optimized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seek_keyframe_interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    video_links: Mapped[list[VideoItemPerson]] = relationship(back_populates="person", cascade="all, delete-orphan")


class VideoItemCategoryTag(Base):
    __tablename__ = "video_item_category_tags"
    __table_args__ = (UniqueConstraint("video_id", "tag_id", name="uq_video_item_category_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video_items.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("video_category_tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    video: Mapped[VideoItem] = relationship(back_populates="category_links")
    tag: Mapped[VideoCategoryTag] = relationship(back_populates="video_links")


class VideoItemPerson(Base):
    __tablename__ = "video_item_people"
    __table_args__ = (UniqueConstraint("video_id", "person_id", name="uq_video_item_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video_items.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("video_people.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    session: Mapped[VideoUploadSession] = relationship(back_populates="parts")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class UploadHistory(Base):
    __tablename__ = "upload_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    upload_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # "gallery" | "rich"
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
