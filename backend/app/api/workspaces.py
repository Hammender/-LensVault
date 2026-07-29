from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.context import PERMISSION_FIELDS, CurrentContext, ensure_private_workspace, require_context, require_workspace_owner
from app.mappers.workspaces import invitation_to_read, member_to_read, workspace_to_read, workspaces_to_read
from app.models import User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.schemas import AdminUserCreate, UserRead, WorkspaceCreate, WorkspaceInvitationCreate, WorkspaceInvitationRead, WorkspaceMemberRead, WorkspacePermissionUpdate, WorkspaceRead, WorkspaceUpdate
from app.services.auth import hash_password


router = APIRouter()


def _permission_kwargs(payload: WorkspacePermissionUpdate | WorkspaceInvitationCreate) -> dict[str, bool]:
    return {field: bool(getattr(payload, field)) for field in PERMISSION_FIELDS}


def _apply_permissions(target: WorkspaceMember | WorkspaceInvitation, permissions: dict[str, bool]) -> None:
    for field, value in permissions.items():
        setattr(target, field, bool(value))


def _owner_count(db: Session, workspace_id: int) -> int:
    return db.scalar(select(func.count(WorkspaceMember.id)).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")) or 0


def _require_shared_workspace_owner(current: CurrentContext) -> None:
    if current.workspace.kind != "shared":
        raise HTTPException(status_code=400, detail="私人空间不能添加或邀请其他账号")
    if current.role != "owner":
        raise HTTPException(status_code=403, detail="需要该内容空间的 owner 权限")


@router.get("/api/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> list[WorkspaceRead]:
    db.refresh(current.user)
    return workspaces_to_read(db, current.user)


@router.post("/api/workspaces", response_model=WorkspaceRead)
def create_workspace(payload: WorkspaceCreate, request: Request, current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> WorkspaceRead:
    workspace = Workspace(name=payload.name.strip(), kind="shared", owner_user_id=current.user.id)
    db.add(workspace)
    db.flush()
    membership = WorkspaceMember(workspace_id=workspace.id, user_id=current.user.id, role="owner")
    db.add(membership)
    db.commit()
    db.refresh(membership)
    request.app.state.services.pictures.ensure_system_tags(db, workspace.id)
    return workspace_to_read(membership)


@router.patch("/api/workspaces/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(workspace_id: int, payload: WorkspaceUpdate, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> WorkspaceRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    current.workspace.name = payload.name.strip()
    db.commit()
    db.refresh(current.membership)
    return workspace_to_read(current.membership)


@router.get("/api/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
def list_workspace_members(workspace_id: int, current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> list[WorkspaceMemberRead]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权访问该内容空间")
    members = db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id).order_by(WorkspaceMember.role.desc(), WorkspaceMember.id.asc())).all()
    return [member_to_read(member) for member in members]


@router.patch("/api/workspaces/{workspace_id}/members/{member_id}", response_model=WorkspaceMemberRead)
def update_workspace_member(workspace_id: int, member_id: int, payload: WorkspacePermissionUpdate, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> WorkspaceMemberRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="owner 拥有全部权限，不需要配置")
    _apply_permissions(member, _permission_kwargs(payload))
    db.commit(); db.refresh(member)
    return member_to_read(member)


@router.delete("/api/workspaces/{workspace_id}/members/{member_id}")
def remove_workspace_member(workspace_id: int, member_id: int, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> dict[str, str]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == "owner" and _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status_code=400, detail="不能移除最后一个 owner")
    db.delete(member); db.commit()
    return {"status": "ok"}


@router.post("/api/workspaces/{workspace_id}/leave")
def leave_workspace(workspace_id: int, current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> dict[str, str]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="只能退出当前内容空间")
    if current.workspace.kind == "private":
        raise HTTPException(status_code=400, detail="不能退出自己的私人空间")
    if current.role == "owner" and _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status_code=400, detail="不能退出最后一个 owner 所在空间")
    db.delete(current.membership); db.commit()
    return {"status": "ok"}


@router.post("/api/workspaces/{workspace_id}/invitations", response_model=WorkspaceInvitationRead)
def invite_workspace_member(workspace_id: int, payload: WorkspaceInvitationCreate, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> WorkspaceInvitationRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    invitee = db.scalar(select(User).where(User.username == payload.username.strip()))
    if invitee is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == invitee.id)) is not None:
        raise HTTPException(status_code=409, detail="该账号已经在此内容空间中")
    existing = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == workspace_id, WorkspaceInvitation.invitee_user_id == invitee.id, WorkspaceInvitation.status == "pending"))
    if existing is not None:
        raise HTTPException(status_code=409, detail="该账号已有待处理邀请")
    invitation = WorkspaceInvitation(workspace_id=workspace_id, inviter_user_id=current.user.id, invitee_user_id=invitee.id, role="member")
    _apply_permissions(invitation, _permission_kwargs(payload))
    db.add(invitation); db.commit(); db.refresh(invitation)
    return invitation_to_read(invitation)


