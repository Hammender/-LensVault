"""插件任务、临时目录、账号快照及元数据的集成回归测试。"""

import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.models import (
    AcquisitionAsset, AcquisitionCategory, AcquisitionPluginCredential, AcquisitionPluginVersion,
    AcquisitionRun, AcquisitionRunItem, AcquisitionSource, AcquisitionSourceItem, AcquisitionSourceScript,
)
from app.api.acquisition import _asset_read
from app.api.acquisition_plugins import PluginPreviewRequest, preview_plugin, test_credential as check_credential
from app.services.acquisition import AcquisitionService, DownloadedRemote
from app.services.acquisition_adapters.contracts import remote_item_from_plugin
from app.services.acquisition_plugins.manager import PluginAborted, validate_manifest
from tests.test_acquisition_plugins import MANIFEST, package


@pytest.fixture
def plugin_site(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    Base.metadata.create_all(engine)
    settings = SimpleNamespace(data_dir=tmp_path, auth_secret_key="review-key", acquisition_download_workers=2,
                               acquisition_max_file_bytes=10000, telegram_max_media_bytes=10000)
    service = AcquisitionService(SimpleNamespace(), SimpleNamespace(), settings, similarity_extractor=SimpleNamespace())
    with Session(engine) as db:
        version = service.plugins.upload(db, package())
        version.status = "ready"
        db.commit()
        service.plugins.activate(db, version)
        source = AcquisitionSource(workspace_id=1, name="测试站点", page_format_key="test-gallery-v1")
        db.add(source)
        db.flush()
        category = AcquisitionCategory(source_id=source.id, name="测试分类", path="test", crawl_url="https://example.test/list")
        db.add(category)
        db.add(AcquisitionSourceScript(source_id=source.id, script_key="test-gallery"))
        db.commit()
        monkeypatch.setattr("app.services.acquisition.ensure_perceptual_feature_dependencies", lambda: None)
        yield SimpleNamespace(engine=engine, db=db, service=service, source=source, category=category,
                              version=version, tmp_path=tmp_path)
    engine.dispose()


def new_run(site, **values):
    run = AcquisitionRun(id=uuid4().hex, workspace_id=1, source_id=site.source.id, category_id=site.category.id,
                         script_key="test-gallery", script_version_snapshot="1.0.0", mode="full", **values)
    site.db.add(run)
    site.db.commit()
    return run


def request_for(site):
    app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(acquisition=site.service)))
    return Request({"type": "http", "app": app})


@pytest.mark.parametrize("failure", ["credentials", "manifest", "parameters"])
def test_pre_execution_failure_finishes_run(plugin_site, failure):
    site = plugin_site
    values = {}
    if failure == "credentials":
        account = site.service.plugins.save_credential(site.db, 1, "test-gallery", "默认", {"cookie": "old"})
        site.service.plugins.settings.auth_secret_key = "changed-key"
        values["credential_id"] = account.id
    if failure == "manifest":
        site.service.plugins.disable(site.db, site.version)
        (site.service.plugins._folder("test-gallery", "1.0.0") / "plugin.json").write_text("broken")
    if failure == "parameters":
        values["parameters_json"] = "[1]"
    run = new_run(site, **values)
    site.service.process_run(site.db, run.id)
    site.db.refresh(run)
    assert run.status == "failed"
    assert run.completed_at is not None
    assert run.id not in site.service._run_abort_events
    assert site.db.scalar(select(AcquisitionRun.id).where(AcquisitionRun.status.in_(("pending", "running")))) is None


@pytest.mark.parametrize("required", [False, True])
def test_optional_credentials_match_run_and_preview(plugin_site, monkeypatch, required):
    site = plugin_site
    manifest = {**MANIFEST, "credentials": [{"key": "cookie", "label": "Cookie", "required": required}]}
    site.service.plugins.active = {"test-gallery": manifest}
    monkeypatch.setattr(site.service.plugins, "run", lambda *args, **kwargs: iter([]))
    if required:
        with pytest.raises(ValueError, match="账号"):
            site.service.start_run(site.db, 1, site.category, "test-gallery", "full")
        with pytest.raises(HTTPException) as error:
            preview_plugin("test-gallery", PluginPreviewRequest(category_id=site.category.id), request_for(site), site.db,
                           SimpleNamespace(role="owner", workspace_id=1))
        assert error.value.status_code == 409
    else:
        run = site.service.start_run(site.db, 1, site.category, "test-gallery", "full")
        assert run.credential_id is None
        assert preview_plugin("test-gallery", PluginPreviewRequest(category_id=site.category.id), request_for(site), site.db,
                              SimpleNamespace(role="owner", workspace_id=1)) == {"items": []}


