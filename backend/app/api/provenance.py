from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api._helpers import get_workspace_object
from app.core.timezones import shanghai_now
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.http.media import stream_storage_object
from app.models import GalleryPhoto, Task, VideoExportJob, VideoItem, VideoItemCategoryTag, VideoItemPerson
from app.schemas.base import BaseModel
from app.services.import_spool import cleanup_import, spool_upload
from app.services.provenance import export_source
from app.services.tasks import create_task, update_task
from app.services.video_transfer import cleanup_exports, ensure_free_space, package_temp_root, run_export, run_import

router = APIRouter(tags=["素材来源与迁移"])


class VideoExportRequest(BaseModel):
    scope: Literal["all", "filtered", "selected"] = "filtered"
    video_ids: list[int] = Field(default_factory=list, max_length=10000)
    category_tag_ids: list[int] = Field(default_factory=list)
    person_ids: list[int] = Field(default_factory=list)
    query: str | None = None
    video_type: Literal["short", "long"] | None = None


class TransferRead(BaseModel):
    id: str
    status: str
    result: dict = Field(default_factory=dict)
    message: str | None = None
    download_url: str | None = None
    expires_at: str | None = None


_EXPORT_BUSY = "同一工作区已有导出任务进行中，请等待完成后再导出"


def _job_read(job):
    return TransferRead(id=job.id, status=job.status, result=json.loads(job.result_json or "{}"),
        expires_at=job.expires_at.isoformat() if job.expires_at else None,
        download_url=f"/api/videos/exports/{job.id}/download" if job.status == "ready" else None)


def _oldest_active_export_id(db: Session, workspace_id: int) -> str | None:
    return db.scalar(select(VideoExportJob.id).where(
        VideoExportJob.workspace_id == workspace_id,
        VideoExportJob.status.in_(["queued", "running"]),
    ).order_by(VideoExportJob.created_at.asc(), VideoExportJob.id.asc()).limit(1))


@router.get("/api/gallery/photos/{photo_id}/source", response_model=dict | None)
def photo_source(photo_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    return export_source(get_workspace_object(db, GalleryPhoto, photo_id, current.workspace_id, "图片"))


@router.get("/api/videos/{video_id}/source", response_model=dict | None)
def video_source(video_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    return export_source(get_workspace_object(db, VideoItem, video_id, current.workspace_id, "视频"))


@router.post("/api/videos/exports", response_model=TransferRead)
def create_video_export(payload: VideoExportRequest, request: Request, background_tasks: BackgroundTasks,
                        db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    if _oldest_active_export_id(db, current.workspace_id) is not None:
        raise HTTPException(409, _EXPORT_BUSY)
    query = select(VideoItem.id).where(
        VideoItem.workspace_id == current.workspace_id,
        VideoItem.status.notin_(["processing", "processing_failed"]),
    )
    if payload.scope == "selected":
        if not payload.video_ids:
            raise HTTPException(422, "请选择要导出的视频")
        query = query.where(VideoItem.id.in_(payload.video_ids))
    elif payload.scope == "filtered":
        if payload.video_type:
            query = query.where(VideoItem.video_type == payload.video_type)
        if payload.query and payload.query.strip():
            word = f"%{payload.query.strip()}%"
            query = query.where(VideoItem.title.like(word) | VideoItem.description.like(word) | VideoItem.filename.like(word))
        for tag_id in set(payload.category_tag_ids):
            query = query.where(VideoItem.id.in_(select(VideoItemCategoryTag.video_id).where(VideoItemCategoryTag.tag_id == tag_id)))
        for person_id in set(payload.person_ids):
            query = query.where(VideoItem.id.in_(select(VideoItemPerson.video_id).where(VideoItemPerson.person_id == person_id)))
    ids = list(db.scalars(query.order_by(VideoItem.created_at.desc(), VideoItem.id.desc())))
    if payload.scope == "selected" and set(ids) != set(payload.video_ids):
        raise HTTPException(422, "所选视频不存在或正在处理中")
    if not ids:
        raise HTTPException(422, "没有可导出的视频")
    total_bytes = db.scalar(select(func.coalesce(func.sum(VideoItem.size_bytes), 0)).where(VideoItem.id.in_(ids))) or 0
    try:
        ensure_free_space(package_temp_root(request.app.state.settings), int(total_bytes))
    except ValueError as exc:
        raise HTTPException(507, str(exc)) from exc
    cleanup_exports(db, request.app.state.services.storage)
    job = VideoExportJob(id=uuid4().hex, workspace_id=current.workspace_id, selection_json=json.dumps(ids))
    db.add(job)
    db.commit()
    if _oldest_active_export_id(db, current.workspace_id) != job.id:
        db.delete(job)
        db.commit()
        raise HTTPException(409, _EXPORT_BUSY)
    background_tasks.add_task(run_export, request.app.state.session_factory, request.app.state.services.videos, job.id)
    return _job_read(job)


@router.get("/api/videos/exports", response_model=list[TransferRead])
def list_video_exports(request: Request, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    cleanup_exports(db, request.app.state.services.storage, current.workspace_id)
    return [_job_read(job) for job in db.scalars(select(VideoExportJob).where(VideoExportJob.workspace_id == current.workspace_id)
                                               .order_by(VideoExportJob.created_at.desc()).limit(20))]


@router.get("/api/videos/exports/{job_id}", response_model=TransferRead)
def get_video_export(job_id: str, request: Request, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    cleanup_exports(db, request.app.state.services.storage, current.workspace_id)
    return _job_read(get_workspace_object(db, VideoExportJob, job_id, current.workspace_id, "导出任务"))


@router.get("/api/videos/exports/{job_id}/download")
def download_video_export(job_id: str, request: Request, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    job = get_workspace_object(db, VideoExportJob, job_id, current.workspace_id, "导出任务")
    if job.status != "ready" or not job.object_key or not job.expires_at or job.expires_at < shanghai_now():
        raise HTTPException(409, "导出包尚未生成或已过期")
    return stream_storage_object(request.app.state.services.storage, request, job.object_key, job.filename, "application/zip")


@router.post("/api/videos/import-zip", response_model=TransferRead)
async def import_video_zip(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...),
                           db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    limit = request.app.state.settings.video_package_upload_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, "素材包超过上传大小上限")
    task = create_task(db, "video_zip_import", "正在接收视频素材包", current.workspace_id, actor_id=current.user.id)
    try:
        path = await spool_upload(request.app.state.settings, task.id, 0, file, max_bytes=limit)
    except ValueError as exc:
        cleanup_import(request.app.state.settings, task.id)
        update_task(db, task.id, status="failed", message=str(exc))
        raise HTTPException(413, str(exc)) from exc
    except Exception:
        cleanup_import(request.app.state.settings, task.id)
        update_task(db, task.id, status="failed", message="素材包上传失败")
        raise
    background_tasks.add_task(run_import, request.app.state.session_factory, request.app.state.services.videos, task.id, path)
    return TransferRead(id=task.id, status=task.status, message=task.message)


@router.get("/api/videos/imports", response_model=list[TransferRead])
def list_video_imports(db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    return [TransferRead(id=task.id, status=task.status, message=task.message, result=json.loads(task.result_json or "{}"))
            for task in db.scalars(select(Task).where(Task.workspace_id == current.workspace_id, Task.kind == "video_zip_import")
                                   .order_by(Task.created_at.desc()).limit(20))]
