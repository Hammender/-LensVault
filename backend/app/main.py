from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from io import BytesIO
import logging
from urllib.parse import quote, urlparse

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import (
    FaceRecord,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GalleryPhotoTag,
    Person,
    PersonTag,
    SamplePhoto,
    Tag,
    Task,
    UploadHistory,
    User,
    VideoCategoryTag,
    VideoItem,
    VideoItemCategoryTag,
    VideoItemPerson,
    VideoPerson,
    VideoSubtitleTrack,
    VideoUploadSession,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
)
from app.schemas import (
    AdminUserCreate,
    AuthSession,
    BootstrapCreate,
    BootstrapStatus,
    FaceRead,
    GalleryPersonTagRead,
    GalleryPhotoDetail,
    GalleryPhotoListItem,
    GalleryPhotoBatchDeleteRequest,
    GalleryPhotoRichTextUpdate,
    GalleryPhotoPersonTagCreate,
    GalleryPhotoTagCreate,
    GalleryTagRead,
    EmbeddedSubtitleStreamRead,
    ImportSubtitleFromVideoRequest,
    LoginRequest,
    PaginatedGalleryPhotos,
    PersonBatchDeleteRequest,
    PersonCreate,
    PersonRead,
    PersonRenameRequest,
    PersonStatistics,
    PersonTagCreate,
    PersonUpdate,
    RegisterRequest,
    SamplePhotoRead,
    SubtitleJobRead,
    SubtitleServiceLogs,
    SubtitleServiceStatus,
    TagCreate,
    TagRead,
    TagStatistics,
    TagUpdate,
    TaskRead,
    UploadHistoryRead,
    UserRead,
    PaginatedVideos,
    VideoCategoryTagCreate,
    VideoCategoryTagRead,
    VideoCategoryTagUpdate,
    VideoItemDetail,
    VideoItemListItem,
    VideoMetadataUpdate,
    VideoPersonBindCreate,
    VideoPersonRead,
    VideoPersonUpdate,
    VideoSubtitleTrackRead,
    VideoSubtitleTrackUpdate,
    VideoTagBindCreate,
    VideoUploadCompleteRequest,
    VideoUploadPartRead,
    VideoUploadSessionCreate,
    VideoUploadSessionRead,
    WorkspaceCreate,
    WorkspaceInvitationCreate,
    WorkspaceInvitationRead,
    WorkspaceMemberRead,
    WorkspacePermissionUpdate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.services.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.services.face import FaceService
from app.services.importer import PictureService
from app.services.milvus import MilvusVectorStore
from app.services.ocr import OcrService
from app.services.storage import MinioStorage
from app.services.subtitles import SubtitleService
from app.services.tasks import create_task, fail_incomplete_tasks, update_task
from app.services.videos import VideoService

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
logger = logging.getLogger(__name__)
logging.getLogger("app").setLevel(logging.INFO)

settings = get_settings()
Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = MinioStorage(settings)
face_service = FaceService(settings)
vector_store = MilvusVectorStore(settings)
ocr_service = OcrService()
picture_service = PictureService(storage, face_service, vector_store, ocr_service, settings)
video_service = VideoService(storage)
subtitle_service = SubtitleService(storage, settings)


@dataclass
class CurrentContext:
    user: User
    workspace_id: int
    role: str
    workspace: Workspace
    membership: WorkspaceMember


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


def _permission_dict(membership: WorkspaceMember) -> dict[str, bool]:
    if membership.role == "owner":
        return dict(ALL_PERMISSIONS)
    return {field: bool(getattr(membership, field)) for field in PERMISSION_FIELDS}


def _permission_kwargs(payload: WorkspacePermissionUpdate | WorkspaceInvitationCreate) -> dict[str, bool]:
    return {field: bool(getattr(payload, field)) for field in PERMISSION_FIELDS}


def _apply_permissions(target: WorkspaceMember | WorkspaceInvitation, permissions: dict[str, bool]) -> None:
    for field, value in permissions.items():
        setattr(target, field, bool(value))


def _workspace_read(membership: WorkspaceMember) -> WorkspaceRead:
    workspace = membership.workspace
    can_leave = workspace.kind == "shared" and membership.role != "owner"
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        kind=workspace.kind,
        role=membership.role,
        permissions=_permission_dict(membership),
        can_leave=can_leave,
    )


def _workspace_reads(db: Session, user: User) -> list[WorkspaceRead]:
    db.expire(user, ["memberships"])
    user_memberships = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).all()
    memberships = sorted(
        (membership for membership in user_memberships if membership.workspace is not None),
        key=lambda item: (0 if item.workspace.kind == "private" else 1, item.workspace.id),
    )
    return [_workspace_read(membership) for membership in memberships]


def _ensure_private_workspace(db: Session, user: User) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.kind == "private", Workspace.owner_user_id == user.id))
    if workspace is None:
        workspace = Workspace(name=f"{user.display_name}的私人空间", kind="private", owner_user_id=user.id)
        db.add(workspace)
        db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        db.flush()
    else:
        membership = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id))
        if membership is None:
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
            db.flush()
    return workspace


def _auth_session(db: Session, user: User, selected_workspace_id: int | None = None) -> AuthSession:
    _ensure_private_workspace(db, user)
    db.commit()
    db.refresh(user)
    workspaces = _workspace_reads(db, user)
    selected = next((workspace for workspace in workspaces if workspace.id == selected_workspace_id), None)
    if selected is None:
        selected = workspaces[0]
    token = create_access_token(user.id, settings.auth_secret_key, settings.access_token_expire_minutes)
    return AuthSession(
        access_token=token,
        user=UserRead.model_validate(user),
        workspace=selected,
        workspaces=workspaces,
    )


def require_context(
    request: Request,
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None),
    workspace_id_query: int | None = Query(default=None, alias="workspace_id"),
    x_workspace_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentContext:
    token = access_token
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    user_id = decode_access_token(token, settings.auth_secret_key)
    if user_id is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    _ensure_private_workspace(db, user)
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
        membership = sorted(memberships, key=lambda item: (0 if item.workspace.kind == "private" else 1, item.workspace_id))[0]
    current = CurrentContext(user=user, workspace_id=membership.workspace_id, role=membership.role, workspace=membership.workspace, membership=membership)
    _enforce_request_permission(request, current)
    return current


def _has_permission(current: CurrentContext, field: str) -> bool:
    if current.role == "owner":
        return True
    return bool(getattr(current.membership, field))


def _require_permission(current: CurrentContext, field: str) -> None:
    if not _has_permission(current, field):
        raise HTTPException(status_code=403, detail="当前账号没有该操作权限")


def _enforce_request_permission(request: Request, current: CurrentContext) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    path = request.url.path
    if path.startswith("/api/auth/") or path.startswith("/api/workspaces") or path.startswith("/api/workspace-invitations"):
        return
    if path in {"/api/gallery/photos/import", "/api/gallery/rich-photos/import", "/api/gallery/photos/import-zip"}:
        _require_permission(current, "can_add_gallery")
        return
    if path == "/api/gallery/photos/batch-delete" or (path.startswith("/api/gallery/photos") and request.method == "DELETE"):
        _require_permission(current, "can_delete_gallery")
        return
    if path.startswith("/api/gallery/photos") or path.startswith("/api/tags"):
        _require_permission(current, "can_edit_gallery")
        return
    if path == "/api/persons/import" or (path == "/api/persons" and request.method == "POST") or path.endswith("/samples"):
        _require_permission(current, "can_add_samples")
        return
    if path == "/api/persons/batch-delete" or (path.startswith("/api/persons") and request.method == "DELETE"):
        _require_permission(current, "can_delete_samples")
        return
    if path.startswith("/api/persons"):
        _require_permission(current, "can_edit_samples")
        return
    if path.startswith("/api/videos/upload-sessions"):
        _require_permission(current, "can_add_videos")
        return
    if "/subtitles" in path:
        _require_permission(current, "can_edit_videos")
        return
    if path.startswith("/api/videos") and request.method == "DELETE":
        _require_permission(current, "can_delete_videos")
        return
    if path.startswith("/api/videos") or path.startswith("/api/video-category-tags") or path.startswith("/api/video-people") or path.startswith("/api/subtitle-service"):
        _require_permission(current, "can_edit_videos")
        return


def require_workspace_owner(current: CurrentContext = Depends(require_context)) -> CurrentContext:
    if current.role != "owner":
        raise HTTPException(status_code=403, detail="需要该内容空间的 owner 权限")
    return current