def test_selected_optional_account_must_be_valid_and_in_workspace(plugin_site):
    site = plugin_site
    site.service.plugins.active = {"test-gallery": {**MANIFEST, "credentials": []}}
    account = site.service.plugins.save_credential(site.db, 2, "test-gallery", "其他工作区", {})
    account.status = "valid"
    site.db.commit()
    with pytest.raises(ValueError, match="不可用"):
        site.service.start_run(site.db, 1, site.category, "test-gallery", "full", credential_id=account.id)
    account.workspace_id = 1
    account.status = "untested"
    site.db.commit()
    with pytest.raises(ValueError, match="测试"):
        site.service.start_run(site.db, 1, site.category, "test-gallery", "full", credential_id=account.id)


@pytest.mark.parametrize("change", ["save", "delete", "version", "none"])
def test_credential_test_only_commits_matching_snapshot(plugin_site, monkeypatch, change):
    site = plugin_site
    manager = site.service.plugins
    account = manager.save_credential(site.db, 1, "test-gallery", "默认", {"cookie": "old"})
    account_id = account.id
    def during_test(manifest, operation, request):
        assert request["credentials"] == {"cookie": "old"}
        with Session(site.engine) as concurrent:
            if change == "save":
                manager.save_credential(concurrent, 1, "test-gallery", "默认", {"cookie": "new"})
            elif change == "delete":
                concurrent.delete(concurrent.get(AcquisitionPluginCredential, account_id))
                concurrent.commit()
            elif change == "version":
                old = concurrent.get(AcquisitionPluginVersion, site.version.id)
                manager.disable(concurrent, old)
        return {"ok": True}
    monkeypatch.setattr(manager, "run", during_test)
    if change == "none":
        result = check_credential(account_id, request_for(site), site.db, SimpleNamespace(workspace_id=1))
        assert result["status"] == "valid"
    else:
        with pytest.raises(HTTPException) as error:
            check_credential(account_id, request_for(site), site.db, SimpleNamespace(workspace_id=1))
        assert error.value.status_code == (404 if change == "delete" else 409)
        remaining = site.db.get(AcquisitionPluginCredential, account_id)
        if remaining is not None:
            assert remaining.status != "valid"


@pytest.mark.parametrize("value, expected", [("昨天", None), (123, None), ("2026-10-03T00:00:00Z", "2026-10-03T08:00:00+08:00"),
                                             ("2026-10-03T08:00:00", "2026-10-03T08:00:00+08:00")])
def test_plugin_timestamp_normalization_and_legacy_read(plugin_site, value, expected):
    site = plugin_site
    remote = remote_item_from_plugin({"external_key": "one", "source_url": "https://example.test/one", "published_at": value})
    assert remote.published_at == expected
    asset = AcquisitionAsset(id="one", workspace_id=1, sha256="a" * 64, filename="test.jpg", content_type="image/jpeg", size_bytes=1)
    item = AcquisitionSourceItem(source_id=site.source.id, external_key="one", source_url=remote.source_url,
                                 metadata_json=json.dumps({"published_at": value}))
    run = new_run(site)
    site.db.add_all([asset, item])
    site.db.flush()
    site.db.add(AcquisitionRunItem(run_id=run.id, source_item_id=item.id, asset_id=asset.id))
    site.db.commit()
    result = _asset_read(site.db, asset)
    assert (result.source_published_at.isoformat() if result.source_published_at else None) == expected


@pytest.mark.parametrize("stop", [False, True])
def test_run_cleans_nested_files_and_unconsumed_parallel_results(plugin_site, monkeypatch, stop):
    site = plugin_site
    started = threading.Event()
    directories = []
    def fake_run(manifest, operation, request, **kwargs):
        if operation == "enumerate_pages":
            return iter([{"page_number": 1, "items": [
                {"external_key": "first", "source_url": "https://example.test/first"},
                {"external_key": "second", "source_url": "https://example.test/second"},
            ], "stop_reason": "collection_end"}])
        root = site.tmp_path / request["temporary_dir"]
        directories.append(root)
        if request["item"]["external_key"] == "first" and stop:
            assert started.wait(2)
            raise PluginAborted("采集已停止")
        path = root / "nested" / "picture.jpg"
        path.parent.mkdir()
        path.write_bytes(b"sample-media")
        (root / "sidecar.txt").write_text("临时附属文件")
        return {"path": str(path)}
    template = DownloadedRemote(b"sample-media", "image/jpeg", "https://example.test", "source", "picture.jpg", "image",
                                1, 1, None, None, (), "a" * 64, None, None, None)
    def analyze(remote, payload, content_type, url, path):
        started.set()
        if stop:
            time.sleep(0.1)
        return replace(template, file_path=path)
    monkeypatch.setattr(site.service.plugins, "run", fake_run)
    monkeypatch.setattr(site.service, "_analyze_downloaded_media", analyze)
    monkeypatch.setattr(site.service, "_persist_downloaded_remote", lambda *args: None)
    run = new_run(site)
    site.service.process_run(site.db, run.id)
    site.db.refresh(run)
    assert run.status == ("interrupted" if stop else "completed")
    assert directories and all(not directory.exists() for directory in directories)
    assert list((site.tmp_path / "acquisition" / "plugin-tmp").iterdir()) == []


