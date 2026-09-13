from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
import threading
import time
import subprocess
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.timezones import as_shanghai_naive, shanghai_isoformat, shanghai_now
from app.models import (
    AcquisitionAsset,
    AcquisitionCategory,
    AcquisitionExportJob,
    AcquisitionImportBatch,
    AcquisitionImportBatchItem,
    AcquisitionImportedPhoto,
    AcquisitionRun,
    AcquisitionRunItem,
    AcquisitionScript,
    AcquisitionSimilarityCandidate,
    AcquisitionSource,
    AcquisitionSourceScript,
    AcquisitionSourceItem,
    AcquisitionTelegramHashtag,
    AcquisitionTelegramMessage,
    GalleryPhoto,
    VideoItem,
)
from app.services.importer import PictureService
from app.services.acquisition_adapters import (
    AccessBlockedError,
    LEGACY_SCRIPT_KEYS,
    SCRIPT_REGISTRY,
    RaindropPageAdapter,
    RaindropWorkersAdapter,
    RemoteItem,
    curl_request_bytes,
    get_script,
    is_tls_transport_error,
    script_catalog,
)
from app.services.similarity import (
    DinoV2FeatureExtractor,
    GallerySimilarityScanner,
    PrimaryFaceAssessment,
    PerceptualFeatures,
    assess_primary_face,
    compute_mirrored_perceptual_hashes,
    compute_orb_features,
    compute_perceptual_features,
    compute_perceptual_features_from_image,
    cosine_similarity,
    ensure_perceptual_feature_dependencies,
    hash_similarity,
    open_normalized_image,
    orb_feature_similarity,
)
from app.services.storage import MinioStorage
from app.services.telegram import TelegramService
from app.services.video_processing import extract_video_cover_frame


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PendingRemote:
    remote: RemoteItem
    source_item_id: int
    run_item_id: int


class _HammingBKTree:
    def __init__(self) -> None:
        self.root: tuple[int, list[int], dict[int, object]] | None = None

    @staticmethod
    def _distance(left: int, right: int) -> int:
        return (left ^ right).bit_count()

    def add(self, hash_value: str, identifier: int) -> None:
        value = int(hash_value, 16)
        if self.root is None:
            self.root = (value, [identifier], {})
            return
        node = self.root
        while True:
            node_value, identifiers, children = node
            distance = self._distance(value, node_value)
            if distance == 0:
                identifiers.append(identifier)
                return
            child = children.get(distance)
            if child is None:
                children[distance] = (value, [identifier], {})
                return
            node = child  # type: ignore[assignment]

    def query(self, hash_value: str, max_distance: int) -> set[int]:
        if self.root is None:
            return set()
        value = int(hash_value, 16)
        matches: set[int] = set()
        pending = [self.root]
        while pending:
            node_value, identifiers, children = pending.pop()
            distance = self._distance(value, node_value)
            if distance <= max_distance:
                matches.update(identifiers)
            minimum = distance - max_distance
            maximum = distance + max_distance
            pending.extend(
                child for edge_distance, child in children.items()
                if minimum <= edge_distance <= maximum
            )
        return matches