def _get_workspace_object(db: Session, model, object_id: int, workspace_id: int, label: str):
    item = db.get(model, object_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item


def _member_to_read(membership: WorkspaceMember) -> WorkspaceMemberRead:
    return WorkspaceMemberRead(
        id=membership.id,
        user=UserRead.model_validate(membership.user),
        role=membership.role,
        permissions=_permission_dict(membership),
        created_at=membership.created_at,
    )


def _invitation_to_read(invitation: WorkspaceInvitation) -> WorkspaceInvitationRead:
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


def _owner_count(db: Session, workspace_id: int) -> int:
    return db.scalar(
        select(func.count(WorkspaceMember.id)).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
    ) or 0


def _require_shared_workspace_owner(current: CurrentContext) -> None:
    if current.workspace.kind != "shared":
        raise HTTPException(status_code=400, detail="私人空间不能添加或邀请其他账号")
    if current.role != "owner":
        raise HTTPException(status_code=403, detail="需要该内容空间的 owner 权限")


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Application startup begin")
    storage.ensure_bucket()
    vector_store.ensure_collections()
    face_service.warmup()
    ocr_status = ocr_service.engine_status()
    logger.info(
        "OCR engines status rapidocr_ready=%s tesseract_ready=%s rapidocr_error=%s tesseract_error=%s",
        ocr_status["rapidocr_ready"],
        ocr_status["tesseract_ready"],
        ocr_status["rapidocr_error"] or "-",
        ocr_status["tesseract_error"] or "-",
    )
    db = SessionLocal()
    try:
        for workspace in db.scalars(select(Workspace)).all():
            picture_service.ensure_system_tags(db, workspace.id)
        recovered = fail_incomplete_tasks(db, "gallery_import")
        recovered += fail_incomplete_tasks(db, "gallery_rich_import")
        recovered += fail_incomplete_tasks(db, "gallery_zip_import")
        recovered += fail_incomplete_tasks(db, "person_import")
        recovered += fail_incomplete_tasks(db, "video_subtitle_generation")
        if recovered > 0:
            logger.warning("Recovered interrupted gallery tasks count=%d", recovered)
    finally:
        db.close()
    logger.info(
        "Startup dependencies ready minio_bucket=%s milvus_known=%s milvus_unknown=%s",
        settings.minio_bucket,
        settings.milvus_known_collection,
        settings.milvus_unknown_collection,
    )


def _gallery_photo_to_list_item(photo: GalleryPhoto) -> GalleryPhotoListItem:
    persons = [
        GalleryPersonTagRead(
            person_id=tag.person_id,
            person_name=tag.person.display_name,
            is_unknown=tag.person.is_unknown,
            source=tag.source,
        )
        for tag in sorted(photo.person_tags, key=lambda item: (item.person.is_unknown, item.person.display_name.lower()))
    ]
    tags = [
        GalleryTagRead(id=item.tag.id, name=item.tag.name, is_system=item.tag.is_system)
        for item in sorted(photo.tags, key=lambda link: link.tag.name.lower())
    ]
    return GalleryPhotoListItem(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        is_rich_text=photo.is_rich_text,
        rich_text=photo.rich_text,
        ocr_status=photo.ocr_status,
        persons=persons,
        tags=tags,
        thumbnail_url=f"/api/gallery/photos/{photo.id}/thumbnail",
        original_url=f"/api/gallery/photos/{photo.id}/original",
    )


def _gallery_photo_to_detail(photo: GalleryPhoto) -> GalleryPhotoDetail:
    item = _gallery_photo_to_list_item(photo)
    faces = [
        FaceRead(
            id=face.id,
            bbox_left=face.bbox_left,
            bbox_top=face.bbox_top,
            bbox_right=face.bbox_right,
            bbox_bottom=face.bbox_bottom,
            matched_person_id=face.matched_person_id,
            match_score=face.match_score,
            needs_review=face.needs_review,
            vector_collection=face.vector_collection,
        )
        for face in photo.faces
    ]
    return GalleryPhotoDetail(
        **item.model_dump(),
        faces=faces,
        created_at=photo.created_at,
        content_type=photo.content_type,
    )


def _video_person_to_read(person: VideoPerson) -> VideoPersonRead:
    return VideoPersonRead(
        id=person.id,
        name=person.name,
        note=person.note,
        avatar_url=f"/api/video-people/{person.id}/avatar" if person.avatar_object_key else None,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


def _video_category_to_read(tag: VideoCategoryTag) -> VideoCategoryTagRead:
    return VideoCategoryTagRead.model_validate(tag)


def _video_stream_url(video: VideoItem) -> str:
    return f"/api/videos/{video.id}/stream"


def _video_play_url(video: VideoItem) -> str:
    return f"/api/videos/{video.id}/play"


def _video_cover_url(video: VideoItem) -> str | None:
    if not video.cover_object_key:
        return None
    return f"/api/videos/{video.id}/cover"


def _subtitle_to_read(track: VideoSubtitleTrack) -> VideoSubtitleTrackRead:
    vtt_url = None
    if track.status == "ready" and track.content_vtt:
        vtt_url = f"/api/videos/{track.video_id}/subtitles/{track.id}.vtt"
    return VideoSubtitleTrackRead(
        id=track.id,
        video_id=track.video_id,
        language=track.language,
        label=track.label,
        source_language=track.source_language,
        provider=track.provider,
        status=track.status,
        error_message=track.error_message,
        task_id=track.task_id,
        generated_at=track.generated_at,
        created_at=track.created_at,
        updated_at=track.updated_at,
        vtt_url=vtt_url,
    )


def _video_to_list_item(video: VideoItem) -> VideoItemListItem:
    categories = sorted((link.tag for link in video.category_links), key=lambda item: item.name.lower())
    people = sorted((link.person for link in video.person_links), key=lambda item: item.name.lower())
    subtitle_tracks = sorted(video.subtitle_tracks, key=lambda item: item.created_at)
    return VideoItemListItem(
        id=video.id,
        title=video.title,
        description=video.description,
        filename=video.filename,
        content_type=video.content_type,
        size_bytes=video.size_bytes,
        duration_seconds=video.duration_seconds,
        width=video.width,
        height=video.height,
        original_video_codec=video.original_video_codec,
        original_audio_codec=video.original_audio_codec,
        video_codec=video.video_codec,
        audio_codec=video.audio_codec,
        status=video.status,
        category_tags=[_video_category_to_read(tag) for tag in categories],
        people=[_video_person_to_read(person) for person in people],
        stream_url=_video_stream_url(video),
        play_url=_video_play_url(video),
        cover_url=_video_cover_url(video),
        faststart_applied=video.faststart_applied,
        processed_at=video.processed_at,
        processing_error=video.processing_error,
        subtitle_tracks=[_subtitle_to_read(track) for track in subtitle_tracks],
        created_at=video.created_at,
        updated_at=video.updated_at,
    )


def _video_to_detail(video: VideoItem) -> VideoItemDetail:
    item = _video_to_list_item(video)
    return VideoItemDetail(**item.model_dump(), sha256=video.sha256)


def _video_session_to_read(session: VideoUploadSession) -> VideoUploadSessionRead:
    uploaded_parts = sorted(part.part_index for part in session.parts)
    return VideoUploadSessionRead(
        id=session.id,
        filename=session.filename,
        title=session.title,
        description=session.description,
        content_type=session.content_type,
        size_bytes=session.size_bytes,
        part_size=session.part_size,
        total_parts=session.total_parts,
        uploaded_parts=uploaded_parts,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _parse_range_header(range_header: str | None, size: int) -> tuple[int, int] | None:
    if not range_header:
        return None
    unit, _, range_value = range_header.partition("=")
    if unit.strip().lower() != "bytes" or "," in range_value:
        raise HTTPException(status_code=416, detail="Invalid range", headers={"Content-Range": f"bytes */{size}"})
    start_text, _, end_text = range_value.partition("-")
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid range", headers={"Content-Range": f"bytes */{size}"}) from exc
    if start < 0 or end < start or start >= size:
        raise HTTPException(status_code=416, detail="Invalid range", headers={"Content-Range": f"bytes */{size}"})
    return start, min(end, size - 1)


def _iter_minio_response(response, chunk_size: int = 1024 * 1024):
    try:
        for chunk in response.stream(chunk_size):
            yield chunk
    finally:
        response.close()
        response.release_conn()


def _content_disposition(disposition: str, filename: str) -> str:
    original = filename or "file"
    fallback = "".join(ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\", ";"} else "_" for ch in original)
    fallback = fallback.strip(" ._") or "file"
    encoded = quote(original, safe="")
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def _stream_storage_object(
    request: Request,
    object_key: str,
    filename: str,
    content_type: str | None,
) -> StreamingResponse:
    stat = storage.stat_object(object_key)
    size = stat.size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": _content_disposition("inline", filename),
    }
    media_type = content_type or "application/octet-stream"
    range_tuple = _parse_range_header(request.headers.get("range"), size)
    if range_tuple is None:
        response = storage.get_stream(object_key)
        headers["Content-Length"] = str(size)
        return StreamingResponse(_iter_minio_response(response), media_type=media_type, headers=headers)

    start, end = range_tuple
    length = end - start + 1
    response = storage.get_stream(object_key, offset=start, length=length)
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        }
    )
    return StreamingResponse(
        _iter_minio_response(response),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


def _sample_photo_to_read(photo: SamplePhoto) -> SamplePhotoRead:
    return SamplePhotoRead(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        status=photo.status,
        error_message=photo.error_message,
        thumbnail_url=f"/api/persons/{photo.person_id}/samples/{photo.id}/thumbnail",
        original_url=f"/api/persons/{photo.person_id}/samples/{photo.id}/original",
        created_at=photo.created_at,
    )


def _person_to_read(db: Session, person: Person) -> PersonRead:
    sample_count = db.scalar(select(func.count(SamplePhoto.id)).where(SamplePhoto.person_id == person.id)) or 0
    gallery_count = (
        db.scalar(
            select(func.count(func.distinct(GalleryPhotoPersonTag.gallery_photo_id))).where(
                GalleryPhotoPersonTag.person_id == person.id
            )
        )
        or 0
    )
    return PersonRead(
        id=person.id,
        name=person.name,
        display_name=person.display_name,
        note=person.note,
        is_unknown=person.is_unknown,
        unknown_serial=person.unknown_serial,
        sample_count=sample_count,
        gallery_photo_count=gallery_count,
        created_at=person.created_at,
    )


def _parse_tag_names(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    names: list[str] = []
    for value in raw:
        for piece in value.split(","):
            normalized = piece.strip()
            if normalized:
                names.append(normalized)
    return list(dict.fromkeys(names))


def _parse_gallery_metadata(raw: str | None, file_count: int) -> list[dict[str, list[str] | str | None]]:
    defaults: list[dict[str, list[str] | str | None]] = [
        {"person_names": [], "tag_names": [], "rich_text": None} for _ in range(file_count)
    ]
    if not raw:
        return defaults
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    if not isinstance(payload, list):
        return defaults
    for index, item in enumerate(payload[:file_count]):
        if not isinstance(item, dict):
            continue
        person_names = item.get("person_names")
        tag_names = item.get("tag_names")
        if isinstance(person_names, list):
            defaults[index]["person_names"] = [str(name).strip() for name in person_names if str(name).strip()]
        if isinstance(tag_names, list):
            defaults[index]["tag_names"] = [str(name).strip() for name in tag_names if str(name).strip()]
        rich_text = item.get("rich_text")
        if rich_text is not None:
            defaults[index]["rich_text"] = str(rich_text).strip() or None
    return defaults


def _safe_zip_name(value: str | None, fallback: str) -> str:
    normalized = (value or "").strip()
    for char in '<>:"/\\|?*\0':
        normalized = normalized.replace(char, "_")
    normalized = normalized.strip(" .")
    return normalized or fallback


def _unique_zip_path(path: str, used_paths: set[str]) -> str:
    if path not in used_paths:
        used_paths.add(path)
        return path
    stem, dot, suffix = path.rpartition(".")
    base = stem if dot else path
    extension = f".{suffix}" if dot else ""
    counter = 2
    while True:
        candidate = f"{base}_{counter}{extension}"
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        counter += 1


def _apply_gallery_filters(query, person_ids: list[int], tag_ids: list[int], exclude_person_ids: list[int], exclude_tag_ids: list[int]):
    if person_ids:
        matched_persons = (
            select(GalleryPhotoPersonTag.gallery_photo_id)
            .where(GalleryPhotoPersonTag.person_id.in_(person_ids))
            .group_by(GalleryPhotoPersonTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.in_(select(matched_persons.c.gallery_photo_id)))

    if tag_ids:
        matched_tags = (
            select(GalleryPhotoTag.gallery_photo_id)
            .where(GalleryPhotoTag.tag_id.in_(tag_ids))
            .group_by(GalleryPhotoTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.in_(select(matched_tags.c.gallery_photo_id)))

    if exclude_person_ids:
        excluded_persons = (
            select(GalleryPhotoPersonTag.gallery_photo_id)
            .where(GalleryPhotoPersonTag.person_id.in_(exclude_person_ids))
            .group_by(GalleryPhotoPersonTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.notin_(select(excluded_persons.c.gallery_photo_id)))

    if exclude_tag_ids:
        excluded_tags = (
            select(GalleryPhotoTag.gallery_photo_id)
            .where(GalleryPhotoTag.tag_id.in_(exclude_tag_ids))
            .group_by(GalleryPhotoTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.notin_(select(excluded_tags.c.gallery_photo_id)))

    return query


def _process_gallery_import_task(
    task_id: str,
    uploads: list[tuple[str, bytes, str | None]],
    metadata_by_index: list[dict[str, list[str] | str | None]],
    rich_mode: bool,
    workspace_id: int,
) -> None:
    logger.info("Gallery import task started task_id=%s files=%d rich_mode=%s", task_id, len(uploads), rich_mode)
    db = SessionLocal()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在识别上传图片")
        total = max(len(uploads), 1)
        total_known = 0
        total_unknown_created = 0
        total_unknown_reused = 0
        total_duplicated = 0
        for index, (filename, payload, content_type) in enumerate(uploads, start=1):
            metadata = metadata_by_index[index - 1] if index - 1 < len(metadata_by_index) else {"person_names": [], "tag_names": []}
            logger.info(
                "Gallery import processing task_id=%s index=%d/%d filename=%s bytes=%d manual_persons=%d manual_tags=%d",
                task_id,
                index,
                total,
                filename,
                len(payload),
                len(metadata.get("person_names", [])),
                len(metadata.get("tag_names", [])),
            )
            photo, summary = picture_service.import_gallery_photo(
                db,
                filename,
                payload,
                content_type,
                metadata.get("tag_names", []),  # type: ignore[arg-type]
                rich_mode,
                metadata.get("rich_text"),  # type: ignore[arg-type]
                workspace_id,
            )
            for raw_name in metadata.get("person_names", []):  # type: ignore[assignment]
                person_name = raw_name.strip()
                if not person_name:
                    continue
                person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == person_name))
                if person is None:
                    person = Person(workspace_id=workspace_id, name=person_name, display_name=person_name, note=None, is_unknown=False)
                    db.add(person)
                    db.flush()
                    logger.info(
                        "Created person from gallery upload task_id=%s photo_id=%s person_id=%s name=%s",
                        task_id,
                        photo.id,
                        person.id,
                        person_name,
                    )
                picture_service._ensure_gallery_person_tag(db, photo.id, person.id, "manual_upload")
                picture_service._apply_person_tags_to_gallery_photo(db, photo.id, person.id)
            db.commit()
            total_known += summary.known_matches
            total_unknown_created += summary.unknown_created
            total_unknown_reused += summary.unknown_reused
            total_duplicated += summary.duplicated
            logger.info(
                "Gallery import progress task_id=%s index=%d/%d photo_id=%s known=%d unknown_created=%d unknown_reused=%d duplicated=%d",
                task_id,
                index,
                total,
                photo.id,
                total_known,
                total_unknown_created,
                total_unknown_reused,
                total_duplicated,
            )
            update_task(
                db,
                task_id,
                status="running",
                progress=index / total,
                message=(
                    f"已处理 {index}/{total} 张，识别 {total_known} 个已知人物，"
                    f"新增 {total_unknown_created} 个未知人物，重复跳过 {total_duplicated} 张"
                ),
            )
        final_message = (
            f"导入完成：识别 {total_known} 个已知人物，新增 {total_unknown_created} 个未知人物，"
            f"复用 {total_unknown_reused} 个未知人物，重复跳过 {total_duplicated} 张"
        )
        update_task(db, task_id, status="completed", progress=1.0, message=final_message)
        # 记录上传历史
        try:
            history = UploadHistory(
                workspace_id=workspace_id,
                upload_type="rich" if rich_mode else "gallery",
                total_count=total,
                success_count=total - total_duplicated,
                duplicate_count=total_duplicated,
            )
            db.add(history)
            db.commit()
            logger.info(
                "Upload history recorded upload_type=%s total=%d success=%d duplicate=%d",
                "rich" if rich_mode else "gallery",
                total,
                total - total_duplicated,
                total_duplicated,
            )
        except Exception:
            logger.exception("Failed to record upload history")
            db.rollback()
        logger.info(
            "Gallery import task completed task_id=%s known=%d unknown_created=%d unknown_reused=%d duplicated=%d",
            task_id,
            total_known,
            total_unknown_created,
            total_unknown_reused,
            total_duplicated,
        )
    except Exception as exc:
        logger.exception("Gallery import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        try:
            failed_db = SessionLocal()
            try:
                update_task(failed_db, task_id, status="failed", message=str(exc))
            finally:
                failed_db.close()
        except Exception:
            logger.exception("Failed to persist task failed status task_id=%s", task_id)
    finally:
        db.close()
        logger.debug("Gallery import task db session closed task_id=%s", task_id)


def _process_person_import_task(task_id: str, zip_bytes: bytes, workspace_id: int) -> None:
    logger.info("Person import task started task_id=%s bytes=%d", task_id, len(zip_bytes))
    db = SessionLocal()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在解析导入数据")

        def progress_callback(processed: int, total: int) -> None:
            progress = 0.05 + 0.9 * (processed / max(total, 1))
            update_task(
                db,
                task_id,
                status="running",
                progress=min(progress, 1.0),
                message=f"正在处理 {processed}/{total} 个样本",
            )

        result = picture_service.import_persons_from_zip(db, zip_bytes, workspace_id, progress_callback)

        message = (
            f"导入完成：创建 {result['created_persons']} 个人物，"
            f"匹配 {result['existing_persons']} 个已有，"
            f"新增 {result['added_samples']} 个样本，"
            f"跳过 {result['skipped_samples']} 个重复，"
            f"绑定 {result['tags_added']} 个标签"
        )
        update_task(db, task_id, status="completed", progress=1.0, message=message)
        logger.info("Person import task completed task_id=%s %s", task_id, message)
    except Exception as exc:
        logger.exception("Person import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        try:
            failed_db = SessionLocal()
            try:
                update_task(failed_db, task_id, status="failed", message=str(exc))
            finally:
                failed_db.close()
        except Exception:
            logger.exception("Failed to persist task failed status task_id=%s", task_id)
    finally:
        db.close()
        logger.debug("Person import task db session closed task_id=%s", task_id)


def _process_gallery_zip_import_task(task_id: str, zip_bytes: bytes, workspace_id: int) -> None:
    logger.info("Gallery zip import task started task_id=%s bytes=%d", task_id, len(zip_bytes))
    db = SessionLocal()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在解析展示图 ZIP")

        def progress_callback(processed: int, total: int) -> None:
            progress = 0.05 + 0.9 * (processed / max(total, 1))
            update_task(
                db,
                task_id,
                status="running",
                progress=min(progress, 1.0),
                message=f"正在还原展示图 {processed}/{total}",
            )

        result = picture_service.import_gallery_from_zip(db, zip_bytes, workspace_id, progress_callback)
        message = (
            f"导入完成：新增 {result['added_photos']} 张，"
            f"更新 {result['updated_existing']} 张已有图，"
            f"跳过 {result['skipped_photos']} 张，"
            f"绑定 {result['tags_added']} 个普通标签，"
            f"绑定 {result['persons_added']} 个人物标签"
        )
        update_task(db, task_id, status="completed", progress=1.0, message=message)
        logger.info("Gallery zip import task completed task_id=%s %s", task_id, message)
    except Exception as exc:
        logger.exception("Gallery zip import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        try:
            failed_db = SessionLocal()
            try:
                update_task(failed_db, task_id, status="failed", message=str(exc))
            finally:
                failed_db.close()
        except Exception:
            logger.exception("Failed to persist task failed status task_id=%s", task_id)
    finally:
        db.close()
        logger.debug("Gallery zip import task db session closed task_id=%s", task_id)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/bootstrap-status", response_model=BootstrapStatus)
def get_bootstrap_status(db: Session = Depends(get_db)) -> BootstrapStatus:
    return BootstrapStatus(required=(db.scalar(select(func.count(User.id))) or 0) == 0)


@app.post("/api/auth/bootstrap", response_model=AuthSession)
def bootstrap_admin(payload: BootstrapCreate, db: Session = Depends(get_db)) -> AuthSession:
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
    picture_service.ensure_system_tags(db, workspace.id)
    db.refresh(user)
    return _auth_session(db, user)


@app.post("/api/auth/login", response_model=AuthSession)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthSession:
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return _auth_session(db, user)


@app.post("/api/auth/register", response_model=AuthSession)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthSession:
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
    picture_service.ensure_system_tags(db, private_workspace.id)
    db.refresh(user)
    return _auth_session(db, user)


@app.get("/api/auth/me", response_model=AuthSession)
def get_current_session(current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> AuthSession:
    db.refresh(current.user)
    return _auth_session(db, current.user, current.workspace_id)


@app.get("/api/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> list[WorkspaceRead]:
    db.refresh(current.user)
    return _workspace_reads(db, current.user)


@app.post("/api/workspaces", response_model=WorkspaceRead)
def create_workspace(payload: WorkspaceCreate, current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> WorkspaceRead:
    name = payload.name.strip()
    workspace = Workspace(name=name, kind="shared", owner_user_id=current.user.id)
    db.add(workspace)
    db.flush()
    membership = WorkspaceMember(workspace_id=workspace.id, user_id=current.user.id, role="owner")
    db.add(membership)
    db.commit()
    db.refresh(membership)
    picture_service.ensure_system_tags(db, workspace.id)
    return _workspace_read(membership)


@app.patch("/api/workspaces/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current: CurrentContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
) -> WorkspaceRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    current.workspace.name = payload.name.strip()
    db.commit()
    db.refresh(current.membership)
    return _workspace_read(current.membership)


@app.get("/api/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
def list_workspace_members(
    workspace_id: int,
    current: CurrentContext = Depends(require_context),
    db: Session = Depends(get_db),
) -> list[WorkspaceMemberRead]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权访问该内容空间")
    members = db.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id).order_by(WorkspaceMember.role.desc(), WorkspaceMember.id.asc())
    ).all()
    return [_member_to_read(member) for member in members]


@app.patch("/api/workspaces/{workspace_id}/members/{member_id}", response_model=WorkspaceMemberRead)
def update_workspace_member(
    workspace_id: int,
    member_id: int,
    payload: WorkspacePermissionUpdate,
    current: CurrentContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
) -> WorkspaceMemberRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="owner 拥有全部权限，不需要配置")
    _apply_permissions(member, _permission_kwargs(payload))
    db.commit()
    db.refresh(member)
    return _member_to_read(member)


@app.delete("/api/workspaces/{workspace_id}/members/{member_id}")
def remove_workspace_member(
    workspace_id: int,
    member_id: int,
    current: CurrentContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == "owner" and _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status_code=400, detail="不能移除最后一个 owner")
    db.delete(member)
    db.commit()
    return {"status": "ok"}


@app.post("/api/workspaces/{workspace_id}/leave")
def leave_workspace(
    workspace_id: int,
    current: CurrentContext = Depends(require_context),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="只能退出当前内容空间")
    if current.workspace.kind == "private":
        raise HTTPException(status_code=400, detail="不能退出自己的私人空间")
    if current.role == "owner" and _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status_code=400, detail="不能退出最后一个 owner 所在空间")
    db.delete(current.membership)
    db.commit()
    return {"status": "ok"}


@app.post("/api/workspaces/{workspace_id}/invitations", response_model=WorkspaceInvitationRead)
def invite_workspace_member(
    workspace_id: int,
    payload: WorkspaceInvitationCreate,
    current: CurrentContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
) -> WorkspaceInvitationRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    username = payload.username.strip()
    invitee = db.scalar(select(User).where(User.username == username))
    if invitee is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == invitee.id)) is not None:
        raise HTTPException(status_code=409, detail="该账号已经在此内容空间中")
    existing = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.invitee_user_id == invitee.id,
            WorkspaceInvitation.status == "pending",
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="该账号已有待处理邀请")
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        inviter_user_id=current.user.id,
        invitee_user_id=invitee.id,
        role="member",
    )
    _apply_permissions(invitation, _permission_kwargs(payload))
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return _invitation_to_read(invitation)


@app.get("/api/workspace-invitations", response_model=list[WorkspaceInvitationRead])
def list_my_workspace_invitations(current: CurrentContext = Depends(require_context), db: Session = Depends(get_db)) -> list[WorkspaceInvitationRead]:
    invitations = db.scalars(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.invitee_user_id == current.user.id, WorkspaceInvitation.status == "pending")
        .order_by(WorkspaceInvitation.created_at.desc())
    ).all()
    return [_invitation_to_read(invitation) for invitation in invitations]


@app.post("/api/workspace-invitations/{invitation_id}/accept", response_model=WorkspaceRead)
def accept_workspace_invitation(
    invitation_id: int,
    current: CurrentContext = Depends(require_context),
    db: Session = Depends(get_db),
) -> WorkspaceRead:
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.invitee_user_id != current.user.id or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="邀请不存在")
    if invitation.workspace.kind != "shared":
        raise HTTPException(status_code=400, detail="该内容空间不能加入")
    existing = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == invitation.workspace_id, WorkspaceMember.user_id == current.user.id))
    if existing is not None:
        invitation.status = "accepted"
        db.commit()
        db.refresh(existing)
        return _workspace_read(existing)
    membership = WorkspaceMember(workspace_id=invitation.workspace_id, user_id=current.user.id, role=invitation.role)
    _apply_permissions(membership, {field: bool(getattr(invitation, field)) for field in PERMISSION_FIELDS})
    invitation.status = "accepted"
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return _workspace_read(membership)


