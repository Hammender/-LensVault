from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import threading
import time
import subprocess
from contextlib import nullcontext
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.timezones import as_shanghai_naive, shanghai_isoformat, shanghai_now
from app.models import (
    AcquisitionAsset,
    AcquisitionCategory,
    AcquisitionExportJob,
    AcquisitionImportBatch,
    AcquisitionImportBatchItem,
    AcquisitionPluginCredential,
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
    SCRIPT_REGISTRY,
    RemoteItem,
    curl_request_bytes,
    get_script,
    is_tls_transport_error,
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
from app.services.preview_runtime import preview_source_guard, preview_source_exists
from app.services.thumbnails import acquisition_preview_cache_prefix
from app.services.telegram import TelegramRunAborted, TelegramService
from app.services.acquisition_plugins.manager import PluginAborted, PluginAdapter, PluginManager
from app.services.acquisition_plugins.context import PluginExecutionContext
from app.services.acquisition_plugins.runtime import check_abort, safe_error
from app.services.video_processing import extract_video_cover_frame
from app.services.acquisition_frames import AcquisitionFrameService

logger = logging.getLogger(__name__)

_VIDEO_SUFFIXES = {
    ".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".ts", ".webm", ".wmv",
}


def _video_container_magic(path: Path) -> bool:
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return False
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return True
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return True
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return True
    if header.startswith(b"\x00\x00\x01\xba") or header.startswith(b"\x00\x00\x01\xb3"):
        return True
    return False


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
    payload: bytes | None
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
    file_path: Path | None = None
    size_bytes: int = 0
    temporary_dir: Path | None = None

    def cleanup(self) -> None:
        if self.temporary_dir is not None:
            shutil.rmtree(self.temporary_dir, ignore_errors=True)


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
        self.plugins = PluginManager(self.settings)
        self._download_policy = threading.local()
        self.similarity_scanner = similarity_scanner
        self.face_service = face_service
        self.video_service = video_service
        self._run_abort_events: dict[str, threading.Event] = {}
        self._run_abort_lock = threading.Lock()
        self._frames: AcquisitionFrameService | None = None
        self._capture_lock = threading.Lock()
        self.similarity_extractor = similarity_extractor or (
            similarity_scanner.extractor if similarity_scanner is not None else DinoV2FeatureExtractor(self.settings)
        )

    def scripts(self) -> list[dict[str, object]]:
        builtin = [get_script(key).metadata() for key in sorted(SCRIPT_REGISTRY)]
        installed = []
        snapshot = self.plugins.active
        for key in sorted(snapshot):
            if key in SCRIPT_REGISTRY:
                continue
            definition = self.plugins.definition_from_manifest(snapshot[key])
            if definition is None:
                continue
            installed.append({
                **definition.metadata(),
                "credentials": snapshot[key].get("credentials", []),
                "is_plugin": True,
            })
        return builtin + installed

    def get_definition(self, key: str, version: str | None = None,
                       credentials: dict[str, object] | None = None):
        if key in SCRIPT_REGISTRY:
            return get_script(key)
        return self.plugins.get_definition(key, version, credentials)

    def refresh_plugins(self, db: Session) -> None:
        self.plugins.refresh(db)

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
        definition = self.get_definition(selected_script) if selected_script else None
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
        definition = self.get_definition(script_key)
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
        credential_id: int | None = None,
    ) -> AcquisitionRun:
        with self.plugins.catalog.lock:
            return self._start_run(db, workspace_id, category, script_key, mode, parameters, credential_id)

    def _start_run(
        self,
        db: Session,
        workspace_id: int | None,
        category: AcquisitionCategory,
        script_key: str,
        mode: str,
        parameters: dict[str, object] | None = None,
        credential_id: int | None = None,
    ) -> AcquisitionRun:
        if mode not in {"incremental", "full", "verify"}:
            raise ValueError("采集模式必须为 incremental、full 或 verify")
        source = db.get(AcquisitionSource, category.source_id)
        if source is None or source.workspace_id != workspace_id or not source.enabled or not category.enabled:
            raise ValueError("采集站点或分类不可用")
        definition = self.get_definition(script_key)
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
        if isinstance(definition.adapter, PluginAdapter):
            fields = definition.adapter.manifest.get("credentials", [])
            if any(field.get("required") is True for field in fields) and credential_id is None:
                raise ValueError("该插件需要先选择账号配置")
            if credential_id is not None:
                account = db.get(AcquisitionPluginCredential, credential_id)
                if account is None or account.workspace_id != workspace_id or account.script_key != script_key:
                    raise ValueError("账号配置不可用")
                if account.status != "valid":
                    raise ValueError("请先测试账号连接，确认凭据可用")
        default_parameters = json.loads(binding.default_parameters_json or "{}")
        requested_parameters = dict(parameters or {})
        legacy_default_force = self._pop_legacy_force_full_scan(default_parameters)
        legacy_requested_force = self._pop_legacy_force_full_scan(requested_parameters)
        defaults = definition.validate_parameters(default_parameters)
        validated_parameters = definition.validate_parameters({**defaults, **requested_parameters})
        if definition.key == "telegram-channel-mtproto" and validated_parameters.get("comments_only") and (
            category.telegram_entity_type in {"bot", "group"} or category.telegram_topic_id is not None
        ):
            raise ValueError("仅采集评论区媒体只支持频道，不支持机器人、群组或论坛话题")
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
            credential_id=credential_id,
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
        self._register_run_abort(run.id)
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

    def _download_and_analyze(self, remote: RemoteItem, referer: str,
                              plugin_adapter: PluginAdapter | None = None) -> DownloadedRemote:
        file_path: Path | None = None
        temporary_dir: Path | None = None
        if plugin_adapter is not None:
            temporary_root = self.settings.data_dir / "acquisition" / "plugin-tmp"
            temporary_root.mkdir(parents=True, exist_ok=True)
            temporary_dir = (plugin_adapter.context.download_directory() if plugin_adapter.context is not None
                             else Path(tempfile.mkdtemp(prefix="download-", dir=temporary_root)))
            try:
                file_path = plugin_adapter.download(asdict(remote), temporary_dir)
                limit = self.settings.telegram_max_media_bytes if remote.media_type == "video" else self.settings.acquisition_max_file_bytes
                if file_path.stat().st_size > limit:
                    raise ValueError("采集媒体超过大小上限")
                content_type = mimetypes.guess_type(file_path.name)[0]
                resolved_url = remote.source_url
                payload = file_path.read_bytes() if remote.media_type == "image" else None
            except Exception:
                shutil.rmtree(temporary_dir, ignore_errors=True)
                raise
        else:
            result = self._download_remote(remote, referer)
            if len(result) == 2:  # 兼容测试和第三方扩展中的旧下载器实现。
                payload, content_type = result
                resolved_url = remote.source_url
            else:
                payload, content_type, resolved_url = result
        execution = plugin_adapter.context if plugin_adapter is not None else None
        previous = getattr(self._download_policy, "plugin_context", None)
        self._download_policy.plugin_context = execution
        try:
            if execution is not None:
                check_abort(execution.abort_event, execution.deadline)
            downloaded = self._analyze_downloaded_media(remote, payload, content_type, resolved_url, file_path)
            if execution is not None:
                check_abort(execution.abort_event, execution.deadline)
            return replace(downloaded, temporary_dir=temporary_dir)
        except Exception:
            if temporary_dir is not None:
                shutil.rmtree(temporary_dir, ignore_errors=True)
            raise
        finally:
            if previous is None:
                del self._download_policy.plugin_context
            else:
                self._download_policy.plugin_context = previous

    def _analyze_downloaded_media(self, remote: RemoteItem, payload: bytes | None,
                                   content_type: str | None, resolved_url: str,
                                   file_path: Path | None) -> DownloadedRemote:
        filename = file_path.name if file_path else Path(urlparse(resolved_url).path).name or Path(urlparse(remote.source_url).path).name
        media_type = remote.media_type
        content_type = (content_type or "").lower()
        if media_type == "image":
            assert payload is not None
            width, height, blur, warnings, features = self._analyze_image_payload(payload)
            duration = None
            perceptual_phash = features.phash
            perceptual_dhash = features.dhash
            quality_score = features.quality_score
        else:
            suffix = Path(filename).suffix.lower()
            named_as_video = content_type.startswith("video/") or suffix in _VIDEO_SUFFIXES
            duration = width = height = None
            if file_path is not None:
                duration, width, height, has_video_stream = self._probe_video_details(file_path)
                if not named_as_video and not has_video_stream and not _video_container_magic(file_path):
                    raise RuntimeError(f"{resolved_url}: 返回内容不是视频")
            elif not named_as_video:
                raise RuntimeError(f"{resolved_url}: 返回内容不是视频")
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
        if file_path is not None:
            digest = hashlib.sha256()
            with file_path.open("rb") as media:
                for chunk in iter(lambda: media.read(1024 * 1024), b""):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
            size_bytes = file_path.stat().st_size
        else:
            assert payload is not None
            sha256 = hashlib.sha256(payload).hexdigest()
            size_bytes = len(payload)
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
            sha256=sha256,
            perceptual_phash=perceptual_phash,
            perceptual_dhash=perceptual_dhash,
            quality_score=quality_score,
            file_path=file_path,
            size_bytes=size_bytes,
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
        registered = event is not None
        logger.info("收到采集停止请求 run_id=%s registered=%s", run_id, registered)
        if event is None:
            return False
        event.set()
        return True

    def _register_run_abort(self, run_id: str) -> threading.Event:
        with self._run_abort_lock:
            event = self._run_abort_events.get(run_id)
            if event is None:
                event = threading.Event()
                self._run_abort_events[run_id] = event
            return event

    def _clear_run_abort(self, run_id: str) -> None:
        with self._run_abort_lock:
            self._run_abort_events.pop(run_id, None)

    def _mark_run_interrupted(self, db: Session, run: AcquisitionRun) -> None:
        current = db.get(AcquisitionRun, run.id)
        if current is None or current.status not in {"pending", "running"}:
            return
        current.status = "interrupted"
        current.stop_reason = "requested_end"
        current.completed_at = shanghai_now()
        db.commit()

    def process_run(self, db: Session, run_id: str) -> None:
        run = db.get(AcquisitionRun, run_id)
        if run is None or run.status not in {"pending", "running"}:
            return
        abort_event = self._register_run_abort(run_id)
        context = PluginExecutionContext(self.plugins.root.parent / "plugin-tmp", abort_event)
        try:
            with context:
                lease = (self.plugins.lease(run.script_key or "", run.script_version_snapshot)
                         if run.script_key not in SCRIPT_REGISTRY else nullcontext())
                with lease:
                    self._process_run_body(db, run_id, abort_event, context)
        except Exception as exc:
            db.rollback()
            current = db.get(AcquisitionRun, run_id)
            if not isinstance(exc, PluginAborted):
                logger.error("采集任务失败 run_id=%s error=%s", run_id, safe_error(str(exc), context.secrets))
            if current is not None and current.status in {"pending", "running"}:
                current.status = "interrupted" if isinstance(exc, PluginAborted) else "failed"
                current.error_message = safe_error(str(exc), context.secrets)
                current.completed_at = shanghai_now()
                if isinstance(exc, PluginAborted):
                    current.stop_reason = "requested_end"
                db.commit()
        finally:
            self._clear_run_abort(run_id)

    def _process_run_body(self, db: Session, run_id: str, abort_event: threading.Event,
                          context: PluginExecutionContext) -> None:
        run = db.get(AcquisitionRun, run_id)
        if run is not None and abort_event.is_set():
            self._mark_run_interrupted(db, run)
            return
        if run is None:
            return
        source = db.get(AcquisitionSource, run.source_id)
        category = db.get(AcquisitionCategory, run.category_id)
        if source is None or category is None:
            run.status = "failed"
            run.completed_at = shanghai_now()
            run.error_message = "采集站点或分类已被删除"
            db.commit()
            return
        credentials = {}
        if run.credential_id is not None:
            account = db.get(AcquisitionPluginCredential, run.credential_id)
            if account is None or account.workspace_id != run.workspace_id or account.script_key != run.script_key:
                run.status = "failed"
                run.completed_at = shanghai_now()
                run.error_message = "账号配置不可用"
                db.commit()
                return
            credentials = self.plugins.credentials(account)
        context.credentials = dict(credentials)
        definition = self.get_definition(run.script_key or "", run.script_version_snapshot, credentials)
        if definition is None:
            run.status = "failed"
            run.completed_at = shanghai_now()
            run.error_message = "运行所使用的采集脚本不可用"
            db.commit()
            return
        parameters = json.loads(run.parameters_json or "{}")
        if not isinstance(parameters, dict):
            raise ValueError("运行参数必须是对象")
        if definition.key == "telegram-channel-mtproto":
            self._process_telegram_run(db, run, source, category, parameters,
                definition.adapter if isinstance(definition.adapter, PluginAdapter) else None)
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
            if isinstance(definition.adapter, PluginAdapter):
                definition.adapter.abort_event = abort_event
                definition.adapter.context = context
                context.manifest = definition.adapter.manifest
            try:
                def download(prepared: PendingRemote) -> DownloadedRemote:
                    limiter.wait(abort_event)
                    item_referer = prepared.remote.referer_url or referer
                    self._download_policy.context = _DownloadPolicyContext(limiter, abort_event)
                    try:
                        if isinstance(definition.adapter, PluginAdapter):
                            return self._download_and_analyze(prepared.remote, item_referer, definition.adapter)
                        return self._download_and_analyze(prepared.remote, item_referer)
                    finally:
                        del self._download_policy.context

                stopped = False
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="acquisition-download") as executor:
                    pages = None
                    try:
                        pages = definition.adapter.enumerate_pages(
                            referer, parameters, known_external_keys, run.mode == "incremental",
                        )
                        for page in pages:
                            if abort_event.is_set():
                                stopped = True
                                break
                            run.scan_end_page = page.page_number
                            pending = [prepared for remote in page.items if (prepared := self._prepare_remote_item(db, run, source, category, remote)) is not None]
                            futures = {executor.submit(download, prepared): prepared for prepared in pending}
                            for future in as_completed(futures):
                                prepared = futures[future]
                                try:
                                    downloaded = future.result()
                                    try:
                                        self._persist_downloaded_remote(db, run.id, prepared, downloaded)
                                    finally:
                                        downloaded.cleanup()
                                except PluginAborted:
                                    abort_event.set()
                                    stopped = True
                                    for pending_future in futures:
                                        pending_future.cancel()
                                    break
                                except CancelledError:
                                    abort_event.set()
                                    stopped = True
                                    for pending_future in futures:
                                        pending_future.cancel()
                                    break
                                except AccessBlockedError as exc:
                                    self._record_remote_failure(db, run.id, prepared, RuntimeError(safe_error(str(exc), context.secrets)))
                                    abort_event.set()
                                    for pending_future in futures:
                                        if pending_future is not future:
                                            pending_future.cancel()
                                    raise
                                except Exception as exc:
                                    self._record_remote_failure(db, run.id, prepared, RuntimeError(safe_error(str(exc), context.secrets)))
                            run = db.get(AcquisitionRun, run_id)
                            if run is None:
                                return
                            if page.stop_reason is not None:
                                run.stop_reason = page.stop_reason
                                run.reached_collection_end = page.reached_collection_end
                            db.commit()
                            if stopped:
                                break
                    except PluginAborted:
                        stopped = True
                    finally:
                        close = getattr(pages, "close", None)
                        if close is not None:
                            close()
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
                if isinstance(definition.adapter, PluginAdapter):
                    definition.adapter.abort_event = None
                    definition.adapter.deadline = None
        except PluginAborted:
            run = db.get(AcquisitionRun, run_id)
            if run is None:
                return
            run.status = "interrupted"
            run.stop_reason = "requested_end"
            run.completed_at = shanghai_now()
        except Exception as exc:
            db.rollback()
            run = db.get(AcquisitionRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error_message = safe_error(str(exc), context.secrets)
            run.completed_at = shanghai_now()
            logger.error("采集任务失败 run_id=%s script=%s error=%s", run_id, run.script_key, run.error_message)
        db.commit()

    def _process_telegram_run(
        self,
        db: Session,
        run: AcquisitionRun,
        source: AcquisitionSource,
        category: AcquisitionCategory,
        parameters: dict[str, object],
        plugin_adapter: PluginAdapter | None = None,
    ) -> None:
        from app.models import TelegramAccount

        abort_event = self._register_run_abort(run.id)
        if abort_event.is_set():
            self._mark_run_interrupted(db, run)
            return
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
            if plugin_adapter is None:
                TelegramService(self.settings).read_channel_media(
                    account, category.crawl_url, parameters, temporary_root,
                    on_records=persist_batch,
                    abort_event=abort_event,
                )
            else:
                credentials = {
                    "api_id": account.api_id,
                    "api_hash_encrypted": account.api_hash_encrypted,
                    "session_encrypted": account.session_encrypted,
                    "encryption_key": self.settings.telegram_session_encryption_key,
                    "max_media_bytes": self.settings.telegram_max_media_bytes,
                    "download_timeout_seconds": self.settings.telegram_download_timeout_seconds,
                    "flood_wait_max_seconds": self.settings.telegram_flood_wait_max_seconds,
                }
                definition = self.plugins.get_definition(run.script_key or "", run.script_version_snapshot, credentials)
                if definition is None or not isinstance(definition.adapter, PluginAdapter):
                    raise ValueError("Telegram 插件版本不可用")
                plugin_adapter.abort_event = abort_event
                try:
                    temporary_root.mkdir(parents=True, exist_ok=True)
                    for page in definition.adapter.enumerate_pages(category.crawl_url, parameters, set(), False):
                        if abort_event.is_set():
                            raise TelegramRunAborted()
                        for item in page.items:
                            if abort_event.is_set():
                                raise TelegramRunAborted()
                            record = dict(item.plugin_data or {})
                            for field in ("published_at", "edited_at"):
                                if record.get(field):
                                    record[field] = datetime.fromisoformat(str(record[field]))
                            try:
                                record["path"] = definition.adapter.download(asdict(item), temporary_root)
                            except (TelegramRunAborted, PluginAborted):
                                raise
                            except Exception as exc:
                                if not record.get("protected_content"):
                                    raise
                                logger.warning(
                                    "Telegram 插件下载受保护媒体失败 message_id=%s: %s",
                                    record.get("message_id"),
                                    exc,
                                )
                            persist_batch([record])
                    if definition.adapter.last_state and isinstance(definition.adapter.last_state.get("session_encrypted"), str):
                        account.session_encrypted = definition.adapter.last_state["session_encrypted"]
                        db.commit()
                finally:
                    plugin_adapter.abort_event = None
            if abort_event.is_set():
                raise TelegramRunAborted()
            run.status = "completed"
            run.reached_collection_end = True
            run.stop_reason = "collection_end"
            run.completed_at = shanghai_now()
            db.commit()
        except TelegramRunAborted:
            logger.info("Telegram 采集已按请求停止 run_id=%s", run.id)
            self._mark_run_interrupted(db, run)
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
        path = record.get("path")
        has_file = isinstance(path, Path) and path.is_file()
        if record.get("protected_content") and not has_file:
            source_item.status = "ignored_protected"
            source_item.last_error = "频道限制保存内容"
            run_item.status = "ignored_protected"
            run_item.collection_outcome = "ignored"
            run.ignored_count += 1
            db.commit()
            return
        if not has_file:
            raise RuntimeError("Telegram 媒体临时文件不存在")
        assert isinstance(path, Path)
        media_type = str(record["media_type"])
        payload = path.read_bytes() if media_type == "image" else None
        if payload is None:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
        else:
            sha256 = hashlib.sha256(payload).hexdigest()
        content_type = (
            record.get("content_type")
            or mimetypes.guess_type(path.name)[0]
            or ("image/jpeg" if media_type == "image" else "video/mp4")
        )
        if self._mark_library_duplicate_if_exists(db, run, source_item, run_item, sha256, media_type):
            return
        asset = db.scalar(select(AcquisitionAsset).where(
            AcquisitionAsset.workspace_id == run.workspace_id, AcquisitionAsset.sha256 == sha256
        ))
        if asset is None:
            asset_id = uuid4().hex
            object_key = self._asset_key(run.workspace_id, asset_id, path.name)
            if payload is None:
                self.storage.put_file(object_key, path, content_type)
            else:
                self.storage.put_bytes(object_key, payload, content_type)
            width = height = None
            blur = None
            phash = dhash = None
            quality = None
            warnings: list[str] = []
            duration = None
            if media_type == "image":
                assert payload is not None
                width, height, blur, warnings, features = self._analyze_image_payload(payload)
                phash, dhash, quality = features.phash, features.dhash, features.quality_score
            else:
                duration = record.get("duration_seconds")
                width = record.get("width")
                height = record.get("height")
            asset = AcquisitionAsset(
                id=asset_id, workspace_id=run.workspace_id, sha256=sha256, filename=path.name,
                content_type=content_type, media_type=media_type, object_key=object_key,
                size_bytes=path.stat().st_size,
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
        duration, width, height, _has_video = self._probe_video_details(path)
        return duration, width, height

    def _probe_video_details(self, path: Path) -> tuple[float | None, int | None, int | None, bool]:
        command = [self.settings.ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path)]
        try:
            timeout = 60
            execution = getattr(self._download_policy, "plugin_context", None)
            if execution is not None and execution.deadline is not None:
                check_abort(execution.abort_event, execution.deadline)
                timeout = min(timeout, execution.deadline - time.monotonic())
            completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
            result = json.loads(completed.stdout)
            stream = next((item for item in result.get("streams", []) if item.get("codec_type") == "video"), {})
            duration = float(result.get("format", {}).get("duration")) if result.get("format", {}).get("duration") else None
            return duration, stream.get("width"), stream.get("height"), bool(stream)
        except Exception:
            return None, None, None, False

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
                metadata_json=json.dumps({"caption": remote.caption, "hashtags": remote.hashtags,
                    "published_at": remote.published_at, "channel_title": remote.channel_title}, ensure_ascii=False),
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
            item.metadata_json = json.dumps({"caption": remote.caption, "hashtags": remote.hashtags,
                "published_at": remote.published_at, "channel_title": remote.channel_title}, ensure_ascii=False)
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
        if downloaded.file_path is not None:
            self.storage.put_file(object_key, downloaded.file_path, downloaded.content_type)
        else:
            assert downloaded.payload is not None
            self.storage.put_bytes(object_key, downloaded.payload, downloaded.content_type)
        return AcquisitionAsset(
            id=asset_id,
            workspace_id=run.workspace_id,
            sha256=downloaded.sha256,
            filename=downloaded.filename,
            content_type=downloaded.content_type or mimetypes.guess_type(downloaded.filename)[0],
            media_type=downloaded.media_type,
            object_key=object_key,
            size_bytes=downloaded.size_bytes or len(downloaded.payload or b""),
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
                        downloaded.width, downloaded.height, downloaded.quality_score, downloaded.size_bytes or len(downloaded.payload or b"")
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
        # 插件错误已由调用方脱敏，不附加可能包含原始凭据的异常堆栈。
        logger.warning(
            "采集媒体失败 run_id=%s script=%s run_item_id=%s source_item_id=%s error=%s",
            run_id, run.script_key, prepared.run_item_id, prepared.source_item_id, str(exc),
        )

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
            with preview_source_guard(asset.object_key) if asset.object_key else nullcontext():
                if asset.object_key:
                    self.storage.remove_object(asset.object_key)
                remove_prefix = getattr(self.storage, "remove_prefix", None)
                if remove_prefix is not None:
                    try:
                        remove_prefix(acquisition_preview_cache_prefix(asset.workspace_id, asset.id, asset.sha256))
                    except Exception:
                        logger.warning("清理采集预览缓存失败 asset_id=%s", asset.id, exc_info=True)
                cover_key = self._preview_key(asset.workspace_id, asset.id)
                self.storage.remove_object(cover_key)
                if asset.preview_object_key and asset.preview_object_key != cover_key:
                    self.storage.remove_object(asset.preview_object_key)
                asset.preview_object_key = None
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
        batch_started_at = time.perf_counter()
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
            item_started_at = time.perf_counter()
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
                    try:
                        self.video_service.optimize_video_faststart(video.id)
                    except Exception as exc:
                        logger.exception("采集视频后台优化未完成：video_id=%s", video.id)
                        db.rollback()
                        failed_video = db.get(VideoItem, video.id)
                        if failed_video is not None and failed_video.status in {"uploaded", "processing"}:
                            failed_video.status = "processing_failed"
                            failed_video.processing_error = str(exc)[:2000]
                            failed_video.processed_at = shanghai_now()
                            db.commit()
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
                source_key = asset.object_key
                filename = asset.filename
                content_type = asset.content_type
                workspace_id = batch.workspace_id
                rich_text = batch.is_rich_text
                db.rollback()
                download_started_at = time.perf_counter()
                payload = self.storage.get_bytes(source_key)
                download_ms = (time.perf_counter() - download_started_at) * 1000
                import_options = {}
                recognition_ms = 0.0
                if hasattr(self.pictures, "prepare_gallery_recognition"):
                    recognition_started_at = time.perf_counter()
                    try:
                        prepared_image = self.pictures.prepare_gallery_image(payload)
                        import_options["prepared_image"] = prepared_image
                        with Session(db.get_bind()) as recognition_db:
                            import_options["recognition_plan"] = self.pictures.prepare_gallery_recognition(
                                recognition_db, payload, workspace_id, image_bgr=prepared_image[3],
                            )
                    except Exception:
                        logger.exception("采集图片识别失败，继续保存图片 batch_id=%s item_id=%s", batch_id, item_id)
                        import_options["recognition_plan"] = None
                    recognition_ms = (time.perf_counter() - recognition_started_at) * 1000
                persist_started_at = time.perf_counter()
                photo, summary = self.pictures.import_gallery_photo(
                    db,
                    filename,
                    payload,
                    content_type,
                    workspace_id=workspace_id,
                    source_object_key=source_key,
                    ingest_source="acquisition",
                    is_rich_text=rich_text,
                    **import_options,
                )
                persist_ms = (time.perf_counter() - persist_started_at) * 1000
                if max(download_ms, recognition_ms, persist_ms) >= 1000:
                    logger.warning("采集图片入库阶段耗时 batch_id=%s item_id=%s 读取=%.0fms 识别=%.0fms 保存=%.0fms",
                                   batch_id, item_id, download_ms, recognition_ms, persist_ms)
                if summary.duplicated:
                    self._finish_gallery_duplicate(db, item, asset, photo)
                else:
                    self._finish_imported(db, item, asset, photo)
                self._refresh_import_batch(db, batch_id)
                db.commit()
                self._cleanup_asset_object(db, asset)
            except Exception as exc:
                logger.exception("采集图片入库失败 batch_id=%s item_id=%s", batch_id, item_id)
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
            finally:
                item_duration_ms = (time.perf_counter() - item_started_at) * 1000
                if item_duration_ms >= 1000:
                    logger.warning("采集图片入库耗时 batch_id=%s item_id=%s duration_ms=%.0f",
                                   batch_id, item_id, item_duration_ms)
        batch = db.get(AcquisitionImportBatch, batch_id)
        if batch is not None:
            self._refresh_import_batch(db, batch_id, finish=True)
            db.commit()
            logger.info("采集图片入库完成 batch_id=%s count=%s duration_ms=%.0f",
                        batch_id, batch.total_count, (time.perf_counter() - batch_started_at) * 1000)

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

    @property
    def frames(self) -> AcquisitionFrameService:
        with self._capture_lock:
            if self._frames is None:
                self._frames = AcquisitionFrameService(self.storage, self.settings)
            return self._frames

    def capture_frame(self, db: Session, video: AcquisitionAsset, frame: dict,
                      payload: bytes, source_metadata: dict) -> tuple[AcquisitionAsset, str]:
        """截图是独立素材；不构造爬取条目、不改变原视频状态和采集计数。"""
        digest = hashlib.sha256(payload).hexdigest()
        with self._capture_lock:
            existing = db.scalar(select(AcquisitionAsset).where(
                AcquisitionAsset.workspace_id == video.workspace_id, AcquisitionAsset.sha256 == digest
            ))
            if existing and existing.status not in {"rejected", "import_failed"}:
                return existing, "imported" if existing.status in {"imported", "gallery_duplicate"} else "existing"
            if self._gallery_photo_by_sha(db, video.workspace_id, digest) is not None:
                # 若图库中已有同一画面，仍保留可追溯的素材记录，但不重复进入待审核。
                imported = True
            else:
                imported = False
            width, height, blur, warnings, features = self._analyze_image_payload(payload)
            asset_id = existing.id if existing else uuid4().hex
            milliseconds = round(frame["time_seconds"] * 1000)
            color_conversion = frame.get("color_conversion")
            suffix = "_sRGB" if color_conversion else ""
            filename = f"{Path(video.filename).stem[:400]}_截图_{milliseconds // 60000:02d}-{milliseconds // 1000 % 60:02d}-{milliseconds % 1000:03d}{suffix}.png"
            key = self._asset_key(video.workspace_id, asset_id, filename)
            metadata = {**source_metadata, "video_asset_id": video.id, "video_filename": video.filename,
                        "video_sha256": video.sha256, "frame_index": frame["frame_index"],
                        "time_seconds": frame["time_seconds"]}
            if color_conversion:
                metadata["color_conversion"] = color_conversion
            asset = existing or AcquisitionAsset(id=asset_id, workspace_id=video.workspace_id, sha256=digest)
            try:
                self.storage.put_bytes(key, payload, "image/png")
                asset.filename = filename
                asset.content_type = "image/png"
                asset.media_type = "image"
                asset.object_key = key
                asset.size_bytes = len(payload)
                asset.width, asset.height, asset.blur_score = width, height, blur
                asset.perceptual_phash, asset.perceptual_dhash = features.phash, features.dhash
                asset.quality_score = features.quality_score
                asset.quality_warnings = json.dumps(warnings, ensure_ascii=False)
                asset.capture_metadata_json = json.dumps(metadata, ensure_ascii=False)
                asset.status = "gallery_duplicate" if imported else "pending_review"
                asset.error_message = None
                asset.created_at = shanghai_now()
                db.add(asset)
                db.commit()
            except Exception as exc:
                db.rollback()
                self.storage.remove_object(key)
                if isinstance(exc, IntegrityError):
                    winner = db.scalar(select(AcquisitionAsset).where(
                        AcquisitionAsset.workspace_id == video.workspace_id, AcquisitionAsset.sha256 == digest
                    ))
                    if winner:
                        return winner, "imported" if winner.status in {"imported", "gallery_duplicate"} else "existing"
                raise
            if imported:
                self._cleanup_asset_object(db, asset)
            return asset, "imported" if imported else "restored" if existing else "created"

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
            with preview_source_guard(asset.object_key):
                if not preview_source_exists(self.storage, asset.object_key):
                    return None
                self.storage.put_bytes(key, cover, "image/jpeg")
                if not preview_source_exists(self.storage, asset.object_key):
                    self.storage.remove_object(key)
                    return None
                asset.preview_object_key = key
                db.commit()
            return cover
        except Exception:
            db.rollback()
            return None

    def _cleanup_asset_object(self, db: Session, asset: AcquisitionAsset, commit: bool = True) -> None:
        pending_error: str | None = None
        with preview_source_guard(asset.object_key) if asset.object_key else nullcontext():
            if asset.object_key:
                try:
                    self.storage.remove_object(asset.object_key)
                except Exception as exc:
                    pending_error = f"临时文件待清理：{exc}"
                else:
                    asset.object_key = None
            remove_prefix = getattr(self.storage, "remove_prefix", None)
            if remove_prefix is not None:
                try:
                    remove_prefix(acquisition_preview_cache_prefix(asset.workspace_id, asset.id, asset.sha256))
                except Exception as exc:
                    logger.warning("清理采集预览缓存失败 asset_id=%s error=%s", asset.id, exc)
            try:
                cover_key = self._preview_key(asset.workspace_id, asset.id)
                self.storage.remove_object(cover_key)
                if asset.preview_object_key and asset.preview_object_key != cover_key:
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


_CATCHPICS_DIRECTORIES = {
    "raindrop-ftxsri-workers-dev": {
        "base_url": "https://raindrop.ftxsri.workers.dev",
        "script_name": "raindrop-ftxsri-workers-dev",
        "script_version": "1.0.2",
        "page_format_key": "raindrop-workers-json-v1",
    },
    "shfwzwz-raindrop-page": {
        "base_url": "https://shfwzwz.raindrop.page",
        "script_name": "shfwzwz-raindrop-page",
        "script_version": "1.2.0",
        "page_format_key": "raindrop-public-page-v1",
    },
}


def _bind_historical_script(db: Session, source: AcquisitionSource, script_key: str, page_format_key: str) -> None:
    """把历史目录记到站点上，不把该脚本放进可选脚本列表。"""
    meta = _CATCHPICS_DIRECTORIES[script_key]
    if db.get(AcquisitionScript, script_key) is None:
        db.add(AcquisitionScript(
            key=script_key,
            name=meta["script_name"],
            version=meta["script_version"],
            page_format_key=page_format_key,
            description="历史目录迁入记录",
            parameter_schema_json="[]",
            enabled=False,
        ))
        db.flush()
    binding = db.scalar(
        select(AcquisitionSourceScript).where(
            AcquisitionSourceScript.source_id == source.id,
            AcquisitionSourceScript.script_key == script_key,
        )
    )
    if binding is None:
        binding = AcquisitionSourceScript(source_id=source.id, script_key=script_key)
        db.add(binding)
    binding.enabled = True
    binding.default_parameters_json = "{}"
    source.page_format_key = page_format_key
    db.commit()


def migrate_catchpics_history(
    service: AcquisitionService,
    db: Session,
    workspace_id: int | None,
    root: Path,
    dry_run: bool,
) -> dict[str, int]:
    """只读取旧目录；实际迁入会复制图片到采集工作区，绝不删除旧文件。"""
    meta = _CATCHPICS_DIRECTORIES.get(root.name)
    if meta is None:
        raise ValueError("仅支持迁移 catchPics 中已登记的两个历史目录")
    script_key = root.name
    base_url = meta["base_url"]
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
        _bind_historical_script(db, source, script_key, meta["page_format_key"])
        stats["sources"] = 1
    else:
        if db.scalar(select(AcquisitionSourceScript).where(AcquisitionSourceScript.source_id == source.id, AcquisitionSourceScript.script_key == script_key)) is None:
            _bind_historical_script(db, source, script_key, meta["page_format_key"])
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
            run = AcquisitionRun(
                id=uuid4().hex,
                workspace_id=workspace_id,
                source_id=source.id,
                category_id=category.id,
                script_key=script_key,
                script_name_snapshot=meta["script_name"],
                script_version_snapshot=meta["script_version"],
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
