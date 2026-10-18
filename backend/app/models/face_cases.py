from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezones import shanghai_now
from app.db import Base


class FaceRecognitionCase(Base):
    __tablename__ = "face_recognition_cases"
    __table_args__ = (UniqueConstraint("workspace_id", "recognition_key", name="uq_face_case_recognition"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_photo_id: Mapped[int | None] = mapped_column(ForeignKey("gallery_photos.id", ondelete="SET NULL"), index=True)
    source_face_id: Mapped[int] = mapped_column(Integer)
    correct_person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    correct_person_name: Mapped[str] = mapped_column(String(256))
    answer_type: Mapped[str] = mapped_column(String(32), default="known_person", server_default="known_person", index=True)
    excluded_person_id: Mapped[int | None] = mapped_column(
        ForeignKey("persons.id", ondelete="SET NULL", name="fk_face_cases_excluded_person"), nullable=True,
    )
    excluded_person_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(32), index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    recognition_key: Mapped[str] = mapped_column(String(64))
    embedding_version: Mapped[str | None] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="active")
    cleanup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
