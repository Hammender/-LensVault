from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import User, Workspace, WorkspaceMember
from app.services.auth import decode_access_token


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

# 以 FastAPI 路由模板为键，避免权限判断依赖字符串前缀或动态参数值。
ROUTE_PERMISSION_MATRIX: dict[tuple[str, str], str] = {
    ("POST", "/api/acquisition/sources"): "can_edit_gallery",
    ("PATCH", "/api/acquisition/sources/{source_id}"): "can_edit_gallery",
    ("POST", "/api/acquisition/sources/{source_id}/scripts"): "can_edit_gallery",
    ("DELETE", "/api/acquisition/sources/{source_id}/scripts/{script_key}"): "can_edit_gallery",
    ("DELETE", "/api/acquisition/sources/{source_id}"): "can_edit_gallery",
    ("POST", "/api/acquisition/sources/{source_id}/categories"): "can_edit_gallery",
    ("PATCH", "/api/acquisition/categories/{category_id}"): "can_edit_gallery",
    ("DELETE", "/api/acquisition/categories/{category_id}"): "can_edit_gallery",
    ("POST", "/api/acquisition/categories/{category_id}/runs"): "can_add_gallery",
    ("POST", "/api/acquisition/assets/import"): "can_add_gallery",
    ("POST", "/api/acquisition/assets/reject"): "can_delete_gallery",
    ("POST", "/api/acquisition/similarity/scan"): "can_edit_gallery",
    ("POST", "/api/persons"): "can_add_samples",
    ("POST", "/api/persons/batch-delete"): "can_delete_samples",
    ("POST", "/api/persons/import"): "can_add_samples",
    ("PATCH", "/api/persons/{person_id}"): "can_edit_samples",
    ("POST", "/api/persons/{person_id}/rename"): "can_edit_samples",
    ("DELETE", "/api/persons/{person_id}"): "can_delete_samples",
    ("POST", "/api/persons/{person_id}/tags"): "can_edit_samples",
    ("DELETE", "/api/persons/{person_id}/tags/{tag_id}"): "can_delete_samples",
    ("POST", "/api/persons/{person_id}/samples"): "can_add_samples",
    ("DELETE", "/api/persons/{person_id}/samples/{sample_photo_id}"): "can_delete_samples",
    ("POST", "/api/tags"): "can_edit_gallery",
    ("PATCH", "/api/tags/{tag_id}"): "can_edit_gallery",
    ("DELETE", "/api/tags/{tag_id}"): "can_edit_gallery",
    ("POST", "/api/gallery/photos/import"): "can_add_gallery",
    ("POST", "/api/gallery/rich-photos/import"): "can_add_gallery",
    ("POST", "/api/gallery/photos/import-zip"): "can_add_gallery",
    ("POST", "/api/gallery/similarity-scans"): "can_edit_gallery",
    ("PATCH", "/api/gallery/similarity-scans/{scan_id}/groups/{group_id}"): "can_edit_gallery",
    ("POST", "/api/gallery/photos/batch-delete"): "can_delete_gallery",
    ("DELETE", "/api/gallery/photos/{photo_id}"): "can_delete_gallery",
    ("POST", "/api/gallery/photos/{photo_id}/persons"): "can_edit_gallery",
    ("POST", "/api/gallery/photos/{photo_id}/persons/{person_id}/sample"): "can_edit_gallery",
    ("DELETE", "/api/gallery/photos/{photo_id}/persons/{person_id}/sample"): "can_delete_gallery",
    ("DELETE", "/api/gallery/photos/{photo_id}/persons/{person_id}"): "can_delete_gallery",
    ("POST", "/api/gallery/photos/{photo_id}/tags"): "can_edit_gallery",
    ("DELETE", "/api/gallery/photos/{photo_id}/tags/{tag_id}"): "can_delete_gallery",
    ("PATCH", "/api/gallery/photos/{photo_id}/rich-text"): "can_edit_gallery",
    ("POST", "/api/gallery/photos/{photo_id}/re-recognize"): "can_edit_gallery",
    ("POST", "/api/gallery/photos/re-recognize-unknown"): "can_edit_gallery",
    ("POST", "/api/video-category-tags"): "can_edit_videos",
    ("PATCH", "/api/video-category-tags/{tag_id}"): "can_edit_videos",
    ("DELETE", "/api/video-category-tags/{tag_id}"): "can_edit_videos",
    ("POST", "/api/video-people"): "can_edit_videos",
    ("PATCH", "/api/video-people/{person_id}"): "can_edit_videos",
    ("DELETE", "/api/video-people/{person_id}"): "can_edit_videos",
    ("POST", "/api/videos/upload-sessions"): "can_add_videos",
    ("PUT", "/api/videos/upload-sessions/{session_id}/parts/{part_index}"): "can_add_videos",
    ("POST", "/api/videos/upload-sessions/{session_id}/complete"): "can_add_videos",
    ("DELETE", "/api/videos/upload-sessions/{session_id}"): "can_add_videos",
    ("POST", "/api/videos/{video_id}/optimize-playback"): "can_edit_videos",
    ("POST", "/api/videos/{video_id}/subtitles/generate"): "can_edit_videos",
    ("POST", "/api/videos/{video_id}/subtitles/{track_id}/cancel"): "can_edit_videos",
    ("PATCH", "/api/videos/{video_id}/subtitles/{track_id}"): "can_edit_videos",
    ("DELETE", "/api/videos/{video_id}/subtitles/{track_id}"): "can_edit_videos",
    ("PATCH", "/api/videos/{video_id}"): "can_edit_videos",
    ("DELETE", "/api/videos/{video_id}"): "can_delete_videos",
    ("PUT", "/api/videos/{video_id}/cover"): "can_edit_videos",
    ("POST", "/api/videos/{video_id}/category-tags"): "can_edit_videos",
    ("DELETE", "/api/videos/{video_id}/category-tags/{tag_id}"): "can_delete_videos",
    ("POST", "/api/videos/{video_id}/people"): "can_edit_videos",
    ("DELETE", "/api/videos/{video_id}/people/{person_id}"): "can_delete_videos",
    ("POST", "/api/subtitle-service/start"): "can_edit_videos",
    ("POST", "/api/subtitle-service/stop"): "can_edit_videos",
}


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
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    permission = ROUTE_PERMISSION_MATRIX.get((request.method, route_path))
    if permission is not None:
        require_permission(current, permission)


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
    app = request.scope.get("app")
    settings = app.state.settings if app is not None else get_settings()
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