def test_in_flight_preview_lease_blocks_uninstall(plugin_site):
    site = plugin_site
    manager = site.service.plugins
    with manager.lease("test-gallery"):
        manager.disable(site.db, site.version)
        with pytest.raises(ValueError, match="调用"):
            manager.uninstall(site.db, site.version)
    manager.uninstall(site.db, site.version)


def test_catalog_refresh_keeps_old_snapshot_available(plugin_site, monkeypatch):
    site = plugin_site
    manager = site.service.plugins
    previous = manager.active
    original_scalars = site.db.scalars
    def loading(*args, **kwargs):
        assert manager.active["test-gallery"]["version"] == "1.0.0"
        return original_scalars(*args, **kwargs)
    monkeypatch.setattr(site.db, "scalars", loading)
    manager.refresh(site.db)
    manager.active["test-gallery"]["version"] = "modified-copy"
    assert previous["test-gallery"]["version"] == "1.0.0"
    assert manager.active["test-gallery"]["version"] == "1.0.0"


def test_finished_run_is_not_executed_again(plugin_site, monkeypatch):
    site = plugin_site
    run = new_run(site)
    run.status = "completed"
    site.db.commit()
    monkeypatch.setattr(site.service, "_process_run_body", lambda *args: pytest.fail("已结束任务被再次执行"))
    site.service.process_run(site.db, run.id)


def test_running_task_keeps_version_and_credentials_after_upgrade(plugin_site, monkeypatch):
    site = plugin_site
    manager = site.service.plugins
    account = manager.save_credential(site.db, 1, "test-gallery", "默认", {"cookie": "old"})
    account.status = "valid"
    site.db.commit()
    seen = []
    def fake_run(manifest, operation, request, **kwargs):
        seen.append((str(manifest["version"]), request["credentials"]["cookie"]))
        if operation == "enumerate_pages":
            # 发生在执行已经读取账号、但媒体下载尚未开始的时刻。
            with Session(site.engine) as concurrent:
                updated = manager.upload(concurrent, package({**MANIFEST, "version": "1.0.1"}))
                updated.status = "ready"
                concurrent.commit()
                manager.activate(concurrent, updated)
                manager.save_credential(concurrent, 1, "test-gallery", "默认", {"cookie": "new"})
            return iter([{"page_number": 1, "items": [{"external_key": "one", "source_url": "https://example.test/one"}],
                          "stop_reason": "collection_end"}])
        path = site.tmp_path / request["temporary_dir"] / "picture.jpg"
        path.write_bytes(b"sample-media")
        return {"path": str(path)}
    template = DownloadedRemote(b"sample-media", "image/jpeg", "https://example.test", "source", "picture.jpg", "image",
                                1, 1, None, None, (), "a" * 64, None, None, None)
    monkeypatch.setattr(manager, "run", fake_run)
    monkeypatch.setattr(site.service, "_analyze_downloaded_media", lambda remote, payload, content_type, url, path: replace(template, file_path=path))
    monkeypatch.setattr(site.service, "_persist_downloaded_remote", lambda *args: None)
    run = new_run(site, credential_id=account.id)
    site.service.process_run(site.db, run.id)
    site.db.refresh(run)
    assert run.status == "completed"
    assert seen == [("1.0.0", "old"), ("1.0.0", "old")]
    assert manager.active["test-gallery"]["version"] == "1.0.1"


@pytest.mark.parametrize("field", ["required", "secret"])
def test_credential_flags_require_booleans(field):
    with pytest.raises(ValueError, match="布尔"):
        validate_manifest({**MANIFEST, "credentials": [{"key": "cookie", "label": "Cookie", field: "false"}]})
