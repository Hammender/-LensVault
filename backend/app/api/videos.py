from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
import logging
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api._helpers import get_workspace_object
from app.core.timezones import shanghai_now
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.http.media import stream_storage_object
from app.mappers.videos import (
    subtitle_to_read as _subtitle_to_read,
    video_category_to_read as _video_category_to_read,
    video_play_url as _video_play_url,
    video_person_to_read as _video_person_to_read,
    video_session_to_read as _video_session_to_read,
    video_stream_url as _video_stream_url,
    video_to_detail as _video_to_detail,
    video_to_list_item as _video_to_list_item,
)
from app.models import (
    VideoCategoryTag,
    VideoItem,
    VideoItemCategoryTag,
    VideoItemPerson,
    VideoPerson,
    VideoSubtitleTrack,
    VideoUploadSession,
)
from app.schemas import (
    PaginatedVideos,
    VideoCategoryTagCreate,
    VideoCategoryTagRead,
    VideoCategoryTagUpdate,
    VideoItemDetail,
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
)
from app.services.tasks import create_task

_state_context: ContextVar[object] = ContextVar("video_request_state")
logger = logging.getLogger(__name__)


class _StateProxy:
    def __init__(self, *path: str):
        self.path = path

    def __getattr__(self, attribute: str):
        value = _state_context.get()
        for name in self.path:
            value = getattr(value, name)
        return getattr(value, attribute)


async def _bind_state(request: Request):
    token = _state_context.set(request.app.state)
    try:
        yield
    finally:
        _state_context.reset(token)


storage = _StateProxy("services", "storage")
video_service = _StateProxy("services", "videos")
subtitle_service = _StateProxy("services", "subtitles")
settings = _StateProxy("settings")
router = APIRouter(dependencies=[Depends(_bind_state)])

@router.get("/api/video-category-tags", response_model=list[VideoCategoryTagRead])
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


@router.post("/api/video-category-tags", response_model=VideoCategoryTagRead)
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
    except IntegrityError as exc:
        db.rollback()
        normalized = payload.name.strip()
        existing = db.scalar(
            select(VideoCategoryTag).where(
                VideoCategoryTag.workspace_id == current.workspace_id,
                VideoCategoryTag.name == normalized,
            )
        )
        if existing is not None:
            return _video_category_to_read(existing)
        raise