class _DownloadStartLimiter:
    def __init__(
        self,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval_seconds = max(0.0, float(interval_seconds))
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait(self, abort_event: threading.Event | None = None) -> None:
        with self._lock:
            if abort_event is not None and abort_event.is_set():
                raise CancelledError()
            delay = max(0.0, self._next_start - self._clock())
            if delay:
                if abort_event is not None:
                    if abort_event.wait(delay):
                        raise CancelledError()
                else:
                    self._sleeper(delay)
            if abort_event is not None and abort_event.is_set():
                raise CancelledError()
            self._next_start = self._clock() + self.interval_seconds


@dataclass
class _DownloadPolicyContext:
    limiter: _DownloadStartLimiter
    abort_event: threading.Event
    reserved_start: bool = True


@dataclass(frozen=True)
class DownloadedRemote:
    payload: bytes
    content_type: str | None
    resolved_url: str
    resolved_candidate: str
    filename: str
    media_type: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    blur_score: float | None
    quality_warnings: tuple[str, ...]
    sha256: str
    perceptual_phash: str | None
    perceptual_dhash: str | None
    quality_score: float | None


class AcquisitionService:
    """独立的采集工作流；站点适配器不接触数据库或对象存储。"""

    terminal_source_statuses = {
        "pending_review",
        "imported",
        "rejected",
        "gallery_duplicate",
        "ignored_video",
        "import_queued",
        "importing",
        "import_failed",
        "ignored_protected",
    }

    def __init__(
        self,
        storage: MinioStorage,
        pictures: PictureService,
        settings: Settings | None = None,
        similarity_extractor: DinoV2FeatureExtractor | None = None,
        similarity_scanner: GallerySimilarityScanner | None = None,
        face_service: object | None = None,
        video_service: object | None = None,
    ) -> None:
        self.storage = storage
        self.pictures = pictures
        self.settings = settings or get_settings()
        self._download_policy = threading.local()
        self.similarity_scanner = similarity_scanner
        self.face_service = face_service
        self.video_service = video_service
        self._run_abort_events: dict[str, threading.Event] = {}
        self._run_abort_lock = threading.Lock()
        self.similarity_extractor = similarity_extractor or (
            similarity_scanner.extractor if similarity_scanner is not None else DinoV2FeatureExtractor(self.settings)
        )

    @staticmethod
    def scripts() -> list[dict[str, object]]:
        return script_catalog()

    def create_source(
        self,
        db: Session,
        workspace_id: int | None,
        name: str,
        base_url: str | None = None,
        notes: str | None = None,
        script_key: str | None = None,
    ) -> AcquisitionSource:
        selected_script = (script_key or "").strip() or None
        definition = get_script(selected_script) if selected_script else None
        if selected_script and definition is None:
            raise ValueError("采集脚本不存在或未注册")
        if definition and definition.key == "telegram-channel-mtproto":
            resolved_url = "https://t.me"
        else:
            if not (base_url or "").strip():
                raise ValueError("网站 URL 不能为空")
            self._validate_http_url(str(base_url), "网站 URL")
            resolved_url = str(base_url).strip()
        source = AcquisitionSource(
            workspace_id=workspace_id,
            name=name.strip(),
            adapter_key="",
            base_url=resolved_url,
            notes=(notes or "").strip() or None,
        )
        db.add(source)
        db.flush()
        if definition is not None:
            self.bind_script(db, source, definition.key, commit=False)
        db.commit()
        db.refresh(source)
        return source

    def update_source(self, db: Session, source: AcquisitionSource, **values: object) -> AcquisitionSource:
        if "base_url" in values and values["base_url"] is not None:
            self._validate_http_url(str(values["base_url"]), "网站 URL")
        for field in ("name", "base_url", "notes", "enabled"):
            if field in values and values[field] is not None:
                setattr(source, field, values[field])
        db.commit()
        db.refresh(source)
        return source

    @staticmethod
    def _validate_http_url(value: str, label: str) -> None:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label}必须是完整的 http(s) 地址")

    def bind_script(
        self,
        db: Session,
        source: AcquisitionSource,
        script_key: str,
        default_parameters: dict[str, object] | None = None,
        *,
        commit: bool = True,
    ) -> AcquisitionSourceScript:
        definition = get_script(script_key)
        if definition is None:
            raise ValueError("采集脚本不存在或未注册")
        if source.page_format_key and source.page_format_key != definition.page_format_key:
            raise ValueError("该脚本的网页格式与站点已绑定脚本不一致")
        parameters = definition.validate_parameters(default_parameters)
        binding = db.scalar(
            select(AcquisitionSourceScript).where(
                AcquisitionSourceScript.source_id == source.id,
                AcquisitionSourceScript.script_key == definition.key,
            )
        )
        if binding is None:
            binding = AcquisitionSourceScript(source_id=source.id, script_key=definition.key)
            db.add(binding)
        binding.enabled = True
        binding.default_parameters_json = json.dumps(parameters, ensure_ascii=False)
        source.page_format_key = definition.page_format_key
        if commit:
            db.commit()
            db.refresh(binding)
        else:
            db.flush()
        return binding

    def unbind_script(self, db: Session, source: AcquisitionSource, script_key: str) -> None:
        binding = db.scalar(
            select(AcquisitionSourceScript).where(
                AcquisitionSourceScript.source_id == source.id,
                AcquisitionSourceScript.script_key == script_key,
            )
        )
        if binding is None:
            raise ValueError("站点未绑定该脚本")
        db.delete(binding)
        db.flush()
        remaining = db.scalar(select(AcquisitionSourceScript).where(AcquisitionSourceScript.source_id == source.id))
        if remaining is None:
            source.page_format_key = None
        db.commit()

    def create_category(
        self,
        db: Session,
        source: AcquisitionSource,
        name: str,
        crawl_url: str,
        notes: str | None = None,
        **telegram_values: object,
    ) -> AcquisitionCategory:
        self._validate_category_url(source, crawl_url)
        category = AcquisitionCategory(
            source_id=source.id,
            parent_id=None,
            name=name.strip(),
            path=name.strip(),
            crawl_url=crawl_url.strip(),
            notes=(notes or "").strip() or None,
            telegram_peer_id=telegram_values.get("telegram_peer_id"),
            telegram_entity_type=telegram_values.get("telegram_entity_type"),
            telegram_username=telegram_values.get("telegram_username"),
            telegram_topic_id=telegram_values.get("telegram_topic_id"),
            telegram_topic_title=telegram_values.get("telegram_topic_title"),
            telegram_source_mode=str(telegram_values.get("telegram_source_mode") or "manual"),
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        return category

    def update_category(self, db: Session, category: AcquisitionCategory, **values: object) -> AcquisitionCategory:
        if "crawl_url" in values and values["crawl_url"] is not None:
            source = db.get(AcquisitionSource, category.source_id)
            if source is None:
                raise ValueError("分类所属站点不存在")
            self._validate_category_url(source, str(values["crawl_url"]))
        for field in ("name", "crawl_url", "notes", "enabled", "telegram_peer_id", "telegram_entity_type", "telegram_username", "telegram_topic_id", "telegram_topic_title", "telegram_source_mode"):
            if field in values and values[field] is not None:
                setattr(category, field, values[field])
        if "name" in values and values["name"] is not None:
            category.path = str(values["name"])
        db.commit()
        db.refresh(category)
        return category

    def _validate_category_url(self, source: AcquisitionSource, crawl_url: str) -> None:
        if source.page_format_key == "telegram-channel-v1":
            if not crawl_url.strip():
                raise ValueError("Telegram 频道不能为空")
            return
        self._validate_http_url(crawl_url, "分类 URL")
        source_host = (urlparse(source.base_url or "").hostname or "").lower()
        category_host = (urlparse(crawl_url.strip()).hostname or "").lower()
        if not source_host or source_host != category_host:
            raise ValueError("分类 URL 必须属于当前站点的主机名")

    def start_run(
        self,
        db: Session,
        workspace_id: int | None,
        category: AcquisitionCategory,
        script_key: str,
        mode: str,
        parameters: dict[str, object] | None = None,
    ) -> AcquisitionRun:
        if mode not in {"incremental", "full", "verify"}:
            raise ValueError("采集模式必须为 incremental、full 或 verify")
        source = db.get(AcquisitionSource, category.source_id)
        if source is None or source.workspace_id != workspace_id or not source.enabled or not category.enabled:
            raise ValueError("采集站点或分类不可用")
        definition = get_script(script_key)
        if definition is None:
            raise ValueError("采集脚本不存在或未注册")
        binding = db.scalar(
            select(AcquisitionSourceScript).where(
                AcquisitionSourceScript.source_id == source.id,
                AcquisitionSourceScript.script_key == definition.key,
                AcquisitionSourceScript.enabled.is_(True),
            )
        )
        if binding is None:
            raise ValueError("该脚本未绑定到分类所属站点")
        if source.page_format_key != definition.page_format_key:
            raise ValueError("脚本网页格式与站点不一致")
        default_parameters = json.loads(binding.default_parameters_json or "{}")
        requested_parameters = dict(parameters or {})
        legacy_default_force = self._pop_legacy_force_full_scan(default_parameters)
        legacy_requested_force = self._pop_legacy_force_full_scan(requested_parameters)
        defaults = definition.validate_parameters(default_parameters)
        validated_parameters = definition.validate_parameters({**defaults, **requested_parameters})
        legacy_force = legacy_requested_force if legacy_requested_force is not None else legacy_default_force
        if legacy_force and mode == "incremental":
            mode = "full"
        active = db.scalar(
            select(AcquisitionRun).where(
                AcquisitionRun.category_id == category.id,
                AcquisitionRun.status.in_(("pending", "running")),
            )
        )
        if active is not None:
            raise ValueError("该分类已有正在运行的采集任务")
        try:
            ensure_perceptual_feature_dependencies()
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        run = AcquisitionRun(
            id=uuid4().hex,
            workspace_id=workspace_id,
            source_id=source.id,
            category_id=category.id,
            script_key=definition.key,
            script_name_snapshot=definition.name,
            script_version_snapshot=definition.version,
            source_name_snapshot=source.name,
            category_name_snapshot=category.name,
            category_url_snapshot=category.crawl_url,
            parameters_json=json.dumps(validated_parameters, ensure_ascii=False),
            mode=mode,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @staticmethod
    def _pop_legacy_force_full_scan(parameters: dict[str, object]) -> bool | None:
        if "force_full_scan" not in parameters:
            return None
        value = parameters.pop("force_full_scan")
        if not isinstance(value, bool):
            raise ValueError("旧参数“强制扫描全部指定页面”必须是布尔值")
        return value

    def _download(
        self,
        url: str,
        referer: str,
        abort_on_access_block: bool = False,
    ) -> tuple[bytes, str | None]:
        request = Request(
            url,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,video/*,*/*;q=0.8",
                "Referer": referer,
                "User-Agent": "PictureShow acquisition/1.0",
            },
        )
        last_error: Exception | None = None
        for _ in range(self.settings.acquisition_download_retries):
            try:
                self._wait_for_download_start()
                with urlopen(request, timeout=self.settings.acquisition_download_timeout_seconds) as response:
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > self.settings.acquisition_max_file_bytes:
                        raise ValueError("文件超过下载大小上限")
                    chunks: list[bytes] = []
                    size = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self.settings.acquisition_max_file_bytes:
                            raise ValueError("文件超过下载大小上限")
                        chunks.append(chunk)
                    return b"".join(chunks), response.headers.get_content_type()
            except HTTPError as exc:
                if abort_on_access_block and exc.code in {403, 429}:
                    raise AccessBlockedError(url, exc.code) from exc
                last_error = exc
            except Exception as exc:  # noqa: PERF203 - 保留最后一次远端错误
                last_error = exc
                if is_tls_transport_error(exc):
                    try:
                        return curl_request_bytes(
                            url,
                            "image/avif,image/webp,image/apng,image/*,video/*,*/*;q=0.8",
                            referer,
                            self.settings.acquisition_download_timeout_seconds,
                            self.settings.acquisition_max_file_bytes,
                            self.settings.acquisition_download_retries,
                            abort_on_access_block=abort_on_access_block,
                            before_attempt=self._wait_for_download_start,
                        )
                    except AccessBlockedError:
                        raise
                    except Exception as fallback_exc:
                        last_error = fallback_exc
                        break
        raise RuntimeError(str(last_error or "下载失败"))

    def _wait_for_download_start(self) -> None:
        policy: _DownloadPolicyContext | None = getattr(self._download_policy, "context", None)
        if policy is None:
            return
        if policy.reserved_start:
            policy.reserved_start = False
            return
        policy.limiter.wait(policy.abort_event)

    def _download_remote(self, remote: RemoteItem, referer: str) -> tuple[bytes, str | None, str]:
        candidates = list(remote.candidate_urls or (remote.source_url,))
        errors: list[str] = []
        index = 0
        while index < len(candidates):
            candidate = candidates[index]
            index += 1
            try:
                payload, content_type = self._download(candidate, referer, remote.abort_on_access_block)
                if "/get_cache_url?" in candidate:
                    cache_payload = json.loads(payload.decode("utf-8"))
                    cache_url = str(cache_payload.get("url") or "").strip()
                    if cache_url and cache_url not in candidates:
                        candidates.insert(index, cache_url)
                    continue
                expected_prefix = "video/" if remote.media_type == "video" else "image/"
                content_type_lower = (content_type or "").lower()
                if content_type and not content_type_lower.startswith(expected_prefix) and not (
                    remote.media_type == "video" and content_type_lower == "application/octet-stream"
                ):
                    errors.append(f"{candidate}: 返回类型 {content_type}")
                    continue
                return payload, content_type, candidate
            except AccessBlockedError:
                if remote.abort_on_access_block:
                    raise
                errors.append(f"{candidate}: 站点拒绝访问")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
        raise RuntimeError("；".join(errors) or "没有可下载的图片地址")

    def _download_and_analyze(self, remote: RemoteItem, referer: str) -> DownloadedRemote:
        result = self._download_remote(remote, referer)
        if len(result) == 2:  # 兼容测试和第三方扩展中的旧下载器实现。
            payload, content_type = result
            resolved_url = remote.source_url
        else:
            payload, content_type, resolved_url = result
        filename = Path(urlparse(resolved_url).path).name or Path(urlparse(remote.source_url).path).name
        media_type = remote.media_type
        content_type = (content_type or "").lower()
        if media_type == "image":
            width, height, blur, warnings, features = self._analyze_image_payload(payload)
            duration = None
            perceptual_phash = features.phash
            perceptual_dhash = features.dhash
            quality_score = features.quality_score
        else:
            suffix = Path(filename).suffix.lower()
            if not content_type.startswith("video/") and suffix not in {".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".ts", ".webm", ".wmv"}:
                raise RuntimeError(f"{resolved_url}: 返回内容不是视频")
            duration = width = height = None
            blur = None
            warnings = []
            perceptual_phash = None
            perceptual_dhash = None
            quality_score = None
        if resolved_url == remote.source_url or (remote.candidate_urls and resolved_url == remote.candidate_urls[0]):
            candidate = "source"
        elif remote.preview_url and resolved_url == remote.preview_url:
            candidate = "preview"
        else:
            candidate = "cache"
        return DownloadedRemote(
            payload=payload,
            content_type=content_type,
            resolved_url=resolved_url,
            resolved_candidate=candidate,
            filename=filename or f"{remote.external_key}{'.mp4' if media_type == 'video' else '.img'}",
            media_type=media_type,
            width=width,
            height=height,
            duration_seconds=duration,
            blur_score=blur,
            quality_warnings=tuple(warnings),
            sha256=hashlib.sha256(payload).hexdigest(),
            perceptual_phash=perceptual_phash,
            perceptual_dhash=perceptual_dhash,
            quality_score=quality_score,
        )

    def _quality(self, payload: bytes) -> tuple[int, int, float, list[str]]:
        image = open_normalized_image(payload)
        try:
            return self._quality_image(image)
        finally:
            image.close()

    def _quality_image(self, image: Image.Image) -> tuple[int, int, float, list[str]]:
        width, height = image.size
        grey = np.asarray(image.convert("L"), dtype=np.float32)
        blur = float(np.var(np.diff(grey, axis=0))) if grey.shape[0] > 1 else 0.0
        warnings: list[str] = []
        if width * height < self.settings.acquisition_quality_min_pixels:
            warnings.append("像素较低")
        if min(width, height) and max(width, height) / min(width, height) > self.settings.acquisition_quality_max_aspect_ratio:
            warnings.append("宽高比极端")
        if blur < self.settings.acquisition_quality_blur_threshold:
            warnings.append("可能模糊")
        return width, height, blur, warnings

    def _analyze_image_payload(self, payload: bytes) -> tuple[int, int, float, list[str], PerceptualFeatures]:
        """一次解码完成审核质量和相似图特征，避免每张图重复读取像素。"""
        image = open_normalized_image(payload)
        try:
            width, height, blur, warnings = self._quality_image(image)
            features = compute_perceptual_features_from_image(image)
            return width, height, blur, warnings, features
        finally:
            image.close()

    def _asset_key(self, workspace_id: int | None, asset_id: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".bin"
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}acquisition/assets/{asset_id}{suffix}"

    @staticmethod
    def _has_completed_full_scan(db: Session, category_id: int, script_key: str) -> bool:
        return db.scalar(
            select(AcquisitionRun.id).where(
                AcquisitionRun.category_id == category_id,
                AcquisitionRun.script_key == script_key,
                AcquisitionRun.status == "completed",
                AcquisitionRun.scan_start_page == 1,
                AcquisitionRun.reached_collection_end.is_(True),
                AcquisitionRun.error_count == 0,
            )
        ) is not None

    def stop_run(self, run_id: str) -> bool:
        """请求停止正在运行的采集任务。返回该任务是否仍在运行并已发出停止信号。"""
        with self._run_abort_lock:
            event = self._run_abort_events.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    def process_run(self, db: Session, run_id: str) -> None:
        run = db.get(AcquisitionRun, run_id)
        if run is None:
            return
        source = db.get(AcquisitionSource, run.source_id)
        category = db.get(AcquisitionCategory, run.category_id)
        if source is None or category is None:
            run.status = "failed"
            run.error_message = "采集站点或分类已被删除"
            db.commit()
            return
        definition = get_script(run.script_key or "")
        if definition is None:
            run.status = "failed"
            run.error_message = "运行所使用的采集脚本不可用"
            db.commit()
            return
        try:
            parameters = json.loads(run.parameters_json or "{}")
        except (TypeError, json.JSONDecodeError):
            parameters = {}
        if definition.key == "telegram-channel-mtproto":
            self._process_telegram_run(db, run, source, category, parameters)
            return
        has_failed_sources = db.scalar(
            select(AcquisitionSourceItem.id).where(
                AcquisitionSourceItem.category_id == category.id,
                AcquisitionSourceItem.script_key == definition.key,
                AcquisitionSourceItem.status == "failed",
            )
        ) is not None
        known_external_keys: set[str] = set()
        if run.mode == "incremental" and not has_failed_sources and self._has_completed_full_scan(db, category.id, definition.key):
            known_external_keys = set(
                db.scalars(
                    select(AcquisitionSourceItem.remote_external_key).where(
                        AcquisitionSourceItem.category_id == category.id,
                        AcquisitionSourceItem.script_key == definition.key,
                        AcquisitionSourceItem.remote_external_key.is_not(None),
                    )
                ).all()
            )
        run.status = "running"
        run.started_at = shanghai_now()
        run.scan_start_page = int(parameters.get("start_page") or 1)
        run.scan_end_page = None
        run.reached_collection_end = False
        run.stop_reason = None
        db.commit()
        try:
            referer = run.category_url_snapshot or category.crawl_url
            workers = max(1, int(getattr(self.settings, "acquisition_download_workers", 6)))
            if definition.max_download_workers is not None:
                workers = min(workers, max(1, definition.max_download_workers))
            limiter = _DownloadStartLimiter(definition.download_start_interval_seconds)
            abort_event = threading.Event()
            with self._run_abort_lock:
                self._run_abort_events[run_id] = abort_event
            try:
                def download(prepared: PendingRemote) -> DownloadedRemote:
                    limiter.wait(abort_event)
                    item_referer = prepared.remote.referer_url or referer
                    self._download_policy.context = _DownloadPolicyContext(limiter, abort_event)
                    try:
                        return self._download_and_analyze(prepared.remote, item_referer)
                    finally:
                        del self._download_policy.context

                stopped = False
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="acquisition-download") as executor:
                    for page in definition.adapter.enumerate_pages(referer, parameters, known_external_keys, run.mode == "incremental"):
                        if abort_event.is_set():
                            stopped = True
                            break
                        run.scan_end_page = page.page_number
                        pending = [prepared for remote in page.items if (prepared := self._prepare_remote_item(db, run, source, category, remote)) is not None]
                        futures = {executor.submit(download, prepared): prepared for prepared in pending}
                        for future in as_completed(futures):
                            prepared = futures[future]
                            try:
                                self._persist_downloaded_remote(db, run.id, prepared, future.result())
                            except CancelledError:
                                abort_event.set()
                                stopped = True
                                break
                            except AccessBlockedError as exc:
                                self._record_remote_failure(db, run.id, prepared, exc)
                                abort_event.set()
                                for pending_future in futures:
                                    if pending_future is not future:
                                        pending_future.cancel()
                                raise
                            except Exception as exc:
                                self._record_remote_failure(db, run.id, prepared, exc)
                        run = db.get(AcquisitionRun, run_id)
                        if run is None:
                            return
                        if page.stop_reason is not None:
                            run.stop_reason = page.stop_reason
                            run.reached_collection_end = page.reached_collection_end
                        db.commit()
                if stopped:
                    run = db.get(AcquisitionRun, run_id)
                    if run is None:
                        return
                    run.status = "interrupted"
                    run.stop_reason = "requested_end"
                else:
                    run.status = "completed"
                run.completed_at = shanghai_now()
            finally:
                with self._run_abort_lock:
                    self._run_abort_events.pop(run_id, None)
        except Exception as exc:
            db.rollback()
            run = db.get(AcquisitionRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = shanghai_now()
        db.commit()

    def _process_telegram_run(
        self,
        db: Session,
        run: AcquisitionRun,
        source: AcquisitionSource,
        category: AcquisitionCategory,
        parameters: dict[str, object],
    ) -> None:
        from app.models import TelegramAccount

        account = db.scalar(select(TelegramAccount).where(TelegramAccount.workspace_id == run.workspace_id))
        if account is None or account.status != "active" or not account.session_encrypted:
            run.status = "failed"
            run.error_message = "当前工作区 Telegram 账号不可用"
            run.completed_at = shanghai_now()
            db.commit()
            return
        run.status = "running"
        run.started_at = shanghai_now()
        run.scan_start_page = 1
        run.scan_end_page = None
        run.error_message = None
        db.commit()
        temporary_root = self.settings.data_dir / "acquisition" / "telegram-tmp" / run.id
        persisted = 0

        def persist_batch(batch: list[dict[str, object]]) -> None:
            nonlocal persisted
            for record in batch:
                persisted += 1
                run.scan_end_page = persisted
                self._persist_telegram_record(db, run, source, category, record)
                path = record.get("path")
                if isinstance(path, Path) and path.is_file():
                    path.unlink(missing_ok=True)

        try:
            parameters = dict(parameters)
            if category.telegram_username:
                parameters.setdefault("username", category.telegram_username)
            if category.telegram_peer_id:
                parameters.setdefault("peer_id", category.telegram_peer_id)
            if category.telegram_topic_id is not None:
                parameters.setdefault("topic_id", category.telegram_topic_id)
            if category.telegram_entity_type in {"bot", "group"}:
                parameters["collect_comments"] = False
            TelegramService(self.settings).read_channel_media(
                account,
                category.crawl_url,
                parameters,
                temporary_root,
                on_records=persist_batch,
            )
            run.status = "completed"
            run.reached_collection_end = True
            run.stop_reason = "collection_end"
            run.completed_at = shanghai_now()
            db.commit()
        except Exception as exc:
            db.rollback()
            run = db.get(AcquisitionRun, run.id)
            if run is not None:
                run.status = "failed"
                run.error_message = str(exc)
                run.completed_at = shanghai_now()
                db.commit()
        finally:
            if temporary_root.exists():
                for path in temporary_root.rglob("*"):
                    if path.is_file():
                        path.unlink(missing_ok=True)
                try:
                    temporary_root.rmdir()
                    temporary_root.parent.rmdir()
                except OSError:
                    pass

    def _persist_telegram_record(
        self,
        db: Session,
        run: AcquisitionRun,
        source: AcquisitionSource,
        category: AcquisitionCategory,
        record: dict[str, object],
    ) -> None:
        external_key = str(record["external_key"])
        scoped_key = _stable_key(f"{category.id}:{run.script_key}:{external_key}")
        source_item = db.scalar(select(AcquisitionSourceItem).where(
            AcquisitionSourceItem.source_id == source.id, AcquisitionSourceItem.external_key == scoped_key
        ))
        if source_item is None:
            source_item = AcquisitionSourceItem(
                source_id=source.id, category_id=category.id, script_key=run.script_key,
                external_key=scoped_key, remote_external_key=external_key,
                source_url=str(record["source_url"]), title=str(record.get("caption") or "")[:512] or None,
            )
            db.add(source_item)
            db.flush()
        run_item = AcquisitionRunItem(run_id=run.id, source_item_id=source_item.id)
        db.add(run_item)
        run.total_count += 1
        metadata = db.scalar(select(AcquisitionTelegramMessage).where(AcquisitionTelegramMessage.source_item_id == source_item.id))
        if metadata is None:
            metadata = AcquisitionTelegramMessage(
                workspace_id=run.workspace_id or 0, source_item_id=source_item.id,
                channel_id=str(record["channel_id"]), channel_title=record.get("channel_title"),
                channel_username=record.get("channel_username"), message_id=int(record["message_id"]),
                grouped_id=record.get("grouped_id"), media_type=str(record["media_type"]),
                peer_id=record.get("peer_id"), entity_type=record.get("entity_type"),
                sender_id=record.get("sender_id"), sender_username=record.get("sender_username"),
                sender_is_bot=bool(record.get("sender_is_bot")),
                reply_to_message_id=record.get("reply_to_message_id"), topic_id=record.get("topic_id"),
                topic_title=record.get("topic_title"), is_comment=bool(record.get("is_comment")),
                root_channel_message_id=record.get("root_channel_message_id"),
            )
            db.add(metadata)
            db.flush()
        metadata.published_at = record.get("published_at")
        metadata.edited_at = record.get("edited_at")
        metadata.caption = record.get("caption")
        metadata.message_url = str(record["source_url"])
        metadata.protected_content = bool(record.get("protected_content"))
        metadata.peer_id = record.get("peer_id")
        metadata.entity_type = record.get("entity_type")
        metadata.sender_id = record.get("sender_id")
        metadata.sender_username = record.get("sender_username")
        metadata.sender_is_bot = bool(record.get("sender_is_bot"))
        metadata.reply_to_message_id = record.get("reply_to_message_id")
        metadata.topic_id = record.get("topic_id")
        metadata.topic_title = record.get("topic_title")
        metadata.is_comment = bool(record.get("is_comment"))
        metadata.root_channel_message_id = record.get("root_channel_message_id")
        db.query(AcquisitionTelegramHashtag).filter(AcquisitionTelegramHashtag.telegram_message_id == metadata.id).delete()
        for raw, normalized in record.get("hashtags", []):
            db.add(AcquisitionTelegramHashtag(telegram_message_id=metadata.id, tag_raw=raw, tag_normalized=normalized))
        if record.get("protected_content"):
            source_item.status = "ignored_protected"
            source_item.last_error = "频道限制保存内容"
            run_item.status = "ignored_protected"
            run_item.collection_outcome = "ignored"
            run.ignored_count += 1
            db.commit()
            return
        path = record.get("path")
        if not isinstance(path, Path) or not path.is_file():
            raise RuntimeError("Telegram 媒体临时文件不存在")
        payload = path.read_bytes()
        sha256 = hashlib.sha256(payload).hexdigest()
        media_type = str(record["media_type"])
        content_type = mimetypes.guess_type(path.name)[0] or ("image/jpeg" if media_type == "image" else "video/mp4")
        if self._mark_library_duplicate_if_exists(db, run, source_item, run_item, sha256, media_type):
            return
        asset = db.scalar(select(AcquisitionAsset).where(
            AcquisitionAsset.workspace_id == run.workspace_id, AcquisitionAsset.sha256 == sha256
        ))
        if asset is None:
            asset_id = uuid4().hex
            object_key = self._asset_key(run.workspace_id, asset_id, path.name)
            self.storage.put_bytes(object_key, payload, content_type)
            width = height = None
            blur = None
            phash = dhash = None
            quality = None
            warnings: list[str] = []
            duration = None
            if media_type == "image":
                width, height, blur, warnings, features = self._analyze_image_payload(payload)
                phash, dhash, quality = features.phash, features.dhash, features.quality_score
            else:
                duration = record.get("duration_seconds")
                width = record.get("width")
                height = record.get("height")
            asset = AcquisitionAsset(
                id=asset_id, workspace_id=run.workspace_id, sha256=sha256, filename=path.name,
                content_type=content_type, media_type=media_type, object_key=object_key, size_bytes=len(payload),
                width=width, height=height, duration_seconds=duration, blur_score=blur,
                perceptual_phash=phash, perceptual_dhash=dhash, quality_score=quality,
                quality_warnings=json.dumps(warnings, ensure_ascii=False),
            )
            db.add(asset)
            run.downloaded_count += 1
            run.candidate_count += 1
            run_item.collection_outcome = "candidate"
        elif asset.status in {"rejected", "imported", "gallery_duplicate"} or not asset.object_key:
            run.content_duplicate_count += 1
            run_item.collection_outcome = "content_duplicate"
            run_item.asset_id = asset.id
            run_item.status = asset.status
            source_item.status = asset.status
            db.commit()
            return
        else:
            run.content_duplicate_count += 1
            run_item.collection_outcome = "content_duplicate"
        run_item.asset_id = asset.id
        run_item.status = "pending_review"
        source_item.status = "pending_review"
        source_item.last_error = None
        db.commit()

    def _probe_video_file(self, path: Path) -> tuple[float | None, int | None, int | None]:
        command = [self.settings.ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
            result = json.loads(completed.stdout)
            stream = next((item for item in result.get("streams", []) if item.get("codec_type") == "video"), {})
            duration = float(result.get("format", {}).get("duration")) if result.get("format", {}).get("duration") else None
            return duration, stream.get("width"), stream.get("height")
        except Exception:
            return None, None, None

    def _prepare_remote_item(
        self,
        db: Session,
        run: AcquisitionRun,
        source: AcquisitionSource,
        category: AcquisitionCategory,
        remote: RemoteItem,
    ) -> PendingRemote | None:
        now = shanghai_now()
        scoped_external_key = _stable_key(f"{category.id}:{run.script_key}:{remote.external_key}")
        item = db.scalar(
            select(AcquisitionSourceItem).where(
                AcquisitionSourceItem.source_id == source.id,
                AcquisitionSourceItem.external_key == scoped_external_key,
            )
        )
        if item is None:
            item = AcquisitionSourceItem(
                source_id=source.id,
                category_id=category.id,
                script_key=run.script_key,
                external_key=scoped_external_key,
                remote_external_key=remote.external_key,
                source_url=remote.source_url,
                preview_url=remote.preview_url,
                title=remote.title,
            )
            db.add(item)
            db.flush()
        else:
            item.category_id = category.id
            item.script_key = run.script_key
            item.remote_external_key = remote.external_key
            item.source_url = remote.source_url
            item.preview_url = remote.preview_url
            item.title = remote.title
            item.last_seen_at = now
        existing_run_item = db.scalar(
            select(AcquisitionRunItem).where(
                AcquisitionRunItem.run_id == run.id,
                AcquisitionRunItem.source_item_id == item.id,
            )
        )
        if existing_run_item is not None:
            db.commit()
            return None
        run.total_count += 1
        run_item = AcquisitionRunItem(run_id=run.id, source_item_id=item.id)
        db.add(run_item)
        # 先保存运行条目检查点，使后续下载失败也能可靠回滚并记录原因。
        db.commit()
        if remote.ignored_reason:
            item.status = "ignored_video"
            item.last_error = remote.ignored_reason
            run_item.status = "ignored_video"
            run_item.collection_outcome = "ignored"
            run.ignored_count += 1
            db.commit()
            return None
        if run.mode != "verify" and item.status in self.terminal_source_statuses:
            run_item.status = "skipped"
            run_item.collection_outcome = "source_skipped"
            run.skipped_count += 1
            db.commit()
            return None
        return PendingRemote(remote=remote, source_item_id=item.id, run_item_id=run_item.id)

    @staticmethod
    def _normalized_image_difference(left_payload: bytes, right_payload: bytes) -> float:
        left = open_normalized_image(left_payload).resize((64, 64), Image.Resampling.LANCZOS)
        right = open_normalized_image(right_payload).resize((64, 64), Image.Resampling.LANCZOS)
        try:
            left_array = np.asarray(left, dtype=np.float32)
            right_array = np.asarray(right, dtype=np.float32)
            return float(np.mean(np.abs(left_array - right_array)) / 255.0)
        finally:
            left.close()
            right.close()

    def _find_resolution_variant(
        self,
        db: Session,
        run: AcquisitionRun,
        downloaded: DownloadedRemote,
    ) -> AcquisitionAsset | None:
        candidates = db.scalars(
            select(AcquisitionAsset).where(
                AcquisitionAsset.workspace_id == run.workspace_id,
                AcquisitionAsset.media_type == "image",
                AcquisitionAsset.status == "pending_review",
                AcquisitionAsset.object_key.is_not(None),
                AcquisitionAsset.perceptual_phash.is_not(None),
                AcquisitionAsset.perceptual_dhash.is_not(None),
                AcquisitionAsset.sha256 != downloaded.sha256,
            )
        ).all()
        matches: list[AcquisitionAsset] = []
        incoming_ratio = downloaded.width / max(downloaded.height, 1)
        for candidate in candidates:
            if not candidate.width or not candidate.height or not candidate.object_key:
                continue
            candidate_ratio = candidate.width / candidate.height
            if abs(incoming_ratio - candidate_ratio) / max(incoming_ratio, candidate_ratio) > 0.01:
                continue
            if hash_similarity(candidate.perceptual_phash or "", downloaded.perceptual_phash) < 0.9375:
                continue
            if hash_similarity(candidate.perceptual_dhash or "", downloaded.perceptual_dhash) < 0.9375:
                continue
            try:
                existing_payload = self.storage.get_bytes(candidate.object_key)
                difference = self._normalized_image_difference(downloaded.payload, existing_payload)
            except Exception:
                continue
            if difference <= 8 / 255:
                matches.append(candidate)
        return max(
            matches,
            key=lambda asset: (
                int(asset.width or 0) * int(asset.height or 0),
                float(asset.quality_score or 0),
                int(asset.size_bytes or 0),
            ),
            default=None,
        )

    @staticmethod
    def _asset_rank(width: int, height: int, quality_score: float, size_bytes: int) -> tuple[int, float, int]:
        return width * height, quality_score, size_bytes

    def _create_asset(self, run: AcquisitionRun, downloaded: DownloadedRemote) -> AcquisitionAsset:
        asset_id = uuid4().hex
        object_key = self._asset_key(run.workspace_id, asset_id, downloaded.filename)
        self.storage.put_bytes(object_key, downloaded.payload, downloaded.content_type)
        return AcquisitionAsset(
            id=asset_id,
            workspace_id=run.workspace_id,
            sha256=downloaded.sha256,
            filename=downloaded.filename,
            content_type=downloaded.content_type or mimetypes.guess_type(downloaded.filename)[0],
            media_type=downloaded.media_type,
            object_key=object_key,
            size_bytes=len(downloaded.payload),
            width=downloaded.width,
            height=downloaded.height,
            duration_seconds=downloaded.duration_seconds,
            blur_score=downloaded.blur_score,
            perceptual_phash=downloaded.perceptual_phash,
            perceptual_dhash=downloaded.perceptual_dhash,
            quality_score=downloaded.quality_score,
            quality_warnings=json.dumps(downloaded.quality_warnings, ensure_ascii=False),
        )

    def _persist_downloaded_remote(
        self,
        db: Session,
        run_id: str,
        prepared: PendingRemote,
        downloaded: DownloadedRemote,
    ) -> None:
        run = db.get(AcquisitionRun, run_id)
        item = db.get(AcquisitionSourceItem, prepared.source_item_id)
        run_item = db.get(AcquisitionRunItem, prepared.run_item_id)
        if run is None or item is None or run_item is None:
            raise RuntimeError("采集运行条目检查点丢失")
        run_item.resolved_url = downloaded.resolved_url
        run_item.resolved_candidate = downloaded.resolved_candidate
        run.download_success_count += 1
        object_to_remove: str | None = None
        try:
            if self._mark_library_duplicate_if_exists(db, run, item, run_item, downloaded.sha256, downloaded.media_type):
                return
            asset = db.scalar(
                select(AcquisitionAsset).where(
                    AcquisitionAsset.workspace_id == run.workspace_id,
                    AcquisitionAsset.sha256 == downloaded.sha256,
                )
            )
            if asset is None:
                variant = self._find_resolution_variant(db, run, downloaded) if downloaded.media_type == "image" else None
                if variant is not None:
                    incoming_rank = self._asset_rank(
                        downloaded.width, downloaded.height, downloaded.quality_score, len(downloaded.payload)
                    )
                    existing_rank = self._asset_rank(
                        int(variant.width or 0), int(variant.height or 0), float(variant.quality_score or 0), int(variant.size_bytes)
                    )
                    if incoming_rank <= existing_rank:
                        run_item.asset_id = variant.id
                        run_item.status = "pending_review"
                        run_item.collection_outcome = "resolution_duplicate"
                        item.status = "pending_review"
                        item.last_error = None
                        item.failed_at = None
                        run.resolution_duplicate_count += 1
                        db.commit()
                        return
                    asset = self._create_asset(run, downloaded)
                    db.add(asset)
                    db.flush()
                    for linked_item in db.scalars(
                        select(AcquisitionRunItem).where(AcquisitionRunItem.asset_id == variant.id)
                    ).all():
                        linked_item.asset_id = asset.id
                    object_to_remove = variant.object_key
                    db.delete(variant)
                    run.resolution_upgrade_count += 1
                else:
                    asset = self._create_asset(run, downloaded)
                db.add(asset)
                run.downloaded_count += 1
                run.candidate_count += 1
                run_item.collection_outcome = "candidate"
            elif asset.status in {"rejected", "imported", "gallery_duplicate"} or not asset.object_key:
                run_item.asset_id = asset.id
                run_item.status = asset.status
                run_item.collection_outcome = "content_duplicate"
                item.status = asset.status
                run.content_duplicate_count += 1
                db.commit()
                return
            else:
                run.content_duplicate_count += 1
                run_item.collection_outcome = "content_duplicate"
            run_item.asset_id = asset.id
            run_item.status = "pending_review"
            item.status = "pending_review"
            item.last_error = None
            item.failed_at = None
            db.commit()
        except Exception:
            db.rollback()
            raise
        if object_to_remove:
            try:
                self.storage.remove_object(object_to_remove)
            except Exception:
                pass

    def _record_remote_failure(
        self,
        db: Session,
        run_id: str,
        prepared: PendingRemote,
        exc: Exception,
    ) -> None:
        db.rollback()
        run = db.get(AcquisitionRun, run_id)
        item = db.get(AcquisitionSourceItem, prepared.source_item_id)
        run_item = db.get(AcquisitionRunItem, prepared.run_item_id)
        if run is None or item is None or run_item is None:
            raise RuntimeError("采集运行条目检查点丢失") from exc
        item.status = "failed"
        item.last_error = str(exc)
        item.failed_at = shanghai_now()
        run_item.status = "failed"
        run_item.collection_outcome = "failed"
        run_item.error_message = str(exc)
        run.error_count += 1
        db.commit()

    def _process_remote_item(
        self,
        db: Session,
        run: AcquisitionRun,
        source: AcquisitionSource,
        category: AcquisitionCategory,
        remote: RemoteItem,
    ) -> None:
        prepared = self._prepare_remote_item(db, run, source, category, remote)
        if prepared is None:
            return
        try:
            downloaded = self._download_and_analyze(remote, run.category_url_snapshot or category.crawl_url)
            self._persist_downloaded_remote(db, run.id, prepared, downloaded)
        except Exception as exc:
            self._record_remote_failure(db, run.id, prepared, exc)

    def reject_assets(self, db: Session, workspace_id: int | None, asset_ids: list[str]) -> int:
        assets = db.scalars(
            select(AcquisitionAsset).where(AcquisitionAsset.workspace_id == workspace_id, AcquisitionAsset.id.in_(asset_ids))
        ).all()
        if not assets:
            return 0
        asset_ids = [asset.id for asset in assets]
        run_items = db.scalars(
            select(AcquisitionRunItem).where(AcquisitionRunItem.asset_id.in_(asset_ids))
        ).all()
        source_item_ids = {item.source_item_id for item in run_items}
        source_items = {
            item.id: item
            for item in db.scalars(select(AcquisitionSourceItem).where(AcquisitionSourceItem.id.in_(source_item_ids))).all()
        }
        for asset in assets:
            if asset.object_key:
                self.storage.remove_object(asset.object_key)
            asset.object_key = None
            asset.status = "rejected"
        for run_item in run_items:
            run_item.status = "rejected"
            source_item = source_items.get(run_item.source_item_id)
            if source_item is not None:
                source_item.status = "rejected"
        db.commit()
        return len(assets)

    def create_import_batch(
        self,
        db: Session,
        workspace_id: int | None,
        asset_ids: list[str],
        *,
        is_rich_text: bool = False,
    ) -> AcquisitionImportBatch:
        ordered_ids = list(dict.fromkeys(asset_ids))
        if len(ordered_ids) != len(asset_ids):
            raise ValueError("入库选择中包含重复图片")
        assets = db.scalars(
            select(AcquisitionAsset).where(
                AcquisitionAsset.workspace_id == workspace_id,
                AcquisitionAsset.id.in_(ordered_ids),
            )
        ).all()
        asset_by_id = {asset.id: asset for asset in assets}
        unavailable = [
            asset_id
            for asset_id in ordered_ids
            if asset_id not in asset_by_id
            or asset_by_id[asset_id].status not in {"pending_review", "import_failed"}
            or not asset_by_id[asset_id].object_key
        ]
        if unavailable:
            raise ValueError(f"有 {len(unavailable)} 张图片已不在可入库状态，请刷新后重试")
        batch = AcquisitionImportBatch(
            id=uuid4().hex,
            workspace_id=workspace_id,
            status="queued",
            is_rich_text=is_rich_text,
            total_count=len(ordered_ids),
        )
        db.add(batch)
        for ordinal, asset_id in enumerate(ordered_ids):
            db.add(AcquisitionImportBatchItem(
                batch_id=batch.id, asset_id=asset_id, ordinal=ordinal,
                target_type="video" if asset_by_id[asset_id].media_type == "video" else "image",
            ))
            asset_by_id[asset_id].status = "import_queued"
            asset_by_id[asset_id].error_message = None
        db.commit()
        db.refresh(batch)
        return batch

    def process_import_batch(self, db: Session, batch_id: str) -> None:
        batch = db.get(AcquisitionImportBatch, batch_id)
        if batch is None or batch.status not in {"queued", "running"}:
            return
        batch.status = "running"
        batch.started_at = batch.started_at or shanghai_now()
        db.commit()
        item_ids = list(
            db.scalars(
                select(AcquisitionImportBatchItem.id)
                .where(AcquisitionImportBatchItem.batch_id == batch_id)
                .order_by(AcquisitionImportBatchItem.ordinal.asc())
            ).all()
        )
        for item_id in item_ids:
            item = db.get(AcquisitionImportBatchItem, item_id)
            if item is None or item.status in {"imported", "gallery_duplicate"}:
                continue
            asset = db.get(AcquisitionAsset, item.asset_id)
            try:
                if asset is None or not asset.object_key:
                    raise RuntimeError("采集临时图片不存在")
                item.status = "processing"
                item.attempt_count += 1
                item.error_message = None
                asset.status = "importing"
                asset.error_message = None
                if item.target_type == "video":
                    if self.video_service is None:
                        raise RuntimeError("视频导入服务不可用")
                    existing_video = db.scalar(
                        select(VideoItem).where(
                            VideoItem.workspace_id == batch.workspace_id,
                            VideoItem.sha256 == asset.sha256,
                        )
                    )
                    if existing_video is not None:
                        item.promotion_intent = "gallery_duplicate"
                        self._finish_video_duplicate(db, item, asset, existing_video)
                        self._refresh_import_batch(db, batch_id)
                        db.commit()
                        self._cleanup_asset_object(db, asset)
                        continue
                    metadata = db.scalar(select(AcquisitionTelegramMessage).join(
                        AcquisitionSourceItem, AcquisitionTelegramMessage.source_item_id == AcquisitionSourceItem.id
                    ).join(AcquisitionRunItem, AcquisitionRunItem.source_item_id == AcquisitionSourceItem.id).where(
                        AcquisitionRunItem.asset_id == asset.id
                    ))
                    video = self.video_service.import_acquisition_asset(
                        db, asset, batch.workspace_id, metadata.caption if metadata else None
                    )
                    item.video_id = video.id
                    item.status = "imported"
                    item.error_message = None
                    asset.status = "imported"
                    self._set_linked_item_statuses(db, asset, "imported")
                    self._refresh_import_batch(db, batch_id)
                    db.commit()
                    self._cleanup_asset_object(db, asset)
                    continue
                gallery_photo = self._gallery_photo_by_sha(
                    db,
                    batch.workspace_id,
                    asset.sha256,
                    is_rich_text=batch.is_rich_text,
                )
                if gallery_photo is not None:
                    item.promotion_intent = "gallery_duplicate"
                    self._finish_gallery_duplicate(db, item, asset, gallery_photo)
                    self._refresh_import_batch(db, batch_id)
                    db.commit()
                    self._cleanup_asset_object(db, asset)
                    continue
                item.promotion_intent = "new"
                db.commit()
                payload = self.storage.get_bytes(asset.object_key)
                photo, summary = self.pictures.import_gallery_photo(
                    db,
                    asset.filename,
                    payload,
                    asset.content_type,
                    workspace_id=batch.workspace_id,
                    source_object_key=asset.object_key,
                    ingest_source="acquisition",
                    is_rich_text=batch.is_rich_text,
                )
                if summary.duplicated:
                    self._finish_gallery_duplicate(db, item, asset, photo)
                else:
                    self._finish_imported(db, item, asset, photo)
                self._refresh_import_batch(db, batch_id)
                db.commit()
                self._cleanup_asset_object(db, asset)
            except Exception as exc:
                db.rollback()
                item = db.get(AcquisitionImportBatchItem, item_id)
                asset = db.get(AcquisitionAsset, item.asset_id) if item is not None else None
                batch = db.get(AcquisitionImportBatch, batch_id)
                gallery_photo = self._gallery_photo_by_sha(
                    db,
                    batch.workspace_id,
                    asset.sha256,
                    is_rich_text=batch.is_rich_text,
                ) if batch and asset else None
                if item is not None and asset is not None and item.promotion_intent == "new" and gallery_photo is not None:
                    self._finish_imported(db, item, asset, gallery_photo)
                elif item is not None:
                    item.status = "failed"
                    item.error_message = str(exc)
                    if asset is not None:
                        asset.status = "import_failed"
                        asset.error_message = str(exc)
                        self._set_linked_item_statuses(db, asset, "import_failed")
                self._refresh_import_batch(db, batch_id)
                db.commit()
                if item is not None and asset is not None and item.status in {"imported", "gallery_duplicate"}:
                    self._cleanup_asset_object(db, asset)
        batch = db.get(AcquisitionImportBatch, batch_id)
        if batch is not None:
            self._refresh_import_batch(db, batch_id, finish=True)
            db.commit()

    def import_assets(
        self,
        db: Session,
        workspace_id: int | None,
        asset_ids: list[str],
        *,
        is_rich_text: bool = False,
    ) -> dict[str, int]:
        """兼容内部调用；新的 API 会先持久化批次再交给后台处理。"""
        batch = self.create_import_batch(db, workspace_id, asset_ids, is_rich_text=is_rich_text)
        self.process_import_batch(db, batch.id)
        db.refresh(batch)
        return {"imported": batch.imported_count, "duplicates": batch.duplicate_count}

    @staticmethod
    def _gallery_photo_by_sha(
        db: Session,
        workspace_id: int | None,
        sha256: str,
        *,
        is_rich_text: bool = False,
    ) -> GalleryPhoto | None:
        return db.scalar(
            select(GalleryPhoto).where(
                GalleryPhoto.workspace_id == workspace_id,
                GalleryPhoto.sha256 == sha256,
                GalleryPhoto.is_rich_text.is_(is_rich_text),
            )
        )

    @staticmethod
    def _existing_library_item(
        db: Session,
        workspace_id: int | None,
        sha256: str,
        media_type: str,
    ) -> GalleryPhoto | VideoItem | None:
        if media_type == "video":
            return db.scalar(
                select(VideoItem).where(
                    VideoItem.workspace_id == workspace_id,
                    VideoItem.sha256 == sha256,
                )
            )
        return db.scalar(
            select(GalleryPhoto).where(
                GalleryPhoto.workspace_id == workspace_id,
                GalleryPhoto.sha256 == sha256,
                GalleryPhoto.is_rich_text.is_(False),
            )
        )

    def _mark_library_duplicate_if_exists(
        self,
        db: Session,
        run: AcquisitionRun,
        item: AcquisitionSourceItem,
        run_item: AcquisitionRunItem,
        sha256: str,
        media_type: str,
    ) -> bool:
        if self._existing_library_item(db, run.workspace_id, sha256, media_type) is None:
            return False
        asset = db.scalar(
            select(AcquisitionAsset).where(
                AcquisitionAsset.workspace_id == run.workspace_id,
                AcquisitionAsset.sha256 == sha256,
            )
        )
        if asset is not None:
            run_item.asset_id = asset.id
            self._mark_asset_gallery_duplicate(db, asset)
        item.status = "gallery_duplicate"
        run_item.status = "gallery_duplicate"
        run_item.collection_outcome = "gallery_duplicate"
        run.gallery_duplicate_count += 1
        db.commit()
        return True

    def _set_linked_item_statuses(self, db: Session, asset: AcquisitionAsset, status: str) -> None:
        for run_item in db.scalars(select(AcquisitionRunItem).where(AcquisitionRunItem.asset_id == asset.id)).all():
            run_item.status = status
            source_item = db.get(AcquisitionSourceItem, run_item.source_item_id)
            if source_item is not None:
                source_item.status = status

    def _record_import_provenance(self, db: Session, asset: AcquisitionAsset, photo: GalleryPhoto) -> None:
        run_items = db.scalars(
            select(AcquisitionRunItem).where(AcquisitionRunItem.asset_id == asset.id)
        ).all()
        for run_item in run_items:
            run_item.status = "imported"
            source_item = db.get(AcquisitionSourceItem, run_item.source_item_id)
            if source_item is not None:
                source_item.status = "imported"

        run_ids = list(dict.fromkeys(run_item.run_id for run_item in run_items))
        if not run_ids:
            return
        existing_keys = set(
            db.execute(
                select(AcquisitionImportedPhoto.run_id, AcquisitionImportedPhoto.asset_id).where(
                    AcquisitionImportedPhoto.run_id.in_(run_ids),
                    AcquisitionImportedPhoto.asset_id == asset.id,
                )
            ).all()
        )
        existing_keys.update(
            (entry.run_id, entry.asset_id)
            for entry in db.new
            if isinstance(entry, AcquisitionImportedPhoto)
        )
        for run_id in run_ids:
            key = (run_id, asset.id)
            if key in existing_keys:
                continue
            run = db.get(AcquisitionRun, run_id)
            category = db.get(AcquisitionCategory, run.category_id) if run else None
            if run is None:
                continue
            db.add(
                AcquisitionImportedPhoto(
                    run_id=run.id,
                    asset_id=asset.id,
                    gallery_photo_id=photo.id,
                    gallery_photo_snapshot_id=photo.id,
                    filename_snapshot=photo.filename,
                    sha256_snapshot=photo.sha256,
                    category_path_snapshot=category.name if category else "",
                )
            )
            existing_keys.add(key)
            run.imported_count += 1

    def _finish_imported(
        self,
        db: Session,
        item: AcquisitionImportBatchItem | None,
        asset: AcquisitionAsset,
        photo: GalleryPhoto,
    ) -> None:
        self._record_import_provenance(db, asset, photo)
        asset.status = "imported"
        asset.error_message = None
        if item is not None:
            item.status = "imported"
            item.gallery_photo_id = photo.id
            item.error_message = None

    def _mark_asset_gallery_duplicate(self, db: Session, asset: AcquisitionAsset) -> None:
        if asset.status == "imported":
            return
        self._set_linked_item_statuses(db, asset, "gallery_duplicate")
        asset.status = "gallery_duplicate"
        asset.error_message = None
        self._cleanup_asset_object(db, asset, commit=False)

    def _finish_gallery_duplicate(
        self,
        db: Session,
        item: AcquisitionImportBatchItem,
        asset: AcquisitionAsset,
        photo: GalleryPhoto,
    ) -> None:
        self._set_linked_item_statuses(db, asset, "gallery_duplicate")
        asset.status = "gallery_duplicate"
        asset.error_message = None
        item.status = "gallery_duplicate"
        item.gallery_photo_id = photo.id
        item.error_message = None

    def _finish_video_duplicate(
        self,
        db: Session,
        item: AcquisitionImportBatchItem,
        asset: AcquisitionAsset,
        video: VideoItem,
    ) -> None:
        self._set_linked_item_statuses(db, asset, "gallery_duplicate")
        asset.status = "gallery_duplicate"
        asset.error_message = None
        item.status = "gallery_duplicate"
        item.video_id = video.id
        item.error_message = None

    def _preview_key(self, workspace_id: int | None, asset_id: str) -> str:
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}acquisition/previews/{asset_id}.jpg"

    def ensure_video_preview(self, db: Session, asset: AcquisitionAsset) -> bytes | None:
        if asset.preview_object_key:
            try:
                return self.storage.get_bytes(asset.preview_object_key)
            except Exception:
                asset.preview_object_key = None
        if asset.media_type != "video" or not asset.object_key:
            return None
        suffix = Path(asset.filename).suffix.lower() or ".mp4"
        try:
            with tempfile.TemporaryDirectory(prefix="acq-preview-") as temp_dir:
                input_path = Path(temp_dir) / f"input{suffix}"
                output_path = Path(temp_dir) / "cover.jpg"
                input_path.write_bytes(self.storage.get_bytes(asset.object_key))
                extracted = extract_video_cover_frame(
                    self.settings.ffmpeg_path,
                    input_path,
                    output_path,
                    capture_at=float(getattr(self.settings, "video_cover_capture_seconds", 1.0)),
                    duration_seconds=asset.duration_seconds,
                )
                if not extracted:
                    return None
                cover = output_path.read_bytes()
            key = self._preview_key(asset.workspace_id, asset.id)
            self.storage.put_bytes(key, cover, "image/jpeg")
            asset.preview_object_key = key
            db.commit()
            return cover
        except Exception:
            db.rollback()
            return None

    def _cleanup_asset_object(self, db: Session, asset: AcquisitionAsset, commit: bool = True) -> None:
        pending_error: str | None = None
        if asset.object_key:
            try:
                self.storage.remove_object(asset.object_key)
            except Exception as exc:
                pending_error = f"临时文件待清理：{exc}"
            else:
                asset.object_key = None
        if asset.preview_object_key:
            try:
                self.storage.remove_object(asset.preview_object_key)
            except Exception:
                pass
            else:
                asset.preview_object_key = None
        if pending_error:
            asset.error_message = pending_error
        if commit:
            db.commit()

    @staticmethod
    def _refresh_import_batch(db: Session, batch_id: str, finish: bool = False) -> None:
        batch = db.get(AcquisitionImportBatch, batch_id)
        if batch is None:
            return
        statuses = list(
            db.scalars(
                select(AcquisitionImportBatchItem.status).where(AcquisitionImportBatchItem.batch_id == batch_id)
            ).all()
        )
        batch.imported_count = statuses.count("imported")
        batch.duplicate_count = statuses.count("gallery_duplicate")
        batch.failed_count = statuses.count("failed")
        batch.processed_count = batch.imported_count + batch.duplicate_count + batch.failed_count
        if finish or batch.processed_count >= batch.total_count:
            batch.status = "completed_with_errors" if batch.failed_count else "completed"
            batch.completed_at = shanghai_now()

    def scan_similarity(
        self,
        db: Session,
        workspace_id: int | None,
        scan_task_id: str | None = None,
        progress: Callable[[float, str], None] | None = None,
        *,
        scan_type: str = "normal",
        scope: str = "pending_only",
    ) -> int:
        # 扫描由用户手动触发，只创建人工审核提示，不会自动删除或合并图片。
        if scan_type not in {"normal", "mirror"}:
            raise ValueError("不支持的相似检查类型")
        if scope not in {"pending_only", "pending_to_gallery"}:
            raise ValueError("不支持的相似检查范围")
        assets = db.scalars(
            select(AcquisitionAsset).where(
                AcquisitionAsset.workspace_id == workspace_id,
                AcquisitionAsset.media_type == "image",
                AcquisitionAsset.status == "pending_review",
                AcquisitionAsset.object_key.is_not(None),
            )
            .order_by(AcquisitionAsset.created_at.asc(), AcquisitionAsset.id.asc())
        ).all()
        asset_payloads: dict[str, bytes] = {}
        fingerprints: dict[str, object] = {}
        mirror_hashes: dict[str, tuple[str, str]] = {}
        asset_count = len(assets)
        if progress:
            progress(0.05, f"准备扫描 {asset_count} 张待审核图片")
        for index, asset in enumerate(assets):
            try:
                payload = self.storage.get_bytes(asset.object_key or "")
                asset_payloads[asset.id] = payload
                perceptual = compute_perceptual_features(payload)
                fingerprints[asset.id] = perceptual
                asset.blur_score = getattr(perceptual, "blur_score", asset.blur_score)
                asset.quality_score = getattr(perceptual, "quality_score", asset.quality_score)
                asset.quality_version = getattr(
                    self.settings,
                    "gallery_similarity_quality_version",
                    "technical-quality-v2",
                )
                asset.resolution_score = getattr(perceptual, "resolution_score", asset.resolution_score)
                asset.sharpness_score = getattr(perceptual, "sharpness_score", asset.sharpness_score)
                asset.artifact_score = getattr(perceptual, "artifact_score", asset.artifact_score)
                asset.exposure_score = getattr(perceptual, "exposure_score", asset.exposure_score)
                primary_face = PrimaryFaceAssessment(None, None, False)
                if self.face_service is not None:
                    try:
                        detections = self.face_service.detect_faces(payload)  # type: ignore[attr-defined]
                        primary_face = assess_primary_face(payload, detections, self.settings)
                    except Exception:
                        primary_face = PrimaryFaceAssessment(None, None, False)
                asset.primary_face_quality_score = primary_face.quality_score
                asset.primary_face_embedding = primary_face.embedding
                asset.primary_face_dominant = primary_face.dominant
                db.add(asset)
                if scan_type == "mirror":
                    mirror_hashes[asset.id] = compute_mirrored_perceptual_hashes(payload)
            except Exception:
                continue
            if progress and (index % 5 == 0 or index + 1 == asset_count):
                progress(0.05 + 0.3 * (index + 1) / max(1, asset_count), f"读取图片 {index + 1}/{asset_count}")
        asset_vectors = self._encode_similarity_vectors(asset_payloads) if scan_type == "normal" else {}
        candidates: list[AcquisitionSimilarityCandidate] = []
        orb_cache: dict[tuple[str, bool], object] = {}

        def asset_orb(asset_id: str, *, mirrored: bool = False):
            key = (asset_id, mirrored)
            if key not in orb_cache:
                orb_cache[key] = compute_orb_features(asset_payloads[asset_id], mirrored=mirrored)
            return orb_cache[key]

        def perceptual_score(left, right_phash: str, right_dhash: str) -> float:
            return (
                hash_similarity(left.phash, right_phash)
                + hash_similarity(left.dhash, right_dhash)
            ) / 2

        def promoted_near_score(base_score: float, left_orb, right_orb) -> float:
            if base_score < 0.82:
                return base_score
            local_score = orb_feature_similarity(left_orb, right_orb)
            return max(base_score, min(1.0, 0.85 + local_score * 0.15))

        if scope == "pending_only":
            comparable_assets = [asset for asset in assets if asset.id in fingerprints]
            pair_total = len(comparable_assets) * (len(comparable_assets) - 1) // 2
            compared = 0
            for index, asset in enumerate(comparable_assets):
                left = fingerprints[asset.id]
                for other in comparable_assets[index + 1 :]:
                    right = fingerprints[other.id]
                    direct_base = perceptual_score(left, right.phash, right.dhash)
                    direct_score = promoted_near_score(
                        direct_base,
                        asset_orb(asset.id),
                        asset_orb(other.id),
                    )
                    relation_type = "near_duplicate"
                    score = direct_score
                    accepted = direct_score >= self.settings.gallery_similarity_near_threshold
                    if scan_type == "mirror":
                        mirror_phash, mirror_dhash = mirror_hashes[other.id]
                        mirror_base = perceptual_score(left, mirror_phash, mirror_dhash)
                        score = promoted_near_score(
                            mirror_base,
                            asset_orb(asset.id),
                            asset_orb(other.id, mirrored=True),
                        )
                        accepted = (
                            score >= self.settings.gallery_similarity_near_threshold
                            and score > direct_score
                        )
                    elif not accepted:
                        vector_score = cosine_similarity(asset_vectors[asset.id], asset_vectors[other.id])
                        if vector_score >= self.settings.gallery_similarity_scene_threshold:
                            score = vector_score
                            relation_type = "same_scene"
                            accepted = True
                    if accepted:
                        candidates.append(AcquisitionSimilarityCandidate(
                            workspace_id=workspace_id,
                            scan_task_id=scan_task_id,
                            scan_type=scan_type,
                            scan_scope=scope,
                            relation_type=relation_type,
                            asset_id=asset.id,
                            other_asset_id=other.id,
                            score=score,
                        ))
                    compared += 1
                    if progress and (compared % 100 == 0 or compared == pair_total):
                        progress(0.45 + 0.5 * compared / max(1, pair_total), f"比对图片 {compared}/{pair_total}")
        else:
            gallery_photos = {
                photo.id: photo
                for photo in db.scalars(
                    select(GalleryPhoto).where(GalleryPhoto.workspace_id == workspace_id)
                ).all()
            }
            gallery_features, _ = self.similarity_scanner.ensure_features(
                db,
                gallery_photos,
                progress,
                include_vectors=scan_type == "normal",
            )
            hash_index = _HammingBKTree()
            for photo_id, feature in gallery_features.items():
                indexed_hash = feature.mirror_phash if scan_type == "mirror" else feature.phash
                if indexed_hash:
                    hash_index.add(indexed_hash, photo_id)
            gallery_orb_cache: dict[tuple[int, bool], object] = {}

            def gallery_orb(photo_id: int, *, mirrored: bool = False):
                key = (photo_id, mirrored)
                if key not in gallery_orb_cache:
                    gallery_orb_cache[key] = compute_orb_features(
                        self.storage.get_bytes(gallery_photos[photo_id].object_key),
                        mirrored=mirrored,
                    )
                return gallery_orb_cache[key]

            valid_assets = [asset for asset in assets if asset.id in fingerprints]
            for index, asset in enumerate(valid_assets):
                left = fingerprints[asset.id]
                scored_gallery: dict[int, tuple[float, str]] = {}
                for photo_id in hash_index.query(left.phash, 23):
                    right = gallery_features[photo_id]
                    direct_base = perceptual_score(left, right.phash, right.dhash)
                    direct_score = promoted_near_score(
                        direct_base,
                        asset_orb(asset.id),
                        gallery_orb(photo_id),
                    )
                    if scan_type == "mirror":
                        if not right.mirror_phash or not right.mirror_dhash:
                            continue
                        mirror_base = perceptual_score(left, right.mirror_phash, right.mirror_dhash)
                        score = promoted_near_score(
                            mirror_base,
                            asset_orb(asset.id),
                            gallery_orb(photo_id, mirrored=True),
                        )
                        if score >= self.settings.gallery_similarity_near_threshold and score > direct_score:
                            scored_gallery[photo_id] = (score, "near_duplicate")
                    elif direct_score >= self.settings.gallery_similarity_near_threshold:
                        scored_gallery[photo_id] = (direct_score, "near_duplicate")
                if scan_type == "normal":
                    for photo_id, vector_score in self.similarity_scanner.vector_store.search_gallery_similarity(
                        workspace_id=workspace_id,
                        feature_version=self.settings.gallery_similarity_model_version,
                        vector=asset_vectors[asset.id],
                        score_threshold=self.settings.gallery_similarity_scene_threshold,
                        limit=500,
                    ):
                        if photo_id not in gallery_photos:
                            continue
                        current = scored_gallery.get(photo_id)
                        if current is None:
                            scored_gallery[photo_id] = (vector_score, "same_scene")
                for photo_id, (score, relation_type) in scored_gallery.items():
                    candidates.append(AcquisitionSimilarityCandidate(
                        workspace_id=workspace_id,
                        scan_task_id=scan_task_id,
                        scan_type=scan_type,
                        scan_scope=scope,
                        relation_type=relation_type,
                        asset_id=asset.id,
                        gallery_photo_id=photo_id,
                        score=score,
                    ))
                if progress:
                    progress(
                        0.55 + 0.4 * (index + 1) / max(1, len(valid_assets)),
                        f"联查图库 {index + 1}/{len(valid_assets)}",
                    )
        db.query(AcquisitionSimilarityCandidate).filter(
            AcquisitionSimilarityCandidate.workspace_id == workspace_id,
            AcquisitionSimilarityCandidate.scan_type == scan_type,
            AcquisitionSimilarityCandidate.scan_scope == scope,
        ).delete(synchronize_session=False)
        db.add_all(candidates)
        db.commit()
        return len(candidates)

    def _encode_similarity_vectors(self, payloads: dict[object, bytes]) -> dict[object, np.ndarray]:
        vectors: dict[object, np.ndarray] = {}
        identifiers = list(payloads)
        batch_size = max(1, self.settings.gallery_similarity_batch_size)
        for offset in range(0, len(identifiers), batch_size):
            batch_ids = identifiers[offset : offset + batch_size]
            images = [open_normalized_image(payloads[identifier], max_edge=1024) for identifier in batch_ids]
            try:
                batch_vectors = self.similarity_extractor.encode(images)
            finally:
                for image in images:
                    image.close()
            for identifier, vector in zip(batch_ids, batch_vectors, strict=True):
                vectors[identifier] = vector
        return vectors

    def create_export_job(self, db: Session, workspace_id: int | None, filters: dict[str, object]) -> AcquisitionExportJob:
        job = AcquisitionExportJob(id=uuid4().hex, workspace_id=workspace_id, filters_json=json.dumps(filters, ensure_ascii=False))
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def build_export(self, db: Session, job_id: str) -> None:
        job = db.get(AcquisitionExportJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()
        try:
            filters = json.loads(job.filters_json)
            query = (
                select(AcquisitionImportedPhoto, AcquisitionRun, AcquisitionCategory, GalleryPhoto)
                .join(AcquisitionRun, AcquisitionRun.id == AcquisitionImportedPhoto.run_id)
                .join(AcquisitionCategory, AcquisitionCategory.id == AcquisitionRun.category_id)
                .outerjoin(GalleryPhoto, GalleryPhoto.id == AcquisitionImportedPhoto.gallery_photo_id)
                .where(AcquisitionRun.workspace_id == job.workspace_id)
            )
            if filters.get("run_id"):
                query = query.where(AcquisitionRun.id == str(filters["run_id"]))
            if filters.get("source_id"):
                query = query.where(AcquisitionRun.source_id == int(filters["source_id"]))
            if filters.get("category_id"):
                query = query.where(AcquisitionRun.category_id == int(filters["category_id"]))
            if filters.get("date_from"):
                date_from = as_shanghai_naive(datetime.fromisoformat(str(filters["date_from"])))
                query = query.where(AcquisitionImportedPhoto.created_at >= date_from)
            if filters.get("date_to"):
                date_to = as_shanghai_naive(datetime.fromisoformat(str(filters["date_to"])))
                query = query.where(AcquisitionImportedPhoto.created_at <= date_to)
            rows = db.execute(query.order_by(AcquisitionImportedPhoto.created_at.asc())).all()
            unique_rows = []
            seen_asset_ids: set[str] = set()
            for row in rows:
                history = row[0]
                if history.asset_id in seen_asset_ids:
                    continue
                seen_asset_ids.add(history.asset_id)
                unique_rows.append(row)
            rows = unique_rows
            temp_root = self.settings.data_dir / "tmp" / "acquisition-exports"
            temp_root.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_name = tempfile.mkstemp(prefix=f"{job.id}-", suffix=".zip", dir=temp_root)
            os.close(temp_fd)
            temp_path = Path(temp_name)
            missing: list[dict[str, object]] = []
            exported_items: list[dict[str, object]] = []
            exported = 0
            try:
                with ZipFile(temp_path, "w", ZIP_DEFLATED, allowZip64=True) as archive:
                    for history, run, category, photo in rows:
                        if photo is None:
                            missing.append({"run_id": run.id, "gallery_photo_id": history.gallery_photo_snapshot_id, "filename": history.filename_snapshot})
                            continue
                        target_name = f"images/{photo.id}_{Path(photo.filename).name}"
                        response = self.storage.get_stream(photo.object_key)
                        try:
                            with archive.open(target_name, "w") as target:
                                while chunk := response.read(1024 * 1024):
                                    target.write(chunk)
                            exported_items.append(
                                {
                                    "run_id": run.id,
                                    "category_path": category.name,
                                    "gallery_photo_id": photo.id,
                                    "filename": photo.filename,
                                    "sha256": photo.sha256,
                                    "archive_path": target_name,
                                }
                            )
                            exported += 1
                        finally:
                            response.close()
                            response.release_conn()
                    archive.writestr(
                        "metadata.json",
                        json.dumps(
                            {
                                "created_at": shanghai_isoformat(shanghai_now()),
                                "filters": filters,
                                "exported_count": exported,
                                "missing_count": len(missing),
                                "items": exported_items,
                                "missing": missing,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                object_key = f"workspaces/{job.workspace_id}/acquisition/exports/{job.id}.zip"
                self.storage.put_file(object_key, temp_path, "application/zip")
            finally:
                temp_path.unlink(missing_ok=True)
            job.status = "ready"
            job.object_key = object_key
            job.filename = f"acquisition_export_{shanghai_now():%Y%m%d_%H%M%S}.zip"
            job.item_count = exported
            job.missing_count = len(missing)
            job.completed_at = shanghai_now()
            job.expires_at = shanghai_now() + timedelta(hours=self.settings.acquisition_export_ttl_hours)
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
        db.commit()

    def cleanup_expired_exports(self, db: Session) -> int:
        jobs = db.scalars(
            select(AcquisitionExportJob).where(
                AcquisitionExportJob.status == "ready",
                AcquisitionExportJob.expires_at.is_not(None),
                AcquisitionExportJob.expires_at < shanghai_now(),
            )
        ).all()
        for job in jobs:
            if job.object_key:
                self.storage.remove_object(job.object_key)
            job.status = "expired"
            job.object_key = None
        db.commit()
        return len(jobs)

    def recover_imports(self, db: Session) -> dict[str, int]:
        """将服务中断时的入库状态收敛为可追溯的成功或可重试失败。"""
        recovered = 0
        failed = 0
        incomplete_batches = db.scalars(
            select(AcquisitionImportBatch).where(AcquisitionImportBatch.status.in_(("queued", "running")))
        ).all()
        for batch in incomplete_batches:
            items = db.scalars(
                select(AcquisitionImportBatchItem).where(
                    AcquisitionImportBatchItem.batch_id == batch.id,
                    AcquisitionImportBatchItem.status.in_(("queued", "processing")),
                )
            ).all()
            for item in items:
                asset = db.get(AcquisitionAsset, item.asset_id)
                photo = self._gallery_photo_by_sha(
                    db,
                    batch.workspace_id,
                    asset.sha256,
                    is_rich_text=batch.is_rich_text,
                ) if asset else None
                if asset is not None and photo is not None and item.promotion_intent == "new":
                    self._finish_imported(db, item, asset, photo)
                    recovered += 1
                elif asset is not None and photo is not None and item.promotion_intent == "gallery_duplicate":
                    self._finish_gallery_duplicate(db, item, asset, photo)
                    recovered += 1
                else:
                    item.status = "failed"
                    item.error_message = "服务重启前入库未完成，可重新提交"
                    if asset is not None:
                        asset.status = "import_failed"
                        asset.error_message = item.error_message
                        self._set_linked_item_statuses(db, asset, "import_failed")
                    failed += 1
            self._refresh_import_batch(db, batch.id, finish=True)
        active_asset_ids = set(
            db.scalars(
                select(AcquisitionImportBatchItem.asset_id).where(
                    AcquisitionImportBatchItem.status.in_(("queued", "processing"))
                )
            ).all()
        )
        legacy_assets = db.scalars(
            select(AcquisitionAsset).where(AcquisitionAsset.status.in_(("importing", "import_queued")))
        ).all()
        for asset in legacy_assets:
            if asset.id in active_asset_ids:
                continue
            photo = self._gallery_photo_by_sha(db, asset.workspace_id, asset.sha256)
            if photo is not None:
                self._finish_imported(db, None, asset, photo)
                recovered += 1
            else:
                asset.status = "import_failed"
                asset.error_message = "服务重启前入库未完成，可重新提交"
                self._set_linked_item_statuses(db, asset, "import_failed")
                failed += 1
        db.commit()
        cleanup_assets = db.scalars(
            select(AcquisitionAsset).where(
                AcquisitionAsset.status.in_(("imported", "gallery_duplicate")),
                AcquisitionAsset.object_key.is_not(None),
            )
        ).all()
        for asset in cleanup_assets:
            self._cleanup_asset_object(db, asset)
        return {"recovered": recovered, "failed": failed}

    def reconcile_run_metrics(self, db: Session) -> int:
        """为旧数据补齐不可变采集结果，并从明细重算漏斗计数。"""
        changed = 0
        runs = db.scalars(select(AcquisitionRun)).all()
        earliest_asset_items = {}
        for asset_id, item_id in db.execute(
            select(AcquisitionRunItem.asset_id, AcquisitionRunItem.id)
            .where(AcquisitionRunItem.asset_id.is_not(None))
            .order_by(AcquisitionRunItem.id.asc())
        ).all():
            if asset_id is not None:
                earliest_asset_items.setdefault(asset_id, item_id)
        for run in runs:
            items = db.scalars(
                select(AcquisitionRunItem).where(AcquisitionRunItem.run_id == run.id).order_by(AcquisitionRunItem.id.asc())
            ).all()
            for item in items:
                if item.collection_outcome not in {None, "", "pending"}:
                    continue
                if item.status == "ignored_video":
                    outcome = "ignored"
                elif item.status == "skipped":
                    outcome = "source_skipped"
                elif item.status == "failed":
                    outcome = "failed"
                elif item.asset_id is None:
                    outcome = "gallery_duplicate" if item.status == "gallery_duplicate" else "failed"
                else:
                    asset = db.get(AcquisitionAsset, item.asset_id)
                    outcome = (
                        "candidate"
                        if asset is not None and asset.created_at >= run.created_at and earliest_asset_items.get(asset.id) == item.id
                        else "content_duplicate"
                    )
                item.collection_outcome = outcome
                changed += 1
            outcomes = [item.collection_outcome for item in items]
            run.skipped_count = outcomes.count("source_skipped")
            run.ignored_count = outcomes.count("ignored")
            run.candidate_count = outcomes.count("candidate")
            run.content_duplicate_count = outcomes.count("content_duplicate")
            run.gallery_duplicate_count = outcomes.count("gallery_duplicate")
            run.resolution_duplicate_count = outcomes.count("resolution_duplicate")
            run.download_success_count = (
                run.candidate_count
                + run.content_duplicate_count
                + run.gallery_duplicate_count
                + run.resolution_duplicate_count
            )
            run.downloaded_count = run.candidate_count
            run.error_count = outcomes.count("failed")
        db.commit()
        return changed

    def recover_runs(self, db: Session) -> int:
        runs = db.scalars(select(AcquisitionRun).where(AcquisitionRun.status.in_(("pending", "running")))).all()
        for run in runs:
            run.status = "interrupted"
            run.error_message = "服务重启前采集未完成，可手动重新运行"
        db.commit()
        return len(runs)


def migrate_catchpics_history(
    service: AcquisitionService,
    db: Session,
    workspace_id: int | None,
    root: Path,
    dry_run: bool,
) -> dict[str, int]:
    """只读取旧目录；实际迁入会复制图片到采集工作区，绝不删除旧文件。"""
    supported_roots = {
        "raindrop-ftxsri-workers-dev": ("raindrop-ftxsri-workers-dev", "https://raindrop.ftxsri.workers.dev"),
        "shfwzwz-raindrop-page": ("shfwzwz-raindrop-page", "https://shfwzwz.raindrop.page"),
    }
    if root.name not in supported_roots:
        raise ValueError("仅支持迁移 catchPics 中已注册的两个脚本目录")
    script_key, base_url = supported_roots[root.name]
    resource = root / "resource"
    image_extensions = {".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".jxl", ".png", ".tif", ".tiff", ".webp", ".img"}
    images = [
        path for path in resource.rglob("*")
        if path.is_file() and path.suffix.lower() in image_extensions
    ] if resource.exists() else []
    record_paths = [path for name in ("state.json", "manifest.json") for path in root.rglob(name)]
    records: list[dict[str, str]] = []
    for path in record_paths:
        try:
            records.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        except OSError:
            continue
    stats = {"files": len(images), "sources": 0, "categories": 0, "assets": 0, "records": len(records)}
    if dry_run:
        return stats
    source = db.scalar(select(AcquisitionSource).where(AcquisitionSource.workspace_id == workspace_id, AcquisitionSource.name == root.name))
    if source is None:
        source = service.create_source(db, workspace_id, root.name, base_url, "由 catchPics 历史资源迁入")
        service.bind_script(db, source, script_key)
        stats["sources"] = 1
    else:
        if db.scalar(select(AcquisitionSourceScript).where(AcquisitionSourceScript.source_id == source.id, AcquisitionSourceScript.script_key == script_key)) is None:
            service.bind_script(db, source, script_key)
    source.settings_json = json.dumps({
        "legacy_root": str(root),
        "legacy_records": records,
    }, ensure_ascii=False)
    run_by_category: dict[str, AcquisitionRun] = {}
    for path in images:
        relative = path.relative_to(resource)
        category_path = str(relative.parent).replace("\\", "/") if relative.parent != Path(".") else "未分类"
        category = db.scalar(select(AcquisitionCategory).where(AcquisitionCategory.source_id == source.id, AcquisitionCategory.path == category_path))
        if category is None:
            category = AcquisitionCategory(
                source_id=source.id,
                name=category_path.split("/")[-1],
                path=category_path,
                crawl_url=f"file://{resource / relative.parent}",
                notes="由 catchPics 历史目录迁入",
            )
            db.add(category)
            db.commit()
            db.refresh(category)
            stats["categories"] += 1
        run = run_by_category.get(category_path)
        if run is None:
            definition = SCRIPT_REGISTRY[script_key]
            run = AcquisitionRun(
                id=uuid4().hex,
                workspace_id=workspace_id,
                source_id=source.id,
                category_id=category.id,
                script_key=script_key,
                script_name_snapshot=definition.name,
                script_version_snapshot=definition.version,
                source_name_snapshot=source.name,
                category_name_snapshot=category.name,
                category_url_snapshot=category.crawl_url,
                parameters_json="{}",
                mode="legacy",
                status="completed",
                started_at=shanghai_now(),
                completed_at=shanghai_now(),
            )
            db.add(run)
            db.flush()
            run_by_category[category_path] = run
        payload = path.read_bytes()
        try:
            width, height, blur, warnings = service._quality(payload)
        except Exception:
            continue
        sha256 = hashlib.sha256(payload).hexdigest()
        asset = db.scalar(select(AcquisitionAsset).where(AcquisitionAsset.workspace_id == workspace_id, AcquisitionAsset.sha256 == sha256))
        if asset is None:
            asset_id = uuid4().hex
            object_key = service._asset_key(workspace_id, asset_id, path.name)
            service.storage.put_bytes(object_key, payload, mimetypes.guess_type(path.name)[0])
            asset = AcquisitionAsset(id=asset_id, workspace_id=workspace_id, sha256=sha256, filename=path.name, content_type=mimetypes.guess_type(path.name)[0], object_key=object_key, size_bytes=len(payload), width=width, height=height, blur_score=blur, quality_warnings=json.dumps(warnings, ensure_ascii=False))
            db.add(asset)
            stats["assets"] += 1
        external_key = _stable_key(str(relative))
        source_item = db.scalar(select(AcquisitionSourceItem).where(AcquisitionSourceItem.source_id == source.id, AcquisitionSourceItem.external_key == external_key))
        if source_item is None:
            source_item = AcquisitionSourceItem(source_id=source.id, category_id=category.id, script_key=script_key, external_key=external_key, remote_external_key=external_key, source_url=f"file://{path}", status="pending_review")
            db.add(source_item)
            db.flush()
        if db.scalar(select(AcquisitionRunItem).where(AcquisitionRunItem.run_id == run.id, AcquisitionRunItem.source_item_id == source_item.id)) is None:
            db.add(AcquisitionRunItem(run_id=run.id, source_item_id=source_item.id, asset_id=asset.id, status="pending_review"))
    db.commit()
    return stats
