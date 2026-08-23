from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from io import BytesIO
import json
import logging
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api._helpers import get_workspace_object
from app.core.timezones import shanghai_isoformat, shanghai_now
from app.background_tasks import process_gallery_import_task, process_gallery_similarity_scan_task, process_gallery_zip_import_task
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context, require_permission
from app.http.media import stream_storage_object
from app.mappers.gallery import gallery_photo_to_detail as _gallery_photo_to_detail, gallery_photo_to_list_item as _gallery_photo_to_list_item
from app.mappers.people import person_to_read
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, GallerySimilarityFeature, GallerySimilarityGroup, GallerySimilarityGroupMember, GallerySimilarityGroupPair, GallerySimilarityScan, Person, PersonTag, SamplePhoto, Tag, Task
from app.schemas import (
    GallerySimilarityAutoDeleteExecuteRequest,
    GallerySimilarityAutoDeleteResponse,
    GallerySimilarityAutoDeletePreviewCluster,
    GallerySimilarityAutoDeletePreviewMember,
    GallerySimilarityAutoDeletePreviewResponse,
    GallerySimilarityClusterRead,
    GallerySimilarityGroupRead,
    GallerySimilarityGroupUpdate,
    GallerySimilarityMemberRead,
    GallerySimilarityScanCreate,
    GallerySimilarityScanOverview,
    GallerySimilarityScanRead,
    GalleryPhotoBatchDeleteRequest,
    GalleryPhotoDetail,
    GalleryPhotoExportRequest,
    GalleryPhotoPersonTagCreate,
    GalleryPhotoRichTextUpdate,
    GalleryPhotoTagCreate,
    PaginatedGalleryPhotos,
    PaginatedGallerySimilarityGroups,
    TaskRead,
)
from app.services.similarity import (
    AutoDeleteClusterPlan,
    build_normal_near_duplicate_auto_delete_plan,
    derive_group_auto_clusters,
    load_similarity_scan_overview,
    mark_similarity_scans_stale,
    perceptual_component,
    select_exact_mirror_auto_delete_photo_ids,
    select_normal_near_duplicate_auto_delete_photo_ids,
)
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


def _gallery_display_order() -> tuple[object, ...]:
    return (
        GalleryPhoto.display_batch_at.desc(),
        GalleryPhoto.display_index.asc(),
        GalleryPhoto.created_at.desc(),
        GalleryPhoto.id.desc(),
    )


GalleryUploadMetadata = dict[str, list[int] | list[str] | str | None]
_INVALID_PERSON_SELECTION = "所选人物不存在，请先在样本库创建人物后再上传。"


def _parse_gallery_metadata(raw: str | None, file_count: int) -> list[GalleryUploadMetadata]:
    defaults: list[GalleryUploadMetadata] = [
        {"person_ids": [], "tag_names": [], "rich_text": None} for _ in range(file_count)
    ]
    if not raw:
        return defaults
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="上传元数据格式无效。") from exc
    if not isinstance(payload, list) or len(payload) != file_count:
        raise HTTPException(status_code=422, detail="上传元数据格式无效。")
    allowed_keys = {"person_ids", "tag_names", "rich_text"}
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or not set(item).issubset(allowed_keys):
            raise HTTPException(status_code=422, detail="上传元数据格式无效。")
        person_ids = item.get("person_ids", [])
        tag_names = item.get("tag_names")
        if not isinstance(person_ids, list) or any(
            isinstance(person_id, bool) or not isinstance(person_id, int) or person_id <= 0 for person_id in person_ids
        ):
            raise HTTPException(status_code=422, detail="上传元数据格式无效。")
        if tag_names is not None and (
            not isinstance(tag_names, list) or any(not isinstance(name, str) for name in tag_names)
        ):
            raise HTTPException(status_code=422, detail="上传元数据格式无效。")
        defaults[index]["person_ids"] = list(dict.fromkeys(person_ids))
        defaults[index]["tag_names"] = list(
            dict.fromkeys(name.strip() for name in (tag_names or []) if name.strip())
        )
        rich_text = item.get("rich_text")
        if rich_text is not None and not isinstance(rich_text, str):
            raise HTTPException(status_code=422, detail="上传元数据格式无效。")
        defaults[index]["rich_text"] = (rich_text.strip() or None) if rich_text is not None else None
    return defaults


