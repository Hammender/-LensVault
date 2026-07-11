from __future__ import annotations

from app.models import VideoCategoryTag, VideoItem, VideoPerson, VideoSubtitleTrack, VideoUploadSession
from app.schemas import (
    VideoCategoryTagRead,
    VideoItemDetail,
    VideoItemListItem,
    VideoPersonRead,
    VideoSubtitleTrackRead,
    VideoUploadSessionRead,
)


def video_person_to_read(person: VideoPerson) -> VideoPersonRead:
    return VideoPersonRead(
        id=person.id,
        name=person.name,
        note=person.note,
        avatar_url=f"/api/video-people/{person.id}/avatar" if person.avatar_object_key else None,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


def video_category_to_read(tag: VideoCategoryTag) -> VideoCategoryTagRead:
    return VideoCategoryTagRead.model_validate(tag)


def video_stream_url(video: VideoItem) -> str:
    return f"/api/videos/{video.id}/stream"


def video_play_url(video: VideoItem) -> str:
    return f"/api/videos/{video.id}/play"


def video_cover_url(video: VideoItem) -> str | None:
    if not video.cover_object_key:
        return None
    return f"/api/videos/{video.id}/cover"


def subtitle_to_read(track: VideoSubtitleTrack) -> VideoSubtitleTrackRead:
    vtt_url = None
    srt_url = None
    if track.status == "ready" and track.content_vtt:
        vtt_url = f"/api/videos/{track.video_id}/subtitles/{track.id}.vtt"
        srt_url = f"/api/videos/{track.video_id}/subtitles/{track.id}.srt"
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
        srt_url=srt_url,
    )


def video_to_list_item(video: VideoItem) -> VideoItemListItem:
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
        category_tags=[video_category_to_read(tag) for tag in categories],
        people=[video_person_to_read(person) for person in people],
        stream_url=video_stream_url(video),
        play_url=video_play_url(video),
        cover_url=video_cover_url(video),
        faststart_applied=video.faststart_applied,
        seek_optimized=video.seek_optimized,
        seek_optimized_at=video.seek_optimized_at,
        seek_keyframe_interval_seconds=video.seek_keyframe_interval_seconds,
        processed_at=video.processed_at,
        processing_error=video.processing_error,
        subtitle_tracks=[subtitle_to_read(track) for track in subtitle_tracks],
        created_at=video.created_at,
        updated_at=video.updated_at,
    )


def video_to_detail(video: VideoItem) -> VideoItemDetail:
    item = video_to_list_item(video)
    return VideoItemDetail(**item.model_dump(), sha256=video.sha256)


def video_session_to_read(session: VideoUploadSession) -> VideoUploadSessionRead:
    return VideoUploadSessionRead(
        id=session.id,
        filename=session.filename,
        title=session.title,
        description=session.description,
        content_type=session.content_type,
        size_bytes=session.size_bytes,
        part_size=session.part_size,
        total_parts=session.total_parts,
        uploaded_parts=sorted(part.part_index for part in session.parts),
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
