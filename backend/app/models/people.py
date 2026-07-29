from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.core.timezones import shanghai_now
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

    person: Mapped[Person] = relationship(back_populates="sample_photos")
    faces: Mapped[list[FaceRecord]] = relationship(back_populates="sample_photo", cascade="all, delete-orphan")
    source_gallery_photo: Mapped[GalleryPhoto | None] = relationship(
        back_populates="promoted_samples", foreign_keys=[source_gallery_photo_id]
    )
