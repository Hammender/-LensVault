from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from io import BytesIO
import json
import logging
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api._helpers import get_workspace_object
from app.background_tasks import process_gallery_import_task, process_gallery_similarity_scan_task, process_gallery_zip_import_task
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.http.media import stream_storage_object
from app.mappers.gallery import gallery_photo_to_detail as _gallery_photo_to_detail, gallery_photo_to_list_item as _gallery_photo_to_list_item
from app.mappers.people import person_to_read
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, GallerySimilarityGroup, GallerySimilarityScan, Person, PersonTag, SamplePhoto, Tag, Task
from app.schemas import (
    GallerySimilarityGroupRead,
    GallerySimilarityGroupUpdate,
    GallerySimilarityMemberRead,
    GallerySimilarityScanCreate,
    GallerySimilarityScanOverview,
    GallerySimilarityScanRead,
    GalleryPhotoBatchDeleteRequest,
    GalleryPhotoDetail,
    GalleryPhotoPersonTagCreate,
    GalleryPhotoRichTextUpdate,
    GalleryPhotoTagCreate,
    PaginatedGalleryPhotos,
    PaginatedGallerySimilarityGroups,
    TaskRead,
)
from app.services.similarity import load_similarity_scan_overview, mark_similarity_scans_stale
from app.services.tasks import create_task
from app.services.thumbnails import animated_thumbnail_cache_key, render_gallery_thumbnail

_services_context: ContextVar[object] = ContextVar("gallery_services")


class _ServiceProxy:
    def __init__(self, name: str):
        self.name = name

    def __getattr__(self, attribute: str):
        return getattr(getattr(_services_context.get(), self.name), attribute)


async def _bind_services(request: Request):
    token = _services_context.set(request.app.state.services)
    try:
        yield
    finally:
        _services_context.reset(token)


storage = _ServiceProxy("storage")
picture_service = _ServiceProxy("pictures")
imports_router = APIRouter()
router = APIRouter(dependencies=[Depends(_bind_services)])
logger = logging.getLogger(__name__)


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


def _gallery_similarity_scan_read(db: Session, scan: GallerySimilarityScan) -> GallerySimilarityScanRead:
    task = db.get(Task, scan.task_id) if scan.task_id else None
    return GallerySimilarityScanRead(
        id=scan.id,
        task_id=scan.task_id,
        person_id=scan.person_id,
        include_cross_type=scan.include_cross_type,
        status=scan.status,
        is_stale=scan.is_stale,
        feature_version=scan.feature_version,
        photo_count=scan.photo_count,
        candidate_pair_count=scan.candidate_pair_count,
        group_count=scan.group_count,
        error_message=scan.error_message,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
        task=TaskRead.model_validate(task) if task is not None else None,
    )


def _gallery_similarity_group_read(db: Session, group: GallerySimilarityGroup) -> GallerySimilarityGroupRead:
    people = db.scalars(select(Person).where(Person.id.in_([link.person_id for link in group.people])).order_by(Person.display_name.asc())).all()
    members: list[GallerySimilarityMemberRead] = []
    for member in sorted(group.members, key=lambda item: (-item.quality_score, item.gallery_photo_id)):
        photo = member.gallery_photo
        for link in photo.person_tags:
            link.person
        for link in photo.tags:
            link.tag
        members.append(
            GallerySimilarityMemberRead(
                photo=_gallery_photo_to_list_item(photo),
                score_to_representative=member.score_to_representative,
                quality_score=member.quality_score,
                recommended_keep=member.recommended_keep,
            )
        )
    return GallerySimilarityGroupRead(
        id=group.id,
        ordinal=group.ordinal,
        tier=group.tier,
        review_status=group.review_status,
        min_score=group.min_score,
        average_score=group.average_score,
        people=[person_to_read(db, person) for person in people],
        members=members,
    )


