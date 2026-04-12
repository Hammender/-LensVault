from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_unknown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    unknown_serial: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    person: Mapped[Person] = relationship(back_populates="sample_photos")
    faces: Mapped[list[FaceRecord]] = relationship(back_populates="sample_photo", cascade="all, delete-orphan")


class GalleryPhoto(Base):
    __tablename__ = "gallery_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class FaceRecord(Base):
    __tablename__ = "face_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    vector_collection: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    sample_photo: Mapped[SamplePhoto | None] = relationship(back_populates="faces")
    gallery_photo: Mapped[GalleryPhoto | None] = relationship(back_populates="faces")
    matched_person: Mapped[Person | None] = relationship(back_populates="faces")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
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


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
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
