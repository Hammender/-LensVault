from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.timezones import as_shanghai_naive, shanghai_isoformat, shanghai_now
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.http.media import stream_storage_object
from app.models import (
    AcquisitionAsset,
    AcquisitionCategory,
    AcquisitionExportJob,
    AcquisitionImportBatch,
    AcquisitionImportBatchItem,
    AcquisitionImportedPhoto,
    AcquisitionRun,
    AcquisitionRunItem,
    AcquisitionSimilarityCandidate,
    AcquisitionSource,
    AcquisitionSourceScript,
    GalleryPhoto,
    Task,
)
from app.schemas import (
    AcquisitionAssetAction,
    AcquisitionAssetRead,
    AcquisitionAssetSummary,
    AcquisitionCategoryCreate,
    AcquisitionCategoryRead,
    AcquisitionCategoryUpdate,
    AcquisitionExportCreate,
    AcquisitionExportRead,
    AcquisitionImportBatchItemRead,
    AcquisitionImportBatchItemDetailRead,
    AcquisitionImportBatchRead,
    AcquisitionImportOriginRead,
    AcquisitionRunCreate,
    AcquisitionRunRead,
    AcquisitionScriptRead,
    AcquisitionSourceCreate,
    AcquisitionSourceRead,
    AcquisitionSourceScriptBind,
    AcquisitionSourceUpdate,
    AcquisitionSimilarityResultRead,
    PaginatedAcquisitionAssets,
    PaginatedAcquisitionImportBatchItems,
    PaginatedAcquisitionImportBatches,
    TaskRead,
)
from app.services.acquisition import AcquisitionService
from app.services.tasks import create_task, update_task


router = APIRouter(prefix="/api/acquisition", tags=["图片采集"])


def _service(request: Request) -> AcquisitionService:
    return request.app.state.services.acquisition


def _source_or_404(db: Session, source_id: int, workspace_id: int) -> AcquisitionSource:
    source = db.get(AcquisitionSource, source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="采集站点不存在")
    return source


def _category_or_404(db: Session, category_id: int, workspace_id: int) -> AcquisitionCategory:
    category = db.get(AcquisitionCategory, category_id)
    source = db.get(AcquisitionSource, category.source_id) if category else None
    if category is None or source is None or source.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="采集分类不存在")
    return category


def _asset_read(asset: AcquisitionAsset) -> AcquisitionAssetRead:
    try:
        warnings = json.loads(asset.quality_warnings or "[]")
    except json.JSONDecodeError:
        warnings = []
    return AcquisitionAssetRead(
        id=asset.id,
        filename=asset.filename,
        content_type=asset.content_type,
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        blur_score=asset.blur_score,
        quality_warnings=warnings if isinstance(warnings, list) else [],
        status=asset.status,
        created_at=asset.created_at,
        preview_url=f"/api/acquisition/assets/{asset.id}/original" if asset.object_key else None,
    )


