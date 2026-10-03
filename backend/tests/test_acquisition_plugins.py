"""采集插件安装、子进程协议与凭据隔离回归测试。"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.models import AcquisitionAsset, AcquisitionCategory, AcquisitionPluginVersion, AcquisitionScript, AcquisitionSource, AcquisitionSourceScript
from app.api.acquisition_plugins import PluginPreviewRequest, preview_plugin
from app.services.acquisition import AcquisitionService
from app.services.acquisition_adapters.contracts import RemoteItem, remote_item_from_plugin, script_parameter_from_manifest
from app.services.acquisition_plugins.manager import (
    PluginAborted,
    PluginManager,
    STALE_PREPARE_ERROR,
    validate_manifest,
)
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
        installed = tmp_path / "acquisition" / "plugins" / "test-gallery" / "1.0.0" / "plugin.json"
        with pytest.raises(ValueError, match="已上传"):
            manager.upload(db, package())
        assert installed.is_file()
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


def test_runtime_uses_current_worker_and_plugin_virtual_environment(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    script = "import sys\ndef test_connection(credentials):\n    return {'ok': True, 'prefix': sys.prefix}\n"
    with Session(engine) as db:
        row = manager.upload(db, package({**MANIFEST, "credentials": []}, script))
        manager.prepare(db, row)
        manager.activate(db, row)
        folder = manager._folder(row.script_key, row.version)
        (folder / "_pictureshow_worker.py").write_text("raise RuntimeError('旧版协议')")
        result = manager.run(manager.active[row.script_key], "test_connection", {"credentials": {}})
        assert result["ok"] is True
        assert Path(result["prefix"]).resolve() == (folder / ".venv").resolve()


def engine_with_foreign_keys():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_upload_with_foreign_keys_saves_script_before_version(tmp_path: Path):
    engine = engine_with_foreign_keys()
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    with Session(engine) as db:
        row = manager.upload(db, package())
        assert row.status == "uploaded"
        script = db.get(AcquisitionScript, "test-gallery")
        assert script is not None and script.enabled is False
        folder = tmp_path / "acquisition" / "plugins" / "test-gallery" / "1.0.0"
        assert (folder / "plugin.json").is_file()
        assert (folder / "_pictureshow_worker.py").is_file()
        second = manager.upload(db, package({**MANIFEST, "version": "1.0.1"}))
        assert second.version == "1.0.1"
        assert db.get(AcquisitionScript, "test-gallery").version == "1.0.0"


def test_upload_replaces_directory_left_without_database_row(tmp_path: Path):
    engine = engine_with_foreign_keys()
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    leftover = tmp_path / "acquisition" / "plugins" / "test-gallery" / "1.0.0"
    leftover.mkdir(parents=True)
    (leftover / "stale.txt").write_text("orphan", encoding="utf-8")
    with Session(engine) as db:
        row = manager.upload(db, package())
        assert row.script_key == "test-gallery"
        assert db.get(AcquisitionScript, "test-gallery") is not None
    assert (leftover / "plugin.json").is_file()
    assert not (leftover / "stale.txt").exists()


def test_upload_database_error_leaves_no_plugin_directory(tmp_path: Path, monkeypatch):
    engine = engine_with_foreign_keys()
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    real_commit = Session.commit

    def fail_when_version_pending(self):
        if any(isinstance(obj, AcquisitionPluginVersion) for obj in self.new):
            raise IntegrityError("INSERT", {}, Exception("FOREIGN KEY constraint failed"))
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", fail_when_version_pending)
    with Session(engine) as db:
        with pytest.raises(ValueError, match="插件版本保存失败"):
            manager.upload(db, package())
        assert db.get(AcquisitionScript, "test-gallery") is None
        assert db.scalars(select(AcquisitionPluginVersion)).all() == []
    assert not (tmp_path / "acquisition" / "plugins" / "test-gallery").exists()


def test_upload_removes_saved_version_when_directory_move_fails(tmp_path: Path, monkeypatch):
    engine = engine_with_foreign_keys()
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))

    def fail_move(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.services.acquisition_plugins.manager.shutil.move", fail_move)
    with Session(engine) as db:
        with pytest.raises(ValueError, match="插件文件无法保存到数据目录"):
            manager.upload(db, package())
        assert db.get(AcquisitionScript, "test-gallery") is None
        assert db.scalars(select(AcquisitionPluginVersion)).all() == []
    assert not (tmp_path / "acquisition" / "plugins" / "test-gallery" / "1.0.0").exists()


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
    manager.active = {"test-gallery": {**MANIFEST, "credentials": []}}

    def fake_run(manifest, operation, request, *, stream=False, abort_event=None, timeout=None, deadline=None):
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


def test_prepare_unexpected_error_marks_failed(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    with Session(engine) as db:
        row = manager.upload(db, package())
        monkeypatch.setattr(
            "app.services.acquisition_plugins.manager.subprocess.run",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with pytest.raises(ValueError, match="插件依赖准备失败：RuntimeError"):
            manager.prepare(db, row)
        stored = db.get(AcquisitionPluginVersion, row.id)
        assert stored.status == "failed"
        assert stored.last_error == "插件依赖准备失败：RuntimeError"


def test_recover_stuck_prepares_and_stale_uninstall(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    with Session(engine) as db:
        row = manager.upload(db, package())
        row.status = "preparing"
        db.commit()
        assert manager.recover_stuck_prepares(db) == 1
        stored = db.get(AcquisitionPluginVersion, row.id)
        assert stored.status == "failed"
        assert stored.last_error == STALE_PREPARE_ERROR
        stored.status = "preparing"
        db.commit()
        manager.uninstall(db, stored)
        assert db.get(AcquisitionPluginVersion, row.id) is None


def test_in_flight_prepare_blocks_uninstall(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path, auth_secret_key="non-default-test-secret"))
    with Session(engine) as db:
        row = manager.upload(db, package())
        manager.preparing_ids.add(row.id)
        row.status = "preparing"
        db.commit()
        with pytest.raises(ValueError, match="环境正在准备"):
            manager.uninstall(db, row)


def test_manifest_rejects_unknown_parameter_fields():
    with pytest.raises(ValueError, match="未知字段"):
        validate_manifest({**MANIFEST, "parameters": [{**MANIFEST["parameters"][0], "help": "x"}]})


def test_select_options_accept_public_api_shape():
    parameter = script_parameter_from_manifest({
        "key": "sort", "label": "排序", "type": "select",
        "options": [{"value": "new", "label": "最新"}],
    })
    assert parameter.options == (("new", "最新"),)
    definition_options = {**MANIFEST, "parameters": [{
        "key": "sort", "label": "排序", "type": "select", "options": [{"value": "new", "label": "最新"}],
    }]}
    validate_manifest(definition_options)


def test_remote_item_filters_unknown_keys_and_validates_media_type():
    item = remote_item_from_plugin({
        "external_key": "a", "source_url": "https://example.test/a", "extra": 1, "media_type": "video",
    })
    assert item.media_type == "video"
    assert item.external_key == "a"
    with pytest.raises(ValueError, match="媒体类型"):
        remote_item_from_plugin({"external_key": "a", "source_url": "https://example.test/a", "media_type": "audio"})


def test_max_download_workers_must_be_positive_int():
    with pytest.raises(ValueError, match="max_download_workers"):
        validate_manifest({**MANIFEST, "max_download_workers": "3"})
    with pytest.raises(ValueError, match="max_download_workers"):
        validate_manifest({**MANIFEST, "max_download_workers": True})
    validate_manifest({**MANIFEST, "max_download_workers": 3})


def test_plugin_run_abort_kills_child_process(tmp_path: Path):
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    abort = threading.Event()
    threading.Timer(0.3, abort.set).start()
    started = time.monotonic()
    with pytest.raises(PluginAborted, match="采集已停止"):
        manager._run_once(
            [sys.executable, "-c", "import time; time.sleep(30); print('{}')"],
            "", tmp_path, [], abort, 10,
        )
    assert time.monotonic() - started < 8


def test_preview_sets_deadline_on_adapter(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    manager.active = {"test-gallery": {**MANIFEST, "credentials": []}}
    seen = {}

    def fake_run(manifest, operation, request, *, stream=False, abort_event=None, timeout=None, deadline=None):
        seen["deadline"] = deadline
        if operation == "enumerate_pages":
            return iter([{"page_number": 1, "items": [{"external_key": "one", "source_url": "https://example.test/one.jpg"}],
                          "stop_reason": "collection_end"}])
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
        before = time.monotonic()
        preview_plugin("test-gallery", PluginPreviewRequest(category_id=category.id), request, db, current)
        assert seen["deadline"] is not None
        assert before < seen["deadline"] <= before + 46


def test_plugin_video_named_bin_is_accepted_by_magic(tmp_path: Path):
    service = AcquisitionService(
        SimpleNamespace(), SimpleNamespace(),
        SimpleNamespace(data_dir=tmp_path, ffprobe_path="ffprobe-missing-binary"),
    )
    remote = RemoteItem("one", "https://example.test/clip", media_type="video")
    video_path = tmp_path / "media.bin"
    video_path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32)
    downloaded = service._analyze_downloaded_media(remote, None, None, remote.source_url, video_path)
    assert downloaded.media_type == "video"
    text_path = tmp_path / "notes.bin"
    text_path.write_bytes(b"this is not a video file")
    with pytest.raises(RuntimeError, match="不是视频"):
        service._analyze_downloaded_media(remote, None, None, remote.source_url, text_path)