def _validate_gallery_person_ids(db: Session, metadata: list[GalleryUploadMetadata], workspace_id: int) -> None:
    requested_ids = {
        person_id
        for item in metadata
        for person_id in item.get("person_ids", [])
        if isinstance(person_id, int)
    }
    if not requested_ids:
        return
    valid_ids = set(
        db.scalars(
            select(Person.id).where(
                Person.id.in_(requested_ids),
                Person.workspace_id == workspace_id,
                Person.is_unknown.is_(False),
            )
        ).all()
    )
    if valid_ids != requested_ids:
        raise HTTPException(status_code=422, detail=_INVALID_PERSON_SELECTION)


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
        scan_type=scan.scan_type,
        auto_delete_exact_mirror=scan.auto_delete_exact_mirror,
        auto_deleted_count=scan.auto_deleted_count,
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


def _gallery_similarity_group_read(
    db: Session,
    group: GallerySimilarityGroup,
    auto_cluster_threshold: float,
    auto_cluster_perceptual_min: float,
) -> GallerySimilarityGroupRead:
    pair_rows = db.scalars(
        select(GallerySimilarityGroupPair).where(GallerySimilarityGroupPair.group_id == group.id)
    ).all()
    member_photo_ids = [member.gallery_photo_id for member in group.members]
    feature_map = (
        {
            row.gallery_photo_id: row
            for row in db.scalars(
                select(GallerySimilarityFeature).where(
                    GallerySimilarityFeature.gallery_photo_id.in_(member_photo_ids)
                )
            ).all()
        }
        if member_photo_ids
        else {}
    )
    # 与自动整理预案同一道纯哈希门槛，避免 ORB 背景加成把同机位不同瞬间的图混入簇。
    qualifying_pairs = [
        (row.left_gallery_photo_id, row.right_gallery_photo_id, row.score)
        for row in pair_rows
        if row.score >= auto_cluster_threshold
        and perceptual_component(
            feature_map.get(row.left_gallery_photo_id),
            feature_map.get(row.right_gallery_photo_id),
        )
        >= auto_cluster_perceptual_min
    ]
    clusters = derive_group_auto_clusters(qualifying_pairs, auto_cluster_threshold)
    cluster_index_by_photo: dict[int, int] = {}
    for index, cluster in enumerate(clusters, start=1):
        for photo_id in cluster.member_ids:
            cluster_index_by_photo[photo_id] = index
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
                overall_quality_score=member.overall_quality_score,
                face_quality_score=member.face_quality_score,
                quality_score=member.quality_score,
                recommended_keep=member.recommended_keep,
                auto_cluster_index=cluster_index_by_photo.get(member.gallery_photo_id),
            )
        )
    return GallerySimilarityGroupRead(
        id=group.id,
        ordinal=group.ordinal,
        tier=group.tier,
        review_status=group.review_status,
        min_score=group.min_score,
        average_score=group.average_score,
        face_quality_enabled=group.face_quality_enabled,
        recommendation_status=group.recommendation_status,
        people=[person_to_read(db, person) for person in people],
        members=members,
        clusters=[
            GallerySimilarityClusterRead(
                index=index,
                member_photo_ids=list(cluster.member_ids),
                min_pair_score=cluster.min_score,
                average_pair_score=cluster.average_score,
            )
            for index, cluster in enumerate(clusters, start=1)
        ],
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
    metadata = _parse_gallery_metadata(metadata_json, len(files))
    _validate_gallery_person_ids(db, metadata, current.workspace_id)
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
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
    metadata = _parse_gallery_metadata(metadata_json, len(files))
    _validate_gallery_person_ids(db, metadata, current.workspace_id)
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
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


def _resolve_gallery_export_photos(
    db: Session,
    workspace_id: int,
    payload: GalleryPhotoExportRequest,
) -> list[GalleryPhoto]:
    base_query = (
        select(GalleryPhoto)
        .where(GalleryPhoto.workspace_id == workspace_id)
        .order_by(*_gallery_display_order())
    )
    if payload.scope == "all":
        photos = db.scalars(base_query).unique().all()
    elif payload.scope == "selected":
        requested_ids = set(payload.photo_ids)
        photos = db.scalars(base_query.where(GalleryPhoto.id.in_(requested_ids))).unique().all()
        if {photo.id for photo in photos} != requested_ids:
            raise HTTPException(status_code=422, detail="所选图片不存在或不属于当前空间。")
    else:
        filtered_query = _apply_gallery_filters(
            base_query,
            payload.person_ids,
            payload.tag_ids,
            payload.exclude_person_ids,
            payload.exclude_tag_ids,
        )
        photos = db.scalars(filtered_query).unique().all()
        if payload.scope == "from_start":
            start_index = next(
                (index for index, photo in enumerate(photos) if photo.id == payload.start_photo_id),
                None,
            )
            if start_index is None:
                raise HTTPException(status_code=422, detail="起点图片不在当前筛选结果中。")
            photos = photos[: start_index + 1]
    if not photos:
        raise HTTPException(status_code=422, detail="当前导出范围内没有图片。")
    return list(photos)


def _build_gallery_export_response(
    request: Request,
    photos: list[GalleryPhoto],
    scope: str,
) -> StreamingResponse:
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
        for display_index, photo in enumerate(photos):
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
                    "display_index": display_index,
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
            json.dumps({"version": 2, "kind": "gallery_export", "scope": scope, "exported_at": shanghai_isoformat(shanghai_now()), "photos": manifest_photos}, ensure_ascii=False, indent=2),
        )

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="gallery_export_{shanghai_now():%Y%m%d_%H%M%S}.zip"'},
    )


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
    payload = GalleryPhotoExportRequest(
        scope=scope,
        person_ids=person_ids,
        tag_ids=tag_ids,
        exclude_person_ids=exclude_person_ids,
        exclude_tag_ids=exclude_tag_ids,
    )
    photos = _resolve_gallery_export_photos(db, current.workspace_id, payload)
    return _build_gallery_export_response(request, photos, scope)


