from __future__ import annotations

import io
import hashlib
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
from PIL import Image
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db import Base
from app.api.acquisition import list_asset_ids, list_history, list_import_batch_items, list_import_batches, list_sources
from app.lifecycle import ensure_acquisition_schema
from app.models import (
    AcquisitionAsset,
    AcquisitionCategory,
    AcquisitionImportBatch,
    AcquisitionImportBatchItem,
    AcquisitionImportedPhoto,
    AcquisitionRunItem,
    AcquisitionRun,
    AcquisitionScript,
    AcquisitionSimilarityCandidate,
    AcquisitionSourceItem,
    AcquisitionSource,
    GalleryPhoto,
)
from app.services.acquisition import AcquisitionService
from app.services.acquisition_adapters import (
    RaindropPageAdapter,
    RaindropWorkersAdapter,
    RemoteItem,
    RemotePage,
    curl_request_bytes,
    get_script,
    script_catalog,
    stable_key,
)


class AcquisitionAdapterTests(unittest.TestCase):
    def test_registered_script_names_match_catchpics_directories(self) -> None:
        catalog = script_catalog()
        self.assertEqual(
            {item["name"] for item in catalog},
            {"raindrop-ftxsri-workers-dev", "shfwzwz-raindrop-page"},
        )
        self.assertEqual({item["version"] for item in catalog}, {"1.0.2", "1.2.0"})

    def test_raindrop_page_normalizes_relative_image_urls(self) -> None:
        payload = (
            b'<article><img src="/images/a.jpg" alt="A">'
            b'<a href="https://cdn.example.test/a.jpg">source</a></article>'
        )
        with patch(
            "app.services.acquisition_adapters._request_bytes",
            return_value=(payload, "text/html; charset=utf-8"),
        ):
            items = list(
                RaindropPageAdapter().enumerate(
                    "https://shfwzwz.raindrop.page/album",
                    {"max_pages": 1},
                    set(),
                    False,
                )
            )
        self.assertEqual(items[0].source_url, "https://cdn.example.test/a.jpg")
        self.assertEqual(items[0].preview_url, "https://shfwzwz.raindrop.page/images/a.jpg")
        self.assertTrue(items[0].external_key)

    def test_raindrop_page_skips_items_repeated_across_dynamic_pages(self) -> None:
        first_page = (
            b'<a href="/album/sort=-created&amp;perpage=30&amp;page=1">next</a>'
            b'<span>60 bookmarks</span>'
            b'<article><a href="https://cdn.example.test/a.jpg">a</a></article>'
            b'<article><a href="https://cdn.example.test/shared.jpg">shared</a></article>'
        )
        second_page = (
            b'<article><a href="https://cdn.example.test/shared.jpg">shared</a></article>'
            b'<article><a href="https://cdn.example.test/c.jpg">c</a></article>'
        )
        with patch(
            "app.services.acquisition_adapters._request_bytes",
            side_effect=[
                (first_page, "text/html; charset=utf-8"),
                (second_page, "text/html; charset=utf-8"),
            ],
        ) as request:
            items = list(
                RaindropPageAdapter().enumerate(
                    "https://shfwzwz.raindrop.page/album/sort=-created&perpage=30&page=0",
                    {},
                    set(),
                    False,
                )
            )

        self.assertEqual(len(items), 3)
        self.assertEqual(request.call_count, 2)

    def test_raindrop_page_scans_inclusive_one_based_page_range(self) -> None:
        first_page = (
            b'<span>90 bookmarks</span>'
            b'<article><a href="https://cdn.example.test/a.jpg">a</a></article>'
        )
        second_page = b'<article><a href="https://cdn.example.test/b.jpg">b</a></article>'
        third_page = b'<article><a href="https://cdn.example.test/c.jpg">c</a></article>'
        with patch(
            "app.services.acquisition_adapters._request_bytes",
            side_effect=[
                (first_page, "text/html; charset=utf-8"),
                (second_page, "text/html; charset=utf-8"),
                (third_page, "text/html; charset=utf-8"),
            ],
        ) as request:
            pages = list(
                RaindropPageAdapter().enumerate_pages(
                    "https://shfwzwz.raindrop.page/album",
                    {"start_page": 2, "end_page": 3},
                    set(),
                    True,
                )
            )

        self.assertEqual([page.page_number for page in pages], [2, 3])
        self.assertEqual([page.items[0].source_url for page in pages], [
            "https://cdn.example.test/b.jpg",
            "https://cdn.example.test/c.jpg",
        ])
        self.assertEqual(pages[-1].stop_reason, "collection_end")
        self.assertEqual(request.call_count, 3)

    def test_raindrop_page_full_mode_ignores_known_page_early_stop(self) -> None:
        first_page = (
            b'<span>60 bookmarks</span>'
            b'<article><a href="https://cdn.example.test/a.jpg">a</a></article>'
        )
        second_page = b'<article><a href="https://cdn.example.test/b.jpg">b</a></article>'
        known = {stable_key("https://cdn.example.test/a.jpg")}
        with patch(
            "app.services.acquisition_adapters._request_bytes",
            return_value=(first_page, "text/html; charset=utf-8"),
        ):
            normal_pages = list(
                RaindropPageAdapter().enumerate_pages(
                    "https://shfwzwz.raindrop.page/album",
                    {"start_page": 1},
                    known,
                    True,
                )
            )
        with patch(
            "app.services.acquisition_adapters._request_bytes",
            side_effect=[
                (first_page, "text/html; charset=utf-8"),
                (second_page, "text/html; charset=utf-8"),
            ],
        ):
            forced_pages = list(
                RaindropPageAdapter().enumerate_pages(
                    "https://shfwzwz.raindrop.page/album",
                    {"start_page": 1},
                    known,
                    False,
                )
            )

        self.assertEqual([page.stop_reason for page in normal_pages], ["known_page"])
        self.assertEqual([page.page_number for page in forced_pages], [1, 2])
        self.assertEqual(forced_pages[-1].stop_reason, "collection_end")

    def test_curl_fallback_uses_system_routing_and_complete_retry_budget(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="text/html", stderr="")
        with patch("app.services.acquisition_adapters.shutil.which", return_value="curl.exe"), patch(
            "app.services.acquisition_adapters.subprocess.run",
            return_value=completed,
        ) as run:
            payload, content_type = curl_request_bytes(
                "https://shfwzwz.raindrop.page/album",
                "text/html",
                "https://shfwzwz.raindrop.page/album",
                timeout=45,
                retries=3,
            )

        command = run.call_args.args[0]
        self.assertEqual(payload, b"")
        self.assertEqual(content_type, "text/html")
        self.assertIn("--ipv4", command)
        self.assertNotIn("--resolve", command)
        self.assertEqual(command[command.index("--retry") + 1], "2")
        self.assertEqual(command[command.index("--max-time") + 1], "45")
        self.assertEqual(run.call_args.kwargs["timeout"], 147)

    def test_curl_fallback_reports_sanitized_timeout_and_removes_temporary_file(self) -> None:
        temporary_path: Path | None = None

        def expire(command: list[str], **kwargs: object) -> None:
            nonlocal temporary_path
            temporary_path = Path(command[command.index("--output") + 1])
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with patch("app.services.acquisition_adapters.shutil.which", return_value="curl.exe"), patch(
            "app.services.acquisition_adapters.subprocess.run",
            side_effect=expire,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "请求 shfwzwz.raindrop.page 超时：最多尝试 3 次，每次 45 秒",
            ) as raised:
                curl_request_bytes(
                    "https://shfwzwz.raindrop.page/private-path",
                    "text/html",
                    "https://shfwzwz.raindrop.page/private-path",
                    timeout=45,
                    retries=3,
                )

        self.assertNotIn("private-path", str(raised.exception))
        self.assertIsNotNone(temporary_path)
        self.assertFalse(temporary_path.exists())

    def test_raindrop_workers_uses_stable_record_key(self) -> None:
        payload = json.dumps(
            {"items": [{"_id": "remote-17", "type": "image", "link": "https://cdn.example.test/a.jpg"}]}
        ).encode()
        with patch(
            "app.services.acquisition_adapters._request_bytes",
            return_value=(payload, "application/json"),
        ):
            items = list(
                RaindropWorkersAdapter().enumerate(
                    "https://raindrop.ftxsri.workers.dev/collection-1",
                    {"max_pages": 1},
                    set(),
                    True,
                )
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_key, "remote-17")
        self.assertEqual(items[0].source_url, "https://cdn.example.test/a.jpg")

    def test_script_parameters_are_validated(self) -> None:
        definition = get_script("raindrop-ftxsri-workers-dev")
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.validate_parameters({}), {})
        self.assertEqual(definition.validate_parameters({"max_pages": "2"}), {"max_pages": 2})
        with self.assertRaisesRegex(ValueError, "不能小于"):
            definition.validate_parameters({"max_pages": 0})
        with self.assertRaisesRegex(ValueError, "未知参数"):
            definition.validate_parameters({"category_name": "不能传给脚本"})

        page_definition = get_script("shfwzwz-raindrop-page")
        assert page_definition is not None
        self.assertEqual(
            page_definition.validate_parameters({"max_pages": "3"}),
            {"start_page": 1, "end_page": 3},
        )
        self.assertEqual(
            page_definition.validate_parameters({"start_page": "2", "end_page": "4"}),
            {"start_page": 2, "end_page": 4},
        )
        with self.assertRaisesRegex(ValueError, "未知参数"):
            page_definition.validate_parameters({"force_full_scan": True})
        with self.assertRaisesRegex(ValueError, "结束页不能小于起始页"):
            page_definition.validate_parameters({"start_page": 4, "end_page": 2})


class AcquisitionModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.service = AcquisitionService(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_site_script_category_and_run_snapshots(self) -> None:
        source = self.service.create_source(
            self.db,
            None,
            "我的采集网站",
            "https://raindrop.ftxsri.workers.dev",
            "站点备注",
        )
        binding = self.service.bind_script(self.db, source, "raindrop-ftxsri-workers-dev", {"max_pages": 3})
        category = self.service.create_category(
            self.db,
            source,
            "这个名字仅用于展示",
            "https://raindrop.ftxsri.workers.dev/collection-1",
            "分类备注",
        )
        run = self.service.start_run(
            self.db,
            None,
            category,
            "raindrop-ftxsri-workers-dev",
            "incremental",
            {"max_pages": 2},
        )

        self.assertEqual(binding.script_key, "raindrop-ftxsri-workers-dev")
        self.assertEqual(source.page_format_key, "raindrop-workers-json-v1")
        self.assertEqual(run.source_name_snapshot, "我的采集网站")
        self.assertEqual(run.category_name_snapshot, "这个名字仅用于展示")
        self.assertEqual(run.category_url_snapshot, category.crawl_url)
        self.assertEqual(json.loads(run.parameters_json), {"max_pages": 2})

    def test_legacy_force_parameter_maps_to_full_mode_and_is_not_persisted(self) -> None:
        source = self.service.create_source(
            self.db,
            None,
            "旧参数兼容站点",
            "https://shfwzwz.raindrop.page",
        )
        self.service.bind_script(self.db, source, "shfwzwz-raindrop-page")
        category = self.service.create_category(
            self.db,
            source,
            "旧参数兼容分类",
            "https://shfwzwz.raindrop.page/collection",
        )

        with patch("app.services.acquisition.ensure_perceptual_feature_dependencies"):
            run = self.service.start_run(
                self.db,
                None,
                category,
                "shfwzwz-raindrop-page",
                "incremental",
                {"start_page": 2, "end_page": 4, "force_full_scan": True},
            )

        self.assertEqual(run.mode, "full")
        self.assertEqual(json.loads(run.parameters_json), {"start_page": 2, "end_page": 4})

    def test_missing_image_analysis_dependencies_prevent_run_creation(self) -> None:
        source = self.service.create_source(
            self.db,
            None,
            "依赖预检站点",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, "raindrop-ftxsri-workers-dev")
        category = self.service.create_category(
            self.db,
            source,
            "依赖预检分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )

        with patch(
            "app.services.acquisition.ensure_perceptual_feature_dependencies",
            side_effect=RuntimeError("图片分析依赖不可用：ImageHash"),
        ), self.assertRaisesRegex(ValueError, "图片分析依赖不可用"):
            self.service.start_run(self.db, None, category, "raindrop-ftxsri-workers-dev", "incremental", {})

        self.assertEqual(self.db.query(AcquisitionRun).count(), 0)

    def test_full_mode_skips_successes_and_immediately_retries_failures(self) -> None:
        definition = get_script("raindrop-ftxsri-workers-dev")
        assert definition is not None
        source = self.service.create_source(
            self.db,
            None,
            "全量发现测试站点",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, definition.key)
        category = self.service.create_category(
            self.db,
            source,
            "全量发现测试分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )
        with patch("app.services.acquisition.ensure_perceptual_feature_dependencies"):
            run = self.service.start_run(self.db, None, category, definition.key, "full", {})

        successful_remote = RemoteItem("successful", "https://cdn.example.test/successful.jpg")
        failed_remote = RemoteItem("failed", "https://cdn.example.test/failed.jpg")
        for remote, status in ((successful_remote, "pending_review"), (failed_remote, "failed")):
            self.db.add(AcquisitionSourceItem(
                source_id=source.id,
                category_id=category.id,
                script_key=definition.key,
                external_key=hashlib.sha256(f"{category.id}:{definition.key}:{remote.external_key}".encode()).hexdigest(),
                remote_external_key=remote.external_key,
                source_url=remote.source_url,
                status=status,
            ))
        self.db.commit()

        skipped = self.service._prepare_remote_item(self.db, run, source, category, successful_remote)
        retried = self.service._prepare_remote_item(self.db, run, source, category, failed_remote)

        self.assertIsNone(skipped)
        self.assertIsNotNone(retried)
        self.assertEqual(run.skipped_count, 1)

        run.status = "interrupted"
        self.db.commit()
        with patch("app.services.acquisition.ensure_perceptual_feature_dependencies"):
            verify_run = self.service.start_run(self.db, None, category, definition.key, "verify", {})
        verified = self.service._prepare_remote_item(self.db, verify_run, source, category, successful_remote)
        self.assertIsNotNone(verified)

    def test_failed_sources_disable_incremental_known_page_early_stop(self) -> None:
        definition = get_script("raindrop-ftxsri-workers-dev")
        assert definition is not None
        source = self.service.create_source(
            self.db,
            None,
            "失败来源增量测试站点",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, definition.key)
        category = self.service.create_category(
            self.db,
            source,
            "失败来源增量测试分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )
        with patch("app.services.acquisition.ensure_perceptual_feature_dependencies"):
            baseline = self.service.start_run(self.db, None, category, definition.key, "incremental", {})
        baseline.status = "completed"
        baseline.scan_start_page = 1
        baseline.reached_collection_end = True
        self.db.add(AcquisitionSourceItem(
            source_id=source.id,
            category_id=category.id,
            script_key=definition.key,
            external_key="failed-source",
            remote_external_key="failed-source",
            source_url="https://cdn.example.test/failed.jpg",
            status="failed",
        ))
        self.db.commit()
        with patch("app.services.acquisition.ensure_perceptual_feature_dependencies"):
            retry_run = self.service.start_run(self.db, None, category, definition.key, "incremental", {})

        with patch.object(definition.adapter, "enumerate_pages", return_value=[]) as enumerate_pages:
            self.service.process_run(self.db, retry_run.id)

        self.assertEqual(enumerate_pages.call_args.args[2], set())
        self.assertTrue(enumerate_pages.call_args.args[3])

    def test_only_completed_error_free_run_reaching_collection_end_establishes_incremental_baseline(self) -> None:
        definition = get_script("raindrop-ftxsri-workers-dev")
        assert definition is not None
        self.db.add(
            AcquisitionScript(
                key=definition.key,
                name=definition.name,
                version=definition.version,
                page_format_key=definition.page_format_key,
                parameter_schema_json="[]",
            )
        )
        self.db.commit()
        source = self.service.create_source(
            self.db,
            None,
            "增量基线测试站点",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, definition.key)
        category = self.service.create_category(
            self.db,
            source,
            "增量基线测试分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )
        run = self.service.start_run(
            self.db,
            None,
            category,
            definition.key,
            "incremental",
            {"max_pages": 2},
        )

        run.status = "completed"
        self.db.commit()
        self.assertFalse(self.service._has_completed_full_scan(self.db, category.id, definition.key))

        run.status = "interrupted"
        run.scan_start_page = 1
        run.reached_collection_end = True
        self.db.commit()
        self.assertFalse(self.service._has_completed_full_scan(self.db, category.id, definition.key))

        run.status = "completed"
        self.db.commit()
        self.assertTrue(self.service._has_completed_full_scan(self.db, category.id, definition.key))

        run.error_count = 1
        self.db.commit()
        self.assertFalse(self.service._has_completed_full_scan(self.db, category.id, definition.key))

    def test_site_rejects_other_page_format_and_external_category_url(self) -> None:
        source = self.service.create_source(
            self.db,
            None,
            "格式固定的网站",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, "raindrop-ftxsri-workers-dev")

        with self.assertRaisesRegex(ValueError, "网页格式"):
            self.service.bind_script(self.db, source, "shfwzwz-raindrop-page")
        with self.assertRaisesRegex(ValueError, "当前站点"):
            self.service.create_category(self.db, source, "错误分类", "https://example.com/collection")

    def test_legacy_adapter_binding_is_migrated_without_deleting_site(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE acquisition_sources ("
                    "id INTEGER PRIMARY KEY, workspace_id INTEGER, name VARCHAR(128) NOT NULL, "
                    "adapter_key VARCHAR(64) NOT NULL, base_url VARCHAR(1024), enabled BOOLEAN NOT NULL DEFAULT 1, "
                    "settings_json TEXT, created_at DATETIME, updated_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO acquisition_sources (id, name, adapter_key) "
                    "VALUES (1, 'raindrop.ftxsri.workers.dev', 'raindrop-workers'), "
                    "(2, '用户自定义站点名', 'raindrop-workers')"
                )
            )
        Base.metadata.create_all(engine)

        ensure_acquisition_schema(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("acquisition_sources")}
        with engine.connect() as connection:
            source = connection.execute(
                text("SELECT name, base_url, page_format_key FROM acquisition_sources WHERE id=1")
            ).mappings().one()
            binding = connection.execute(
                text("SELECT script_key FROM acquisition_source_scripts WHERE source_id=1")
            ).scalar_one()
            custom_name = connection.execute(
                text("SELECT name FROM acquisition_sources WHERE id=2")
            ).scalar_one()
        self.assertIn("notes", columns)
        self.assertEqual(source["name"], "raindrop-ftxsri-workers-dev")
        self.assertEqual(source["base_url"], "https://raindrop.ftxsri.workers.dev")
        self.assertEqual(source["page_format_key"], "raindrop-workers-json-v1")
        self.assertEqual(binding, "raindrop-ftxsri-workers-dev")
        self.assertEqual(custom_name, "用户自定义站点名")
        engine.dispose()

    def test_schema_migration_restores_deferred_assets_to_pending_review(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO acquisition_assets (id, sha256, filename, size_bytes, status, created_at, updated_at) "
                "VALUES ('legacy-deferred', :sha256, 'legacy.jpg', 0, 'deferred', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"sha256": "d" * 64})

        ensure_acquisition_schema(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("acquisition_similarity_candidates")}
        asset_indexes = {index["name"] for index in inspect(engine).get_indexes("acquisition_assets")}
        with engine.connect() as connection:
            status = connection.execute(text(
                "SELECT status FROM acquisition_assets WHERE id = 'legacy-deferred'"
            )).scalar_one()
        self.assertIn("scan_task_id", columns)
        self.assertIn("ix_acquisition_assets_perceptual_phash", asset_indexes)
        self.assertIn("ix_acquisition_assets_perceptual_dhash", asset_indexes)
        self.assertEqual(status, "pending_review")
        engine.dispose()

    def test_process_run_rolls_back_before_recording_database_failure(self) -> None:
        definition = get_script("raindrop-ftxsri-workers-dev")
        assert definition is not None
        self.db.add(
            AcquisitionScript(
                key=definition.key,
                name=definition.name,
                version=definition.version,
                page_format_key=definition.page_format_key,
                parameter_schema_json="[]",
            )
        )
        self.db.commit()
        source = self.service.create_source(
            self.db,
            None,
            "事务回滚测试站点",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, definition.key)
        category = self.service.create_category(
            self.db,
            source,
            "事务回滚测试分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )
        run = self.service.start_run(self.db, None, category, definition.key, "incremental", {})
        source_item = AcquisitionSourceItem(
            source_id=source.id,
            category_id=category.id,
            script_key=definition.key,
            external_key="scoped-remote-a",
            remote_external_key="remote-a",
            source_url="https://cdn.example.test/a.jpg",
        )
        self.db.add(source_item)
        self.db.flush()
        self.db.add(AcquisitionRunItem(run_id=run.id, source_item_id=source_item.id))
        self.db.commit()

        def violate_unique_constraint(db: Session, *_args: object) -> None:
            db.add(AcquisitionRunItem(run_id=run.id, source_item_id=source_item.id))
            db.flush()

        with (
            patch.object(
                definition.adapter,
                "enumerate_pages",
                return_value=[RemotePage(1, (RemoteItem("remote-a", "https://cdn.example.test/a.jpg"),), "collection_end")],
            ),
            patch.object(self.service, "_prepare_remote_item", side_effect=violate_unique_constraint),
        ):
            self.service.process_run(self.db, run.id)

        self.db.refresh(run)
        self.assertEqual(run.status, "failed")
        self.assertIsNotNone(run.completed_at)
        self.assertIn("UNIQUE constraint failed", run.error_message or "")

    def test_process_run_downloads_eight_items_concurrently(self) -> None:
        definition = get_script("raindrop-ftxsri-workers-dev")
        assert definition is not None
        self.db.add(
            AcquisitionScript(
                key=definition.key,
                name=definition.name,
                version=definition.version,
                page_format_key=definition.page_format_key,
                parameter_schema_json="[]",
            )
        )
        self.db.commit()
        source = self.service.create_source(
            self.db,
            None,
            "并发下载测试站点",
            "https://raindrop.ftxsri.workers.dev",
        )
        self.service.bind_script(self.db, source, definition.key)
        category = self.service.create_category(
            self.db,
            source,
            "并发下载测试分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )
        run = self.service.start_run(self.db, None, category, definition.key, "incremental", {})
        barrier = threading.Barrier(8, timeout=2)
        active = 0
        peak_active = 0
        lock = threading.Lock()

        def download(_remote: RemoteItem, _referer: str) -> object:
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            barrier.wait()
            with lock:
                active -= 1
            return object()

        remotes = tuple(
            RemoteItem(f"remote-{index}", f"https://cdn.example.test/{index}.jpg")
            for index in range(8)
        )
        with (
            patch.object(
                definition.adapter,
                "enumerate_pages",
                return_value=[RemotePage(1, remotes, "collection_end")],
            ),
            patch.object(self.service, "_download_and_analyze", side_effect=download),
            patch.object(self.service, "_persist_downloaded_remote"),
        ):
            self.service.process_run(self.db, run.id)

        self.db.refresh(run)
        self.assertEqual(peak_active, 8)
        self.assertEqual(run.status, "completed")


class AcquisitionQualityTests(unittest.TestCase):
    def test_quality_warnings_do_not_reject_valid_image(self) -> None:
        settings = SimpleNamespace(
            acquisition_quality_min_pixels=512 * 512,
            acquisition_quality_max_aspect_ratio=4.0,
            acquisition_quality_blur_threshold=45.0,
        )
        service = AcquisitionService(SimpleNamespace(), SimpleNamespace(), settings)
        image = Image.new("RGB", (32, 32), color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")

        width, height, _, warnings = service._quality(buffer.getvalue())

        self.assertEqual((width, height), (32, 32))
        self.assertIn("像素较低", warnings)
        self.assertIn("可能模糊", warnings)


class AcquisitionSimilarityTests(unittest.TestCase):
    def test_vector_similarity_can_match_when_perceptual_hashes_do_not(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        image = Image.new("RGB", (32, 32), color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        payload = buffer.getvalue()
        storage = SimpleNamespace(get_bytes=lambda _key: payload)
        extractor = SimpleNamespace(
            encode=lambda images: np.asarray([[1.0, 0.0] for _image in images], dtype=np.float32)
        )
        settings = SimpleNamespace(
            gallery_similarity_batch_size=32,
            gallery_similarity_near_threshold=0.92,
            gallery_similarity_scene_threshold=0.88,
        )
        service = AcquisitionService(storage, SimpleNamespace(), settings, extractor)
        db.add_all(
            [
                AcquisitionAsset(
                    id="asset-a",
                    sha256="a" * 64,
                    filename="a.jpg",
                    object_key="a.jpg",
                    status="pending_review",
                ),
                AcquisitionAsset(
                    id="asset-b",
                    sha256="b" * 64,
                    filename="b.jpg",
                    object_key="b.jpg",
                    status="pending_review",
                ),
                AcquisitionAsset(
                    id="asset-deferred",
                    sha256="c" * 64,
                    filename="deferred.jpg",
                    object_key="deferred.jpg",
                    status="deferred",
                ),
            ]
        )
        db.commit()
        progress_updates: list[tuple[float, str]] = []

        with patch(
            "app.services.acquisition.compute_perceptual_features",
            side_effect=[
                SimpleNamespace(phash="0" * 16, dhash="0" * 16),
                SimpleNamespace(phash="f" * 16, dhash="f" * 16),
            ],
        ):
            created = service.scan_similarity(
                db,
                None,
                scan_task_id="scan-task",
                progress=lambda value, message: progress_updates.append((value, message)),
            )

        candidate = db.query(AcquisitionSimilarityCandidate).one()
        self.assertEqual(created, 1)
        self.assertEqual({candidate.asset_id, candidate.other_asset_id}, {"asset-a", "asset-b"})
        self.assertEqual(candidate.scan_task_id, "scan-task")
        self.assertAlmostEqual(candidate.score, 1.0)
        self.assertTrue(progress_updates)
        self.assertTrue(all("deferred.jpg" not in message for _, message in progress_updates))
        db.close()
        engine.dispose()

    def test_failed_similarity_scan_preserves_previous_results(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        image = Image.new("RGB", (32, 32), color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        payload = buffer.getvalue()
        extractor = SimpleNamespace(encode=lambda _images: (_ for _ in ()).throw(RuntimeError("向量服务不可用")))
        settings = SimpleNamespace(
            gallery_similarity_batch_size=32,
            gallery_similarity_near_threshold=0.92,
            gallery_similarity_scene_threshold=0.88,
        )
        service = AcquisitionService(SimpleNamespace(get_bytes=lambda _key: payload), SimpleNamespace(), settings, extractor)
        db.add_all([
            AcquisitionAsset(id="asset-a", sha256="a" * 64, filename="a.jpg", object_key="a.jpg", status="pending_review"),
            AcquisitionAsset(id="asset-b", sha256="b" * 64, filename="b.jpg", object_key="b.jpg", status="pending_review"),
        ])
        db.flush()
        db.add(AcquisitionSimilarityCandidate(asset_id="asset-a", other_asset_id="asset-b", score=0.95))
        db.commit()

        with self.assertRaisesRegex(RuntimeError, "向量服务不可用"):
            service.scan_similarity(db, None, scan_task_id="failed-scan")
        db.rollback()

        candidate = db.query(AcquisitionSimilarityCandidate).one()
        self.assertAlmostEqual(candidate.score, 0.95)
        self.assertIsNone(candidate.scan_task_id)
        db.close()
        engine.dispose()


class AcquisitionWorkflowTests(unittest.TestCase):
    def test_resolution_variants_keep_only_the_highest_resolution_future_asset(self) -> None:
        class MemoryStorage:
            def __init__(self) -> None:
                self.objects: dict[str, bytes] = {}

            def put_bytes(self, key: str, payload: bytes, _content_type: str | None = None) -> None:
                self.objects[key] = payload

            def get_bytes(self, key: str) -> bytes:
                return self.objects[key]

            def remove_object(self, key: str) -> None:
                self.objects.pop(key, None)

        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(engine)
        db = Session(engine, autoflush=False)
        storage = MemoryStorage()
        settings = SimpleNamespace(
            acquisition_quality_min_pixels=1,
            acquisition_quality_max_aspect_ratio=10.0,
            acquisition_quality_blur_threshold=0.0,
        )
        service = AcquisitionService(storage, SimpleNamespace(), settings)
        definition = get_script("raindrop-ftxsri-workers-dev")
        assert definition is not None
        db.add(AcquisitionScript(
            key=definition.key,
            name=definition.name,
            version=definition.version,
            page_format_key=definition.page_format_key,
            parameter_schema_json="[]",
        ))
        db.commit()
        source = service.create_source(db, None, "清晰度去重站点", "https://raindrop.ftxsri.workers.dev")
        service.bind_script(db, source, definition.key)
        category = service.create_category(
            db,
            source,
            "清晰度去重分类",
            "https://raindrop.ftxsri.workers.dev/collection-1",
        )
        run = service.start_run(db, None, category, definition.key, "incremental", {})

        payloads: list[bytes] = []
        for size in (32, 64, 24):
            image = Image.new("RGB", (size, size), color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG")
            payloads.append(buffer.getvalue())

        with patch.object(
            service,
            "_download_remote",
            side_effect=[(payload, "image/jpeg") for payload in payloads],
        ):
            for index in range(3):
                service._process_remote_item(
                    db,
                    run,
                    source,
                    category,
                    RemoteItem(f"variant-{index}", f"https://cdn.example.test/variant-{index}.jpg"),
                )

        assets = db.query(AcquisitionAsset).all()
        run_items = db.query(AcquisitionRunItem).filter_by(run_id=run.id).all()
        self.assertEqual(len(assets), 1)
        self.assertEqual((assets[0].width, assets[0].height), (64, 64))
        self.assertEqual({item.asset_id for item in run_items}, {assets[0].id})
        self.assertEqual(run.resolution_upgrade_count, 1)
        self.assertEqual(run.resolution_duplicate_count, 1)
        self.assertEqual(len(storage.objects), 1)
        db.close()
        engine.dispose()

    def test_deduplicate_import_trace_export_and_deleted_gallery_snapshot(self) -> None:
        class Stream(io.BytesIO):
            def release_conn(self) -> None:
                pass

        class MemoryStorage:
            def __init__(self) -> None:
                self.objects: dict[str, bytes] = {}

            def put_bytes(self, key: str, payload: bytes, _content_type: str | None = None) -> None:
                self.objects[key] = payload

            def get_bytes(self, key: str) -> bytes:
                return self.objects[key]

            def remove_object(self, key: str) -> None:
                self.objects.pop(key, None)

            def get_stream(self, key: str) -> Stream:
                return Stream(self.objects[key])

            def put_file(self, key: str, path: Path, _content_type: str | None = None) -> None:
                self.objects[key] = path.read_bytes()

        class PictureImporter:
            def __init__(self, storage: MemoryStorage) -> None:
                self.storage = storage

            def import_gallery_photo(
                self,
                db: Session,
                filename: str,
                payload: bytes,
                content_type: str | None,
                *,
                workspace_id: int | None,
                source_object_key: str,
            ) -> tuple[GalleryPhoto, SimpleNamespace]:
                object_key = "gallery/imported.jpg"
                self.storage.put_bytes(object_key, payload, content_type)
                photo = GalleryPhoto(
                    workspace_id=workspace_id,
                    filename=filename,
                    content_type=content_type,
                    sha256=__import__("hashlib").sha256(payload).hexdigest(),
                    object_key=object_key,
                )
                db.add(photo)
                db.flush()
                return photo, SimpleNamespace(duplicated=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine("sqlite+pysqlite:///:memory:")
            with engine.begin() as connection:
                connection.execute(text("PRAGMA foreign_keys=ON"))
            Base.metadata.create_all(engine)
            # 生产会话关闭 autoflush；同一运行的多个来源条目可指向同一 SHA 图片。
            db = Session(engine, autoflush=False)
            storage = MemoryStorage()
            settings = SimpleNamespace(
                acquisition_quality_min_pixels=1,
                acquisition_quality_max_aspect_ratio=10.0,
                acquisition_quality_blur_threshold=0.0,
                acquisition_export_ttl_hours=24,
                gallery_similarity_batch_size=32,
                gallery_similarity_near_threshold=0.92,
                gallery_similarity_scene_threshold=0.88,
                data_dir=Path(temp_dir),
            )
            service = AcquisitionService(
                storage,
                PictureImporter(storage),
                settings,
                SimpleNamespace(encode=lambda images: np.ones((len(images), 2), dtype=np.float32)),
            )
            definition = get_script("raindrop-ftxsri-workers-dev")
            assert definition is not None
            db.add(
                AcquisitionScript(
                    key=definition.key,
                    name=definition.name,
                    version=definition.version,
                    page_format_key=definition.page_format_key,
                    parameter_schema_json="[]",
                )
            )
            db.commit()
            source = service.create_source(
                db, None, "raindrop-ftxsri-workers-dev", "https://raindrop.ftxsri.workers.dev"
            )
            service.bind_script(db, source, definition.key)
            category = service.create_category(
                db,
                source,
                "自定义分类名",
                "https://raindrop.ftxsri.workers.dev/collection-1",
            )
            run = service.start_run(db, None, category, definition.key, "incremental", {})
            image = Image.new("RGB", (32, 32), color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG")
            payload = buffer.getvalue()

            with patch.object(service, "_download_remote", return_value=(payload, "image/jpeg")) as download_remote:
                service._process_remote_item(
                    db, run, source, category, RemoteItem("remote-a", "https://cdn.example.test/a.jpg")
                )
                service._process_remote_item(
                    db, run, source, category, RemoteItem("remote-a", "https://cdn.example.test/a.jpg")
                )
                service._process_remote_item(
                    db, run, source, category, RemoteItem("remote-b", "https://cdn.example.test/b.jpg")
                )

            asset = db.query(AcquisitionAsset).one()
            self.assertEqual(db.query(AcquisitionRunItem).count(), 2)
            self.assertEqual(run.total_count, 2)
            self.assertEqual(run.downloaded_count, 1)
            self.assertEqual(run.download_success_count, 2)
            self.assertEqual(run.candidate_count, 1)
            self.assertEqual(run.content_duplicate_count, 1)
            self.assertEqual(download_remote.call_count, 2)
            self.assertEqual(len(storage.objects), 1)

            run.status = "interrupted"
            db.commit()
            retry_run = service.start_run(db, None, category, definition.key, "incremental", {})
            with patch.object(service, "_download_remote") as retry_download:
                service._process_remote_item(
                    db,
                    retry_run,
                    source,
                    category,
                    RemoteItem("remote-a", "https://cdn.example.test/a.jpg"),
                )
            self.assertEqual(retry_download.call_count, 0)
            self.assertEqual(retry_run.skipped_count, 1)

            result = service.import_assets(db, None, [asset.id])
            provenance = db.query(AcquisitionImportedPhoto).one()
            photo = db.get(GalleryPhoto, provenance.gallery_photo_id)
            assert photo is not None
            self.assertEqual(result, {"imported": 1, "duplicates": 0})
            self.assertEqual(provenance.category_path_snapshot, "自定义分类名")
            self.assertIsNone(asset.object_key)

            context = SimpleNamespace(workspace_id=None)
            self.assertEqual(len(list_sources(db=db, current=context)), 1)
            self.assertEqual(len(list_history(db=db, current=context)), 1)

            job = service.create_export_job(db, None, {"run_id": run.id})
            service.build_export(db, job.id)
            db.refresh(job)
            self.assertEqual(job.status, "ready")
            assert job.object_key is not None
            with ZipFile(io.BytesIO(storage.objects[job.object_key])) as archive:
                metadata = json.loads(archive.read("metadata.json"))
                self.assertEqual(metadata["exported_count"], 1)
                self.assertEqual(len([name for name in archive.namelist() if name.startswith("images/")]), 1)

            db.delete(photo)
            db.commit()
            db.refresh(provenance)
            self.assertIsNone(provenance.gallery_photo_id)
            self.assertEqual(provenance.filename_snapshot, "a.jpg")
            db.close()
            engine.dispose()

    def test_import_batch_persists_selection_and_isolates_item_failures(self) -> None:
        class MemoryStorage:
            def __init__(self, objects: dict[str, bytes]) -> None:
                self.objects = objects

            def get_bytes(self, key: str) -> bytes:
                return self.objects[key]

            def remove_object(self, key: str) -> None:
                self.objects.pop(key, None)

        class SelectiveImporter:
            def import_gallery_photo(
                self,
                db: Session,
                filename: str,
                payload: bytes,
                content_type: str | None,
                **kwargs: object,
            ) -> tuple[GalleryPhoto, SimpleNamespace]:
                if filename == "broken.jpg":
                    raise RuntimeError("模拟单张处理失败")
                photo = GalleryPhoto(
                    workspace_id=kwargs["workspace_id"],
                    filename=filename,
                    content_type=content_type,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    object_key=f"gallery/{filename}",
                )
                db.add(photo)
                db.flush()
                return photo, SimpleNamespace(duplicated=False)

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        payloads = {
            "temp/first.jpg": b"first",
            "temp/broken.jpg": b"broken",
            "temp/last.jpg": b"last",
        }
        service = AcquisitionService(MemoryStorage(payloads), SelectiveImporter(), SimpleNamespace())
        assets = [
            AcquisitionAsset(
                id=name.split(".")[0],
                sha256=hashlib.sha256(payload).hexdigest(),
                filename=name,
                object_key=f"temp/{name}",
                status="pending_review",
            )
            for name, payload in (("first.jpg", b"first"), ("broken.jpg", b"broken"), ("last.jpg", b"last"))
        ]
        db.add_all(assets)
        db.commit()

        batch = service.create_import_batch(db, None, [asset.id for asset in assets])
        self.assertEqual(db.query(AcquisitionImportBatchItem).filter_by(batch_id=batch.id).count(), 3)
        self.assertTrue(all(asset.status == "import_queued" for asset in assets))

        service.process_import_batch(db, batch.id)
        db.refresh(batch)
        self.assertEqual(batch.status, "completed_with_errors")
        self.assertEqual((batch.total_count, batch.processed_count), (3, 3))
        self.assertEqual((batch.imported_count, batch.failed_count), (2, 1))
        self.assertEqual(db.get(AcquisitionAsset, "broken").status, "import_failed")
        self.assertEqual(db.get(AcquisitionAsset, "last").status, "imported")
        db.close()
        engine.dispose()

    def test_import_batch_reconciles_gallery_commit_before_later_failure(self) -> None:
        payload = b"already-copied"

        class MemoryStorage:
            def __init__(self) -> None:
                self.objects = {"temp/photo.jpg": payload}

            def get_bytes(self, key: str) -> bytes:
                return self.objects[key]

            def remove_object(self, key: str) -> None:
                self.objects.pop(key, None)

        class CommitThenFailImporter:
            def import_gallery_photo(self, db: Session, filename: str, *_args: object, **kwargs: object) -> object:
                db.add(
                    GalleryPhoto(
                        workspace_id=kwargs["workspace_id"],
                        filename=filename,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        object_key="gallery/photo.jpg",
                    )
                )
                db.commit()
                raise RuntimeError("模拟图库提交后的中断")

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        storage = MemoryStorage()
        service = AcquisitionService(storage, CommitThenFailImporter(), SimpleNamespace())
        asset = AcquisitionAsset(
            id="recoverable",
            sha256=hashlib.sha256(payload).hexdigest(),
            filename="photo.jpg",
            object_key="temp/photo.jpg",
            status="pending_review",
        )
        db.add(asset)
        db.commit()
        batch = service.create_import_batch(db, None, [asset.id])

        service.process_import_batch(db, batch.id)

        db.refresh(batch)
        db.refresh(asset)
        self.assertEqual(batch.status, "completed")
        self.assertEqual(batch.imported_count, 1)
        self.assertEqual(asset.status, "imported")
        self.assertIsNone(asset.object_key)
        self.assertNotIn("temp/photo.jpg", storage.objects)
        db.close()
        engine.dispose()

    def test_import_batch_history_groups_items_and_keeps_unassigned_legacy_imports(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        source = AcquisitionSource(name="示例站点", base_url="https://example.test")
        db.add(source)
        db.flush()
        category = AcquisitionCategory(
            source_id=source.id,
            name="示例分类",
            path="示例分类",
            crawl_url="https://example.test/category",
        )
        db.add(category)
        db.flush()
        run = AcquisitionRun(
            id="run-history",
            source_id=source.id,
            category_id=category.id,
            source_name_snapshot=source.name,
            category_name_snapshot=category.name,
            category_url_snapshot=category.crawl_url,
            status="completed",
        )
        db.add(run)
        db.flush()
        assets = [
            AcquisitionAsset(id="batched", sha256="a" * 64, filename="batched.jpg", status="imported"),
            AcquisitionAsset(id="legacy", sha256="b" * 64, filename="legacy.jpg", status="imported"),
        ]
        db.add_all(assets)
        db.flush()
        source_items = [
            AcquisitionSourceItem(source_id=source.id, category_id=category.id, external_key=asset.id, source_url=f"https://example.test/{asset.id}.jpg", status="imported")
            for asset in assets
        ]
        db.add_all(source_items)
        db.flush()
        db.add_all([
            AcquisitionRunItem(run_id=run.id, source_item_id=source_item.id, asset_id=asset.id, status="imported")
            for source_item, asset in zip(source_items, assets, strict=True)
        ])
        db.add_all([
            AcquisitionImportedPhoto(
                run_id=run.id,
                asset_id=asset.id,
                gallery_photo_snapshot_id=index,
                filename_snapshot=asset.filename,
                sha256_snapshot=asset.sha256,
                category_path_snapshot=category.path,
            )
            for index, asset in enumerate(assets, start=101)
        ])
        batch = AcquisitionImportBatch(
            id="batch-history",
            status="completed",
            total_count=1,
            processed_count=1,
            imported_count=1,
        )
        db.add(batch)
        db.flush()
        db.add(AcquisitionImportBatchItem(
            batch_id=batch.id,
            asset_id="batched",
            ordinal=1,
            status="imported",
            attempt_count=1,
        ))
        db.add(AcquisitionAsset(id="pending", sha256="c" * 64, filename="pending.jpg", status="pending_review"))
        db.commit()

        context = SimpleNamespace(workspace_id=None)
        batches = list_import_batches(
            offset=0,
            limit=15,
            date_from=None,
            date_to=None,
            db=db,
            current=context,
        )
        self.assertEqual(batches.total, 1)
        self.assertEqual(batches.unassigned_imported_count, 1)
        self.assertEqual(set(list_asset_ids(status="imported", db=db, current=context)), {"batched", "legacy"})

        detail = list_import_batch_items(
            batch_id=batch.id,
            status="all",
            offset=0,
            limit=40,
            date_from=None,
            date_to=None,
            db=db,
            current=context,
        )
        self.assertEqual(detail.total, 1)
        self.assertEqual(detail.items[0].filename, "batched.jpg")
        self.assertEqual(len(detail.items[0].origins), 1)

        legacy = list_import_batch_items(
            batch_id="unassigned",
            status="all",
            offset=0,
            limit=40,
            date_from=None,
            date_to=None,
            db=db,
            current=context,
        )
        self.assertEqual(legacy.total, 1)
        self.assertEqual(legacy.items[0].asset_id, "legacy")
        db.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
