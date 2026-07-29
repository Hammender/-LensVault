from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.context import AUTH_COOKIE_NAME, CurrentContext, ensure_private_workspace, require_context
from app.mappers.workspaces import workspaces_to_read
from app.models import User, Workspace, WorkspaceMember
from app.schemas import AuthSession, BootstrapCreate, BootstrapStatus, LoginRequest, RegisterRequest, UserRead
from app.services.auth import create_access_token, hash_password, verify_password
from app.services.face_index import build_face_index_health


router = APIRouter()


def _auth_session(request: Request, db: Session, user: User, selected_workspace_id: int | None = None) -> AuthSession:
    ensure_private_workspace(db, user)
    db.commit()
    db.refresh(user)
    workspaces = workspaces_to_read(db, user)
    selected = next((workspace for workspace in workspaces if workspace.id == selected_workspace_id), None)
    if selected is None:
        selected = workspaces[0]
    settings = request.app.state.settings
    return AuthSession(
        access_token=create_access_token(user.id, settings.auth_secret_key, settings.access_token_expire_minutes),
        user=UserRead.model_validate(user),
        workspace=selected,
        workspaces=workspaces,
    )


def _set_auth_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/api",
    )


def _auth_session_with_cookie(
    request: Request,
    response: Response,
    db: Session,
    user: User,
    selected_workspace_id: int | None = None,
) -> AuthSession:
    session = _auth_session(request, db, user, selected_workspace_id)
    _set_auth_cookie(request, response, session.access_token)
    return session


@router.get("/api/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    face_index = build_face_index_health(db, request.app.state.services.vector_store, request.app.state.settings)
    return {
        "status": "ok" if face_index["status"] == "ok" else "degraded",
        "face_index": face_index,
    }


@router.get("/api/auth/bootstrap-status", response_model=BootstrapStatus)
def get_bootstrap_status(db: Session = Depends(get_db)) -> BootstrapStatus:
    return BootstrapStatus(required=(db.scalar(select(func.count(User.id))) or 0) == 0)


@router.post("/api/auth/bootstrap", response_model=AuthSession)
def bootstrap_admin(
    payload: BootstrapCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSession:
    if db.scalar(select(func.count(User.id))) > 0:
        raise HTTPException(status_code=409, detail="系统已初始化")
    username = payload.username.strip()
    display_name = (payload.display_name or username).strip()
    user = User(username=username, display_name=display_name, password_hash=hash_password(payload.password), is_admin=True)
    workspace_name = (payload.workspace_name or f"{display_name}的私人空间").strip()
    workspace = Workspace(name=workspace_name, kind="private")
    db.add_all([user, workspace])
    db.flush()
    workspace.owner_user_id = user.id
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(user)
    request.app.state.services.pictures.ensure_system_tags(db, workspace.id)
    db.refresh(user)
    return _auth_session_with_cookie(request, response, db, user)


@router.post("/api/auth/login", response_model=AuthSession)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSession:
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return _auth_session_with_cookie(request, response, db, user)


@router.post("/api/auth/register", response_model=AuthSession)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSession:
    if db.scalar(select(func.count(User.id))) == 0:
        raise HTTPException(status_code=409, detail="系统尚未初始化，请先创建管理员")
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    display_name = (payload.display_name or username).strip() or username
    user = User(username=username, display_name=display_name, password_hash=hash_password(payload.password), is_admin=False, is_active=True)
    db.add(user)
    db.flush()
    private_workspace = Workspace(name=f"{display_name}的私人空间", kind="private", owner_user_id=user.id)
    db.add(private_workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=private_workspace.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(user)
    request.app.state.services.pictures.ensure_system_tags(db, private_workspace.id)
    db.refresh(user)
    return _auth_session_with_cookie(request, response, db, user)


@router.get("/api/auth/me", response_model=AuthSession)
def get_current_session(
    request: Request,
    response: Response,
    current: CurrentContext = Depends(require_context),
    db: Session = Depends(get_db),
) -> AuthSession:
    db.refresh(current.user)
    return _auth_session_with_cookie(request, response, db, current.user, current.workspace_id)


@router.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    settings = request.app.state.settings
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/api",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return {"status": "ok"}
