"""采集插件安装、子进程协议与凭据隔离回归测试。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.models import AcquisitionAsset, AcquisitionCategory, AcquisitionPluginVersion, AcquisitionScript, AcquisitionSource, AcquisitionSourceScript
from app.api.acquisition_plugins import PluginPreviewRequest, preview_plugin
from app.services.acquisition import AcquisitionService
from app.services.acquisition_plugins.manager import PluginManager
from app.tools.package_acquisition_plugin import package_plugin


MANIFEST = {
    "protocol_version": 1, "key": "test-gallery", "name": "测试图集", "version": "1.0.0",
    "page_format_key": "test-gallery-v1", "description": "测试插件子进程",
    "entrypoint": "plugin.py", "requirements": [],
    "parameters": [{"key": "max_pages", "label": "最大页数", "type": "integer", "default": 1}],
    "credentials": [{"key": "cookie", "label": "Cookie", "required": True, "secret": True}],
}
PLUGIN = '''
from pathlib import Path
def test_connection(credentials):
    return {"ok": credentials.get("cookie") == "secret-cookie"}
def enumerate_pages(crawl_url, parameters, credentials, known_external_keys, incremental):
    assert credentials["cookie"] == "secret-cookie"
    yield {"page_number": 1, "items": [{"external_key": "one", "source_url": crawl_url}], "stop_reason": "collection_end"}
def download(item, credentials, temporary_dir):
    path = Path(temporary_dir) / "picture.jpg"
    path.write_bytes(b"sample-media")
    return {"path": str(path)}
'''


def package(manifest=MANIFEST, script=PLUGIN) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("plugin.py", script)
        archive.writestr("README.md", "# 测试插件\n从开发者工具复制凭据。")
    return output.getvalue()


def test_plugin_install_run_and_credentials_are_separate(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    with Session(engine) as db:
        row = manager.upload(db, package())
        assert row.status == "uploaded"
        with pytest.raises(ValueError, match="已上传"):
            manager.upload(db, package())
        manager.prepare(db, row)
        manager.activate(db, row)
        assert manager.active["test-gallery"]["version"] == "1.0.0"
        account = manager.save_credential(db, 1, "test-gallery", "默认账号", {"cookie": "secret-cookie"})
        assert "secret-cookie" not in account.encrypted_json
        credentials = manager.credentials(account)
        definition = manager.get_definition("test-gallery", credentials=credentials)
        assert definition is not None
        assert manager.run(manager.active["test-gallery"], "test_connection", {"credentials": credentials}) == {"ok": True}
        pages = list(definition.adapter.enumerate_pages("https://example.test/list", {}, set(), False))
        assert pages[0].items[0].external_key == "one"
        destination = tmp_path / "download"
        destination.mkdir()
        path = definition.adapter.download({"source_url": pages[0].items[0].source_url}, destination)
        assert path.read_bytes() == b"sample-media"
        manager.disable(db, row)
        assert manager.get_definition("test-gallery") is None
        assert db.get(AcquisitionPluginVersion, row.id).status == "ready"
        manager.uninstall(db, row)
        assert db.get(AcquisitionPluginVersion, row.id) is None
        assert manager.credentials(account) == credentials


def test_plugin_archive_rejects_unsafe_paths(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("../outside.txt", "bad")
        archive.writestr("plugin.json", json.dumps(MANIFEST))
    with Session(engine) as db, pytest.raises(ValueError, match="无效路径"):
        manager.upload(db, output.getvalue())
    assert not (tmp_path / "outside.txt").exists()


def test_example_json_plugin_package_loads_without_credentials(tmp_path: Path):
    source = Path(__file__).resolve().parents[2] / "examples" / "acquisition-plugin-json-api"
    archive = package_plugin(source, tmp_path / "example-json-gallery.zip")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    with Session(engine) as db:
        row = manager.upload(db, archive.read_bytes())
        manifest = json.loads(row.manifest_json)
        assert manifest["credentials"] == []
        assert manifest["key"] == "example-json-gallery"
        manager.prepare(db, row)
        manager.activate(db, row)
        assert manager.run(manager.active["example-json-gallery"], "test_connection", {"credentials": {}}) == {"ok": True}


def test_builtin_script_key_cannot_be_uploaded_as_plugin(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    manifest = {**MANIFEST, "key": "telegram-channel-mtproto", "page_format_key": "telegram-channel-v1", "name": "Telegram 频道"}
    with Session(engine) as db, pytest.raises(ValueError, match="内置采集脚本"):
        manager.upload(db, package(manifest))


def test_preview_checks_media_without_creating_assets(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    manager.active["test-gallery"] = {**MANIFEST, "credentials": []}

    def fake_run(manifest, operation, request, *, stream=False):
        if operation == "enumerate_pages":
            return iter([{"page_number": 1, "items": [{"external_key": "one", "source_url": "https://example.test/one.jpg"}],
                          "stop_reason": "collection_end"}])
        assert operation == "download"
        path = Path(request["temporary_dir"]) / "one.jpg"
        path.write_bytes(b"sample-media")
        return {"path": str(path)}

    monkeypatch.setattr(manager, "run", fake_run)

    class FakeService:
        plugins = manager

        @staticmethod
        def _download_and_analyze(item, referer, adapter):
            path = adapter.download({"source_url": item.source_url}, tmp_path / "download")
            return SimpleNamespace(file_path=path, media_type="image", filename=path.name, size_bytes=path.stat().st_size)

    (tmp_path / "download").mkdir()
    app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(acquisition=FakeService())))
    request = Request({"type": "http", "app": app})
    current = SimpleNamespace(role="owner", workspace_id=1)
    with Session(engine) as db:
        db.add(AcquisitionScript(key="test-gallery", name="测试", version="1.0.0",
            page_format_key="test-gallery-v1", parameter_schema_json="[]"))
        db.flush()
        source = AcquisitionSource(workspace_id=1, name="站点", base_url="https://example.test", page_format_key="test-gallery-v1")
        db.add(source)
        db.flush()
        category = AcquisitionCategory(source_id=source.id, name="分类", path="分类", crawl_url="https://example.test/list")
        db.add(category)
        db.add(AcquisitionSourceScript(source_id=source.id, script_key="test-gallery"))
        db.commit()
        result = preview_plugin("test-gallery", PluginPreviewRequest(category_id=category.id), request, db, current)
        assert result["items"][0]["size_bytes"] == len(b"sample-media")
        assert db.query(AcquisitionAsset).count() == 0


def test_fresh_runtime_offers_only_builtin_telegram(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    service = AcquisitionService(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(data_dir=tmp_path))
    with Session(engine) as db:
        service.refresh_plugins(db)
        scripts = service.scripts()
        assert [item["key"] for item in scripts] == ["telegram-channel-mtproto"]
        assert scripts[0]["name"] == "Telegram 频道"
        assert all(item.get("is_plugin") is not True for item in scripts)
        assert service.get_definition("idolxxx-gallery") is None
        assert service.get_definition("idolxxx-gallery", "1.1.0") is None
        assert service.get_definition("telegram-channel-mtproto").key == "telegram-channel-mtproto"