@imports_router.post("/api/gallery/photos/export")
def export_gallery_photos_by_selection(
    payload: GalleryPhotoExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    photos = _resolve_gallery_export_photos(db, current.workspace_id, payload)
    return _build_gallery_export_response(request, photos, payload.scope)


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
    if payload.auto_delete_exact_mirror:
        require_permission(current, "can_delete_gallery")
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
        scan_type=payload.scan_type,
        auto_delete_exact_mirror=payload.auto_delete_exact_mirror,
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
        request.app.state.services.pictures,
        scan.id,
        task.id,
    )
    return _gallery_similarity_scan_read(db, scan)


def _resolve_normal_auto_delete_photo_ids(
    plans: list[AutoDeleteClusterPlan],
    requested_ids: list[int],
) -> list[int]:
    """校验显式提交的删除清单：只能删 ready 簇成员，且每簇至少留一张。"""
    deletable_members: set[int] = set()
    ready_cluster_members: list[tuple[int, ...]] = []
    for plan in plans:
        if plan.skip_reason is not None:
            continue
        ready_cluster_members.append(plan.member_ids)
        deletable_members.update(plan.member_ids)
    unknown = [photo_id for photo_id in requested_ids if photo_id not in deletable_members]
    if unknown:
        raise HTTPException(status_code=422, detail=f"以下图片不属于可自动删除的簇：{unknown}")
    for members in ready_cluster_members:
        if all(photo_id in requested_ids for photo_id in members):
            raise HTTPException(status_code=422, detail="每个相同簇至少需要保留一张图片")
    return requested_ids