@app.post("/api/workspace-invitations/{invitation_id}/decline")
def decline_workspace_invitation(
    invitation_id: int,
    current: CurrentContext = Depends(require_context),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.invitee_user_id != current.user.id or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="邀请不存在")
    invitation.status = "declined"
    db.commit()
    return {"status": "ok"}


@app.delete("/api/workspaces/{workspace_id}/invitations/{invitation_id}")
def revoke_workspace_invitation(
    workspace_id: int,
    invitation_id: int,
    current: CurrentContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.workspace_id != workspace_id or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="邀请不存在")
    invitation.status = "revoked"
    db.commit()
    return {"status": "ok"}


@app.post("/api/workspaces/{workspace_id}/users", response_model=UserRead)
def create_workspace_user(
    workspace_id: int,
    payload: AdminUserCreate,
    current: CurrentContext = Depends(require_workspace_owner),
    db: Session = Depends(get_db),
) -> UserRead:
    if current.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="无权管理该内容空间")
    _require_shared_workspace_owner(current)
    username = payload.username.strip()
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    display_name = (payload.display_name or username).strip()
    user = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(payload.password),
        is_admin=False,
    )
    db.add(user)
    db.flush()
    private_workspace = _ensure_private_workspace(db, user)
    shared_membership = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="member")
    _apply_permissions(shared_membership, _permission_kwargs(payload))
    db.add(shared_membership)
    db.commit()
    db.refresh(user)
    picture_service.ensure_system_tags(db, private_workspace.id)
    return UserRead.model_validate(user)


