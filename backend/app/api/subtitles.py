from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.mappers.videos import subtitle_to_read
from app.models import Task, VideoItem, VideoSubtitleTrack
from app.schemas import SubtitleJobRead, SubtitleServiceLogs, SubtitleServiceStatus, TaskRead

router = APIRouter()


@router.get("/api/subtitle-service/status", response_model=SubtitleServiceStatus)
def get_subtitle_service_status(request: Request, current: CurrentContext = Depends(require_context)) -> SubtitleServiceStatus:
    return SubtitleServiceStatus(**request.app.state.services.subtitles.get_translation_service_status())


@router.post("/api/subtitle-service/start", response_model=SubtitleServiceStatus)
def start_subtitle_service(request: Request, current: CurrentContext = Depends(require_context)) -> SubtitleServiceStatus:
    try:
        return SubtitleServiceStatus(**request.app.state.services.subtitles.start_translation_service())
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/subtitle-service/stop", response_model=SubtitleServiceStatus)
def stop_subtitle_service(
    request: Request,
    cancel_running: bool = Query(default=True),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> SubtitleServiceStatus:
    try:
        return SubtitleServiceStatus(**request.app.state.services.subtitles.stop_translation_service(db=db, cancel_running=cancel_running))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/subtitle-service/logs", response_model=SubtitleServiceLogs)
def get_subtitle_service_logs(
    request: Request,
    tail: int = Query(default=200, ge=1, le=1000),
    current: CurrentContext = Depends(require_context),
) -> SubtitleServiceLogs:
    return SubtitleServiceLogs(**request.app.state.services.subtitles.read_translation_service_logs(tail=tail))


@router.get("/api/subtitle-jobs", response_model=list[SubtitleJobRead])
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
                track=subtitle_to_read(track),
                task=TaskRead.model_validate(task) if task is not None else None,
            )
        )
    return jobs