@imports_router.post("/api/gallery/photos/import", response_model=TaskRead)
async def import_gallery_photos(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    metadata = _parse_gallery_metadata(metadata_json, len(uploads))
    task = create_task(db, "gallery_import", f"已排队 {len(uploads)} 张普通图片", current.workspace_id)
    logger.info("Gallery import enqueued task_id=%s files=%d metadata_items=%d rich_mode=false", task.id, len(uploads), len(metadata))
    background_tasks.add_task(
        process_gallery_import_task,
        request.app.state.session_factory,
        request.app.state.services.pictures,
        task.id,
        uploads,
        metadata,
        False,
        current.workspace_id,
    )
    return TaskRead.model_validate(task)


@imports_router.post("/api/gallery/rich-photos/import", response_model=TaskRead)
async def import_gallery_rich_photos(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    metadata = _parse_gallery_metadata(metadata_json, len(uploads))
    task = create_task(db, "gallery_rich_import", f"已排队 {len(uploads)} 张图文图片", current.workspace_id)
    logger.info("Gallery rich import enqueued task_id=%s files=%d metadata_items=%d rich_mode=true", task.id, len(uploads), len(metadata))
    background_tasks.add_task(
        process_gallery_import_task,
        request.app.state.session_factory,
        request.app.state.services.pictures,
        task.id,
        uploads,
        metadata,
        True,
        current.workspace_id,
    )
    return TaskRead.model_validate(task)


@imports_router.get("/api/gallery/photos/export")
def export_gallery_photos(
    request: Request,
    scope: str = Query(default="all", pattern="^(all|filtered)$"),
    person_ids: list[int] = Query(default=[]),
    tag_ids: list[int] = Query(default=[]),
    exclude_person_ids: list[int] = Query(default=[]),
    exclude_tag_ids: list[int] = Query(default=[]),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    base_query = select(GalleryPhoto).where(GalleryPhoto.workspace_id == current.workspace_id).order_by(GalleryPhoto.taken_at.desc().nullslast(), GalleryPhoto.created_at.desc())
    query = _apply_gallery_filters(base_query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids) if scope == "filtered" else base_query
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
    buffer = BytesIO()
    storage = request.app.state.services.storage
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for photo in photos:
            image_bytes = storage.get_bytes(photo.object_key)
            normal_tags = sorted({link.tag.name for link in photo.tags if not link.tag.is_system})
            folder_names = normal_tags or ["_未分类"]
            filename = _safe_zip_name(f"{photo.id}_{photo.filename}", f"{photo.id}_photo")
            zip_paths: list[str] = []
            for tag_name in folder_names:
                zip_path = _unique_zip_path(f"gallery/by_tag/{_safe_zip_name(tag_name, '_未分类')}/{filename}", used_paths)
                archive.writestr(zip_path, image_bytes)
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
                        {"name": item.person.name, "display_name": item.person.display_name, "is_unknown": item.person.is_unknown, "source": item.source}
                        for item in sorted(photo.person_tags, key=lambda item: (item.person.is_unknown, item.person.display_name.lower()))
                    ],
                    "paths": zip_paths,
                }
            )
        archive.writestr(
            "metadata.json",
            json.dumps({"version": 1, "kind": "gallery_export", "scope": scope, "exported_at": datetime.utcnow().isoformat(), "photos": manifest_photos}, ensure_ascii=False, indent=2),
        )

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="gallery_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip"'},
    )


