from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    faces: Mapped[list[Face]] = relationship(back_populates="photo", cascade="all, delete-orphan")
    tags: Mapped[list[PhotoTag]] = relationship(back_populates="photo", cascade="all, delete-orphan")


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    embeddings: Mapped[list[PersonEmbedding]] = relationship(back_populates="person", cascade="all, delete-orphan")
    tags: Mapped[list[PhotoTag]] = relationship(back_populates="person", cascade="all, delete-orphan")


class PersonEmbedding(Base):
    __tablename__ = "person_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    source_photo_id: Mapped[int | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    person: Mapped[Person] = relationship(back_populates="embeddings")


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)
    bbox_left: Mapped[float] = mapped_column(Float)
    bbox_top: Mapped[float] = mapped_column(Float)
    bbox_right: Mapped[float] = mapped_column(Float)
    bbox_bottom: Mapped[float] = mapped_column(Float)
    detection_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    matched_person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cluster_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    photo: Mapped[Photo] = relationship(back_populates="faces")


class PhotoTag(Base):
    __tablename__ = "photo_tags"
    __table_args__ = (UniqueConstraint("photo_id", "person_id", name="uq_photo_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    photo: Mapped[Photo] = relationship(back_populates="tags")
    person: Mapped[Person] = relationship(back_populates="tags")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
