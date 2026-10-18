from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.services.acquisition_adapters.contracts import remote_item_from_plugin
from app.tools.upgrade_plugin_public_metadata import PLUGIN_KEYS, upgrade_package


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("key", sorted(PLUGIN_KEYS))
def test_common_plugin_package_emits_only_allowlisted_public_metadata(tmp_path, key):
    manifest = json.loads((ROOT / "examples/acquisition-plugin-json-api/plugin.json").read_text(encoding="utf-8"))
    manifest.update(key=key, version="1.2.3")
    source, output = tmp_path / "old.zip", tmp_path / "new.zip"
    runtime = '''from dataclasses import asdict
def pages(adapter, *args):
    for page in adapter.enumerate_pages(*args):
        yield {"items": [asdict(item) for item in page.items]}
'''
    with ZipFile(source, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest))
        archive.writestr("_runtime.py", runtime)
        archive.writestr("README.md", "插件说明")
        archive.writestr("plugin.py", "# 保留下载入口\n")
    original = source.read_bytes()
    upgrade_package(source, output)
    assert source.read_bytes() == original
    with ZipFile(output) as archive:
        assert json.loads(archive.read("plugin.json"))["version"] == "1.2.4"
        assert archive.read("plugin.py").decode("utf-8") == "# 保留下载入口\n"
        namespace = {}
        exec(compile(archive.read("_runtime.py"), "_runtime.py", "exec"), namespace)
    @dataclass
    class Item:
        external_key: str = "123"
        source_url: str = "https://example.test/1"
        title: str = "原帖标题"
        plugin_data: dict | None = None
        candidate_urls: tuple = ("https://cdn.test/image?signature=hidden",)
    item = Item(plugin_data={"Cookie": "hidden", "accessToken": "hidden", "sessionId": "hidden"})
    adapter = SimpleNamespace(enumerate_pages=lambda *_: [SimpleNamespace(items=[item])])
    raw = list(namespace["pages"](adapter))[0]["items"][0]
    public = {"original_title": "原帖标题"}
    if key == "raindrop-ftxsri-workers-dev":
        public["work_id"] = "123"
    assert raw["public_metadata"] == public
    assert remote_item_from_plugin(raw).public_metadata == public
    assert raw["plugin_data"] == item.plugin_data
    with pytest.raises(FileExistsError):
        upgrade_package(source, output)
    with pytest.raises(ValueError, match="已变化或已升级"):
        upgrade_package(output, tmp_path / "again.zip")


def test_json_api_example_declares_public_fields_without_copying_record_secrets(monkeypatch):
    spec = importlib.util.spec_from_file_location("json_api_example", ROOT / "examples/acquisition-plugin-json-api/plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {"items": [{"id": 42, "url": "https://example.test/post", "title": "原帖标题",
        "author": "作者", "column": "栏目", "privateKey": "hidden", "cookie": "hidden",
        "download_url": "https://cdn.test/image?signature=hidden", "sessionId": "hidden"}]}
    monkeypatch.setattr(module, "_open", lambda *_: io.StringIO(json.dumps(payload)))
    raw = list(module.enumerate_pages("https://example.test", {}, {}, set(), False))[0]["items"][0]
    assert raw["public_metadata"] == {"work_id": "42", "author": "作者", "column": "栏目", "original_title": "原帖标题"}
    assert remote_item_from_plugin(raw).public_metadata == raw["public_metadata"]


def test_plugin_data_never_becomes_public_metadata():
    raw = {"external_key": "1", "source_url": "https://example.test", "plugin_data": {"title": "内部标题", "token": "hidden"}}
    assert remote_item_from_plugin(raw).public_metadata == {}