@app.post("/api/admin/users", response_model=UserRead)
def create_user(payload: AdminUserCreate, current: CurrentContext = Depends(require_workspace_owner), db: Session = Depends(get_db)) -> UserRead:
    if current.workspace.kind != "shared":
        raise HTTPException(status_code=400, detail="请在共享内容空间中创建成员账号")
    return create_workspace_user(current.workspace_id, payload, current, db)


@app.get("/api/persons", response_model=list[PersonRead])
def list_persons(
    is_unknown: bool | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[PersonRead]:
    query = select(Person).where(Person.workspace_id == current.workspace_id).order_by(Person.is_unknown.asc(), Person.display_name.asc())
    if is_unknown is not None:
        query = query.where(Person.is_unknown.is_(is_unknown))
    persons = db.scalars(query).all()
    return [_person_to_read(db, person) for person in persons]


@app.post("/api/persons", response_model=PersonRead)
def create_person(
    payload: PersonCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PersonRead:
    normalized = payload.name.strip()
    if db.scalar(select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized)) is not None:
        raise HTTPException(status_code=409, detail="Person already exists")
    person = Person(workspace_id=current.workspace_id, name=normalized, display_name=normalized, note=payload.note, is_unknown=False)
    db.add(person)
    db.commit()
    db.refresh(person)
    return _person_to_read(db, person)


@app.post("/api/persons/batch-delete")
def batch_delete_persons(
    payload: PersonBatchDeleteRequest,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    persons = db.scalars(
        select(Person).where(Person.workspace_id == current.workspace_id, Person.id.in_(payload.person_ids))
    ).all()
    if not persons:
        return {"deleted": 0}
    deleted = picture_service.delete_persons(db, persons)
    return {"deleted": deleted}


@app.get("/api/persons/export")
def export_persons(db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> StreamingResponse:
    from datetime import datetime as dt
    from zipfile import ZIP_DEFLATED, ZipFile

    persons = db.scalars(
        select(Person)
        .where(Person.workspace_id == current.workspace_id, Person.is_unknown == False)
        .order_by(Person.display_name)
    ).all()

    export_persons: list[dict] = []
    buf = BytesIO()

    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for person in persons:
            samples = db.scalars(
                select(SamplePhoto).where(SamplePhoto.person_id == person.id).order_by(SamplePhoto.filename)
            ).all()
            tag_links = db.scalars(select(PersonTag).where(PersonTag.person_id == person.id)).all()
            tag_names: list[str] = []
            for tag_link in tag_links:
                tag_link.tag
                tag_names.append(tag_link.tag.name)

            export_samples: list[dict] = []
            for sample in samples:
                image_bytes = storage.get_bytes(sample.object_key)
                zip_path = f"samples/{person.name}/{sample.filename}"
                zf.writestr(zip_path, image_bytes)
                export_samples.append({
                    "filename": sample.filename,
                    "sha256": sample.sha256,
                    "content_type": sample.content_type,
                    "object_key": sample.object_key,
                    "width": sample.width,
                    "height": sample.height,
                    "taken_at": sample.taken_at.isoformat() if sample.taken_at else None,
                })

            export_persons.append({
                "name": person.name,
                "display_name": person.display_name,
                "note": person.note,
                "is_unknown": person.is_unknown,
                "tags": sorted(set(tag_names)),
                "samples": export_samples,
            })

        manifest = {
            "version": 1,
            "exported_at": dt.utcnow().isoformat(),
            "persons": export_persons,
        }
        zf.writestr("metadata.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="person_samples_{timestamp}.zip"'},
    )


@app.post("/api/persons/import", response_model=TaskRead)
async def import_persons(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    zip_bytes = await file.read()
    task = create_task(db, "person_import", "已排队样本库导入", current.workspace_id)
    logger.info("Person import enqueued task_id=%s bytes=%d", task.id, len(zip_bytes))
    background_tasks.add_task(_process_person_import_task, task.id, zip_bytes, current.workspace_id)
    return TaskRead.model_validate(task)


@app.get("/api/persons/{person_id}", response_model=PersonRead)
def get_person(person_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> PersonRead:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    return _person_to_read(db, person)


@app.patch("/api/persons/{person_id}", response_model=PersonRead)
def update_person(
    person_id: int,
    payload: PersonUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PersonRead:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    if payload.name is not None:
        normalized = payload.name.strip()
        duplicate = db.scalar(
            select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized, Person.id != person_id)
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Person already exists")
        person.name = normalized
        person.display_name = normalized
        person.is_unknown = False
    if payload.note is not None:
        person.note = payload.note
    db.add(person)
    db.commit()
    db.refresh(person)
    return _person_to_read(db, person)


@app.post("/api/persons/{person_id}/rename", response_model=PersonRead)
def rename_person(
    person_id: int,
    payload: PersonRenameRequest,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PersonRead:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    try:
        person = picture_service.rename_person(db, person, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _person_to_read(db, person)


@app.delete("/api/persons/{person_id}")
def delete_person(person_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> dict[str, str]:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    picture_service.delete_persons(db, [person])
    return {"status": "ok"}


@app.get("/api/persons/{person_id}/samples", response_model=list[SamplePhotoRead])
def list_person_samples(
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[SamplePhotoRead]:
    _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    photos = db.scalars(select(SamplePhoto).where(SamplePhoto.person_id == person_id).order_by(SamplePhoto.created_at.desc())).all()
    return [_sample_photo_to_read(photo) for photo in photos]


@app.get("/api/persons/{person_id}/tags", response_model=list[TagRead])
def list_person_tags(person_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> list[TagRead]:
    _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    return [TagRead.model_validate(tag) for tag in picture_service.list_person_tags(db, person_id)]


@app.post("/api/persons/{person_id}/tags", response_model=list[TagRead])
def bind_person_tag(
    person_id: int,
    payload: PersonTagCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[TagRead]:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    if payload.tag_id is not None:
        tag = db.get(Tag, payload.tag_id)
        if tag is None or tag.workspace_id != current.workspace_id:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = picture_service._find_or_create_tag(db, payload.name or "", current.workspace_id)
    picture_service.bind_person_tag(db, person, tag)
    return [TagRead.model_validate(item) for item in picture_service.list_person_tags(db, person_id)]


@app.delete("/api/persons/{person_id}/tags/{tag_id}", response_model=list[TagRead])
def unbind_person_tag(
    person_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[TagRead]:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    picture_service.unbind_person_tag(db, person, tag_id)
    return [TagRead.model_validate(item) for item in picture_service.list_person_tags(db, person_id)]


@app.post("/api/persons/{person_id}/samples", response_model=list[SamplePhotoRead])
async def add_person_samples(
    person_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[SamplePhotoRead]:
    person = _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    samples = picture_service.add_person_samples(db, person, uploads)
    return [_sample_photo_to_read(sample) for sample in samples]


@app.delete("/api/persons/{person_id}/samples/{sample_photo_id}")
def delete_person_sample(
    person_id: int,
    sample_photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.workspace_id != current.workspace_id or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    picture_service.delete_sample_photo(db, photo)
    return {"status": "ok"}


@app.get("/api/persons/{person_id}/samples/{sample_photo_id}/original")
def get_sample_original(
    person_id: int,
    sample_photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.workspace_id != current.workspace_id or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    return _stream_storage_object(request, photo.object_key, photo.filename, photo.content_type)


@app.get("/api/persons/{person_id}/samples/{sample_photo_id}/thumbnail")
def get_sample_thumbnail(
    person_id: int,
    sample_photo_id: int,
    width: int = 480,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.workspace_id != current.workspace_id or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    payload = storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@app.get("/api/tags", response_model=list[TagRead])
def list_tags(db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> list[TagRead]:
    tags = db.scalars(select(Tag).where(Tag.workspace_id == current.workspace_id).order_by(Tag.name.asc())).all()
    return [TagRead.model_validate(tag) for tag in tags]


@app.post("/api/tags", response_model=TagRead)
def create_tag(payload: TagCreate, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> TagRead:
    normalized = payload.name.strip()
    existing = db.scalar(select(Tag).where(Tag.workspace_id == current.workspace_id, Tag.name == normalized))
    if existing is not None:
        return TagRead.model_validate(existing)
    tag = Tag(workspace_id=current.workspace_id, name=normalized)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)


@app.patch("/api/tags/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TagRead:
    tag = _get_workspace_object(db, Tag, tag_id, current.workspace_id, "Tag")
    normalized = payload.name.strip()
    duplicate = db.scalar(select(Tag).where(Tag.workspace_id == current.workspace_id, Tag.name == normalized, Tag.id != tag_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")
    tag.name = normalized
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> dict[str, str]:
    tag = _get_workspace_object(db, Tag, tag_id, current.workspace_id, "Tag")
    if tag.is_system:
        raise HTTPException(status_code=400, detail="System tag cannot be deleted")
    db.delete(tag)
    db.commit()
    return {"status": "ok"}


@app.post("/api/gallery/photos/import", response_model=TaskRead)
async def import_gallery_photos(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    metadata = _parse_gallery_metadata(metadata_json, len(uploads))
    task = create_task(db, "gallery_import", f"已排队 {len(uploads)} 张普通图片", current.workspace_id)
    logger.info(
        "Gallery import enqueued task_id=%s files=%d metadata_items=%d rich_mode=false",
        task.id,
        len(uploads),
        len(metadata),
    )
    background_tasks.add_task(_process_gallery_import_task, task.id, uploads, metadata, False, current.workspace_id)
    return TaskRead.model_validate(task)


@app.post("/api/gallery/rich-photos/import", response_model=TaskRead)
async def import_gallery_rich_photos(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    metadata = _parse_gallery_metadata(metadata_json, len(uploads))
    task = create_task(db, "gallery_rich_import", f"已排队 {len(uploads)} 张图文图片", current.workspace_id)
    logger.info(
        "Gallery rich import enqueued task_id=%s files=%d metadata_items=%d rich_mode=true",
        task.id,
        len(uploads),
        len(metadata),
    )
    background_tasks.add_task(_process_gallery_import_task, task.id, uploads, metadata, True, current.workspace_id)
    return TaskRead.model_validate(task)


@app.get("/api/gallery/photos/export")
def export_gallery_photos(
    scope: str = Query(default="all", pattern="^(all|filtered)$"),
    person_ids: list[int] = Query(default=[]),
    tag_ids: list[int] = Query(default=[]),
    exclude_person_ids: list[int] = Query(default=[]),
    exclude_tag_ids: list[int] = Query(default=[]),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    from datetime import datetime as dt
    from zipfile import ZIP_DEFLATED, ZipFile

    base_query = (
        select(GalleryPhoto)
        .where(GalleryPhoto.workspace_id == current.workspace_id)
        .order_by(GalleryPhoto.taken_at.desc().nullslast(), GalleryPhoto.created_at.desc())
    )
    if scope == "filtered":
        query = _apply_gallery_filters(base_query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids)
    else:
        query = base_query

    photos = db.scalars(query).unique().all()
    for photo in photos:
        photo.person_tags
        photo.tags
        for person_tag in photo.person_tags:
            person_tag.person
        for tag_link in photo.tags:
            tag_link.tag

    manifest_photos: list[dict] = []
    used_paths: set[str] = set()
    buf = BytesIO()

    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for photo in photos:
            image_bytes = storage.get_bytes(photo.object_key)
            normal_tags = sorted({link.tag.name for link in photo.tags if not link.tag.is_system})
            folder_names = normal_tags or ["_未分类"]
            filename = _safe_zip_name(f"{photo.id}_{photo.filename}", f"{photo.id}_photo")
            zip_paths: list[str] = []
            for tag_name in folder_names:
                folder = _safe_zip_name(tag_name, "_未分类")
                zip_path = _unique_zip_path(f"gallery/by_tag/{folder}/{filename}", used_paths)
                zf.writestr(zip_path, image_bytes)
                zip_paths.append(zip_path)

            manifest_photos.append(
                {
                    "id": photo.id,
                    "filename": photo.filename,
                    "sha256": photo.sha256,
                    "content_type": photo.content_type,
                    "width": photo.width,
                    "height": photo.height,
                    "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
                    "is_rich_text": photo.is_rich_text,
                    "rich_text": photo.rich_text,
                    "ocr_status": photo.ocr_status,
                    "tags": normal_tags,
                    "persons": [
                        {
                            "name": person_tag.person.name,
                            "display_name": person_tag.person.display_name,
                            "is_unknown": person_tag.person.is_unknown,
                            "source": person_tag.source,
                        }
                        for person_tag in sorted(
                            photo.person_tags,
                            key=lambda item: (item.person.is_unknown, item.person.display_name.lower()),
                        )
                    ],
                    "paths": zip_paths,
                }
            )

        manifest = {
            "version": 1,
            "kind": "gallery_export",
            "scope": scope,
            "exported_at": dt.utcnow().isoformat(),
            "photos": manifest_photos,
        }
        zf.writestr("metadata.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="gallery_export_{timestamp}.zip"'},
    )


@app.post("/api/gallery/photos/import-zip", response_model=TaskRead)
async def import_gallery_export_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    zip_bytes = await file.read()
    task = create_task(db, "gallery_zip_import", "已排队展示图 ZIP 导入", current.workspace_id)
    logger.info("Gallery zip import enqueued task_id=%s bytes=%d", task.id, len(zip_bytes))
    background_tasks.add_task(_process_gallery_zip_import_task, task.id, zip_bytes, current.workspace_id)
    return TaskRead.model_validate(task)


@app.get("/api/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> TaskRead:
    task = db.get(Task, task_id)
    if task is None or task.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)


@app.get("/api/subtitle-service/status", response_model=SubtitleServiceStatus)
def get_subtitle_service_status(current: CurrentContext = Depends(require_context)) -> SubtitleServiceStatus:
    return SubtitleServiceStatus(**subtitle_service.get_translation_service_status())


@app.post("/api/subtitle-service/start", response_model=SubtitleServiceStatus)
def start_subtitle_service(current: CurrentContext = Depends(require_context)) -> SubtitleServiceStatus:
    try:
        return SubtitleServiceStatus(**subtitle_service.start_translation_service())
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/subtitle-service/stop", response_model=SubtitleServiceStatus)
def stop_subtitle_service(
    cancel_running: bool = Query(default=True),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> SubtitleServiceStatus:
    try:
        return SubtitleServiceStatus(**subtitle_service.stop_translation_service(db=db, cancel_running=cancel_running))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/subtitle-service/logs", response_model=SubtitleServiceLogs)
def get_subtitle_service_logs(
    tail: int = Query(default=200, ge=1, le=1000),
    current: CurrentContext = Depends(require_context),
) -> SubtitleServiceLogs:
    return SubtitleServiceLogs(**subtitle_service.read_translation_service_logs(tail=tail))


@app.get("/api/subtitle-jobs", response_model=list[SubtitleJobRead])
def list_subtitle_jobs(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[SubtitleJobRead]:
    tracks = db.scalars(
        select(VideoSubtitleTrack)
        .join(VideoItem, VideoItem.id == VideoSubtitleTrack.video_id)
        .where(VideoSubtitleTrack.status.in_(("pending", "running", "failed", "canceled")))
        .where(VideoItem.workspace_id == current.workspace_id)
        .order_by(VideoSubtitleTrack.updated_at.desc())
        .limit(50)
    ).all()
    jobs: list[SubtitleJobRead] = []
    for track in tracks:
        video = db.get(VideoItem, track.video_id)
        if video is None:
            continue
        task = db.get(Task, track.task_id) if track.task_id else None
        jobs.append(
            SubtitleJobRead(
                video_id=video.id,
                video_title=video.title,
                video_filename=video.filename,
                track=_subtitle_to_read(track),
                task=TaskRead.model_validate(task) if task is not None else None,
            )
        )
    return jobs


@app.get("/api/gallery/photos", response_model=PaginatedGalleryPhotos)
def list_gallery_photos(
    person_ids: list[int] = Query(default=[]),
    tag_ids: list[int] = Query(default=[]),
    exclude_person_ids: list[int] = Query(default=[]),
    exclude_tag_ids: list[int] = Query(default=[]),
    offset: int = 0,
    limit: int = 24,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PaginatedGalleryPhotos:
    query = (
        select(GalleryPhoto)
        .where(GalleryPhoto.workspace_id == current.workspace_id)
        .order_by(GalleryPhoto.created_at.desc())
    )
    count_query = select(func.count(GalleryPhoto.id)).where(GalleryPhoto.workspace_id == current.workspace_id)
    query = _apply_gallery_filters(query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids)
    count_query = _apply_gallery_filters(count_query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids)

    photos = db.scalars(query.offset(offset).limit(limit)).unique().all()
    for photo in photos:
        photo.person_tags
        photo.tags
        for person_tag in photo.person_tags:
            person_tag.person
        for tag_link in photo.tags:
            tag_link.tag
    total = db.scalar(count_query) or 0
    return PaginatedGalleryPhotos(items=[_gallery_photo_to_list_item(photo) for photo in photos], total=total, offset=offset, limit=limit)


@app.get("/api/gallery/photos/{photo_id}", response_model=GalleryPhotoDetail)
def get_gallery_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    photo.person_tags
    photo.tags
    photo.faces
    for tag in photo.person_tags:
        tag.person
    for tag_link in photo.tags:
        tag_link.tag
    return _gallery_photo_to_detail(photo)


@app.post("/api/gallery/photos/batch-delete")
def batch_delete_gallery_photos(
    payload: GalleryPhotoBatchDeleteRequest,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    photos = db.scalars(
        select(GalleryPhoto).where(GalleryPhoto.workspace_id == current.workspace_id, GalleryPhoto.id.in_(payload.photo_ids))
    ).all()
    if not photos:
        return {"deleted": 0}
    deleted = picture_service.delete_gallery_photos(db, photos)
    return {"deleted": deleted}


@app.delete("/api/gallery/photos/{photo_id}")
def delete_gallery_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    photo = _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    picture_service.delete_gallery_photos(db, [photo])
    return {"status": "ok"}


@app.get("/api/gallery/photos/{photo_id}/original")
def get_gallery_original(
    photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    photo = _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    return _stream_storage_object(request, photo.object_key, photo.filename, photo.content_type)


@app.get("/api/gallery/photos/{photo_id}/thumbnail")
def get_gallery_thumbnail(
    photo_id: int,
    width: int = 480,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    photo = _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    payload = storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@app.post("/api/gallery/photos/{photo_id}/persons", response_model=GalleryPhotoDetail)
def add_gallery_photo_person(
    photo_id: int,
    payload: GalleryPhotoPersonTagCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    person = _get_workspace_object(db, Person, payload.person_id, current.workspace_id, "Person")
    picture_service._ensure_gallery_person_tag(db, photo_id, person.id, "manual")
    picture_service._apply_person_tags_to_gallery_photo(db, photo_id, person.id)

    faces = db.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo_id)).all()
    if len(faces) == 1:
        face = faces[0]
        vector = None
        if face.vector_collection == "unknown":
            vector = vector_store.get_face_vector(settings.milvus_unknown_collection, face.id)
        elif face.vector_collection == "known":
            vector = vector_store.get_face_vector(settings.milvus_known_collection, face.id)
        picture_service.move_gallery_face_to_known(db, face, person, vector)

    db.commit()
    return get_gallery_photo(photo_id, db, current)


@app.delete("/api/gallery/photos/{photo_id}/persons/{person_id}", response_model=GalleryPhotoDetail)
def delete_gallery_photo_person(
    photo_id: int,
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    _get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    link = db.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo_id,
            GalleryPhotoPersonTag.person_id == person_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Person tag not found")
    
    person_tags = db.scalars(select(PersonTag).where(PersonTag.person_id == person_id)).all()
    tag_ids = [pt.tag_id for pt in person_tags]
    
    db.delete(link)
    
    for tag_id in tag_ids:
        gallery_tag = db.scalar(
            select(GalleryPhotoTag).where(
                GalleryPhotoTag.gallery_photo_id == photo_id,
                GalleryPhotoTag.tag_id == tag_id,
            )
        )
        if gallery_tag is None or gallery_tag.source != "person":
            continue
        
        still_required = db.scalar(
            select(func.count(PersonTag.id))
            .join(Person, Person.id == PersonTag.person_id)
            .join(
                GalleryPhotoPersonTag,
                GalleryPhotoPersonTag.person_id == PersonTag.person_id,
            )
            .where(
                PersonTag.tag_id == tag_id,
                GalleryPhotoPersonTag.gallery_photo_id == photo_id,
                PersonTag.person_id != person_id,
            )
        ) or 0
        
        if still_required == 0:
            db.delete(gallery_tag)
    
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@app.post("/api/gallery/photos/{photo_id}/tags", response_model=GalleryPhotoDetail)
def add_gallery_photo_tag(
    photo_id: int,
    payload: GalleryPhotoTagCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    if payload.tag_id is not None:
        tag = db.get(Tag, payload.tag_id)
        if tag is None or tag.workspace_id != current.workspace_id:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = picture_service._find_or_create_tag(db, payload.name or "", current.workspace_id)
    picture_service._ensure_gallery_tag(db, photo_id, tag, source="manual")
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@app.delete("/api/gallery/photos/{photo_id}/tags/{tag_id}", response_model=GalleryPhotoDetail)
def delete_gallery_photo_tag(
    photo_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    link = db.scalar(
        select(GalleryPhotoTag).where(
            GalleryPhotoTag.gallery_photo_id == photo_id,
            GalleryPhotoTag.tag_id == tag_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if link.tag.is_system:
        raise HTTPException(status_code=400, detail="System tag cannot be removed")
    db.delete(link)
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@app.patch("/api/gallery/photos/{photo_id}/rich-text", response_model=GalleryPhotoDetail)
def update_gallery_photo_rich_text(
    photo_id: int,
    payload: GalleryPhotoRichTextUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    if not photo.is_rich_text:
        raise HTTPException(status_code=400, detail="Photo is not rich-text type")
    value = (payload.rich_text or "").strip()
    photo.rich_text = value or None
    photo.ocr_status = "manual" if value else "empty"
    db.add(photo)
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@app.post("/api/gallery/photos/{photo_id}/re-recognize", response_model=GalleryPhotoDetail)
def re_recognize_gallery_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = _get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    photo = picture_service.re_recognize_gallery_photo(db, photo)
    return _gallery_photo_to_detail(photo)


@app.post("/api/gallery/photos/re-recognize-unknown")
def re_recognize_unknown_gallery_photos(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    return picture_service.re_recognize_unknown_gallery_photos(db, current.workspace_id)


@app.get("/api/video-category-tags", response_model=list[VideoCategoryTagRead])
def list_video_category_tags(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[VideoCategoryTagRead]:
    tags = db.scalars(
        select(VideoCategoryTag)
        .where(VideoCategoryTag.workspace_id == current.workspace_id)
        .order_by(VideoCategoryTag.name.asc())
    ).all()
    return [_video_category_to_read(tag) for tag in tags]


@app.post("/api/video-category-tags", response_model=VideoCategoryTagRead)
def create_video_category_tag(
    payload: VideoCategoryTagCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoCategoryTagRead:
    try:
        tag = video_service.find_or_create_category_tag(db, payload.name, current.workspace_id)
        db.commit()
        db.refresh(tag)
        return _video_category_to_read(tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/video-category-tags/{tag_id}", response_model=VideoCategoryTagRead)
def update_video_category_tag(
    tag_id: int,
    payload: VideoCategoryTagUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoCategoryTagRead:
    tag = _get_workspace_object(db, VideoCategoryTag, tag_id, current.workspace_id, "Video category tag")
    normalized = payload.name.strip()
    duplicate = db.scalar(
        select(VideoCategoryTag).where(
            VideoCategoryTag.workspace_id == current.workspace_id,
            VideoCategoryTag.name == normalized,
            VideoCategoryTag.id != tag_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Video category tag already exists")
    tag.name = normalized
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _video_category_to_read(tag)


@app.delete("/api/video-category-tags/{tag_id}")
def delete_video_category_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    tag = _get_workspace_object(db, VideoCategoryTag, tag_id, current.workspace_id, "Video category tag")
    db.delete(tag)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/video-people", response_model=list[VideoPersonRead])
def list_video_people(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[VideoPersonRead]:
    people = db.scalars(
        select(VideoPerson)
        .where(VideoPerson.workspace_id == current.workspace_id)
        .order_by(VideoPerson.name.asc())
    ).all()
    return [_video_person_to_read(person) for person in people]


@app.post("/api/video-people", response_model=VideoPersonRead)
async def create_video_person(
    name: str = Form(...),
    note: str | None = Form(default=None),
    avatar: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoPersonRead:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Video person name is required")
    if db.scalar(select(VideoPerson).where(VideoPerson.workspace_id == current.workspace_id, VideoPerson.name == normalized)):
        raise HTTPException(status_code=409, detail="Video person already exists")
    avatar_key = None
    avatar_type = None
    if avatar is not None and avatar.filename:
        try:
            avatar_key, avatar_type = video_service.save_person_avatar(
                await avatar.read(), avatar.filename, avatar.content_type, current.workspace_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    person = VideoPerson(
        workspace_id=current.workspace_id,
        name=normalized,
        note=note,
        avatar_object_key=avatar_key,
        avatar_content_type=avatar_type,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return _video_person_to_read(person)


@app.patch("/api/video-people/{person_id}", response_model=VideoPersonRead)
async def update_video_person(
    person_id: int,
    name: str | None = Form(default=None),
    note: str | None = Form(default=None),
    avatar: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoPersonRead:
    person = _get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    if name is not None:
        normalized = name.strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="Video person name is required")
        duplicate = db.scalar(
            select(VideoPerson).where(
                VideoPerson.workspace_id == current.workspace_id,
                VideoPerson.name == normalized,
                VideoPerson.id != person_id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Video person already exists")
        person.name = normalized
    person.note = note
    old_avatar_key = None
    if avatar is not None and avatar.filename:
        try:
            avatar_key, avatar_type = video_service.save_person_avatar(
                await avatar.read(), avatar.filename, avatar.content_type, current.workspace_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        old_avatar_key = person.avatar_object_key
        person.avatar_object_key = avatar_key
        person.avatar_content_type = avatar_type
    db.add(person)
    db.commit()
    db.refresh(person)
    if old_avatar_key:
        storage.remove_object(old_avatar_key)
    return _video_person_to_read(person)


@app.delete("/api/video-people/{person_id}")
def delete_video_person(
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    person = _get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    avatar_key = person.avatar_object_key
    db.delete(person)
    db.commit()
    if avatar_key:
        storage.remove_object(avatar_key)
    return {"status": "deleted"}


@app.get("/api/video-people/{person_id}/avatar")
def get_video_person_avatar(
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    person = _get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    if not person.avatar_object_key:
        raise HTTPException(status_code=404, detail="Video person avatar not found")
    payload = storage.get_bytes(person.avatar_object_key)
    return Response(content=payload, media_type=person.avatar_content_type or "application/octet-stream")


@app.post("/api/videos/upload-sessions", response_model=VideoUploadSessionRead)
def create_video_upload_session(
    payload: VideoUploadSessionCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoUploadSessionRead:
    try:
        session = video_service.create_upload_session(db, payload, current.workspace_id)
        return _video_session_to_read(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/videos/upload-sessions/{session_id}", response_model=VideoUploadSessionRead)
def get_video_upload_session(
    session_id: str,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoUploadSessionRead:
    session = db.get(VideoUploadSession, session_id)
    if session is None or session.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    return _video_session_to_read(session)


@app.put("/api/videos/upload-sessions/{session_id}/parts/{part_index}", response_model=VideoUploadPartRead)
async def upload_video_part(
    session_id: str,
    part_index: int,
    file: UploadFile = File(...),
    sha256: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoUploadPartRead:
    session = db.get(VideoUploadSession, session_id)
    if session is None or session.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    try:
        part = video_service.put_upload_part(db, session, part_index, await file.read(), sha256)
        return VideoUploadPartRead(
            session_id=part.session_id,
            part_index=part.part_index,
            size_bytes=part.size_bytes,
            sha256=part.sha256,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/videos/upload-sessions/{session_id}/complete", response_model=VideoItemDetail)
def complete_video_upload(
    session_id: str,
    payload: VideoUploadCompleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    session = db.get(VideoUploadSession, session_id)
    if session is None or session.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    try:
        video = video_service.complete_upload(db, session, payload)
        background_tasks.add_task(video_service.optimize_video_faststart, video.id)
        if payload.generate_zh_subtitles:
            task = create_task(db, "video_subtitle_generation", "已排队生成中文字幕", current.workspace_id)
            subtitle_service.prepare_track(db, video.id, task.id)
            background_tasks.add_task(subtitle_service.generate_for_video, video.id, task.id)
            db.refresh(video)
        return _video_to_detail(video)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/videos/upload-sessions/{session_id}")
def cancel_video_upload(
    session_id: str,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    session = db.get(VideoUploadSession, session_id)
    if session is None or session.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    video_service.cancel_upload(db, session)
    return {"status": "cancelled"}


@app.get("/api/videos", response_model=PaginatedVideos)
def list_videos(
    category_tag_ids: list[int] = Query(default=[]),
    person_ids: list[int] = Query(default=[]),
    query_text: str | None = Query(default=None, alias="query"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PaginatedVideos:
    query = select(VideoItem).where(VideoItem.workspace_id == current.workspace_id).order_by(VideoItem.created_at.desc())
    count_query = select(func.count(VideoItem.id)).where(VideoItem.workspace_id == current.workspace_id)
    if query_text and query_text.strip():
        keyword = f"%{query_text.strip()}%"
        query = query.where((VideoItem.title.like(keyword)) | (VideoItem.description.like(keyword)) | (VideoItem.filename.like(keyword)))
        count_query = count_query.where(
            (VideoItem.title.like(keyword)) | (VideoItem.description.like(keyword)) | (VideoItem.filename.like(keyword))
        )
    if category_tag_ids:
        matched_categories = (
            select(VideoItemCategoryTag.video_id)
            .where(VideoItemCategoryTag.tag_id.in_(category_tag_ids))
            .group_by(VideoItemCategoryTag.video_id)
            .having(func.count(func.distinct(VideoItemCategoryTag.tag_id)) == len(set(category_tag_ids)))
            .subquery()
        )
        query = query.where(VideoItem.id.in_(select(matched_categories.c.video_id)))
        count_query = count_query.where(VideoItem.id.in_(select(matched_categories.c.video_id)))
    if person_ids:
        matched_people = (
            select(VideoItemPerson.video_id)
            .where(VideoItemPerson.person_id.in_(person_ids))
            .group_by(VideoItemPerson.video_id)
            .having(func.count(func.distinct(VideoItemPerson.person_id)) == len(set(person_ids)))
            .subquery()
        )
        query = query.where(VideoItem.id.in_(select(matched_people.c.video_id)))
        count_query = count_query.where(VideoItem.id.in_(select(matched_people.c.video_id)))
    total = db.scalar(count_query) or 0
    videos = db.scalars(query.offset(offset).limit(limit)).unique().all()
    return PaginatedVideos(items=[_video_to_list_item(video) for video in videos], total=total, offset=offset, limit=limit)


@app.get("/api/videos/{video_id}", response_model=VideoItemDetail)
def get_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if video_service.needs_metadata_repair(video):
        background_tasks.add_task(video_service.repair_video_metadata, video.id)
    return _video_to_detail(video)


@app.get("/api/videos/{video_id}/subtitles", response_model=list[VideoSubtitleTrackRead])
def list_video_subtitles(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[VideoSubtitleTrackRead]:
    _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    tracks = db.scalars(
        select(VideoSubtitleTrack)
        .where(VideoSubtitleTrack.video_id == video_id)
        .order_by(VideoSubtitleTrack.created_at.asc())
    ).all()
    return [_subtitle_to_read(track) for track in tracks]


@app.get("/api/videos/{video_id}/embedded-subtitle-streams", response_model=list[EmbeddedSubtitleStreamRead])
def list_embedded_subtitle_streams(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[EmbeddedSubtitleStreamRead]:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    try:
        return [EmbeddedSubtitleStreamRead(**stream) for stream in subtitle_service.list_embedded_subtitle_streams(video)]
    except Exception as exc:
        logger.exception("Failed to list embedded subtitle streams video_id=%s", video_id)
        raise HTTPException(status_code=400, detail=str(exc) or "读取视频字幕轨道失败") from exc


@app.post("/api/videos/{video_id}/subtitles/import-from-video", response_model=VideoSubtitleTrackRead)
def import_video_subtitle_from_video(
    video_id: int,
    payload: ImportSubtitleFromVideoRequest,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    target = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    source = _get_workspace_object(db, VideoItem, payload.source_video_id, current.workspace_id, "Video")
    try:
        track = subtitle_service.import_embedded_subtitle(
            db,
            target,
            source,
            payload.stream_index,
            replace=payload.replace,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Failed to import embedded subtitle target_video_id=%s source_video_id=%s stream_index=%s",
            video_id,
            payload.source_video_id,
            payload.stream_index,
        )
        raise HTTPException(status_code=400, detail=str(exc) or "导入字幕失败") from exc
    return _subtitle_to_read(track)


@app.post("/api/videos/{video_id}/subtitles/generate", response_model=VideoSubtitleTrackRead)
def generate_video_subtitles(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    task = create_task(db, "video_subtitle_generation", "已排队生成中文字幕", current.workspace_id)
    track = subtitle_service.prepare_track(db, video.id, task.id)
    background_tasks.add_task(subtitle_service.generate_for_video, video.id, task.id)
    return _subtitle_to_read(track)


@app.post("/api/videos/{video_id}/subtitles/{track_id}/cancel", response_model=VideoSubtitleTrackRead)
def cancel_video_subtitles(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    try:
        track = subtitle_service.cancel_track_generation(db, video_id, track_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _subtitle_to_read(track)


@app.get("/api/videos/{video_id}/subtitles/{track_id}.vtt")
def get_video_subtitle_vtt(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    if track.status != "ready" or not track.content_vtt:
        raise HTTPException(status_code=409, detail="Subtitle track is not ready")
    return Response(content=track.content_vtt, media_type="text/vtt; charset=utf-8")


@app.patch("/api/videos/{video_id}/subtitles/{track_id}", response_model=VideoSubtitleTrackRead)
def update_video_subtitle(
    video_id: int,
    track_id: int,
    payload: VideoSubtitleTrackUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    try:
        track.content_vtt = subtitle_service.validate_webvtt(payload.content_vtt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    track.status = "ready"
    track.error_message = None
    track.generated_at = track.generated_at or datetime.utcnow()
    db.add(track)
    db.commit()
    db.refresh(track)
    return _subtitle_to_read(track)


@app.delete("/api/videos/{video_id}/subtitles/{track_id}")
def delete_video_subtitle(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    db.delete(track)
    db.commit()
    return {"status": "deleted"}


@app.patch("/api/videos/{video_id}", response_model=VideoItemDetail)
def update_video(
    video_id: int,
    payload: VideoMetadataUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if payload.title is not None:
        video.title = payload.title.strip()
    if payload.description is not None:
        video.description = payload.description
    db.add(video)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@app.delete("/api/videos/{video_id}")
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    video_service.delete_video(db, video)
    return {"status": "deleted"}


@app.get("/api/videos/{video_id}/cover")
def get_video_cover(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if not video.cover_object_key:
        raise HTTPException(status_code=404, detail="Video cover not found")
    payload = storage.get_bytes(video.cover_object_key)
    return Response(content=payload, media_type=video.cover_content_type or "image/jpeg")


@app.put("/api/videos/{video_id}/cover", response_model=VideoItemDetail)
async def replace_video_cover(
    video_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    try:
        updated = video_service.save_video_cover(db, video, await file.read(), file.filename or "cover.jpg", file.content_type)
        return _video_to_detail(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/videos/{video_id}/category-tags", response_model=VideoItemDetail)
def add_video_category_tag(
    video_id: int,
    payload: VideoTagBindCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    try:
        tag = (
            db.get(VideoCategoryTag, payload.tag_id)
            if payload.tag_id
            else video_service.find_or_create_category_tag(db, payload.name or "", current.workspace_id)
        )
        if tag is None or tag.workspace_id != current.workspace_id:
            raise HTTPException(status_code=404, detail="Video category tag not found")
        existing = db.scalar(select(VideoItemCategoryTag).where(VideoItemCategoryTag.video_id == video.id, VideoItemCategoryTag.tag_id == tag.id))
        if existing is None:
            db.add(VideoItemCategoryTag(video_id=video.id, tag_id=tag.id))
        db.commit()
        db.refresh(video)
        return _video_to_detail(video)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/videos/{video_id}/category-tags/{tag_id}", response_model=VideoItemDetail)
def remove_video_category_tag(
    video_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    _get_workspace_object(db, VideoCategoryTag, tag_id, current.workspace_id, "Video category tag")
    link = db.scalar(select(VideoItemCategoryTag).where(VideoItemCategoryTag.video_id == video_id, VideoItemCategoryTag.tag_id == tag_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Video category tag link not found")
    db.delete(link)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@app.post("/api/videos/{video_id}/people", response_model=VideoItemDetail)
def add_video_person(
    video_id: int,
    payload: VideoPersonBindCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    person = _get_workspace_object(db, VideoPerson, payload.person_id, current.workspace_id, "Video person")
    existing = db.scalar(select(VideoItemPerson).where(VideoItemPerson.video_id == video.id, VideoItemPerson.person_id == person.id))
    if existing is None:
        db.add(VideoItemPerson(video_id=video.id, person_id=person.id))
        db.commit()
        db.refresh(video)
    return _video_to_detail(video)


@app.delete("/api/videos/{video_id}/people/{person_id}", response_model=VideoItemDetail)
def remove_video_person(
    video_id: int,
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    _get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    link = db.scalar(select(VideoItemPerson).where(VideoItemPerson.video_id == video_id, VideoItemPerson.person_id == person_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Video person link not found")
    db.delete(link)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


def _stream_video_response(video: VideoItem, request: Request) -> StreamingResponse:
    stat = storage.stat_object(video.object_key)
    size = stat.size
    range_tuple = _parse_range_header(request.headers.get("range"), size)
    filename = quote(video.filename)
    if range_tuple is None:
        response = storage.get_stream(video.object_key)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        }
        return StreamingResponse(_iter_minio_response(response), media_type=video.content_type or "video/mp4", headers=headers)
    start, end = range_tuple
    length = end - start + 1
    response = storage.get_stream(video.object_key, offset=start, length=length)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(length),
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
    }
    return StreamingResponse(
        _iter_minio_response(response),
        status_code=206,
        media_type=video.content_type or "video/mp4",
        headers=headers,
    )


@app.get("/api/videos/{video_id}/play")
def play_video(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
):
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if settings.video_use_presigned_play_url:
        try:
            play_url = storage.presigned_get_url(video.object_key, settings.video_presigned_url_expires_seconds)
            response = RedirectResponse(play_url, status_code=307)
            response.headers["X-PictureShow-Video-Mode"] = "minio-presigned"
            response.headers["X-PictureShow-Minio-Endpoint"] = settings.minio_public_endpoint or settings.minio_endpoint
            return response
        except Exception:
            logger.exception("Failed to redirect video play url video_id=%s", video.id)
    response = _stream_video_response(video, request)
    response.headers["X-PictureShow-Video-Mode"] = "backend-stream-fallback"
    return response


@app.get("/api/videos/{video_id}/stream")
def stream_video(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    response = _stream_video_response(video, request)
    response.headers["X-PictureShow-Video-Mode"] = "backend-stream"
    return response


@app.get("/api/videos/{video_id}/playback-diagnostics")
def get_video_playback_diagnostics(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, object]:
    video = _get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    result: dict[str, object] = {
        "video_id": video.id,
        "status": video.status,
        "content_type": video.content_type,
        "size_bytes": video.size_bytes,
        "play_url": _video_play_url(video),
        "stream_url": _video_stream_url(video),
        "presigned_enabled": settings.video_use_presigned_play_url,
        "minio_endpoint": settings.minio_endpoint,
        "minio_public_endpoint": settings.minio_public_endpoint or settings.minio_endpoint,
        "minio_public_secure": settings.minio_secure if settings.minio_public_secure is None else settings.minio_public_secure,
        "expected_mode": "minio-presigned" if settings.video_use_presigned_play_url else "backend-stream",
    }
    if settings.video_use_presigned_play_url:
        try:
            presigned_url = storage.presigned_get_url(video.object_key, settings.video_presigned_url_expires_seconds)
            parsed = urlparse(presigned_url)
            result["presigned_url_scheme"] = parsed.scheme
            result["presigned_url_host"] = parsed.netloc
            result["presigned_url_path_prefix"] = parsed.path.rsplit("/", 1)[0]
            result["presigned_url_ok"] = True
        except Exception as exc:
            logger.exception("Failed to build video playback diagnostic presigned url video_id=%s", video.id)
            result["presigned_url_ok"] = False
            result["presigned_url_error"] = str(exc)[:500]
            result["expected_mode"] = "backend-stream-fallback"
    return result


@app.get("/api/statistics/tags", response_model=list[TagStatistics])
def get_tag_statistics(
    is_system: bool | None = Query(default=None, description="Filter by system tag status"),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[TagStatistics]:
    """Get photo count statistics for each tag."""
    query = (
        select(
            Tag.id,
            Tag.name,
            Tag.is_system,
            func.count(GalleryPhotoTag.gallery_photo_id).label("photo_count"),
        )
        .outerjoin(GalleryPhotoTag, Tag.id == GalleryPhotoTag.tag_id)
        .where(Tag.workspace_id == current.workspace_id)
        .group_by(Tag.id)
    )
    if is_system is not None:
        query = query.where(Tag.is_system == is_system)
    results = db.execute(query).all()
    return [
        TagStatistics(
            tag_id=row.id,
            tag_name=row.name,
            is_system=row.is_system,
            photo_count=row.photo_count,
        )
        for row in results
    ]


@app.get("/api/statistics/upload-history", response_model=list[UploadHistoryRead])
def get_upload_history(
    upload_type: str | None = Query(default=None, description="Filter by upload type: gallery or rich"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[UploadHistoryRead]:
    """Get upload history records."""
    query = (
        select(UploadHistory)
        .where(UploadHistory.workspace_id == current.workspace_id)
        .order_by(UploadHistory.created_at.desc())
    )
    if upload_type:
        query = query.where(UploadHistory.upload_type == upload_type)
    query = query.offset(offset).limit(limit)
    results = db.scalars(query).all()
    return [UploadHistoryRead.model_validate(r) for r in results]


@app.get("/api/statistics/upload-summary")
def get_upload_summary(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict:
    """Get summary statistics of uploads."""
    total_uploads = db.scalar(select(func.count(UploadHistory.id)).where(UploadHistory.workspace_id == current.workspace_id))
    total_photos = db.scalar(select(func.sum(UploadHistory.total_count)).where(UploadHistory.workspace_id == current.workspace_id)) or 0
    total_success = db.scalar(select(func.sum(UploadHistory.success_count)).where(UploadHistory.workspace_id == current.workspace_id)) or 0
    total_duplicates = db.scalar(select(func.sum(UploadHistory.duplicate_count)).where(UploadHistory.workspace_id == current.workspace_id)) or 0
    
    by_type = {}
    for upload_type in ["gallery", "rich"]:
        count = db.scalar(
            select(func.count(UploadHistory.id)).where(
                UploadHistory.workspace_id == current.workspace_id,
                UploadHistory.upload_type == upload_type,
            )
        )
        photos = db.scalar(
            select(func.sum(UploadHistory.total_count)).where(
                UploadHistory.workspace_id == current.workspace_id,
                UploadHistory.upload_type == upload_type,
            )
        ) or 0
        by_type[upload_type] = {"count": count, "photos": photos}
    
    return {
        "total_uploads": total_uploads,
        "total_photos": total_photos,
        "total_success": total_success,
        "total_duplicates": total_duplicates,
        "by_type": by_type,
    }


@app.get("/api/statistics/persons", response_model=list[PersonStatistics])
def get_person_statistics(
    is_unknown: bool | None = Query(default=None, description="Filter by unknown person status"),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[PersonStatistics]:
    """Get photo count statistics for each person."""
    # Create subqueries for counts to avoid cartesian product inflation
    photo_count_sq = (
        select(
            GalleryPhotoPersonTag.person_id,
            func.count(GalleryPhotoPersonTag.gallery_photo_id).label("count")
        )
        .join(GalleryPhoto, GalleryPhoto.id == GalleryPhotoPersonTag.gallery_photo_id)
        .where(GalleryPhoto.workspace_id == current.workspace_id)
        .group_by(GalleryPhotoPersonTag.person_id)
        .subquery()
    )
    
    sample_count_sq = (
        select(
            SamplePhoto.person_id,
            func.count(SamplePhoto.id).label("count")
        )
        .where(SamplePhoto.workspace_id == current.workspace_id)
        .group_by(SamplePhoto.person_id)
        .subquery()
    )

    query = (
        select(
            Person.id,
            Person.name,
            Person.display_name,
            Person.is_unknown,
            func.coalesce(photo_count_sq.c.count, 0).label("photo_count"),
            func.coalesce(sample_count_sq.c.count, 0).label("sample_count"),
        )
        .outerjoin(photo_count_sq, Person.id == photo_count_sq.c.person_id)
        .outerjoin(sample_count_sq, Person.id == sample_count_sq.c.person_id)
        .where(Person.workspace_id == current.workspace_id)
    )
    
    if is_unknown is not None:
        query = query.where(Person.is_unknown == is_unknown)
    
    query = query.order_by(Person.is_unknown.asc(), func.coalesce(photo_count_sq.c.count, 0).desc())
    results = db.execute(query).all()
    
    return [
        PersonStatistics(
            person_id=row.id,
            person_name=row.name,
            display_name=row.display_name,
            is_unknown=row.is_unknown,
            photo_count=row.photo_count,
            sample_count=row.sample_count,
        )
        for row in results
    ]
