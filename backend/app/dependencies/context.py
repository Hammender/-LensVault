from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import User, Workspace, WorkspaceMember
from app.services.auth import decode_access_token


settings = get_settings()
AUTH_COOKIE_NAME = "pictureshow_session"

PERMISSION_FIELDS = (
    "can_add_gallery",
    "can_delete_gallery",
    "can_edit_gallery",
    "can_add_samples",
    "can_delete_samples",
    "can_edit_samples",
    "can_add_videos",
    "can_delete_videos",
    "can_edit_videos",
)

ALL_PERMISSIONS = {field: True for field in PERMISSION_FIELDS}
NO_PERMISSIONS = {field: False for field in PERMISSION_FIELDS}


@dataclass
class CurrentContext:
    user: User
    workspace_id: int
    role: str
    workspace: Workspace
    membership: WorkspaceMember


def ensure_private_workspace(db: Session, user: User) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.kind == "private", Workspace.owner_user_id == user.id))
    if workspace is None:
        workspace = Workspace(name=f"{user.display_name}的私人空间", kind="private", owner_user_id=user.id)
        db.add(workspace)
        db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        db.flush()
    else:
        membership = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if membership is None:
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
            db.flush()
    return workspace


def has_permission(current: CurrentContext, field: str) -> bool:
    if current.role == "owner":
        return True
    return bool(getattr(current.membership, field))


def require_permission(current: CurrentContext, field: str) -> None:
    if not has_permission(current, field):
        raise HTTPException(status_code=403, detail="当前账号没有该操作权限")


def enforce_request_permission(request: Request, current: CurrentContext) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    path = request.url.path
    if path.startswith("/api/auth/") or path.startswith("/api/workspaces") or path.startswith("/api/workspace-invitations"):
        return
    if path in {"/api/gallery/photos/import", "/api/gallery/rich-photos/import", "/api/gallery/photos/import-zip"}:
        require_permission(current, "can_add_gallery")
        return
    if path == "/api/gallery/similarity-scans" and request.method == "POST":
        require_permission(current, "can_edit_gallery")
        return
    if path.startswith("/api/gallery/similarity-scans/"):
        require_permission(current, "can_edit_gallery")
        return
    if path == "/api/gallery/photos/batch-delete" or (path.startswith("/api/gallery/photos") and request.method == "DELETE"):
        require_permission(current, "can_delete_gallery")
        return
    if path.startswith("/api/gallery/photos") or path.startswith("/api/tags"):
        require_permission(current, "can_edit_gallery")
        return
    if path == "/api/persons/import" or (path == "/api/persons" and request.method == "POST") or path.endswith("/samples"):
        require_permission(current, "can_add_samples")
        return
    if path == "/api/persons/batch-delete" or (path.startswith("/api/persons") and request.method == "DELETE"):
        require_permission(current, "can_delete_samples")
        return
    if path.startswith("/api/persons"):
        require_permission(current, "can_edit_samples")
        return
    if path.startswith("/api/videos/upload-sessions"):
        require_permission(current, "can_add_videos")
        return
    if "/subtitles" in path:
        require_permission(current, "can_edit_videos")
        return
    if path.startswith("/api/videos") and request.method == "DELETE":
        require_permission(current, "can_delete_videos")
        return
    if (
        path.startswith("/api/videos")
        or path.startswith("/api/video-category-tags")
        or path.startswith("/api/video-people")
        or path.startswith("/api/subtitle-service")
    ):
        require_permission(current, "can_edit_videos")


def require_context(
    request: Request,
    authorization: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    workspace_id_query: int | None = Query(default=None, alias="workspace_id"),
    x_workspace_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentContext:
    token = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value
    if token is None and request.method in {"GET", "HEAD"}:
        token = session_token
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    user_id = decode_access_token(token, settings.auth_secret_key)
    if user_id is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    ensure_private_workspace(db, user)
    db.commit()
    db.refresh(user)
    memberships = list(user.memberships)
    if not memberships:
        raise HTTPException(status_code=403, detail="账号没有内容空间")
    selected_workspace_id = x_workspace_id if x_workspace_id is not None else workspace_id_query
    if selected_workspace_id is not None:
        membership = next((item for item in memberships if item.workspace_id == selected_workspace_id), None)
        if membership is None:
            raise HTTPException(status_code=403, detail="无权访问该内容空间")
    else:
        membership = sorted(
            memberships,
            key=lambda item: (0 if item.workspace.kind == "private" else 1, item.workspace_id),
        )[0]
    current = CurrentContext(
        user=user,
        workspace_id=membership.workspace_id,
        role=membership.role,
        workspace=membership.workspace,
        membership=membership,
    )
    enforce_request_permission(request, current)
    return current


def require_workspace_owner(current: CurrentContext = Depends(require_context)) -> CurrentContext:
    if current.role != "owner":
        raise HTTPException(status_code=403, detail="需要该内容空间的 owner 权限")
    return current