@router.patch("/api/video-category-tags/{tag_id}", response_model=VideoCategoryTagRead)
def update_video_category_tag(
    tag_id: int,
    payload: VideoCategoryTagUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoCategoryTagRead:
    tag = get_workspace_object(db, VideoCategoryTag, tag_id, current.workspace_id, "Video category tag")
    normalized = payload.name.strip()
    duplicate = db.scalar(
        select(VideoCategoryTag).where(
            VideoCategoryTag.workspace_id == current.workspace_id,
            VideoCategoryTag.name == normalized,
            VideoCategoryTag.id != tag_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="视频分类标签名称已存在")
    tag.name = normalized
    db.add(tag)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(
            select(VideoCategoryTag).where(
                VideoCategoryTag.workspace_id == current.workspace_id,
                VideoCategoryTag.name == normalized,
                VideoCategoryTag.id != tag_id,
            )
        ) is not None:
            raise HTTPException(status_code=409, detail="视频分类标签名称已存在") from exc
        raise
    db.refresh(tag)
    return _video_category_to_read(tag)


@router.delete("/api/video-category-tags/{tag_id}")
def delete_video_category_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    tag = get_workspace_object(db, VideoCategoryTag, tag_id, current.workspace_id, "Video category tag")
    db.delete(tag)
    db.commit()
    return {"status": "deleted"}


@router.get("/api/video-people", response_model=list[VideoPersonRead])
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


@router.post("/api/video-people", response_model=VideoPersonRead)
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
        raise HTTPException(status_code=409, detail="视频人物名称已存在")
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
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if avatar_key:
            storage.remove_object(avatar_key)
        if db.scalar(
            select(VideoPerson).where(
                VideoPerson.workspace_id == current.workspace_id,
                VideoPerson.name == normalized,
            )
        ) is not None:
            raise HTTPException(status_code=409, detail="视频人物名称已存在") from exc
        raise
    db.refresh(person)
    return _video_person_to_read(person)


@router.patch("/api/video-people/{person_id}", response_model=VideoPersonRead)
async def update_video_person(
    person_id: int,
    name: str | None = Form(default=None),
    note: str | None = Form(default=None),
    avatar: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoPersonRead:
    person = get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    normalized_name: str | None = None
    if name is not None:
        normalized = name.strip()
        normalized_name = normalized
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
            raise HTTPException(status_code=409, detail="视频人物名称已存在")
        person.name = normalized
    person.note = note
    old_avatar_key = None
    new_avatar_key = None
    if avatar is not None and avatar.filename:
        try:
            avatar_key, avatar_type = video_service.save_person_avatar(
                await avatar.read(), avatar.filename, avatar.content_type, current.workspace_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        old_avatar_key = person.avatar_object_key
        new_avatar_key = avatar_key
        person.avatar_object_key = avatar_key
        person.avatar_content_type = avatar_type
    db.add(person)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if new_avatar_key:
            storage.remove_object(new_avatar_key)
        if normalized_name is not None and db.scalar(
            select(VideoPerson).where(
                VideoPerson.workspace_id == current.workspace_id,
                VideoPerson.name == normalized_name,
                VideoPerson.id != person_id,
            )
        ) is not None:
            raise HTTPException(status_code=409, detail="视频人物名称已存在") from exc
        raise
    db.refresh(person)
    if old_avatar_key:
        storage.remove_object(old_avatar_key)
    return _video_person_to_read(person)


@router.delete("/api/video-people/{person_id}")
def delete_video_person(
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    person = get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    avatar_key = person.avatar_object_key
    db.delete(person)
    db.commit()
    if avatar_key:
        storage.remove_object(avatar_key)
    return {"status": "deleted"}


@router.get("/api/video-people/{person_id}/avatar")
def get_video_person_avatar(
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    person = get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    if not person.avatar_object_key:
        raise HTTPException(status_code=404, detail="Video person avatar not found")
    payload = storage.get_bytes(person.avatar_object_key)
    return Response(content=payload, media_type=person.avatar_content_type or "application/octet-stream")


@router.post("/api/videos/upload-sessions", response_model=VideoUploadSessionRead)
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


@router.get("/api/videos/upload-sessions/{session_id}", response_model=VideoUploadSessionRead)
def get_video_upload_session(
    session_id: str,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoUploadSessionRead:
    session = db.get(VideoUploadSession, session_id)
    if session is None or session.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    return _video_session_to_read(session)


@router.put("/api/videos/upload-sessions/{session_id}/parts/{part_index}", response_model=VideoUploadPartRead)
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


@router.post("/api/videos/upload-sessions/{session_id}/complete", response_model=VideoItemDetail)
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
        logger.info("视频后台优化已入队：video_id=%s filename=%s trigger=upload", video.id, video.filename)
        if payload.generate_zh_subtitles:
            task = create_task(db, "video_subtitle_generation", "已排队生成中文字幕", current.workspace_id)
            subtitle_service.prepare_track(db, video.id, task.id)
            background_tasks.add_task(subtitle_service.generate_for_video, video.id, task.id)
            db.refresh(video)
        return _video_to_detail(video)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/videos/upload-sessions/{session_id}")
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


@router.get("/api/videos", response_model=PaginatedVideos)
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


@router.get("/api/videos/{video_id}", response_model=VideoItemDetail)
def get_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if video_service.needs_metadata_repair(video):
        background_tasks.add_task(video_service.repair_video_metadata, video.id)
    return _video_to_detail(video)


@router.post("/api/videos/{video_id}/optimize-playback", response_model=VideoItemDetail)
def optimize_video_playback(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if video.status == "processing":
        raise HTTPException(status_code=409, detail="视频正在处理中，请稍后再试")
    video.status = "processing"
    video.processing_error = None
    db.commit()
    db.refresh(video)
    background_tasks.add_task(video_service.optimize_video_for_seek, video.id)
    logger.info("视频拖动优化已入队：video_id=%s filename=%s trigger=manual", video.id, video.filename)
    return _video_to_detail(video)


@router.get("/api/videos/{video_id}/subtitles", response_model=list[VideoSubtitleTrackRead])
def list_video_subtitles(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[VideoSubtitleTrackRead]:
    get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    tracks = db.scalars(
        select(VideoSubtitleTrack)
        .where(VideoSubtitleTrack.video_id == video_id)
        .order_by(VideoSubtitleTrack.created_at.asc())
    ).all()
    return [_subtitle_to_read(track) for track in tracks]


@router.post("/api/videos/{video_id}/subtitles/generate", response_model=VideoSubtitleTrackRead)
def generate_video_subtitles(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    task = create_task(db, "video_subtitle_generation", "已排队生成中文字幕", current.workspace_id)
    track = subtitle_service.prepare_track(db, video.id, task.id)
    background_tasks.add_task(subtitle_service.generate_for_video, video.id, task.id)
    return _subtitle_to_read(track)


@router.post("/api/videos/{video_id}/subtitles/{track_id}/cancel", response_model=VideoSubtitleTrackRead)
def cancel_video_subtitles(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    try:
        track = subtitle_service.cancel_track_generation(db, video_id, track_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _subtitle_to_read(track)


@router.get("/api/videos/{video_id}/subtitles/{track_id}.vtt")
def get_video_subtitle_vtt(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    if track.status != "ready" or not track.content_vtt:
        raise HTTPException(status_code=409, detail="Subtitle track is not ready")
    return Response(content=track.content_vtt, media_type="text/vtt; charset=utf-8")


@router.get("/api/videos/{video_id}/subtitles/{track_id}.srt")
def get_video_subtitle_srt(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    if track.status != "ready" or not track.content_vtt:
        raise HTTPException(status_code=409, detail="Subtitle track is not ready")
    filename = f"{Path(video.filename).stem or 'subtitle'}.srt"
    ascii_filename = quote(filename)
    return Response(
        content=subtitle_service.webvtt_to_srt(track.content_vtt),
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{ascii_filename}"},
    )


@router.patch("/api/videos/{video_id}/subtitles/{track_id}", response_model=VideoSubtitleTrackRead)
def update_video_subtitle(
    video_id: int,
    track_id: int,
    payload: VideoSubtitleTrackUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoSubtitleTrackRead:
    get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    try:
        track.content_vtt = subtitle_service.validate_webvtt(payload.content_vtt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    track.status = "ready"
    track.error_message = None
    track.generated_at = track.generated_at or shanghai_now()
    db.add(track)
    db.commit()
    db.refresh(track)
    return _subtitle_to_read(track)


@router.delete("/api/videos/{video_id}/subtitles/{track_id}")
def delete_video_subtitle(
    video_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    track = db.get(VideoSubtitleTrack, track_id)
    if track is None or track.video_id != video_id:
        raise HTTPException(status_code=404, detail="Subtitle track not found")
    db.delete(track)
    db.commit()
    return {"status": "deleted"}


@router.patch("/api/videos/{video_id}", response_model=VideoItemDetail)
def update_video(
    video_id: int,
    payload: VideoMetadataUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if payload.title is not None:
        video.title = payload.title.strip()
    if payload.description is not None:
        video.description = payload.description
    db.add(video)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@router.delete("/api/videos/{video_id}")
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    video_service.delete_video(db, video)
    return {"status": "deleted"}


@router.get("/api/videos/{video_id}/cover")
def get_video_cover(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    if not video.cover_object_key:
        raise HTTPException(status_code=404, detail="Video cover not found")
    payload = storage.get_bytes(video.cover_object_key)
    return Response(content=payload, media_type=video.cover_content_type or "image/jpeg")


@router.put("/api/videos/{video_id}/cover", response_model=VideoItemDetail)
async def replace_video_cover(
    video_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    try:
        updated = video_service.save_video_cover(db, video, await file.read(), file.filename or "cover.jpg", file.content_type)
        return _video_to_detail(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/videos/{video_id}/category-tags", response_model=VideoItemDetail)
def add_video_category_tag(
    video_id: int,
    payload: VideoTagBindCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
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


@router.delete("/api/videos/{video_id}/category-tags/{tag_id}", response_model=VideoItemDetail)
def remove_video_category_tag(
    video_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    get_workspace_object(db, VideoCategoryTag, tag_id, current.workspace_id, "Video category tag")
    link = db.scalar(select(VideoItemCategoryTag).where(VideoItemCategoryTag.video_id == video_id, VideoItemCategoryTag.tag_id == tag_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Video category tag link not found")
    db.delete(link)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@router.post("/api/videos/{video_id}/people", response_model=VideoItemDetail)
def add_video_person(
    video_id: int,
    payload: VideoPersonBindCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    person = get_workspace_object(db, VideoPerson, payload.person_id, current.workspace_id, "Video person")
    existing = db.scalar(select(VideoItemPerson).where(VideoItemPerson.video_id == video.id, VideoItemPerson.person_id == person.id))
    if existing is None:
        db.add(VideoItemPerson(video_id=video.id, person_id=person.id))
        db.commit()
        db.refresh(video)
    return _video_to_detail(video)


@router.delete("/api/videos/{video_id}/people/{person_id}", response_model=VideoItemDetail)
def remove_video_person(
    video_id: int,
    person_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> VideoItemDetail:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    get_workspace_object(db, VideoPerson, person_id, current.workspace_id, "Video person")
    link = db.scalar(select(VideoItemPerson).where(VideoItemPerson.video_id == video_id, VideoItemPerson.person_id == person_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Video person link not found")
    db.delete(link)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


def _stream_video_response(video: VideoItem, request: Request) -> StreamingResponse:
    return stream_storage_object(
        storage,
        request,
        video.object_key,
        video.filename,
        video.content_type,
        default_media_type="video/mp4",
        include_ascii_filename=False,
    )


@router.get("/api/videos/{video_id}/play")
def play_video(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
):
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
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


@router.get("/api/videos/{video_id}/stream")
def stream_video(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
    response = _stream_video_response(video, request)
    response.headers["X-PictureShow-Video-Mode"] = "backend-stream"
    return response


@router.get("/api/videos/{video_id}/playback-diagnostics")
def get_video_playback_diagnostics(
    video_id: int,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, object]:
    video = get_workspace_object(db, VideoItem, video_id, current.workspace_id, "Video")
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
    try:
        result["object"] = video_service.inspect_playback_object(video)
    except Exception as exc:
        logger.exception("Failed to inspect video playback object video_id=%s", video.id)
        result["object_probe_ok"] = False
        result["object_probe_error"] = str(exc)[:500]
    else:
        result["object_probe_ok"] = True
    return result