@router.get("/api/workspace-invitations", response_model=list[WorkspaceInvitationRead])
def list_my_workspace_invitations(current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> list[WorkspaceInvitationRead]:
    invitations = db.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.invitee_user_id == current.user.id, WorkspaceInvitation.status == "pending").order_by(WorkspaceInvitation.created_at.desc())).all()
    return [invitation_to_read(invitation) for invitation in invitations]


@router.post("/api/workspace-invitations/{invitation_id}/accept", response_model=WorkspaceRead)
def accept_workspace_invitation(invitation_id: int, current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> WorkspaceRead:
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.invitee_user_id != current.user.id or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="邀请不存在")
    if invitation.workspace.kind != "shared":
        raise HTTPException(status_code=400, detail="该内容空间不能加入")
    existing = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == invitation.workspace_id, WorkspaceMember.user_id == current.user.id))
    if existing is not None:
        invitation.status = "accepted"; db.commit(); db.refresh(existing)
        return workspace_to_read(existing)
    membership = WorkspaceMember(workspace_id=invitation.workspace_id, user_id=current.user.id, role=invitation.role)
    _apply_permissions(membership, {field: bool(getattr(invitation, field)) for field in PERMISSION_FIELDS})
    invitation.status = "accepted"; db.add(membership); db.commit(); db.refresh(membership)
    return workspace_to_read(membership)


@router.post("/api/workspace-invitations/{invitation_id}/decline")
def decline_workspace_invitation(invitation_id: int, current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> dict[str, str]:
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.invitee_user_id != current.user.id or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="邀请不存在")
    invitation.status = "declined"; db.commit()
    return {"status": "ok"}


@router.delete("/api/workspaces/{workspace_id}/invitations/{invitation_id}")
def revoke_workspace_invitation(workspace_id: int, invitation_id: int, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> dict[str, str]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.workspace_id != workspace_id or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="邀请不存在")
    invitation.status = "revoked"; db.commit()
    return {"status": "ok"}


@router.post("/api/workspaces/{workspace_id}/users", response_model=UserRead)
def create_workspace_user(workspace_id: int, payload: AdminUserCreate, request: Request, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> UserRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    username = payload.username.strip()
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(username=username, display_name=(payload.display_name or username).strip(), password_hash=hash_password(payload.password), is_admin=False)
    db.add(user); db.flush()
    private_workspace = ensure_private_workspace(db, user)
    shared_membership = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="member")
    _apply_permissions(shared_membership, _permission_kwargs(payload))
    db.add(shared_membership); db.commit(); db.refresh(user)
    request.app.state.services.pictures.ensure_system_tags(db, private_workspace.id)
    return UserRead.model_validate(user)


@router.post("/api/admin/users", response_model=UserRead)
def create_user(payload: AdminUserCreate, request: Request, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> UserRead:
    if current.workspace.kind != "shared":
        raise HTTPException(status_code=400, detail="请在共享内容空间中创建成员账号")
    return create_workspace_user(current.workspace_id, payload, request, current, db)
