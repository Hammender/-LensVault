from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import SessionLocal
from app.models import Task, VideoItem, VideoSubtitleTrack
from app.services.storage import MinioStorage
from app.services.tasks import update_task

logger = logging.getLogger(__name__)
_llama_process: subprocess.Popen | None = None
_llama_log_handle: Any | None = None
_llama_lock = threading.Lock()
_subtitle_cancel_events: dict[str, threading.Event] = {}
_subtitle_cancel_lock = threading.Lock()


class SubtitleCanceledError(RuntimeError):
    pass


class SubtitleService:
    def __init__(self, storage: MinioStorage, settings: Settings | None = None) -> None:
        self.storage = storage
        self.settings = settings or get_settings()
        self._asr_model: Any | None = None
        self._asr_lock = threading.Lock()
        self._asr_status_lock = threading.Lock()
        self._asr_status: dict[str, Any] = {
            "status": "not_loaded",
            "current_video_id": None,
            "current_task_id": None,
            "message": "ASR 模型尚未加载",
            "last_duration_seconds": None,
            "last_language": None,
            "last_segment_count": None,
            "last_error": None,
        }

    def prepare_track(self, db: Session, video_id: int, task_id: str | None = None) -> VideoSubtitleTrack:
        track = db.scalar(
            select(VideoSubtitleTrack).where(
                VideoSubtitleTrack.video_id == video_id,
                VideoSubtitleTrack.language == "zh-CN",
            )
        )
        if track is None:
            track = VideoSubtitleTrack(video_id=video_id, language="zh-CN", label="中文字幕")
            db.add(track)
        track.provider = self.settings.subtitle_translation_provider
        track.status = "pending"
        track.content_vtt = None
        track.error_message = None
        track.task_id = task_id
        track.generated_at = None
        db.commit()
        db.refresh(track)
        return track

    def get_translation_service_status(self) -> dict[str, Any]:
        managed_pid = self._managed_process_pid()
        external_pid = None if managed_pid is not None else self._pid_for_server_port()
        pid = managed_pid or external_pid
        healthy = self._health_ok()
        if healthy:
            status = "running"
            message = "翻译服务正在运行"
        elif pid is not None:
            status = "unhealthy"
            message = "检测到翻译服务进程，但健康检查失败"
        else:
            status = "stopped"
            message = "翻译服务未运行"
        return {
            "status": status,
            "healthy": healthy,
            "managed": managed_pid is not None,
            "pid": pid,
            "endpoint": self._server_root(),
            "model": self.settings.subtitle_translation_model,
            "model_path": str(self.settings.subtitle_translation_model_path),
            "server_path": str(self.settings.subtitle_llama_server_path) if self.settings.subtitle_llama_server_path else None,
            "log_path": str(self._llama_log_path()) if self._llama_log_path() else None,
            "message": message,
            "asr": self.get_asr_status(),
        }

    def get_asr_status(self) -> dict[str, Any]:
        with self._asr_status_lock:
            status = dict(self._asr_status)
        loaded = self._asr_model is not None
        if loaded and status["status"] == "not_loaded":
            status["status"] = "ready"
            status["message"] = "ASR 模型已加载"
        status.update(
            {
                "loaded": loaded,
                "model_path": str(self.settings.subtitle_asr_model_path),
                "device": self.settings.subtitle_asr_device,
                "compute_type": self.settings.subtitle_asr_compute_type,
            }
        )
        return status

    def start_translation_service(self) -> dict[str, Any]:
        self._ensure_translation_server()
        return self.get_translation_service_status()

    def stop_translation_service(self, db: Session | None = None, cancel_running: bool = True) -> dict[str, Any]:
        if cancel_running and db is not None:
            self.cancel_running_jobs(db, "用户关闭翻译服务，字幕生成已取消")
        self._stop_translation_server()
        return self.get_translation_service_status()

    def read_translation_service_logs(self, tail: int = 200) -> dict[str, Any]:
        log_path = self._llama_log_path()
        if log_path is None:
            return {"log_path": None, "exists": False, "content": ""}
        if not log_path.exists():
            return {"log_path": str(log_path), "exists": False, "content": ""}
        max_bytes = max(min(tail, 1000), 1) * 400
        try:
            with log_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(size - max_bytes, 0), os.SEEK_SET)
                lines = handle.read().decode("utf-8", errors="ignore").splitlines()
        except OSError as exc:
            return {"log_path": str(log_path), "exists": True, "content": f"读取日志失败: {exc}"}
        return {"log_path": str(log_path), "exists": True, "content": "\n".join(lines[-tail:])}

    def cancel_track_generation(self, db: Session, video_id: int, track_id: int, message: str = "用户已取消字幕生成") -> VideoSubtitleTrack:
        track = db.get(VideoSubtitleTrack, track_id)
        if track is None or track.video_id != video_id:
            raise ValueError("字幕轨道不存在")
        if track.status not in {"pending", "running"}:
            raise ValueError("只有排队中或生成中的字幕任务可以取消")
        if track.task_id:
            self._request_cancel(track.task_id)
        track.status = "canceled"
        track.error_message = message
        db.add(track)
        db.commit()
        db.refresh(track)
        if track.task_id:
            try:
                update_task(db, track.task_id, status="canceled", message="字幕生成已取消")
            except Exception:
                logger.exception("Failed to mark subtitle task canceled task_id=%s", track.task_id)
        return track

    def cancel_running_jobs(self, db: Session, message: str = "字幕生成已取消") -> int:
        tracks = db.scalars(
            select(VideoSubtitleTrack).where(VideoSubtitleTrack.status.in_(("pending", "running")))
        ).all()
        for track in tracks:
            if track.task_id:
                self._request_cancel(track.task_id)
            track.status = "canceled"
            track.error_message = message
            db.add(track)
        db.commit()
        for track in tracks:
            if track.task_id:
                try:
                    update_task(db, track.task_id, status="canceled", message=message)
                except Exception:
                    logger.exception("Failed to cancel subtitle task task_id=%s", track.task_id)
        return len(tracks)

    def generate_for_video(self, video_id: int, task_id: str | None = None) -> None:
        db = SessionLocal()
        track: VideoSubtitleTrack | None = None
        try:
            if task_id:
                self._register_cancel_event(task_id)
                update_task(db, task_id, status="running", message="正在等待视频处理完成", progress=0.05)
            video = self._wait_for_ready_video(db, video_id)
            self._raise_if_cancelled(task_id, db)
            track = self.prepare_track(db, video.id, task_id)
            track.status = "running"
            db.add(track)
            db.commit()
            self._raise_if_cancelled(task_id, db)

            if task_id:
                update_task(db, task_id, message="正在提取音频", progress=0.15)
            with tempfile.TemporaryDirectory(prefix="pictureshow-subtitles-") as temp_dir:
                video_path = Path(temp_dir) / self._safe_temp_name(video.filename)
                audio_path = Path(temp_dir) / "audio.wav"
                self._download_video(video.object_key, video_path)
                self._raise_if_cancelled(task_id, db)
                self._extract_audio(video_path, audio_path)
                self._raise_if_cancelled(task_id, db)

                if task_id:
                    update_task(db, task_id, message="正在等待语音识别模型", progress=0.28)
                segments, source_language = self._transcribe(audio_path, video.id, task_id, db)
                self._raise_if_cancelled(task_id, db)
                if not segments:
                    raise RuntimeError("未识别到语音内容")

                if task_id:
                    update_task(db, task_id, message="正在翻译字幕", progress=0.65)
                translated = self._translate_segments(segments, source_language, db=db, task_id=task_id)
                self._raise_if_cancelled(task_id, db)
                vtt = self.render_webvtt(segments, translated)

            track.content_vtt = vtt
            track.source_language = source_language
            track.provider = self.settings.subtitle_translation_provider
            track.status = "ready"
            track.error_message = None
            track.generated_at = datetime.utcnow()
            db.add(track)
            db.commit()
            if task_id:
                update_task(db, task_id, status="completed", message="中文字幕生成完成", progress=1.0)
        except SubtitleCanceledError:
            db.rollback()
            self._mark_generation_canceled(db, video_id, task_id, track, "用户已取消字幕生成")
        except Exception as exc:
            if self._is_cancelled(task_id, db):
                db.rollback()
                self._mark_generation_canceled(db, video_id, task_id, track, "用户已取消字幕生成")
                return
            logger.exception("Subtitle generation failed video_id=%s task_id=%s", video_id, task_id)
            db.rollback()
            track = track or self._get_track(db, video_id)
            if track is not None:
                track.status = "failed"
                track.error_message = self._user_facing_error(exc)
                db.add(track)
                db.commit()
            if task_id:
                try:
                    update_task(db, task_id, status="failed", message=self._user_facing_error(exc), progress=1.0)
                except Exception:
                    logger.exception("Failed to update subtitle task after generation error task_id=%s", task_id)
        finally:
            if task_id:
                self._clear_cancel_event(task_id)
            db.close()

    def _wait_for_ready_video(self, db: Session, video_id: int) -> VideoItem:
        deadline = time.monotonic() + max(self.settings.video_transcode_timeout_seconds + 60, 300)
        while True:
            db.expire_all()
            video = db.get(VideoItem, video_id)
            if video is None:
                raise RuntimeError("视频不存在")
            if video.status == "ready":
                return video
            if video.status == "processing_failed":
                raise RuntimeError(video.processing_error or "视频处理失败，无法生成字幕")
            if time.monotonic() >= deadline:
                raise RuntimeError("等待视频处理完成超时，请稍后重试")
            time.sleep(5)

    def _get_track(self, db: Session, video_id: int) -> VideoSubtitleTrack | None:
        return db.scalar(
            select(VideoSubtitleTrack).where(
                VideoSubtitleTrack.video_id == video_id,
                VideoSubtitleTrack.language == "zh-CN",
            )
        )

    def _download_video(self, object_key: str, target_path: Path) -> None:
        response = self.storage.get_stream(object_key)
        try:
            with target_path.open("wb") as output:
                for chunk in response.stream(1024 * 1024):
                    output.write(chunk)
        finally:
            response.close()
            response.release_conn()

    def _extract_audio(self, video_path: Path, audio_path: Path) -> None:
        result = subprocess.run(
            [
                self.settings.ffmpeg_path,
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=self.settings.video_transcode_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr or ""
            if "does not contain any stream" in stderr or "audio" in stderr.lower():
                raise RuntimeError("未检测到音轨")
            raise RuntimeError(f"音频提取失败: {stderr[-500:].strip()}")

    def _transcribe(
        self,
        audio_path: Path,
        video_id: int,
        task_id: str | None = None,
        db: Session | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        acquired = False
        try:
            while not acquired:
                self._raise_if_cancelled(task_id, db)
                acquired = self._asr_lock.acquire(timeout=1)
            started = time.monotonic()
            self._raise_if_cancelled(task_id, db)
            if self._asr_model is None:
                self._set_asr_status(
                    status="loading",
                    current_video_id=video_id,
                    current_task_id=task_id,
                    message="正在加载 faster-whisper 模型",
                    last_error=None,
                )
                if db is not None and task_id:
                    update_task(db, task_id, message="正在加载语音识别模型", progress=0.3)
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError("未安装 faster-whisper，请先在 pictureshow 环境中安装 ASR 依赖") from exc
                if not self.settings.subtitle_asr_model_path.exists():
                    raise RuntimeError(f"ASR 模型不存在: {self.settings.subtitle_asr_model_path}")
                self._asr_model = WhisperModel(
                    str(self.settings.subtitle_asr_model_path),
                    device=self.settings.subtitle_asr_device,
                    compute_type=self.settings.subtitle_asr_compute_type,
                )

            self._set_asr_status(
                status="transcribing",
                current_video_id=video_id,
                current_task_id=task_id,
                message="正在识别语音",
                last_error=None,
            )
            if db is not None and task_id:
                update_task(db, task_id, message="正在识别语音", progress=0.35)

            raw_segments, info = self._asr_model.transcribe(str(audio_path), vad_filter=True)
            segments: list[dict[str, Any]] = []
            for raw_segment in raw_segments:
                text = raw_segment.text.strip()
                if not text:
                    continue
                segments.append(
                    {
                        "id": len(segments),
                        "start": float(raw_segment.start),
                        "end": float(raw_segment.end),
                        "text": text,
                    }
                )
            duration = round(time.monotonic() - started, 1)
            source_language = getattr(info, "language", None)
            self._set_asr_status(
                status="ready",
                current_video_id=None,
                current_task_id=None,
                message=f"语音识别完成，共 {len(segments)} 段",
                last_duration_seconds=duration,
                last_language=source_language,
                last_segment_count=len(segments),
                last_error=None,
            )
            return segments, source_language
        except SubtitleCanceledError:
            if acquired:
                self._set_asr_status(
                    status="ready" if self._asr_model is not None else "not_loaded",
                    current_video_id=None,
                    current_task_id=None,
                    message="语音识别已取消",
                    last_error=None,
                )
            raise
        except Exception as exc:
            self._set_asr_status(
                status="error",
                current_video_id=None,
                current_task_id=None,
                message="语音识别失败",
                last_error=self._user_facing_error(exc),
            )
            raise
        finally:
            if acquired:
                self._asr_lock.release()

    def _set_asr_status(self, **changes: Any) -> None:
        with self._asr_status_lock:
            self._asr_status.update(changes)

    def _translate_segments(
        self,
        segments: list[dict[str, Any]],
        source_language: str | None,
        db: Session | None = None,
        task_id: str | None = None,
    ) -> dict[int, str]:
        if self.settings.subtitle_translation_provider != "local_hymt2":
            raise RuntimeError(f"不支持的字幕翻译服务: {self.settings.subtitle_translation_provider}")
        self._raise_if_cancelled(task_id, db)
        self._ensure_translation_server()
        translated: dict[int, str] = {}
        batch_size = max(self.settings.subtitle_batch_size, 1)
        for start in range(0, len(segments), batch_size):
            self._raise_if_cancelled(task_id, db)
            batch = segments[start : start + batch_size]
            translated.update(self._translate_batch_with_retries(batch, source_language))
            self._raise_if_cancelled(task_id, db)
            if db is not None and task_id:
                progress = 0.65 + 0.3 * min(len(translated) / max(len(segments), 1), 1)
                update_task(
                    db,
                    task_id,
                    message=f"正在翻译字幕 {len(translated)}/{len(segments)}",
                    progress=progress,
                )
        missing = [segment["id"] for segment in segments if segment["id"] not in translated]
        if missing:
            raise RuntimeError(f"翻译结果缺少字幕片段: {missing[:5]}")
        return translated

    def _translate_batch_with_retries(
        self,
        batch: list[dict[str, Any]],
        source_language: str | None,
    ) -> dict[int, str]:
        expected_ids = {int(segment["id"]) for segment in batch}
        if len(batch) == 1:
            segment = batch[0]
            text = self._translate_single_segment(segment, source_language).strip()
            return {int(segment["id"]): text} if text else {}

        translated = {
            segment_id: text
            for segment_id, text in self._translate_delimited_batch(batch, source_language).items()
            if segment_id in expected_ids and text.strip()
        }
        missing = [segment for segment in batch if int(segment["id"]) not in translated]
        if not missing:
            return translated

        logger.warning(
            "Subtitle translation batch missed ids=%s; retrying individually",
            [segment["id"] for segment in missing],
        )
        for segment in missing:
            text = self._translate_single_segment(segment, source_language).strip()
            if text:
                translated[int(segment["id"])] = text
        return translated

    def _translate_delimited_batch(self, batch: list[dict[str, Any]], source_language: str | None) -> dict[int, str]:
        delimiter = "<PICTURESHOW_SUBTITLE_BREAK>"
        source_text = f"\n{delimiter}\n".join(str(segment["text"]) for segment in batch)
        prompt = (
            "请将以下文本准确翻译为简体中文。\n"
            f"你必须在译文中保留等量的分隔符 {delimiter}，绝对不可遗漏、转义或翻译该符号。"
            f"输入文本语言为 {source_language or 'auto'}。"
            "只输出翻译后的结果，不要额外解释。\n\n"
            f"{source_text}"
        )
        content = self._chat_completion(prompt, max_tokens=self._translation_max_tokens(batch))
        parts = [part.strip() for part in content.split(delimiter)]
        if len(parts) != len(batch):
            logger.warning(
                "Subtitle translation delimiter split mismatch expected=%s actual=%s",
                len(batch),
                len(parts),
            )
            return {}
        return {
            int(segment["id"]): text
            for segment, text in zip(batch, parts, strict=True)
            if text
        }

    def _translate_single_segment(self, segment: dict[str, Any], source_language: str | None) -> str:
        prompt = (
            "将以下文本翻译为简体中文，注意只需要输出翻译后的结果，不要额外解释：\n\n"
            f"输入文本语言为 {source_language or 'auto'}。\n"
            "待翻译文本：\n"
            f"{segment['text']}"
        )
        return self._chat_completion(prompt, max_tokens=self._translation_max_tokens([segment])).strip()

    def _chat_completion(self, prompt: str, max_tokens: int) -> str:
        body = {
            "model": self.settings.subtitle_translation_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "top_p": 0.6,
            "top_k": 20,
            "repeat_penalty": 1.05,
            "max_tokens": max_tokens,
        }
        payload = self._post_json(f"{self._api_base()}/chat/completions", body)
        return payload["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _translation_max_tokens(batch: list[dict[str, Any]]) -> int:
        source_length = sum(len(str(segment["text"])) for segment in batch)
        return min(max(source_length * 4 + 512, 512), 4096)

    def _ensure_translation_server(self) -> None:
        if self._health_ok():
            return
        server_path = self.settings.subtitle_llama_server_path
        model_path = self.settings.subtitle_translation_model_path
        if server_path is None or not server_path.exists():
            raise RuntimeError("翻译服务不可用，且 SUBTITLE_LLAMA_SERVER_PATH 未配置或路径不存在")
        if not model_path.exists():
            raise RuntimeError(f"翻译模型不存在: {model_path}")

        global _llama_log_handle, _llama_process
        with _llama_lock:
            if self._health_ok():
                return
            if _llama_process is None or _llama_process.poll() is not None:
                args = [
                    str(server_path),
                    "-m",
                    str(model_path),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    self._server_port(),
                    "--ctx-size",
                    str(self.settings.subtitle_llama_server_context_size),
                    "--threads",
                    str(self.settings.subtitle_llama_server_threads),
                    "--device",
                    self.settings.subtitle_llama_server_device,
                    "--gpu-layers",
                    str(self.settings.subtitle_llama_server_gpu_layers),
                    "--no-webui",
                ]
                if not self.settings.subtitle_llama_server_warmup:
                    args.append("--no-warmup")
                log_handle = subprocess.DEVNULL
                log_path = self._llama_log_path()
                if log_path is not None:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    self._close_llama_log_handle()
                    _llama_log_handle = log_path.open("ab")
                    log_handle = _llama_log_handle
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                _llama_process = subprocess.Popen(
                    args,
                    stdout=log_handle,
                    stderr=log_handle,
                    creationflags=creationflags,
                )
                logger.info("Started subtitle translation llama-server pid=%s log=%s", _llama_process.pid, log_path)

        deadline = time.monotonic() + max(self.settings.subtitle_llama_server_startup_timeout_seconds, 30)
        while time.monotonic() < deadline:
            if self._health_ok():
                return
            if _llama_process is not None and _llama_process.poll() is not None:
                raise RuntimeError(self._llama_start_failed_message(_llama_process.returncode))
            time.sleep(2)
        raise RuntimeError(
            f"翻译服务启动超时，请检查 llama-server 和 Hy-MT2 模型配置；日志: {self._llama_log_path() or '未启用'}"
        )

    def _stop_translation_server(self) -> None:
        global _llama_process
        process: subprocess.Popen | None = None
        with _llama_lock:
            if _llama_process is not None and _llama_process.poll() is None:
                process = _llama_process
            _llama_process = None
            self._close_llama_log_handle()

        last_kill_error: str | None = None
        if process is not None:
            if os.name == "nt":
                last_kill_error = self._terminate_pid(int(process.pid))
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            else:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

        deadline = time.monotonic() + 20
        last_pid: int | None = int(process.pid) if process is not None else None
        while True:
            pid = self._pid_for_server_port()
            if pid is not None:
                last_pid = pid
                last_kill_error = self._terminate_pid(pid)

            if not self._health_ok() and self._pid_for_server_port() is None:
                return

            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)

        pid = self._pid_for_server_port()
        if pid is not None:
            last_pid = pid
        if self._health_ok() or pid is not None:
            detail = f"PID {last_pid}" if last_pid is not None else f"端口 {self._server_port()}"
            if last_kill_error:
                detail = f"{detail}，taskkill 返回: {last_kill_error}"
            raise RuntimeError(f"翻译服务关闭后仍在运行（{detail}），请检查 llama-server 进程")

    def _health_ok(self) -> bool:
        try:
            with request.urlopen(f"{self._server_root()}/health", timeout=2) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, timeout=self.settings.subtitle_translation_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError("翻译服务请求失败") from exc

    def _api_base(self) -> str:
        return self.settings.subtitle_translation_base_url.rstrip("/")

    def _server_root(self) -> str:
        base = self._api_base()
        if base.endswith("/v1"):
            return base[:-3]
        return base

    def _server_port(self) -> str:
        root = self._server_root()
        return root.rsplit(":", 1)[-1].split("/", 1)[0]

    def _managed_process_pid(self) -> int | None:
        process = _llama_process
        if process is not None and process.poll() is None:
            return int(process.pid)
        return None

    def _pid_for_server_port(self) -> int | None:
        port = self._server_port()
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP":
                continue
            local_address = parts[1]
            state = parts[3].upper()
            pid = parts[4]
            if state == "LISTENING" and local_address.rsplit(":", 1)[-1] == port and pid.isdigit():
                return int(pid)
        return None

    def _terminate_pid(self, pid: int) -> str | None:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode != 0:
                message = (result.stderr or result.stdout).strip()
                logger.warning("Failed to terminate subtitle llama-server pid=%s: %s", pid, message)
                return message or f"exit code {result.returncode}"
            return None
        try:
            os.kill(pid, 15)
        except OSError:
            return None
        return None

    def _llama_log_path(self) -> Path | None:
        if self.settings.subtitle_llama_server_log_path is not None:
            return self.settings.subtitle_llama_server_log_path
        return self.settings.data_dir / "logs" / "subtitle-llama-server.log"

    @staticmethod
    def _close_llama_log_handle() -> None:
        global _llama_log_handle
        if _llama_log_handle not in (None, subprocess.DEVNULL):
            try:
                _llama_log_handle.close()
            except Exception:
                logger.exception("Failed to close subtitle llama-server log handle")
        _llama_log_handle = None

    def _register_cancel_event(self, task_id: str) -> None:
        with _subtitle_cancel_lock:
            _subtitle_cancel_events.setdefault(task_id, threading.Event())

    def _request_cancel(self, task_id: str) -> None:
        with _subtitle_cancel_lock:
            event = _subtitle_cancel_events.setdefault(task_id, threading.Event())
            event.set()

    def _clear_cancel_event(self, task_id: str) -> None:
        with _subtitle_cancel_lock:
            _subtitle_cancel_events.pop(task_id, None)

    def _is_cancelled(self, task_id: str | None, db: Session | None = None) -> bool:
        if not task_id:
            return False
        with _subtitle_cancel_lock:
            event = _subtitle_cancel_events.get(task_id)
            if event is not None and event.is_set():
                return True
        if db is not None:
            try:
                task = db.get(Task, task_id)
                if task is not None and task.status == "canceled":
                    return True
            except Exception:
                logger.exception("Failed to check subtitle task cancellation task_id=%s", task_id)
        return False

    def _raise_if_cancelled(self, task_id: str | None, db: Session | None = None) -> None:
        if self._is_cancelled(task_id, db):
            raise SubtitleCanceledError("字幕生成已取消")

    def _mark_generation_canceled(
        self,
        db: Session,
        video_id: int,
        task_id: str | None,
        track: VideoSubtitleTrack | None,
        message: str,
    ) -> None:
        track = track or self._get_track(db, video_id)
        if track is not None:
            track.status = "canceled"
            track.error_message = message
            db.add(track)
            db.commit()
        if task_id:
            try:
                update_task(db, task_id, status="canceled", message=message)
            except Exception:
                logger.exception("Failed to update subtitle task after cancellation task_id=%s", task_id)

    def _llama_start_failed_message(self, returncode: int | None) -> str:
        log_path = self._llama_log_path()
        detail = ""
        if log_path is not None and log_path.exists():
            try:
                with log_path.open("rb") as handle:
                    handle.seek(0, os.SEEK_END)
                    size = handle.tell()
                    handle.seek(max(size - 4000, 0), os.SEEK_SET)
                    detail = handle.read().decode("utf-8", errors="ignore").strip()
            except OSError:
                detail = ""
        if detail:
            return f"翻译服务启动失败，llama-server 退出码 {returncode}。日志尾部: {detail[-1000:]}"
        return f"翻译服务启动失败，llama-server 退出码 {returncode}，日志: {log_path or '未启用'}"

    @staticmethod
    def _extract_json_array(content: str) -> str:
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("翻译服务返回内容不是 JSON 数组")
        return content[start : end + 1]

    @staticmethod
    def render_webvtt(segments: list[dict[str, Any]], translated: dict[int, str]) -> str:
        lines = ["WEBVTT", ""]
        for segment in segments:
            text = translated.get(segment["id"], "").strip()
            if not text:
                continue
            lines.append(f"{_format_timestamp(segment['start'])} --> {_format_timestamp(segment['end'])}")
            lines.append(_sanitize_vtt_text(text))
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def validate_webvtt(content: str) -> str:
        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized.startswith("WEBVTT"):
            raise ValueError("字幕必须是 WebVTT 格式，并以 WEBVTT 开头")
        if "-->" not in normalized and normalized != "WEBVTT":
            raise ValueError("WebVTT 字幕至少需要包含一个时间轴片段")
        return f"{normalized}\n"

    @staticmethod
    def _safe_temp_name(filename: str) -> str:
        suffix = Path(filename).suffix or ".video"
        return f"input{suffix}"

    @staticmethod
    def _user_facing_error(exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__


def _format_timestamp(seconds: float) -> str:
    millis = max(round(seconds * 1000), 0)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def _sanitize_vtt_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip())
