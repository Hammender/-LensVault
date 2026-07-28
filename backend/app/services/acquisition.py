from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
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
    GalleryPhoto,
)
from app.services.importer import PictureService
from app.services.acquisition_adapters import (
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
    compute_perceptual_features,
    cosine_similarity,
    hash_similarity,
    open_normalized_image,
)
from app.services.storage import MinioStorage


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


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
    }

    def __init__(
        self,
        storage: MinioStorage,
        pictures: PictureService,
        settings: Settings | None = None,
        similarity_extractor: DinoV2FeatureExtractor | None = None,
        similarity_scanner: GallerySimilarityScanner | None = None,
    ) -> None:
        self.storage = storage
        self.pictures = pictures
        self.settings = settings or get_settings()
        self.similarity_scanner = similarity_scanner
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
        base_url: str,
        notes: str | None = None,
    ) -> AcquisitionSource:
        self._validate_http_url(base_url, "网站 URL")
        source = AcquisitionSource(
            workspace_id=workspace_id,
            name=name.strip(),
            adapter_key="",
            base_url=base_url.strip(),
            notes=(notes or "").strip() or None,
        )
        db.add(source)
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
        db.commit()
        db.refresh(binding)
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
    ) -> AcquisitionCategory:
        self._validate_category_url(source, crawl_url)
        category = AcquisitionCategory(
            source_id=source.id,
            parent_id=None,
            name=name.strip(),
            path=name.strip(),
            crawl_url=crawl_url.strip(),
            notes=(notes or "").strip() or None,
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
        for field in ("name", "crawl_url", "notes", "enabled"):
            if field in values and values[field] is not None:
                setattr(category, field, values[field])
        if "name" in values and values["name"] is not None:
            category.path = str(values["name"])
        db.commit()
        db.refresh(category)
        return category

    def _validate_category_url(self, source: AcquisitionSource, crawl_url: str) -> None:
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
        if mode not in {"incremental", "verify"}:
            raise ValueError("采集模式必须为 incremental 或 verify")
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
        defaults = json.loads(binding.default_parameters_json or "{}")
        validated_parameters = definition.validate_parameters({**defaults, **(parameters or {})})
        active = db.scalar(
            select(AcquisitionRun).where(
                AcquisitionRun.category_id == category.id,
                AcquisitionRun.status.in_(("pending", "running")),
            )
        )
        if active is not None:
            raise ValueError("该分类已有正在运行的采集任务")
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

    def _download(self, url: str, referer: str) -> tuple[bytes, str | None]:
        request = Request(
            url,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": referer,
                "User-Agent": "PictureShow acquisition/1.0",
            },
        )
        last_error: Exception | None = None
        for _ in range(self.settings.acquisition_download_retries):
            try:
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
            except Exception as exc:  # noqa: PERF203 - 保留最后一次远端错误
                last_error = exc
                if is_tls_transport_error(exc):
                    try:
                        return curl_request_bytes(
                            url,
                            "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                            referer,
                            self.settings.acquisition_download_timeout_seconds,
                            self.settings.acquisition_max_file_bytes,
                            self.settings.acquisition_download_retries,
                        )
                    except Exception as fallback_exc:
                        last_error = fallback_exc
                        break
        raise RuntimeError(str(last_error or "下载失败"))

    def _download_remote(self, remote: RemoteItem, referer: str) -> tuple[bytes, str | None]:
        candidates = list(remote.candidate_urls or (remote.source_url,))
        errors: list[str] = []
        index = 0
        while index < len(candidates):
            candidate = candidates[index]
            index += 1
            try:
                payload, content_type = self._download(candidate, referer)
                if "/get_cache_url?" in candidate:
                    cache_payload = json.loads(payload.decode("utf-8"))
                    cache_url = str(cache_payload.get("url") or "").strip()
                    if cache_url and cache_url not in candidates:
                        candidates.insert(index, cache_url)
                    continue
                if content_type and not content_type.lower().startswith("image/"):
                    errors.append(f"{candidate}: 返回类型 {content_type}")
                    continue
                return payload, content_type
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
        raise RuntimeError("；".join(errors) or "没有可下载的图片地址")

    def _quality(self, payload: bytes) -> tuple[int, int, float, list[str]]:
        image = Image.open(BytesIO(payload))
        image.load()
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

    def _asset_key(self, workspace_id: int | None, asset_id: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".bin"
        prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}acquisition/assets/{asset_id}{suffix}"

    @staticmethod
    def _has_completed_full_scan(db: Session, category_id: int, script_key: str) -> bool:
        parameter_snapshots = db.scalars(
            select(AcquisitionRun.parameters_json).where(
                AcquisitionRun.category_id == category_id,
                AcquisitionRun.script_key == script_key,
                AcquisitionRun.status == "completed",
            )
        ).all()
        for snapshot in parameter_snapshots:
            try:
                parameters = json.loads(snapshot or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if parameters.get("max_pages") in (None, "", 0, "0"):
                return True
        return False

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
        known_external_keys: set[str] = set()
        if self._has_completed_full_scan(db, category.id, definition.key):
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
        run.started_at = datetime.utcnow()
        db.commit()
        try:
            parameters = json.loads(run.parameters_json or "{}")
            for remote in definition.adapter.enumerate(
                run.category_url_snapshot or category.crawl_url,
                parameters,
                known_external_keys,
                run.mode == "incremental",
            ):
                self._process_remote_item(db, run, source, category, remote)
            run.status = "completed"
            run.completed_at = datetime.utcnow()
        except Exception as exc:
            db.rollback()
            run = db.get(AcquisitionRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.utcnow()
        db.commit()

    def _process_remote_item(
        self,
        db: Session,
        run: AcquisitionRun,
        source: AcquisitionSource,
        category: AcquisitionCategory,
        remote: RemoteItem,
    ) -> None:
        now = datetime.utcnow()
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
            return
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
            return
        if run.mode == "incremental" and item.status in self.terminal_source_statuses:
            run_item.status = "skipped"
            run_item.collection_outcome = "source_skipped"
            run.skipped_count += 1
            db.commit()
            return
        if item.status == "failed" and item.failed_at and now - item.failed_at < timedelta(hours=self.settings.acquisition_failed_retry_hours):
            run_item.status = "skipped"
            run_item.collection_outcome = "source_skipped"
            run.skipped_count += 1
            db.commit()
            return
        try:
            payload, content_type = self._download_remote(remote, run.category_url_snapshot or category.crawl_url)
            filename = Path(urlparse(remote.source_url).path).name or f"{remote.external_key}.img"
            width, height, blur, warnings = self._quality(payload)
            sha256 = hashlib.sha256(payload).hexdigest()
            run.download_success_count += 1
            existing_gallery = db.scalar(
                select(GalleryPhoto).where(
                    GalleryPhoto.workspace_id == run.workspace_id,
                    GalleryPhoto.sha256 == sha256,
                    GalleryPhoto.is_rich_text.is_(False),
                )
            )
            if existing_gallery is not None:
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
                return
            asset = db.scalar(
                select(AcquisitionAsset).where(
                    AcquisitionAsset.workspace_id == run.workspace_id,
                    AcquisitionAsset.sha256 == sha256,
                )
            )
            if asset is None:
                asset_id = uuid4().hex
                object_key = self._asset_key(run.workspace_id, asset_id, filename)
                self.storage.put_bytes(object_key, payload, content_type)
                asset = AcquisitionAsset(
                    id=asset_id,
                    workspace_id=run.workspace_id,
                    sha256=sha256,
                    filename=filename,
                    content_type=content_type or mimetypes.guess_type(filename)[0],
                    object_key=object_key,
                    size_bytes=len(payload),
                    width=width,
                    height=height,
                    blur_score=blur,
                    quality_warnings=json.dumps(warnings, ensure_ascii=False),
                )
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
        except Exception as exc:
            db.rollback()
            run = db.get(AcquisitionRun, run.id)
            item = db.get(AcquisitionSourceItem, item.id)
            run_item = db.scalar(
                select(AcquisitionRunItem).where(
                    AcquisitionRunItem.run_id == run.id,
                    AcquisitionRunItem.source_item_id == item.id,
                )
            )
            if run_item is None:
                raise RuntimeError("采集运行条目检查点丢失") from exc
            item.status = "failed"
            item.last_error = str(exc)
            item.failed_at = now
            run_item.status = "failed"
            run_item.collection_outcome = "failed"
            run_item.error_message = str(exc)
            run.error_count += 1
        db.commit()

    def reject_assets(self, db: Session, workspace_id: int | None, asset_ids: list[str]) -> int:
        assets = db.scalars(
            select(AcquisitionAsset).where(AcquisitionAsset.workspace_id == workspace_id, AcquisitionAsset.id.in_(asset_ids))
        ).all()
        for asset in assets:
            if asset.object_key:
                self.storage.remove_object(asset.object_key)
            asset.object_key = None
            asset.status = "rejected"
            for run_item in db.scalars(select(AcquisitionRunItem).where(AcquisitionRunItem.asset_id == asset.id)).all():
                run_item.status = "rejected"
                source_item = db.get(AcquisitionSourceItem, run_item.source_item_id)
                if source_item is not None:
                    source_item.status = "rejected"
        db.commit()
        return len(assets)

    def create_import_batch(
        self,
        db: Session,
        workspace_id: int | None,
        asset_ids: list[str],
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
            total_count=len(ordered_ids),
        )
        db.add(batch)
        for ordinal, asset_id in enumerate(ordered_ids):
            db.add(AcquisitionImportBatchItem(batch_id=batch.id, asset_id=asset_id, ordinal=ordinal))
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
        batch.started_at = batch.started_at or datetime.utcnow()
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
                gallery_photo = self._gallery_photo_by_sha(db, batch.workspace_id, asset.sha256)
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
                gallery_photo = self._gallery_photo_by_sha(db, batch.workspace_id, asset.sha256) if batch and asset else None
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

    def import_assets(self, db: Session, workspace_id: int | None, asset_ids: list[str]) -> dict[str, int]:
        """兼容内部调用；新的 API 会先持久化批次再交给后台处理。"""
        batch = self.create_import_batch(db, workspace_id, asset_ids)
        self.process_import_batch(db, batch.id)
        db.refresh(batch)
        return {"imported": batch.imported_count, "duplicates": batch.duplicate_count}

    @staticmethod
    def _gallery_photo_by_sha(db: Session, workspace_id: int | None, sha256: str) -> GalleryPhoto | None:
        return db.scalar(
            select(GalleryPhoto).where(
                GalleryPhoto.workspace_id == workspace_id,
                GalleryPhoto.sha256 == sha256,
                GalleryPhoto.is_rich_text.is_(False),
            )
        )

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

    def _cleanup_asset_object(self, db: Session, asset: AcquisitionAsset, commit: bool = True) -> None:
        if not asset.object_key:
            return
        object_key = asset.object_key
        try:
            self.storage.remove_object(object_key)
        except Exception as exc:
            asset.error_message = f"临时文件待清理：{exc}"
        else:
            asset.object_key = None
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
            batch.completed_at = datetime.utcnow()

    def scan_similarity(
        self,
        db: Session,
        workspace_id: int | None,
        scan_task_id: str | None = None,
        progress: Callable[[float, str], None] | None = None,
    ) -> int:
        # 扫描由用户手动触发，只创建人工审核提示，不会自动删除或合并图片。
        assets = db.scalars(
            select(AcquisitionAsset).where(
                AcquisitionAsset.workspace_id == workspace_id,
                AcquisitionAsset.status == "pending_review",
                AcquisitionAsset.object_key.is_not(None),
            )
            .order_by(AcquisitionAsset.created_at.asc(), AcquisitionAsset.id.asc())
        ).all()
        asset_payloads: dict[str, bytes] = {}
        fingerprints = {}
        asset_count = len(assets)
        if progress:
            progress(0.05, f"准备扫描 {asset_count} 张待审核图片")
        for index, asset in enumerate(assets):
            try:
                payload = self.storage.get_bytes(asset.object_key or "")
                asset_payloads[asset.id] = payload
                fingerprints[asset.id] = compute_perceptual_features(payload)
            except Exception:
                continue
            if progress and (index % 5 == 0 or index + 1 == asset_count):
                progress(0.05 + 0.3 * (index + 1) / max(1, asset_count), f"读取图片 {index + 1}/{asset_count}")
        asset_vectors = self._encode_similarity_vectors(asset_payloads)
        candidates: list[AcquisitionSimilarityCandidate] = []
        comparable_assets = [asset for asset in assets if asset.id in fingerprints and asset.id in asset_vectors]
        pair_total = len(comparable_assets) * (len(comparable_assets) - 1) // 2
        compared = 0
        for index, asset in enumerate(assets):
            if asset.id not in fingerprints or asset.id not in asset_vectors:
                continue
            for other in assets[index + 1 :]:
                if other.id not in fingerprints or other.id not in asset_vectors:
                    continue
                hash_score = (hash_similarity(fingerprints[asset.id].phash, fingerprints[other.id].phash) + hash_similarity(fingerprints[asset.id].dhash, fingerprints[other.id].dhash)) / 2
                vector_score = cosine_similarity(asset_vectors[asset.id], asset_vectors[other.id])
                score = max(hash_score, vector_score)
                if hash_score >= self.settings.gallery_similarity_near_threshold or vector_score >= self.settings.gallery_similarity_scene_threshold:
                    candidates.append(AcquisitionSimilarityCandidate(
                        workspace_id=workspace_id,
                        scan_task_id=scan_task_id,
                        asset_id=asset.id,
                        other_asset_id=other.id,
                        score=score,
                    ))
                compared += 1
                if progress and (compared % 100 == 0 or compared == pair_total):
                    progress(0.45 + 0.5 * compared / max(1, pair_total), f"比对图片 {compared}/{pair_total}")
        db.query(AcquisitionSimilarityCandidate).filter(
            AcquisitionSimilarityCandidate.workspace_id == workspace_id
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
                query = query.where(AcquisitionImportedPhoto.created_at >= datetime.fromisoformat(str(filters["date_from"])))
            if filters.get("date_to"):
                query = query.where(AcquisitionImportedPhoto.created_at <= datetime.fromisoformat(str(filters["date_to"])))
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
                                "created_at": datetime.utcnow().isoformat(),
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
            job.filename = f"acquisition_export_{datetime.utcnow():%Y%m%d_%H%M%S}.zip"
            job.item_count = exported
            job.missing_count = len(missing)
            job.completed_at = datetime.utcnow()
            job.expires_at = datetime.utcnow() + timedelta(hours=self.settings.acquisition_export_ttl_hours)
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
        db.commit()

    def cleanup_expired_exports(self, db: Session) -> int:
        jobs = db.scalars(
            select(AcquisitionExportJob).where(
                AcquisitionExportJob.status == "ready",
                AcquisitionExportJob.expires_at.is_not(None),
                AcquisitionExportJob.expires_at < datetime.utcnow(),
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
                photo = self._gallery_photo_by_sha(db, batch.workspace_id, asset.sha256) if asset else None
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
            run.download_success_count = run.candidate_count + run.content_duplicate_count + run.gallery_duplicate_count
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
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
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