@router.post(
    "/api/gallery/similarity-scans/{scan_id}/auto-delete-exact-mirrors",
    response_model=GallerySimilarityAutoDeleteResponse,
)
def auto_delete_exact_mirror_groups(
    scan_id: str,
    request: Request,
    payload: GallerySimilarityAutoDeleteExecuteRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityAutoDeleteResponse:
    require_permission(current, "can_delete_gallery")
    scan = db.get(GallerySimilarityScan, scan_id)
    if scan is None or scan.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Similarity scan not found")
    if scan.scan_type not in ("mirror", "normal"):
        raise HTTPException(status_code=422, detail="该扫描类型不支持自动整理")
    if scan.status != "completed" or scan.is_stale:
        raise HTTPException(status_code=409, detail="仅可整理未过期的已完成扫描结果")
    if scan.scan_type == "mirror":
        if payload is not None and payload.delete_photo_ids:
            raise HTTPException(status_code=422, detail="镜像整理不支持自定义删除清单")
        photo_ids = select_exact_mirror_auto_delete_photo_ids(db, scan)
    else:
        scanner = request.app.state.services.similarity
        plans = build_normal_near_duplicate_auto_delete_plan(
            db,
            scan,
            scanner.storage,
            request.app.state.settings,
        )
        requested_ids = list(dict.fromkeys(payload.delete_photo_ids)) if payload is not None else []
        if requested_ids:
            photo_ids = _resolve_normal_auto_delete_photo_ids(plans, requested_ids)
        else:
            photo_ids = [
                photo_id
                for plan in plans
                for photo_id in plan.delete_photo_ids
            ]
    photos = db.scalars(
        select(GalleryPhoto).where(
            GalleryPhoto.workspace_id == current.workspace_id,
            GalleryPhoto.id.in_(photo_ids),
        )
    ).all()
    deleted = picture_service.delete_gallery_photos(db, photos)
    db.refresh(scan)
    scan.auto_deleted_count += deleted
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return GallerySimilarityAutoDeleteResponse(deleted=deleted, scan=_gallery_similarity_scan_read(db, scan))


@router.get(
    "/api/gallery/similarity-scans/{scan_id}/auto-delete-preview",
    response_model=GallerySimilarityAutoDeletePreviewResponse,
)
def preview_normal_near_duplicate_auto_delete(
    scan_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityAutoDeletePreviewResponse:
    require_permission(current, "can_delete_gallery")
    scan = db.get(GallerySimilarityScan, scan_id)
    if scan is None or scan.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Similarity scan not found")
    if scan.scan_type != "normal":
        raise HTTPException(status_code=422, detail="预览仅支持普通相似扫描")
    if scan.status != "completed" or scan.is_stale:
        raise HTTPException(status_code=409, detail="仅可预览未过期的已完成扫描结果")
    scanner = request.app.state.services.similarity
    plans = build_normal_near_duplicate_auto_delete_plan(
        db,
        scan,
        scanner.storage,
        request.app.state.settings,
    )

    member_photo_ids = sorted({photo_id for plan in plans for photo_id in plan.member_ids})
    photos = {
        photo.id: photo
        for photo in db.scalars(
            select(GalleryPhoto).where(
                GalleryPhoto.workspace_id == current.workspace_id,
                GalleryPhoto.id.in_(member_photo_ids),
            )
        ).all()
    }
    member_rows = db.scalars(
        select(GallerySimilarityGroupMember)
        .join(GallerySimilarityGroup, GallerySimilarityGroupMember.group_id == GallerySimilarityGroup.id)
        .where(GallerySimilarityGroup.scan_id == scan.id)
    ).all()
    quality_by_photo: dict[int, float] = {}
    overall_by_photo: dict[int, float] = {}
    face_by_photo: dict[int, float | None] = {}
    for row in member_rows:
        quality_by_photo[row.gallery_photo_id] = max(
            quality_by_photo.get(row.gallery_photo_id, 0.0), row.quality_score
        )
        overall_by_photo[row.gallery_photo_id] = max(
            overall_by_photo.get(row.gallery_photo_id, 0.0), row.overall_quality_score
        )
        if row.face_quality_score is not None:
            face_by_photo[row.gallery_photo_id] = max(
                face_by_photo.get(row.gallery_photo_id) or 0.0,
                row.face_quality_score,
            )
        elif row.gallery_photo_id not in face_by_photo:
            face_by_photo[row.gallery_photo_id] = None

    status_by_reason = {
        None: "ready",
        "overlap": "skipped_overlap",
        "no_retention": "skipped_no_retention",
    }
    cluster_items: list[GallerySimilarityAutoDeletePreviewCluster] = []
    deletable_count = 0
    skipped_cluster_count = 0
    for plan in plans:
        preview_members: list[GallerySimilarityAutoDeletePreviewMember] = []
        ordered_ids = sorted(
            plan.member_ids,
            key=lambda photo_id: (
                photo_id != plan.retained_photo_id,
                -quality_by_photo.get(photo_id, 0.0),
            ),
        )
        for photo_id in ordered_ids:
            photo = photos.get(photo_id)
            if photo is None:
                continue
            preview_members.append(
                GallerySimilarityAutoDeletePreviewMember(
                    photo_id=photo_id,
                    filename=photo.filename,
                    thumbnail_url=f"/api/gallery/photos/{photo.id}/thumbnail?v={photo.sha256}",
                    original_url=f"/api/gallery/photos/{photo.id}/original?v={photo.sha256}",
                    size_bytes=photo.size_bytes,
                    quality_score=quality_by_photo.get(photo_id, 0.0),
                    retained=photo_id == plan.retained_photo_id,
                )
            )
        if plan.skip_reason is None:
            deletable_count += len(plan.delete_photo_ids)
        else:
            skipped_cluster_count += 1
        cluster_items.append(
            GallerySimilarityAutoDeletePreviewCluster(
                status=status_by_reason[plan.skip_reason],
                retained_photo_id=plan.retained_photo_id,
                delete_photo_ids=list(plan.delete_photo_ids),
                members=preview_members,
            )
        )
    return GallerySimilarityAutoDeletePreviewResponse(
        scan_id=scan.id,
        deletable_count=deletable_count,
        skipped_cluster_count=skipped_cluster_count,
        clusters=cluster_items,
    )


@router.get("/api/gallery/similarity-scans/latest", response_model=GallerySimilarityScanRead | None)
def get_latest_gallery_similarity_scan(
    person_id: int | None = None,
    include_cross_type: bool = False,
    scan_type: Literal["normal", "mirror"] = "normal",
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityScanRead | None:
    query = select(GallerySimilarityScan).where(
        GallerySimilarityScan.workspace_id == current.workspace_id,
        GallerySimilarityScan.include_cross_type == include_cross_type,
        GallerySimilarityScan.scan_type == scan_type,
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
    request: Request,
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
        items=[
            _gallery_similarity_group_read(
                db,
                group,
                request.app.state.settings.gallery_similarity_auto_delete_threshold,
                request.app.state.settings.gallery_similarity_auto_delete_perceptual_min,
            )
            for group in groups
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/api/gallery/similarity-scans/{scan_id}/groups/{group_id}", response_model=GallerySimilarityGroupRead | None)
def get_gallery_similarity_group(
    scan_id: str,
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> GallerySimilarityGroupRead | None:
    scan = db.get(GallerySimilarityScan, scan_id)
    if scan is None or scan.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Similarity scan not found")
    group = db.scalar(select(GallerySimilarityGroup).where(GallerySimilarityGroup.id == group_id, GallerySimilarityGroup.scan_id == scan_id))
    if group is None:
        return None
    return _gallery_similarity_group_read(
        db,
        group,
        request.app.state.settings.gallery_similarity_auto_delete_threshold,
        request.app.state.settings.gallery_similarity_auto_delete_perceptual_min,
    )


@router.patch("/api/gallery/similarity-scans/{scan_id}/groups/{group_id}", response_model=GallerySimilarityGroupRead)
def update_gallery_similarity_group(
    scan_id: str,
    group_id: int,
    payload: GallerySimilarityGroupUpdate,
    request: Request,
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
    return _gallery_similarity_group_read(
        db,
        group,
        request.app.state.settings.gallery_similarity_auto_delete_threshold,
        request.app.state.settings.gallery_similarity_auto_delete_perceptual_min,
    )


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
        .order_by(*_gallery_display_order())
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
            db.delete(face)
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


@router.post("/api/gallery/photos/clear-unknown-tags")
def clear_unknown_gallery_person_tags(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    return picture_service.clear_unknown_gallery_person_tags(db, current.workspace_id)
