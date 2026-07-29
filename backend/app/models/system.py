from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.core.timezones import shanghai_now
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        onupdate=shanghai_now,
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="invitations")
    inviter: Mapped[User] = relationship(foreign_keys=[inviter_user_id])
    invitee: Mapped[User] = relationship(foreign_keys=[invitee_user_id])