def _source_read(db: Session, source: AcquisitionSource) -> AcquisitionSourceRead:
    script_keys = list(
        db.scalars(
            select(AcquisitionSourceScript.script_key)
            .where(AcquisitionSourceScript.source_id == source.id, AcquisitionSourceScript.enabled.is_(True))
            .order_by(AcquisitionSourceScript.script_key.asc())
        ).all()
    )
    return AcquisitionSourceRead(
        id=source.id,
        name=source.name,
        base_url=source.base_url or "",
        notes=source.notes,
        page_format_key=source.page_format_key,
        script_keys=script_keys,
        enabled=source.enabled,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _run_read(run: AcquisitionRun) -> AcquisitionRunRead:
    try:
        parameters = json.loads(run.parameters_json or "{}")
    except json.JSONDecodeError:
        parameters = {}
    return AcquisitionRunRead(
        id=run.id,
        source_id=run.source_id,
        category_id=run.category_id,
        script_key=run.script_key,
        script_name=run.script_name_snapshot,
        script_version=run.script_version_snapshot,
        source_name=run.source_name_snapshot,
        category_name=run.category_name_snapshot,
        category_url=run.category_url_snapshot,
        parameters=parameters if isinstance(parameters, dict) else {},
        mode=run.mode,
        status=run.status,
        total_count=run.total_count,
        downloaded_count=run.downloaded_count,
        skipped_count=run.skipped_count,
        download_success_count=run.download_success_count,
        candidate_count=run.candidate_count,
        content_duplicate_count=run.content_duplicate_count,
        gallery_duplicate_count=run.gallery_duplicate_count,
        resolution_duplicate_count=run.resolution_duplicate_count,
        resolution_upgrade_count=run.resolution_upgrade_count,
        ignored_count=run.ignored_count,
        invalid_count=run.invalid_count,
        error_count=run.error_count,
        imported_count=run.imported_count,
        error_message=run.error_message,
        scan_start_page=run.scan_start_page,
        scan_end_page=run.scan_end_page,
        reached_collection_end=run.reached_collection_end,
        stop_reason=run.stop_reason,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _export_read(job: AcquisitionExportJob) -> AcquisitionExportRead:
    return AcquisitionExportRead(
        id=job.id,
        status=job.status,
        filename=job.filename,
        item_count=job.item_count,
        missing_count=job.missing_count,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
        download_url=f"/api/acquisition/exports/{job.id}/download" if job.status == "ready" else None,
    )


def _process_run(session_factory, service: AcquisitionService, run_id: str) -> None:
    db = session_factory()
    try:
        service.process_run(db, run_id)
    finally:
        db.close()


def _process_import(session_factory, service: AcquisitionService, batch_id: str) -> None:
    db = session_factory()
    try:
        service.process_import_batch(db, batch_id)
    finally:
        db.close()


def _batch_read(db: Session, batch: AcquisitionImportBatch, include_items: bool = False) -> AcquisitionImportBatchRead:
    items = []
    if include_items:
        items = [
            AcquisitionImportBatchItemRead.model_validate(item)
            for item in db.scalars(
                select(AcquisitionImportBatchItem)
                .where(AcquisitionImportBatchItem.batch_id == batch.id)
                .order_by(AcquisitionImportBatchItem.ordinal.asc())
            ).all()
        ]
    return AcquisitionImportBatchRead(
        id=batch.id,
        status=batch.status,
        total_count=batch.total_count,
        processed_count=batch.processed_count,
        imported_count=batch.imported_count,
        duplicate_count=batch.duplicate_count,
        failed_count=batch.failed_count,
        error_message=batch.error_message,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        items=items,
    )


def _unassigned_import_filter(workspace_id: int | None):
    successful_batch_item = (
        select(AcquisitionImportBatchItem.id)
        .join(AcquisitionImportBatch, AcquisitionImportBatch.id == AcquisitionImportBatchItem.batch_id)
        .where(
            AcquisitionImportBatchItem.asset_id == AcquisitionImportedPhoto.asset_id,
            AcquisitionImportBatchItem.status == "imported",
            AcquisitionImportBatch.workspace_id == workspace_id,
        )
    )
    return (
        AcquisitionRun.workspace_id == workspace_id,
        ~exists(successful_batch_item),
    )


def _batch_item_details(
    db: Session,
    workspace_id: int | None,
    page_rows: list[AcquisitionImportBatchItem] | list[tuple[str, datetime]],
    unassigned: bool,
) -> list[AcquisitionImportBatchItemDetailRead]:
    if not page_rows:
        return []
    asset_ids = [row[0] if unassigned else row.asset_id for row in page_rows]
    assets = {
        asset.id: asset
        for asset in db.scalars(select(AcquisitionAsset).where(AcquisitionAsset.id.in_(asset_ids))).all()
    }
    provenance_rows = db.execute(
        select(AcquisitionImportedPhoto, AcquisitionRun)
        .join(AcquisitionRun, AcquisitionRun.id == AcquisitionImportedPhoto.run_id)
        .where(AcquisitionImportedPhoto.asset_id.in_(asset_ids), AcquisitionRun.workspace_id == workspace_id)
        .order_by(AcquisitionImportedPhoto.created_at.asc())
    ).all()
    provenance_by_asset: dict[str, list[AcquisitionImportedPhoto]] = {asset_id: [] for asset_id in asset_ids}
    for provenance, _run in provenance_rows:
        provenance_by_asset.setdefault(provenance.asset_id, []).append(provenance)

    origin_rows = db.execute(
        select(AcquisitionRunItem.asset_id, AcquisitionRun)
        .join(AcquisitionRun, AcquisitionRun.id == AcquisitionRunItem.run_id)
        .where(AcquisitionRunItem.asset_id.in_(asset_ids), AcquisitionRun.workspace_id == workspace_id)
        .order_by(AcquisitionRun.created_at.desc())
    ).all()
    origins_by_asset: dict[str, list[AcquisitionImportOriginRead]] = {asset_id: [] for asset_id in asset_ids}
    seen_origins: set[tuple[str, str]] = set()
    for asset_id, run in origin_rows:
        key = (asset_id, run.id)
        if key in seen_origins:
            continue
        seen_origins.add(key)
        origins_by_asset.setdefault(asset_id, []).append(AcquisitionImportOriginRead(
            run_id=run.id,
            source_name=run.source_name_snapshot,
            category_name=run.category_name_snapshot,
            run_created_at=run.created_at,
        ))

    candidate_gallery_ids: set[int] = set()
    if not unassigned:
        candidate_gallery_ids.update(row.gallery_photo_id for row in page_rows if row.gallery_photo_id is not None)
    for rows in provenance_by_asset.values():
        candidate_gallery_ids.update(row.gallery_photo_id for row in rows if row.gallery_photo_id is not None)
    available_gallery_ids = set(db.scalars(
        select(GalleryPhoto.id).where(GalleryPhoto.id.in_(candidate_gallery_ids))
    ).all()) if candidate_gallery_ids else set()

    details: list[AcquisitionImportBatchItemDetailRead] = []
    for index, page_row in enumerate(page_rows):
        item = None if unassigned else page_row
        asset_id = page_row[0] if unassigned else page_row.asset_id
        asset = assets[asset_id]
        provenance = provenance_by_asset.get(asset_id, [])
        current_gallery_id = item.gallery_photo_id if item is not None else None
        if current_gallery_id is None:
            current_gallery_id = next((row.gallery_photo_id for row in provenance if row.gallery_photo_id is not None), None)
        snapshot_gallery_id = next((row.gallery_photo_snapshot_id for row in provenance), current_gallery_id)
        details.append(AcquisitionImportBatchItemDetailRead(
            id=item.id if item is not None else None,
            asset_id=asset_id,
            ordinal=item.ordinal if item is not None else index + 1,
            status=item.status if item is not None else "imported",
            gallery_photo_id=current_gallery_id,
            gallery_photo_snapshot_id=snapshot_gallery_id,
            gallery_available=current_gallery_id in available_gallery_ids if current_gallery_id is not None else False,
            attempt_count=item.attempt_count if item is not None else 0,
            error_message=item.error_message if item is not None else None,
            filename=provenance[0].filename_snapshot if provenance else asset.filename,
            sha256=provenance[0].sha256_snapshot if provenance else asset.sha256,
            imported_at=min((row.created_at for row in provenance), default=None),
            origins=origins_by_asset.get(asset_id, []),
        ))
    return details


def _process_similarity(session_factory, service: AcquisitionService, workspace_id: int, task_id: str) -> None:
    db = session_factory()
    try:
        update_task(db, task_id, status="running", progress=0.02, message="正在准备待审核图片")
        created = service.scan_similarity(
            db,
            workspace_id,
            scan_task_id=task_id,
            progress=lambda value, message: update_task(db, task_id, progress=value, message=message),
        )
        update_task(db, task_id, status="completed", progress=1.0, message=f"扫描完成，发现 {created} 条相似关系")
    except Exception as exc:
        db.rollback()
        update_task(db, task_id, status="failed", message=f"相似扫描失败：{exc}")
    finally:
        db.close()


def _process_export(session_factory, service: AcquisitionService, job_id: str) -> None:
    db = session_factory()
    try:
        service.build_export(db, job_id)
    finally:
        db.close()


@router.get("/scripts", response_model=list[AcquisitionScriptRead])
def list_scripts(request: Request, current: CurrentContext = Depends(require_context)) -> list[AcquisitionScriptRead]:
    return [AcquisitionScriptRead.model_validate(item) for item in _service(request).scripts()]


@router.get("/sources", response_model=list[AcquisitionSourceRead])
def list_sources(
    db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)
) -> list[AcquisitionSourceRead]:
    return [
        _source_read(db, source)
        for source in db.scalars(
            select(AcquisitionSource).where(AcquisitionSource.workspace_id == current.workspace_id).order_by(AcquisitionSource.name.asc())
        )
    ]


@router.post("/sources", response_model=AcquisitionSourceRead)
def create_source(
    payload: AcquisitionSourceCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionSourceRead:
    try:
        source = _service(request).create_source(db, current.workspace_id, payload.name, payload.base_url, payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_read(db, source)


@router.patch("/sources/{source_id}", response_model=AcquisitionSourceRead)
def update_source(
    source_id: int,
    payload: AcquisitionSourceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionSourceRead:
    try:
        source = _service(request).update_source(db, _source_or_404(db, source_id, current.workspace_id), **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_read(db, source)


@router.post("/sources/{source_id}/scripts", response_model=AcquisitionSourceRead)
def bind_source_script(
    source_id: int,
    payload: AcquisitionSourceScriptBind,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionSourceRead:
    source = _source_or_404(db, source_id, current.workspace_id)
    try:
        _service(request).bind_script(db, source, payload.script_key, payload.default_parameters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_read(db, source)


@router.delete("/sources/{source_id}/scripts/{script_key}", response_model=AcquisitionSourceRead)
def unbind_source_script(
    source_id: int,
    script_key: str,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionSourceRead:
    source = _source_or_404(db, source_id, current.workspace_id)
    try:
        _service(request).unbind_script(db, source, script_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(source)
    return _source_read(db, source)


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> dict[str, str]:
    db.delete(_source_or_404(db, source_id, current.workspace_id))
    db.commit()
    return {"status": "ok"}


@router.get("/categories", response_model=list[AcquisitionCategoryRead])
def list_categories(
    source_id: int | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[AcquisitionCategoryRead]:
    query = select(AcquisitionCategory).join(AcquisitionSource).where(AcquisitionSource.workspace_id == current.workspace_id)
    if source_id is not None:
        query = query.where(AcquisitionCategory.source_id == source_id)
    return [AcquisitionCategoryRead.model_validate(category) for category in db.scalars(query.order_by(AcquisitionCategory.name.asc()))]


@router.post("/sources/{source_id}/categories", response_model=AcquisitionCategoryRead)
def create_category(
    source_id: int,
    payload: AcquisitionCategoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionCategoryRead:
    try:
        category = _service(request).create_category(
            db, _source_or_404(db, source_id, current.workspace_id), payload.name, payload.crawl_url, payload.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AcquisitionCategoryRead.model_validate(category)


@router.patch("/categories/{category_id}", response_model=AcquisitionCategoryRead)
def update_category(
    category_id: int,
    payload: AcquisitionCategoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionCategoryRead:
    try:
        category = _service(request).update_category(
            db, _category_or_404(db, category_id, current.workspace_id), **payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AcquisitionCategoryRead.model_validate(category)


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> dict[str, str]:
    db.delete(_category_or_404(db, category_id, current.workspace_id))
    db.commit()
    return {"status": "ok"}


@router.post("/categories/{category_id}/runs", response_model=AcquisitionRunRead)
def start_run(
    category_id: int,
    payload: AcquisitionRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionRunRead:
    try:
        service = _service(request)
        run = service.start_run(
            db,
            current.workspace_id,
            _category_or_404(db, category_id, current.workspace_id),
            payload.script_key,
            payload.mode,
            payload.parameters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(_process_run, request.app.state.session_factory, service, run.id)
    return _run_read(run)


@router.get("/runs", response_model=list[AcquisitionRunRead])
def list_runs(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[AcquisitionRunRead]:
    query = select(AcquisitionRun).where(AcquisitionRun.workspace_id == current.workspace_id)
    if category_id is not None:
        query = query.where(AcquisitionRun.category_id == category_id)
    return [_run_read(run) for run in db.scalars(query.order_by(AcquisitionRun.created_at.desc()))]


@router.get("/assets", response_model=PaginatedAcquisitionAssets)
def list_assets(
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PaginatedAcquisitionAssets:
    query = select(AcquisitionAsset).where(AcquisitionAsset.workspace_id == current.workspace_id)
    if status:
        query = query.where(AcquisitionAsset.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    assets = db.scalars(query.order_by(AcquisitionAsset.created_at.desc()).offset(offset).limit(limit)).all()
    return PaginatedAcquisitionAssets(items=[_asset_read(asset) for asset in assets], total=total, offset=offset, limit=limit)


@router.get("/assets/ids", response_model=list[str])
def list_asset_ids(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[str]:
    query = select(AcquisitionAsset.id).where(AcquisitionAsset.workspace_id == current.workspace_id)
    if status:
        query = query.where(AcquisitionAsset.status == status)
    return list(db.scalars(query.order_by(AcquisitionAsset.created_at.desc())).all())


@router.get("/assets/summary", response_model=AcquisitionAssetSummary)
def get_asset_summary(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionAssetSummary:
    rows = db.execute(
        select(AcquisitionAsset.status, func.count(AcquisitionAsset.id))
        .where(AcquisitionAsset.workspace_id == current.workspace_id)
        .group_by(AcquisitionAsset.status)
    ).all()
    status_counts = {status: count for status, count in rows}
    return AcquisitionAssetSummary(total=sum(status_counts.values()), status_counts=status_counts)


@router.get("/assets/{asset_id}/original")
def get_asset_original(
    asset_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    asset = db.get(AcquisitionAsset, asset_id)
    if asset is None or asset.workspace_id != current.workspace_id or not asset.object_key:
        raise HTTPException(status_code=404, detail="采集临时图片不存在")
    return stream_storage_object(request.app.state.services.storage, request, asset.object_key, asset.filename, asset.content_type)


@router.post("/assets/import", response_model=AcquisitionImportBatchRead)
def import_assets(
    payload: AcquisitionAssetAction,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionImportBatchRead:
    service = _service(request)
    try:
        batch = service.create_import_batch(db, current.workspace_id, payload.asset_ids)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(_process_import, request.app.state.session_factory, service, batch.id)
    return _batch_read(db, batch, include_items=True)


@router.get("/import-batches", response_model=PaginatedAcquisitionImportBatches)
def list_import_batches(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PaginatedAcquisitionImportBatches:
    date_from = as_shanghai_naive(date_from)
    date_to = as_shanghai_naive(date_to)
    filters = [AcquisitionImportBatch.workspace_id == current.workspace_id]
    if date_from:
        filters.append(AcquisitionImportBatch.created_at >= date_from)
    if date_to:
        filters.append(AcquisitionImportBatch.created_at <= date_to)
    total = db.scalar(select(func.count()).select_from(AcquisitionImportBatch).where(*filters)) or 0
    batches = db.scalars(
        select(AcquisitionImportBatch)
        .where(*filters)
        .order_by(AcquisitionImportBatch.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    unassigned_filters = list(_unassigned_import_filter(current.workspace_id))
    if date_from:
        unassigned_filters.append(AcquisitionImportedPhoto.created_at >= date_from)
    if date_to:
        unassigned_filters.append(AcquisitionImportedPhoto.created_at <= date_to)
    unassigned_count = db.scalar(
        select(func.count(func.distinct(AcquisitionImportedPhoto.asset_id)))
        .select_from(AcquisitionImportedPhoto)
        .join(AcquisitionRun, AcquisitionRun.id == AcquisitionImportedPhoto.run_id)
        .where(*unassigned_filters)
    ) or 0
    return PaginatedAcquisitionImportBatches(
        items=[_batch_read(db, batch) for batch in batches],
        total=total,
        offset=offset,
        limit=limit,
        unassigned_imported_count=unassigned_count,
    )


@router.get("/import-batches/{batch_id}", response_model=AcquisitionImportBatchRead)
def get_import_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionImportBatchRead:
    batch = db.get(AcquisitionImportBatch, batch_id)
    if batch is None or batch.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="入库批次不存在")
    return _batch_read(db, batch, include_items=True)


@router.get("/import-batches/{batch_id}/items", response_model=PaginatedAcquisitionImportBatchItems)
def list_import_batch_items(
    batch_id: str,
    status: str = Query(default="all"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PaginatedAcquisitionImportBatchItems:
    date_from = as_shanghai_naive(date_from)
    date_to = as_shanghai_naive(date_to)
    if batch_id == "unassigned":
        filters = list(_unassigned_import_filter(current.workspace_id))
        if date_from:
            filters.append(AcquisitionImportedPhoto.created_at >= date_from)
        if date_to:
            filters.append(AcquisitionImportedPhoto.created_at <= date_to)
        if status not in {"all", "imported"}:
            return PaginatedAcquisitionImportBatchItems(items=[], total=0, offset=offset, limit=limit)
        grouped = (
            select(
                AcquisitionImportedPhoto.asset_id.label("asset_id"),
                func.min(AcquisitionImportedPhoto.created_at).label("imported_at"),
            )
            .join(AcquisitionRun, AcquisitionRun.id == AcquisitionImportedPhoto.run_id)
            .where(*filters)
            .group_by(AcquisitionImportedPhoto.asset_id)
        )
        total = db.scalar(select(func.count()).select_from(grouped.subquery())) or 0
        page_rows = db.execute(
            grouped.order_by(func.min(AcquisitionImportedPhoto.created_at).desc()).offset(offset).limit(limit)
        ).all()
        return PaginatedAcquisitionImportBatchItems(
            items=_batch_item_details(db, current.workspace_id, page_rows, unassigned=True),
            total=total,
            offset=offset,
            limit=limit,
        )

    batch = db.get(AcquisitionImportBatch, batch_id)
    if batch is None or batch.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="入库批次不存在")
    filters = [AcquisitionImportBatchItem.batch_id == batch.id]
    if status != "all":
        filters.append(AcquisitionImportBatchItem.status == status)
    total = db.scalar(
        select(func.count()).select_from(AcquisitionImportBatchItem).where(*filters)
    ) or 0
    page_rows = db.scalars(
        select(AcquisitionImportBatchItem)
        .where(*filters)
        .order_by(AcquisitionImportBatchItem.ordinal.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return PaginatedAcquisitionImportBatchItems(
        items=_batch_item_details(db, current.workspace_id, page_rows, unassigned=False),
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/assets/reject")
def reject_assets(
    payload: AcquisitionAssetAction,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    return {"rejected": _service(request).reject_assets(db, current.workspace_id, payload.asset_ids)}


@router.post("/similarity/scan")
def start_similarity_scan(
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    active = db.scalar(
        select(Task)
        .where(
            Task.workspace_id == current.workspace_id,
            Task.kind == "acquisition_similarity_scan",
            Task.status.in_(("pending", "running")),
        )
        .order_by(Task.created_at.desc())
    )
    if active is not None:
        return TaskRead.model_validate(active)
    task = create_task(db, "acquisition_similarity_scan", "相似扫描已进入队列", current.workspace_id)
    background_tasks.add_task(
        _process_similarity,
        request.app.state.session_factory,
        _service(request),
        current.workspace_id,
        task.id,
    )
    return TaskRead.model_validate(task)


@router.get("/similarity", response_model=AcquisitionSimilarityResultRead)
def list_similarity(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionSimilarityResultRead:
    latest_task = db.scalar(
        select(Task)
        .where(Task.workspace_id == current.workspace_id, Task.kind == "acquisition_similarity_scan")
        .order_by(Task.created_at.desc())
    )
    other_asset = aliased(AcquisitionAsset)
    rows = db.execute(
        select(AcquisitionSimilarityCandidate, AcquisitionAsset, other_asset)
        .join(AcquisitionAsset, AcquisitionAsset.id == AcquisitionSimilarityCandidate.asset_id)
        .join(other_asset, other_asset.id == AcquisitionSimilarityCandidate.other_asset_id)
        .where(
            AcquisitionSimilarityCandidate.workspace_id == current.workspace_id,
            AcquisitionAsset.status == "pending_review",
            other_asset.status == "pending_review",
            AcquisitionAsset.object_key.is_not(None),
            other_asset.object_key.is_not(None),
        )
        .order_by(AcquisitionSimilarityCandidate.score.desc())
    ).all()
    parent: dict[str, str] = {}
    assets: dict[str, AcquisitionAsset] = {}
    edge_scores: dict[tuple[str, str], float] = {}

    def find(asset_id: str) -> str:
        parent.setdefault(asset_id, asset_id)
        while parent[asset_id] != asset_id:
            parent[asset_id] = parent[parent[asset_id]]
            asset_id = parent[asset_id]
        return asset_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for candidate, asset, other in rows:
        assets[asset.id] = asset
        assets[other.id] = other
        union(asset.id, other.id)
        edge_scores[tuple(sorted((asset.id, other.id)))] = candidate.score

    grouped_ids: dict[str, list[str]] = {}
    for asset_id in assets:
        grouped_ids.setdefault(find(asset_id), []).append(asset_id)
    groups: list[dict[str, object]] = []
    for member_ids in grouped_ids.values():
        member_ids.sort(key=lambda asset_id: (assets[asset_id].created_at, asset_id))
        scores = [
            score for (left, right), score in edge_scores.items()
            if left in member_ids and right in member_ids
        ]
        groups.append({
            "id": "-".join(member_ids),
            "max_score": max(scores, default=0.0),
            "average_score": sum(scores) / len(scores) if scores else 0.0,
            "members": [_asset_read(assets[asset_id]).model_dump() for asset_id in member_ids],
        })
    groups.sort(key=lambda group: (-float(group["max_score"]), str(group["id"])))
    generated_at = max((candidate.created_at for candidate, _asset, _other in rows), default=None)
    if generated_at is None and latest_task is not None and latest_task.status == "completed":
        generated_at = latest_task.updated_at
    has_newer_assets = False
    if generated_at is not None:
        has_newer_assets = bool(db.scalar(select(exists().where(
            AcquisitionAsset.workspace_id == current.workspace_id,
            AcquisitionAsset.status == "pending_review",
            AcquisitionAsset.created_at > generated_at,
        ))))
    return AcquisitionSimilarityResultRead(
        task=TaskRead.model_validate(latest_task) if latest_task is not None else None,
        generated_at=generated_at,
        is_stale=has_newer_assets,
        groups=groups[offset : offset + limit],
        total=len(groups),
        offset=offset,
        limit=limit,
    )


@router.get("/history")
def list_history(
    run_id: str | None = None,
    source_id: int | None = None,
    category_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[dict[str, object]]:
    date_from = as_shanghai_naive(date_from)
    date_to = as_shanghai_naive(date_to)
    query = (
        select(AcquisitionImportedPhoto, AcquisitionRun, AcquisitionCategory, GalleryPhoto)
        .join(AcquisitionRun, AcquisitionRun.id == AcquisitionImportedPhoto.run_id)
        .join(AcquisitionCategory, AcquisitionCategory.id == AcquisitionRun.category_id)
        .outerjoin(GalleryPhoto, GalleryPhoto.id == AcquisitionImportedPhoto.gallery_photo_id)
        .where(AcquisitionRun.workspace_id == current.workspace_id)
    )
    if run_id:
        query = query.where(AcquisitionRun.id == run_id)
    if source_id:
        query = query.where(AcquisitionRun.source_id == source_id)
    if category_id:
        query = query.where(AcquisitionRun.category_id == category_id)
    if date_from:
        query = query.where(AcquisitionImportedPhoto.created_at >= date_from)
    if date_to:
        query = query.where(AcquisitionImportedPhoto.created_at <= date_to)
    rows = db.execute(query.order_by(AcquisitionImportedPhoto.created_at.desc())).all()
    unique_rows = []
    seen_asset_ids: set[str] = set()
    for row in rows:
        history = row[0]
        if history.asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(history.asset_id)
        unique_rows.append(row)
    return [
        {
            "id": history.id,
            "run_id": run.id,
            "category_path": category.path,
            "gallery_photo_id": history.gallery_photo_id,
            "gallery_photo_snapshot_id": history.gallery_photo_snapshot_id,
            "filename": history.filename_snapshot,
            "sha256": history.sha256_snapshot,
            "available": photo is not None,
            "created_at": shanghai_isoformat(history.created_at),
        }
        for history, run, category, photo in unique_rows
    ]


@router.post("/exports", response_model=AcquisitionExportRead)
def create_export(
    payload: AcquisitionExportCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> AcquisitionExportRead:
    job = _service(request).create_export_job(
        db,
        current.workspace_id,
        payload.model_dump(mode="json", exclude_none=True),
    )
    background_tasks.add_task(_process_export, request.app.state.session_factory, _service(request), job.id)
    return _export_read(job)


@router.get("/exports", response_model=list[AcquisitionExportRead])
def list_exports(db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> list[AcquisitionExportRead]:
    jobs = db.scalars(
        select(AcquisitionExportJob)
        .where(AcquisitionExportJob.workspace_id == current.workspace_id)
        .order_by(AcquisitionExportJob.created_at.desc())
    )
    return [_export_read(job) for job in jobs]


@router.get("/exports/{job_id}/download")
def download_export(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    job = db.get(AcquisitionExportJob, job_id)
    if job is None or job.workspace_id != current.workspace_id or job.status != "ready" or not job.object_key:
        raise HTTPException(status_code=404, detail="导出文件不可用")
    object_key = job.object_key
    filename = job.filename or "acquisition_export.zip"
    storage = request.app.state.services.storage

    def stream() -> Iterator[bytes]:
        response = storage.get_stream(object_key)
        try:
            while chunk := response.read(1024 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()
            storage.remove_object(object_key)

    job.status = "downloaded"
    job.downloaded_at = shanghai_now()
    job.object_key = None
    db.commit()
    return StreamingResponse(stream(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