@imports_router.post("/api/gallery/photos/import-zip", response_model=TaskRead)
async def import_gallery_export_zip(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    zip_bytes = await file.read()
    task = create_task(db, "gallery_zip_import", "已排队展示图 ZIP 导入", current.workspace_id)
    logger.info("Gallery zip import enqueued task_id=%s bytes=%d", task.id, len(zip_bytes))
    background_tasks.add_task(
        process_gallery_zip_import_task,
        request.app.state.session_factory,
        request.app.state.services.pictures,
        task.id,
        zip_bytes,
        current.workspace_id,
    )
    return TaskRead.model_validate(task)


@imports_router.get("/api/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> TaskRead:
    task = db.get(Task, task_id)
    if task is None or task.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)


@router.post("/api/gallery/similarity-scans", response_model=GallerySimilarityScanRead)
def create_gallery_similarity_scan(
    payload: GallerySimilarityScanCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityScanRead:
    if payload.person_id is not None:
        get_workspace_object(db, Person, payload.person_id, current.workspace_id, "Person")
    running = db.scalar(
        select(GallerySimilarityScan).where(
            GallerySimilarityScan.workspace_id == current.workspace_id,
            GallerySimilarityScan.status.in_(("pending", "running")),
        )
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="当前 workspace 已有相似图片扫描正在运行")
    task = create_task(db, "gallery_similarity_scan", "相似图片扫描已排队", current.workspace_id)
    scan = GallerySimilarityScan(
        id=task.id,
        workspace_id=current.workspace_id,
        task_id=task.id,
        person_id=payload.person_id,
        include_cross_type=payload.include_cross_type,
        status="pending",
        feature_version=request.app.state.settings.gallery_similarity_model_version,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    background_tasks.add_task(
        process_gallery_similarity_scan_task,
        request.app.state.session_factory,
        request.app.state.services.similarity,
        scan.id,
        task.id,
    )
    return _gallery_similarity_scan_read(db, scan)


@router.get("/api/gallery/similarity-scans/latest", response_model=GallerySimilarityScanRead | None)
def get_latest_gallery_similarity_scan(
    person_id: int | None = None,
    include_cross_type: bool = False,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityScanRead | None:
    query = select(GallerySimilarityScan).where(
        GallerySimilarityScan.workspace_id == current.workspace_id,
        GallerySimilarityScan.include_cross_type == include_cross_type,
    )
    query = query.where(GallerySimilarityScan.person_id.is_(None) if person_id is None else GallerySimilarityScan.person_id == person_id)
    scan = db.scalar(query.order_by(GallerySimilarityScan.created_at.desc()).limit(1))
    return _gallery_similarity_scan_read(db, scan) if scan is not None else None


@router.get("/api/gallery/similarity-scans/overview", response_model=GallerySimilarityScanOverview)
def get_gallery_similarity_scan_overview(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityScanOverview:
    active, results = load_similarity_scan_overview(db, current.workspace_id)
    return GallerySimilarityScanOverview(
        active=_gallery_similarity_scan_read(db, active) if active is not None else None,
        results=[_gallery_similarity_scan_read(db, scan) for scan in results],
    )


@router.get("/api/gallery/similarity-scans/{scan_id}/groups", response_model=PaginatedGallerySimilarityGroups)
def list_gallery_similarity_groups(
    scan_id: str,
    tier: str = Query(default="near_duplicate", pattern="^(near_duplicate|same_scene)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PaginatedGallerySimilarityGroups:
    scan = db.get(GallerySimilarityScan, scan_id)
    if scan is None or scan.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Similarity scan not found")
    condition = (GallerySimilarityGroup.scan_id == scan_id, GallerySimilarityGroup.tier == tier, GallerySimilarityGroup.review_status == "pending")
    total = db.scalar(select(func.count(GallerySimilarityGroup.id)).where(*condition)) or 0
    groups = db.scalars(select(GallerySimilarityGroup).where(*condition).order_by(GallerySimilarityGroup.ordinal.asc()).offset(offset).limit(limit)).all()
    return PaginatedGallerySimilarityGroups(
        items=[_gallery_similarity_group_read(db, group) for group in groups], total=total, offset=offset, limit=limit
    )


@router.get("/api/gallery/similarity-scans/{scan_id}/groups/{group_id}", response_model=GallerySimilarityGroupRead | None)
def get_gallery_similarity_group(
    scan_id: str,
    group_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityGroupRead | None:
    scan = db.get(GallerySimilarityScan, scan_id)
    if scan is None or scan.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Similarity scan not found")
    group = db.scalar(select(GallerySimilarityGroup).where(GallerySimilarityGroup.id == group_id, GallerySimilarityGroup.scan_id == scan_id))
    return _gallery_similarity_group_read(db, group) if group is not None else None


@router.patch("/api/gallery/similarity-scans/{scan_id}/groups/{group_id}", response_model=GallerySimilarityGroupRead)
def update_gallery_similarity_group(
    scan_id: str,
    group_id: int,
    payload: GallerySimilarityGroupUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityGroupRead:
    scan = db.get(GallerySimilarityScan, scan_id)
    if scan is None or scan.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Similarity scan not found")
    group = db.scalar(select(GallerySimilarityGroup).where(GallerySimilarityGroup.id == group_id, GallerySimilarityGroup.scan_id == scan_id))
    if group is None:
        raise HTTPException(status_code=404, detail="Similarity group not found")
    group.review_status = payload.review_status
    db.add(group)
    db.commit()
    db.refresh(group)
    return _gallery_similarity_group_read(db, group)


@router.get("/api/gallery/photos", response_model=PaginatedGalleryPhotos)
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


@router.get("/api/gallery/photos/{photo_id}", response_model=GalleryPhotoDetail)
def get_gallery_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    photo.person_tags
    photo.tags
    photo.faces
    photo.promoted_samples
    for tag in photo.person_tags:
        tag.person
    for tag_link in photo.tags:
        tag_link.tag
    return _gallery_photo_to_detail(photo)


@router.post("/api/gallery/photos/batch-delete")
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


@router.delete("/api/gallery/photos/{photo_id}")
def delete_gallery_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    picture_service.delete_gallery_photos(db, [photo])
    return {"status": "ok"}


@router.get("/api/gallery/photos/{photo_id}/original")
def get_gallery_original(
    photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    return stream_storage_object(storage, request, photo.object_key, photo.filename, photo.content_type)


@router.get("/api/gallery/photos/{photo_id}/thumbnail")
def get_gallery_thumbnail(
    photo_id: int,
    width: int = 480,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    payload = storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@router.get("/api/gallery/photos/{photo_id}/animated-thumbnail")
def get_gallery_animated_thumbnail(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    cache_key = animated_thumbnail_cache_key(photo.workspace_id, photo.id, photo.sha256)
    cache_headers = {"Cache-Control": "private, max-age=31536000, immutable"}

    try:
        cached = storage.get_bytes(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return Response(content=cached, media_type="image/webp", headers=cache_headers)

    payload = storage.get_bytes(photo.object_key)
    try:
        thumbnail = render_gallery_thumbnail(payload)
    except Exception:
        logger.exception("Failed to render animated gallery thumbnail photo_id=%s", photo.id)
        return Response(
            content=payload,
            media_type=photo.content_type or "application/octet-stream",
            headers=cache_headers,
        )

    if thumbnail.is_animated:
        try:
            storage.put_bytes(cache_key, thumbnail.payload, thumbnail.media_type)
        except Exception:
            logger.exception("Failed to cache animated gallery thumbnail photo_id=%s", photo.id)
    return Response(content=thumbnail.payload, media_type=thumbnail.media_type, headers=cache_headers)


@router.post("/api/gallery/photos/{photo_id}/persons", response_model=GalleryPhotoDetail)
def add_gallery_photo_person(
    photo_id: int,
    payload: GalleryPhotoPersonTagCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    person = get_workspace_object(db, Person, payload.person_id, current.workspace_id, "Person")
    if person.is_unknown:
        raise HTTPException(status_code=400, detail="不能手动添加系统未知人物标签")
    picture_service.ensure_gallery_person_tag(db, photo_id, person.id, "manual")
    picture_service.apply_person_tags_to_gallery_photo(db, photo_id, person.id)

    faces = db.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo_id)).all()
    if len(faces) == 1:
        picture_service.move_gallery_face_to_known(db, faces[0], person)

    mark_similarity_scans_stale(db, current.workspace_id, {person.id})
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@router.post("/api/gallery/photos/{photo_id}/persons/{person_id}/sample", response_model=GalleryPhotoDetail)
def promote_gallery_photo_person_sample(
    photo_id: int,
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    link = db.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo_id,
            GalleryPhotoPersonTag.person_id == person_id,
        )
    )
    if link is None or person.is_unknown:
        raise HTTPException(status_code=400, detail="当前图片没有可加入样本库的正式人物标签")
    faces = db.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo_id)).all()
    if len(faces) != 1:
        raise HTTPException(status_code=400, detail="只有检测到恰好一张人脸时才能加入样本库")
    try:
        picture_service.promote_gallery_face_to_sample(db, photo, faces[0], person)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_gallery_photo(photo_id, db, current)


@router.delete("/api/gallery/photos/{photo_id}/persons/{person_id}/sample", response_model=GalleryPhotoDetail)
def undo_gallery_photo_person_sample(
    photo_id: int,
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    sample = db.scalar(
        select(SamplePhoto).where(
            SamplePhoto.workspace_id == current.workspace_id,
            SamplePhoto.person_id == person_id,
            SamplePhoto.source_gallery_photo_id == photo_id,
        )
    )
    if sample is None:
        raise HTTPException(status_code=404, detail="该图片尚未加入此人物样本库")
    picture_service.delete_sample_photo(db, sample)
    return get_gallery_photo(photo_id, db, current)


@router.delete("/api/gallery/photos/{photo_id}/persons/{person_id}", response_model=GalleryPhotoDetail)
def delete_gallery_photo_person(
    photo_id: int,
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    link = db.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo_id,
            GalleryPhotoPersonTag.person_id == person_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Person tag not found")
    if picture_service.is_singleton_unknown_person(person):
        faces = db.scalars(
            select(FaceRecord).where(
                FaceRecord.gallery_photo_id == photo_id,
                FaceRecord.matched_person_id == person.id,
            )
        ).all()
        for face in faces:
            face.matched_person_id = None
            face.match_score = None
            face.needs_review = False
            face.vector_collection = None
            db.add(face)
        db.delete(link)
        mark_similarity_scans_stale(db, current.workspace_id, {person.id})
        db.commit()
        return get_gallery_photo(photo_id, db, current)
    
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
    
    mark_similarity_scans_stale(db, current.workspace_id, {person.id})
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@router.post("/api/gallery/photos/{photo_id}/tags", response_model=GalleryPhotoDetail)
def add_gallery_photo_tag(
    photo_id: int,
    payload: GalleryPhotoTagCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    if payload.tag_id is not None:
        tag = db.get(Tag, payload.tag_id)
        if tag is None or tag.workspace_id != current.workspace_id:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = picture_service.find_or_create_tag(db, payload.name or "", current.workspace_id)
    picture_service.ensure_gallery_tag(db, photo_id, tag, source="manual")
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@router.delete("/api/gallery/photos/{photo_id}/tags/{tag_id}", response_model=GalleryPhotoDetail)
def delete_gallery_photo_tag(
    photo_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
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


@router.patch("/api/gallery/photos/{photo_id}/rich-text", response_model=GalleryPhotoDetail)
def update_gallery_photo_rich_text(
    photo_id: int,
    payload: GalleryPhotoRichTextUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    if not photo.is_rich_text:
        raise HTTPException(status_code=400, detail="Photo is not rich-text type")
    value = (payload.rich_text or "").strip()
    photo.rich_text = value or None
    photo.ocr_status = "manual" if value else "empty"
    db.add(photo)
    db.commit()
    return get_gallery_photo(photo_id, db, current)


@router.post("/api/gallery/photos/{photo_id}/re-recognize", response_model=GalleryPhotoDetail)
def re_recognize_gallery_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GalleryPhotoDetail:
    photo = get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "Photo")
    photo = picture_service.re_recognize_gallery_photo(db, photo)
    return _gallery_photo_to_detail(photo)


@router.post("/api/gallery/photos/re-recognize-unknown")
def re_recognize_unknown_gallery_photos(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    return picture_service.re_recognize_unknown_gallery_photos(db, current.workspace_id)


