from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies.context import ALL_PERMISSIONS, PERMISSION_FIELDS
from app.models import User, WorkspaceInvitation, WorkspaceMember
from app.schemas import WorkspaceInvitationRead, WorkspaceMemberRead, WorkspaceRead, UserRead


def permission_dict(membership: WorkspaceMember) -> dict[str, bool]:
    if membership.role == "owner":
        return dict(ALL_PERMISSIONS)
    return {field: bool(getattr(membership, field)) for field in PERMISSION_FIELDS}


def workspace_to_read(membership: WorkspaceMember) -> WorkspaceRead:
    workspace = membership.workspace
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        kind=workspace.kind,
        role=membership.role,
        permissions=permission_dict(membership),
        can_leave=workspace.kind == "shared" and membership.role != "owner",
    )


def workspaces_to_read(db: Session, user: User) -> list[WorkspaceRead]:
    db.expire(user, ["memberships"])
    user_memberships = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).all()
    memberships = sorted(
        (membership for membership in user_memberships if membership.workspace is not None),
        key=lambda item: (0 if item.workspace.kind == "private" else 1, item.workspace.id),
    )
    return [workspace_to_read(membership) for membership in memberships]


def member_to_read(membership: WorkspaceMember) -> WorkspaceMemberRead:
    return WorkspaceMemberRead(
        id=membership.id,
        user=UserRead.model_validate(membership.user),
        role=membership.role,
        permissions=permission_dict(membership),
        created_at=membership.created_at,
    )


def invitation_to_read(invitation: WorkspaceInvitation) -> WorkspaceInvitationRead:
    return WorkspaceInvitationRead(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        workspace_name=invitation.workspace.name,
        inviter_username=invitation.inviter.username,
        invitee_username=invitation.invitee.username,
        status=invitation.status,
        role=invitation.role,
        permissions={field: bool(getattr(invitation, field)) for field in PERMISSION_FIELDS},
        created_at=invitation.created_at,
    )
