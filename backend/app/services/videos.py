from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Lock
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import SessionLocal
from app.models import (
    VideoCategoryTag,
    VideoItem,
    VideoItemCategoryTag,
    VideoItemPerson,
    VideoPerson,
    VideoUploadPart,
    VideoUploadSession,
)
from app.schemas import VideoUploadCompleteRequest, VideoUploadSessionCreate
from app.services.storage import MinioStorage

logger = logging.getLogger(__name__)


class VideoService:
    default_part_size = 16 * 1024 * 1024
    min_part_size = 5 * 1024 * 1024
    max_part_size = 128 * 1024 * 1024
    supported_extensions = {".mp4", ".mkv", ".mov", ".webm"}
    extension_content_types = {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
    }
    supported_content_types = {
        "video/mp4",
        "application/mp4",
        "video/x-matroska",
        "video/matroska",
        "video/quicktime",
        "video/webm",
        "application/octet-stream",
        "",
    }
    supported_format_label = "MP4、MKV、MOV、WEBM"
    browser_video_codecs = {"h264", "avc1"}
    browser_audio_codecs = {"aac", "mp3", "mp4a"}
    metadata_repair_lock = Lock()
    metadata_repair_video_ids: set[int] = set()

    def __init__(self, storage: MinioStorage, settings: Settings | None = None) -> None:
        self.storage = storage
        self.settings = settings or get_settings()

    def create_upload_session(self, db: Session, payload: VideoUploadSessionCreate, workspace_id: int | None) -> VideoUploadSession:
        title = payload.title.strip()
        filename = Path(payload.filename).name.strip()
        content_type = self._normalize_upload_content_type(filename, payload.content_type)
        self._validate_video_file(filename, content_type)

        existing = db.scalar(
            select(VideoItem).where(
                VideoItem.workspace_id == workspace_id,
                VideoItem.filename == filename,
                VideoItem.size_bytes == payload.size_bytes,
            )
        )
        if existing is not None:
            raise ValueError("已存在相同文件名和大小的视频，请勿重复上传")

        part_size = payload.part_size or self.default_part_size
        part_size = min(max(part_size, self.min_part_size), self.max_part_size)
        if payload.size_bytes <= self.default_part_size:
            part_size = max(payload.size_bytes, 1)

        total_parts = (payload.size_bytes + part_size - 1) // part_size
        session = VideoUploadSession(
            id=uuid4().hex,
            workspace_id=workspace_id,
            filename=filename,
            title=title,
            description=payload.description,
            content_type=content_type,
            size_bytes=payload.size_bytes,
            part_size=part_size,
            total_parts=total_parts,
            sha256=payload.sha256.lower() if payload.sha256 else None,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def put_upload_part(
        self,
        db: Session,
        session: VideoUploadSession,
        part_index: int,
        payload: bytes,
        sha256: str | None = None,
    ) -> VideoUploadPart:
        if session.status != "uploading":
            raise ValueError("上传会话不是上传中状态")
        if part_index < 0 or part_index >= session.total_parts:
            raise ValueError("分片序号超出范围")

        expected_size = self._expected_part_size(session, part_index)
        if len(payload) != expected_size:
            raise ValueError(f"分片大小不正确，应为 {expected_size} 字节")

        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if sha256 and sha256.lower() != actual_sha256:
            raise ValueError("分片 SHA256 校验失败")

        existing = db.scalar(
            select(VideoUploadPart).where(
                VideoUploadPart.session_id == session.id,
                VideoUploadPart.part_index == part_index,
            )
        )
        object_key = self._build_part_object_key(session.workspace_id, session.id, part_index)
        self.storage.put_bytes(object_key, payload, session.content_type)
        if existing:
            if existing.object_key != object_key:
                self.storage.remove_object(existing.object_key)
            existing.object_key = object_key
            existing.size_bytes = len(payload)
            existing.sha256 = actual_sha256
            part = existing
        else:
            part = VideoUploadPart(
                session_id=session.id,
                part_index=part_index,
                object_key=object_key,
                size_bytes=len(payload),
                sha256=actual_sha256,
            )
            db.add(part)
        db.commit()
        db.refresh(part)
        return part

    def complete_upload(
        self,
        db: Session,
        session: VideoUploadSession,
        payload: VideoUploadCompleteRequest,
    ) -> VideoItem:
        parts = db.scalars(
            select(VideoUploadPart)
            .where(VideoUploadPart.session_id == session.id)
            .order_by(VideoUploadPart.part_index.asc())
        ).all()
        uploaded_indexes = [part.part_index for part in parts]
        if uploaded_indexes != list(range(session.total_parts)):
            raise ValueError("视频分片尚未上传完整")

        existing = db.scalar(
            select(VideoItem).where(
                VideoItem.filename == session.filename,
                VideoItem.size_bytes == session.size_bytes,
                VideoItem.workspace_id == session.workspace_id,
            )
        )
        if existing is not None:
            raise ValueError("已存在相同文件名和大小的视频，请勿重复上传")

        final_key = self._build_video_object_key(session.workspace_id, session.filename)
        try:
            if len(parts) == 1:
                self.storage.put_bytes(final_key, self.storage.get_bytes(parts[0].object_key), session.content_type)
            else:
                self.storage.compose_object(final_key, [part.object_key for part in parts])

            if session.sha256:
                actual_sha256 = self.hash_object(final_key)
                if actual_sha256 != session.sha256:
                    self.storage.remove_object(final_key)
                    raise ValueError("视频 SHA256 校验失败")

            probe_info = self._probe_object(final_key, session.filename)
            video = VideoItem(
                workspace_id=session.workspace_id,
                title=session.title,
                description=session.description,
                filename=session.filename,
                content_type=session.content_type or "video/mp4",
                sha256=session.sha256,
                object_key=final_key,
                size_bytes=session.size_bytes,
                duration_seconds=probe_info.duration_seconds if probe_info else None,
                width=probe_info.width if probe_info else None,
                height=probe_info.height if probe_info else None,
                original_video_codec=probe_info.video_codec if probe_info else None,
                original_audio_codec=probe_info.audio_codec if probe_info else None,
                video_codec=probe_info.video_codec if probe_info else None,
                audio_codec=probe_info.audio_codec if probe_info else None,
                status="uploaded",
            )
            db.add(video)
            db.flush()
            self.replace_video_tags(db, video, payload.category_tag_ids, payload.category_tag_names)
            self.replace_video_people(db, video, payload.person_ids)
            temp_keys = [part.object_key for part in parts]
            for part in parts:
                db.delete(part)
            db.delete(session)
            db.commit()
            self.storage.remove_objects(temp_keys)
            db.refresh(video)
            return video
        except Exception:
            db.rollback()
            raise

    def process_video_for_playback(self, video_id: int) -> None:
        db = SessionLocal()
        try:
            video = db.get(VideoItem, video_id)
            if video is None:
                return
            video.status = "processing"
            video.processing_error = None
            db.commit()
            object_key = video.object_key

            with tempfile.TemporaryDirectory(prefix="pictureshow-video-") as temp_dir:
                suffix = Path(video.filename).suffix.lower() or ".mp4"
                input_path = Path(temp_dir) / f"input{suffix}"
                output_path = Path(temp_dir) / "playback.mp4"
                cover_path = Path(temp_dir) / "cover.jpg"
                self._download_object_to_file(object_key, input_path)
                original_info = self._probe_video(input_path)
                video = db.get(VideoItem, video_id)
                if video is None:
                    return
                video.duration_seconds = original_info.duration_seconds or video.duration_seconds
                video.width = original_info.width or video.width
                video.height = original_info.height or video.height
                video.original_video_codec = original_info.video_codec or video.original_video_codec
                video.original_audio_codec = original_info.audio_codec or video.original_audio_codec
                video.video_codec = original_info.video_codec or video.video_codec
                video.audio_codec = original_info.audio_codec or video.audio_codec
                db.commit()

                self._extract_cover(input_path, cover_path, original_info.duration_seconds)
                cover_key: str | None = None
                old_cover_key: str | None = None
                if cover_path.exists() and cover_path.stat().st_size > 0:
                    cover_key = self._build_cover_object_key(video.workspace_id, video_id)
                    with cover_path.open("rb") as stream:
                        self.storage.put_stream(cover_key, stream, cover_path.stat().st_size, "image/jpeg")
                    video = db.get(VideoItem, video_id)
                    if video is None:
                        return
                    old_cover_key = video.cover_object_key
                    video.cover_object_key = cover_key
                    video.cover_content_type = "image/jpeg"
                    db.commit()
                    if old_cover_key and old_cover_key != cover_key:
                        self.storage.remove_object(old_cover_key)

                if not self.settings.video_faststart_enabled:
                    video = db.get(VideoItem, video_id)
                    if video is None:
                        return
                    video.status = "ready"
                    video.faststart_applied = False
                    video.processed_at = datetime.utcnow()
                    video.processing_error = None
                    db.commit()
                    return

                if self._is_browser_friendly(original_info) or not self.settings.video_transcode_non_browser_friendly:
                    self._run_faststart(input_path, output_path)
                else:
                    self._run_browser_transcode(input_path, output_path)
                playback_info = self._probe_video(output_path)
                size_bytes = output_path.stat().st_size
                sha256 = self._hash_file(output_path)
                with output_path.open("rb") as stream:
                    self.storage.put_stream(object_key, stream, size_bytes, "video/mp4")

            video = db.get(VideoItem, video_id)
            if video is None:
                return
            video.status = "ready"
            video.faststart_applied = True
            video.sha256 = sha256
            video.content_type = "video/mp4"
            video.duration_seconds = playback_info.duration_seconds or original_info.duration_seconds or video.duration_seconds
            video.width = playback_info.width or original_info.width or video.width
            video.height = playback_info.height or original_info.height or video.height
            video.original_video_codec = original_info.video_codec or video.original_video_codec
            video.original_audio_codec = original_info.audio_codec or video.original_audio_codec
            video.video_codec = playback_info.video_codec or original_info.video_codec or video.video_codec
            video.audio_codec = playback_info.audio_codec or original_info.audio_codec or video.audio_codec
            video.processed_at = datetime.utcnow()
            video.processing_error = None
            db.commit()
        except Exception as exc:
            logger.exception("Video processing failed video_id=%s", video_id)
            db.rollback()
            video = db.get(VideoItem, video_id)
            if video is not None:
                video.status = "processing_failed"
                video.faststart_applied = False
                video.processed_at = datetime.utcnow()
                video.processing_error = str(exc)[:2000]
                db.commit()
        finally:
            db.close()

    def optimize_video_faststart(self, video_id: int) -> None:
        self.process_video_for_playback(video_id)

    def needs_metadata_repair(self, video: VideoItem) -> bool:
        if video.status == "ready" and (not video.original_video_codec or not video.video_codec):
            return True
        return video.status == "processing_failed" and self._is_size_unique_processing_error(video.processing_error)

    def repair_video_metadata(self, video_id: int) -> None:
        with self.metadata_repair_lock:
            if video_id in self.metadata_repair_video_ids:
                return
            self.metadata_repair_video_ids.add(video_id)
        db = SessionLocal()
        try:
            video = db.get(VideoItem, video_id)
            if video is None or not self.needs_metadata_repair(video):
                return
            probe_info = self._probe_object(video.object_key, video.filename)
            if probe_info is None:
                return
            video.duration_seconds = video.duration_seconds or probe_info.duration_seconds
            video.width = video.width or probe_info.width
            video.height = video.height or probe_info.height
            video.original_video_codec = video.original_video_codec or probe_info.video_codec
            video.original_audio_codec = video.original_audio_codec or probe_info.audio_codec
            video.video_codec = video.video_codec or probe_info.video_codec
            video.audio_codec = video.audio_codec or probe_info.audio_codec
            if video.status == "processing_failed" and self._is_size_unique_processing_error(video.processing_error):
                video.status = "ready"
                video.faststart_applied = True
                video.content_type = "video/mp4"
                video.processed_at = datetime.utcnow()
                video.processing_error = None
            db.commit()
        except Exception:
            logger.exception("Video metadata repair failed video_id=%s", video_id)
        finally:
            db.close()
            with self.metadata_repair_lock:
                self.metadata_repair_video_ids.discard(video_id)

    def _is_size_unique_processing_error(self, error: str | None) -> bool:
        return bool(
            error
            and (
                "UNIQUE constraint failed: video_items.filename, video_items.size_bytes" in error
                or "UNIQUE constraint failed: video_items.workspace_id, video_items.filename, video_items.size_bytes" in error
            )
        )

    def _mark_video_ready_without_processing(self, video_id: int) -> None:
        db = SessionLocal()
        try:
            video = db.get(VideoItem, video_id)
            if video is None:
                return
            video.status = "ready"
            video.processing_error = None
            db.commit()
        finally:
            db.close()

    def cancel_upload(self, db: Session, session: VideoUploadSession) -> None:
        parts = db.scalars(select(VideoUploadPart).where(VideoUploadPart.session_id == session.id)).all()
        temp_keys = [part.object_key for part in parts]
        for part in parts:
            db.delete(part)
        db.delete(session)
        db.commit()
        self.storage.remove_objects(temp_keys)

    def delete_video(self, db: Session, video: VideoItem) -> None:
        object_key = video.object_key
        cover_key = video.cover_object_key
        db.delete(video)
        db.commit()
        self.storage.remove_object(object_key)
        if cover_key:
            self.storage.remove_object(cover_key)

    def save_person_avatar(self, payload: bytes, filename: str, content_type: str | None, workspace_id: int | None) -> tuple[str, str | None]:
        clean_name = Path(filename).name or "avatar"
        avatar_type = content_type or "application/octet-stream"
        if not avatar_type.startswith("image/"):
            raise ValueError("人物展示照片必须是图片")
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        object_key = f"{prefix}videos/people/{uuid4().hex}-{clean_name}"
        self.storage.put_bytes(object_key, payload, avatar_type)
        return object_key, avatar_type

    def save_video_cover(self, db: Session, video: VideoItem, payload: bytes, filename: str, content_type: str | None) -> VideoItem:
        if not content_type or not content_type.startswith("image/"):
            raise ValueError("视频封面必须是图片")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        prefix = f"workspaces/{video.workspace_id}/" if video.workspace_id is not None else ""
        object_key = f"{prefix}videos/covers/{video.id}-{uuid4().hex}{suffix}"
        old_cover_key = video.cover_object_key
        self.storage.put_bytes(object_key, payload, content_type)
        video.cover_object_key = object_key
        video.cover_content_type = content_type
        db.add(video)
        db.commit()
        db.refresh(video)
        if old_cover_key and old_cover_key != object_key:
            self.storage.remove_object(old_cover_key)
        return video

    def replace_video_tags(
        self,
        db: Session,
        video: VideoItem,
        tag_ids: list[int],
        tag_names: list[str],
    ) -> None:
        for link in list(video.category_links):
            db.delete(link)
        db.flush()
        tags: list[VideoCategoryTag] = []
        for tag_id in dict.fromkeys(tag_ids):
            tag = db.get(VideoCategoryTag, tag_id)
            if tag is None or tag.workspace_id != video.workspace_id:
                raise ValueError("视频类别标签不存在")
            tags.append(tag)
        for name in dict.fromkeys(name.strip() for name in tag_names if name.strip()):
            tags.append(self.find_or_create_category_tag(db, name, video.workspace_id))
        seen: set[int] = set()
        for tag in tags:
            if tag.id in seen:
                continue
            seen.add(tag.id)
            db.add(VideoItemCategoryTag(video_id=video.id, tag_id=tag.id))

    def replace_video_people(self, db: Session, video: VideoItem, person_ids: list[int]) -> None:
        for link in list(video.person_links):
            db.delete(link)
        db.flush()
        for person_id in dict.fromkeys(person_ids):
            person = db.get(VideoPerson, person_id)
            if person is None or person.workspace_id != video.workspace_id:
                raise ValueError("视频人物不存在")
            db.add(VideoItemPerson(video_id=video.id, person_id=person.id))

    def find_or_create_category_tag(self, db: Session, name: str, workspace_id: int | None) -> VideoCategoryTag:
        normalized = name.strip()
        if not normalized:
            raise ValueError("标签名称不能为空")
        tag = db.scalar(select(VideoCategoryTag).where(VideoCategoryTag.workspace_id == workspace_id, VideoCategoryTag.name == normalized))
        if tag is None:
            tag = VideoCategoryTag(workspace_id=workspace_id, name=normalized)
            db.add(tag)
            db.flush()
        return tag

    def hash_object(self, object_key: str) -> str:
        digest = hashlib.sha256()
        response = self.storage.get_stream(object_key)
        try:
            for chunk in response.stream(1024 * 1024):
                digest.update(chunk)
        finally:
            response.close()
            response.release_conn()
        return digest.hexdigest()

    def _download_object_to_file(self, object_key: str, path: Path) -> None:
        response = self.storage.get_stream(object_key)
        try:
            with path.open("wb") as handle:
                for chunk in response.stream(1024 * 1024):
                    handle.write(chunk)
        finally:
            response.close()
            response.release_conn()

    def _probe_object(self, object_key: str, filename: str) -> "VideoProbeInfo | None":
        try:
            with tempfile.TemporaryDirectory(prefix="pictureshow-video-probe-") as temp_dir:
                suffix = Path(filename).suffix.lower() or ".mp4"
                input_path = Path(temp_dir) / f"input{suffix}"
                self._download_object_to_file(object_key, input_path)
                return self._probe_video(input_path)
        except Exception:
            logger.exception("Video metadata probe failed object_key=%s", object_key)
            return None

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _run_faststart(self, input_path: Path, output_path: Path) -> None:
        command = [
            self.settings.ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.settings.video_faststart_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "ffmpeg faststart failed").strip()
            raise RuntimeError(message[-2000:])
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg faststart did not create output video")

    def _run_browser_transcode(self, input_path: Path, output_path: Path) -> None:
        command = [
            self.settings.ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.settings.video_transcode_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "ffmpeg transcode failed").strip()
            raise RuntimeError(message[-2000:])
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg transcode did not create output video")

    def _extract_cover(self, input_path: Path, output_path: Path, duration_seconds: float | None) -> None:
        capture_at = self.settings.video_cover_capture_seconds
        if duration_seconds and duration_seconds > 0:
            capture_at = min(max(capture_at, duration_seconds * 0.1), max(duration_seconds - 0.1, 0))
        command = [
            self.settings.ffmpeg_path,
            "-y",
            "-ss",
            f"{capture_at:.3f}",
            "-i",
            str(input_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1280:-2:force_original_aspect_ratio=decrease",
            "-q:v",
            "3",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("Video cover extraction failed: %s", (result.stderr or result.stdout or "").strip()[-1000:])

    def _probe_video(self, path: Path) -> "VideoProbeInfo":
        command = [
            self.settings.ffprobe_path,
            "-v",
            "error",
            "-probesize",
            "100M",
            "-analyzeduration",
            "100M",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "ffprobe failed").strip()
            raise RuntimeError(message[-2000:])
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams", [])
        video_stream = next((stream for stream in streams if str(stream.get("codec_type", "")).lower() == "video"), {})
        audio_stream = next((stream for stream in streams if str(stream.get("codec_type", "")).lower() == "audio"), {})
        duration = self._parse_float(video_stream.get("duration")) or self._parse_float(payload.get("format", {}).get("duration"))
        video_codec = self._stream_codec(video_stream)
        audio_codec = self._stream_codec(audio_stream)
        if not video_codec or (streams and not audio_codec):
            fallback_video_codec, fallback_audio_codec = self._probe_codecs_from_ffmpeg_banner(path)
            video_codec = video_codec or fallback_video_codec
            audio_codec = audio_codec or fallback_audio_codec
        return VideoProbeInfo(
            duration_seconds=duration,
            width=self._parse_int(video_stream.get("width")),
            height=self._parse_int(video_stream.get("height")),
            video_codec=video_codec,
            audio_codec=audio_codec,
        )

    def _is_browser_friendly(self, info: "VideoProbeInfo") -> bool:
        if info.video_codec not in self.browser_video_codecs:
            return False
        return info.audio_codec is None or info.audio_codec in self.browser_audio_codecs

    def _build_cover_object_key(self, workspace_id: int | None, video_id: int) -> str:
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}videos/covers/{video_id}-{uuid4().hex}.jpg"

    def _normalize_codec(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if normalized in {"unknown", "none", "n/a", "[0][0][0][0]"}:
            return None
        return normalized or None

    def _stream_codec(self, stream: dict[str, object]) -> str | None:
        return self._normalize_codec(stream.get("codec_name")) or self._normalize_codec(stream.get("codec_tag_string"))

    def _probe_codecs_from_ffmpeg_banner(self, path: Path) -> tuple[str | None, str | None]:
        command = [
            self.settings.ffmpeg_path,
            "-hide_banner",
            "-i",
            str(path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        output = f"{result.stderr or ''}\n{result.stdout or ''}"
        video_match = re.search(r"Stream #\S+.*?Video:\s*([^,\s]+)", output, re.IGNORECASE)
        audio_match = re.search(r"Stream #\S+.*?Audio:\s*([^,\s]+)", output, re.IGNORECASE)
        return (
            self._normalize_codec(video_match.group(1) if video_match else None),
            self._normalize_codec(audio_match.group(1) if audio_match else None),
        )

    def _parse_float(self, value: object) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_int(self, value: object) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _expected_part_size(self, session: VideoUploadSession, part_index: int) -> int:
        start = part_index * session.part_size
        end = min(start + session.part_size, session.size_bytes)
        return end - start

    def _validate_video_file(self, filename: str, content_type: str) -> None:
        if Path(filename).suffix.lower() not in self.supported_extensions:
            raise ValueError(f"当前版本仅支持 {self.supported_format_label} 视频")
        if content_type not in self.supported_content_types:
            raise ValueError(f"当前版本仅支持 {self.supported_format_label} 视频")

    def _normalize_upload_content_type(self, filename: str, content_type: str | None) -> str:
        normalized = (content_type or "").strip().lower()
        if normalized:
            return normalized
        suffix = Path(filename).suffix.lower()
        return self.extension_content_types.get(suffix, "application/octet-stream")

    def _build_video_object_key(self, workspace_id: int | None, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".mp4"
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}videos/library/{uuid4().hex}{suffix}"

    def _build_part_object_key(self, workspace_id: int | None, session_id: str, part_index: int) -> str:
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}videos/tmp/{session_id}/part-{part_index:06d}"


class VideoProbeInfo:
    def __init__(
        self,
        duration_seconds: float | None,
        width: int | None,
        height: int | None,
        video_codec: str | None,
        audio_codec: str | None,
    ) -> None:
        self.duration_seconds = duration_seconds
        self.width = width
        self.height = height
        self.video_codec = video_codec
        self.audio_codec = audio_codec
