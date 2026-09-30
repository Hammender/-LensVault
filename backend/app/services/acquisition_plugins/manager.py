"""插件包校验、版本管理和子进程适配器。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AcquisitionPluginCredential, AcquisitionPluginVersion, AcquisitionRun, AcquisitionScript
from app.services.acquisition_adapters.contracts import RemoteItem, RemotePage, ScriptDefinition, ScriptParameter, SourceAdapter
from app.services.acquisition_adapters.registry import SCRIPT_REGISTRY


KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$")
MAX_PACKAGE_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 80 * 1024 * 1024
MAX_FILES = 200
WORKER = Path(__file__).with_name("worker.py")


def validate_manifest(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or raw.get("protocol_version") != 1:
        raise ValueError("插件清单缺少受支持的协议版本 1")
    manifest = dict(raw)
    key, version = manifest.get("key"), manifest.get("version")
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise ValueError("插件标识只能使用小写字母、数字和连字符")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("插件版本必须采用 1.2.3 格式")
    for field in ("name", "page_format_key", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"插件清单缺少 {field}")
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or not re.fullmatch(r"[a-zA-Z0-9_/.-]+\.py", entrypoint):
        raise ValueError("插件入口必须是包内的 Python 文件")
    path = PurePosixPath(entrypoint)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("插件入口路径无效")
    for field in ("parameters", "credentials", "requirements"):
        if not isinstance(manifest.get(field, []), list):
            raise ValueError(f"插件清单 {field} 必须是列表")
    for item in manifest.get("parameters", []):
        ScriptParameter(**item)
    for item in manifest.get("credentials", []):
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", item["key"]):
            raise ValueError("凭据字段标识无效")
        if not isinstance(item.get("label"), str) or not item["label"]:
            raise ValueError("凭据字段必须提供名称")
    for requirement in manifest.get("requirements", []):
        if not isinstance(requirement, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~]{1,2}[A-Za-z0-9.*+-]+)?", requirement):
            raise ValueError("依赖声明只能包含包名和版本约束")
    return manifest


class PluginManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(getattr(settings, "data_dir", tempfile.gettempdir())) / "acquisition" / "plugins"
        self.active: dict[str, dict[str, object]] = {}
        self.known_keys: set[str] = set()

    def _folder(self, key: str, version: str) -> Path:
        if not KEY_PATTERN.fullmatch(key) or not VERSION_PATTERN.fullmatch(version):
            raise ValueError("插件标识或版本无效")
        return self.root / key / version

    def refresh(self, db: Session) -> None:
        self.active = {}
        rows = db.scalars(select(AcquisitionPluginVersion)).all()
        self.known_keys = {row.script_key for row in rows}
        for row in rows:
            if row.status != "active":
                continue
            if self._folder(row.script_key, row.version).is_dir():
                self.active[row.script_key] = json.loads(row.manifest_json)

    def upload(self, db: Session, payload: bytes) -> AcquisitionPluginVersion:
        if len(payload) > MAX_PACKAGE_BYTES:
            raise ValueError("插件包超过 20 MiB 上限")
        with tempfile.TemporaryDirectory(prefix="pictureshow-plugin-") as temporary:
            stage = Path(temporary)
            try:
                with ZipFile(io.BytesIO(payload)) as archive:
                    members = archive.infolist()
                    if len(members) > MAX_FILES or sum(item.file_size for item in members) > MAX_UNPACKED_BYTES:
                        raise ValueError("插件包中文件过多或解压后过大")
                    names: set[str] = set()
                    for item in members:
                        relative = PurePosixPath(item.filename)
                        if relative.is_absolute() or ".." in relative.parts or "\\" in item.filename or ":" in item.filename:
                            raise ValueError("插件包包含无效路径")
                        if item.filename in names or ((item.external_attr >> 16) & 0o170000) == 0o120000:
                            raise ValueError("插件包包含重复文件或符号链接")
                        names.add(item.filename)
                    archive.extractall(stage)
            except (OSError, BadZipFile) as exc:
                raise ValueError("插件包不是有效 ZIP 文件") from exc
            manifest_path = stage / "plugin.json"
            if not manifest_path.is_file():
                raise ValueError("插件包根目录缺少 plugin.json")
            manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            key, version = str(manifest["key"]), str(manifest["version"])
            if key in SCRIPT_REGISTRY:
                raise ValueError("该标识已由内置采集脚本使用")
            if not (stage / str(manifest["entrypoint"])).is_file():
                raise ValueError("插件入口文件不存在")
            if not (stage / "README.md").is_file():
                raise ValueError("插件包缺少中文使用说明 README.md")
            if db.scalar(select(AcquisitionPluginVersion).where(AcquisitionPluginVersion.script_key == key, AcquisitionPluginVersion.version == version)):
                raise ValueError("该插件版本已上传；版本不可覆盖")
            folder = self._folder(key, version)
            if folder.exists():
                raise ValueError("目标插件目录已存在")
            script = db.get(AcquisitionScript, key)
            if script is None:
                db.add(AcquisitionScript(key=key, name=str(manifest["name"]), version=version,
                    page_format_key=str(manifest["page_format_key"]), description=str(manifest["description"]),
                    parameter_schema_json=json.dumps(manifest.get("parameters", []), ensure_ascii=False), enabled=False))
            elif script.page_format_key != manifest["page_format_key"]:
                raise ValueError("新版本的网页格式与已安装版本不一致")
            folder.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(WORKER, stage / "_pictureshow_worker.py")
            shutil.move(str(stage), str(folder))
            row = AcquisitionPluginVersion(script_key=key, version=version,
                manifest_json=json.dumps(manifest, ensure_ascii=False), package_sha256=hashlib.sha256(payload).hexdigest())
            db.add(row)
            db.commit()
            db.refresh(row)
            self.refresh(db)
            return row

    def prepare(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status not in {"uploaded", "failed", "preparing"}:
            raise ValueError("当前插件版本不需要准备环境")
        row.status = "preparing"
        db.commit()
        folder = self._folder(row.script_key, row.version)
        try:
            subprocess.run([sys.executable, "-m", "venv", str(folder / ".venv")], check=True, timeout=300, capture_output=True)
            python = self._python(folder)
            requirements = json.loads(row.manifest_json).get("requirements", [])
            if requirements:
                subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", *requirements],
                    check=True, timeout=600, capture_output=True)
            row.status = "ready"
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            row.status = "failed"
            raise ValueError(f"插件依赖准备失败：{type(exc).__name__}") from exc
        finally:
            db.commit()

    @staticmethod
    def _python(folder: Path) -> Path:
        return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def activate(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status not in {"ready", "active"}:
            raise ValueError("请先准备插件环境")
        for item in db.scalars(select(AcquisitionPluginVersion).where(
            AcquisitionPluginVersion.script_key == row.script_key, AcquisitionPluginVersion.status == "active")):
            item.status = "ready"
        row.status = "active"
        manifest = json.loads(row.manifest_json)
        script = db.get(AcquisitionScript, row.script_key)
        script.name = str(manifest["name"])
        script.version = row.version
        script.description = str(manifest["description"])
        script.parameter_schema_json = json.dumps(manifest.get("parameters", []), ensure_ascii=False)
        script.enabled = True
        for account in db.scalars(select(AcquisitionPluginCredential).where(AcquisitionPluginCredential.script_key == row.script_key)):
            account.status = "untested"
        db.commit()
        self.refresh(db)

    def disable(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status != "active":
            raise ValueError("该版本未启用")
        row.status = "ready"
        db.get(AcquisitionScript, row.script_key).enabled = False
        db.commit()
        self.refresh(db)

    def uninstall(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status in {"active", "preparing"}:
            raise ValueError("请先停用插件并等待环境准备结束")
        active_run = db.scalar(select(AcquisitionRun.id).where(
            AcquisitionRun.script_key == row.script_key,
            AcquisitionRun.script_version_snapshot == row.version,
            AcquisitionRun.status.in_(("pending", "running"))))
        if active_run is not None:
            raise ValueError("仍有任务正在使用该插件版本")
        folder = self._folder(row.script_key, row.version).resolve()
        if not folder.is_relative_to(self.root.resolve()):
            raise ValueError("插件目录无效")
        db.delete(row)
        db.commit()
        self.refresh(db)
        if folder.exists():
            shutil.rmtree(folder)

    def get_definition(self, key: str, version: str | None = None, credentials: dict[str, object] | None = None) -> ScriptDefinition | None:
        manifest = self.active.get(key)
        if version and (manifest is None or manifest["version"] != version):
            folder = self._folder(key, version)
            if not folder.is_dir():
                return None
            manifest = validate_manifest(json.loads((folder / "plugin.json").read_text(encoding="utf-8")))
        if manifest is None:
            return None
        return ScriptDefinition(key=key, name=str(manifest["name"]), version=str(manifest["version"]),
            page_format_key=str(manifest["page_format_key"]), description=str(manifest["description"]),
            adapter=PluginAdapter(self, manifest, credentials or {}),
            parameters=tuple(ScriptParameter(**item) for item in manifest.get("parameters", [])),
            max_download_workers=manifest.get("max_download_workers"))

    def run(self, manifest: dict[str, object], operation: str, request: dict[str, object], *, stream: bool = False):
        folder = self._folder(str(manifest["key"]), str(manifest["version"]))
        python = self._python(folder)
        if not python.is_file():
            raise ValueError("插件运行环境尚未准备")
        payload = json.dumps({**request, "entrypoint": manifest["entrypoint"], "operation": operation}, ensure_ascii=False)
        command = [str(python), str(folder / "_pictureshow_worker.py")]
        secrets = [str(value) for value in (request.get("credentials") or {}).values() if isinstance(value, str) and value]
        if not stream:
            completed = subprocess.run(command, input=payload, text=True, encoding="utf-8", capture_output=True,
                cwd=folder, timeout=3600 if operation == "download" else 120)
            if completed.returncode:
                message = (completed.stderr or "插件执行失败")[-1000:]
                for secret in secrets:
                    message = message.replace(secret, "[已隐藏凭据]")
                raise RuntimeError(message)
            return json.loads(completed.stdout)
        return self._stream(command, payload, folder, secrets)

    @staticmethod
    def _stream(command: list[str], payload: str, folder: Path, secrets: list[str]):
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                text=True, encoding="utf-8", cwd=folder, bufsize=1)
            timer = threading.Timer(300, process.terminate)
            timer.start()
            try:
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write(payload)
                process.stdin.close()
                for line in process.stdout:
                    timer.cancel()
                    timer = threading.Timer(300, process.terminate)
                    timer.start()
                    if len(line) > 2 * 1024 * 1024:
                        raise ValueError("插件输出行过长")
                    yield json.loads(line)
                if process.wait(timeout=10):
                    errors.seek(0)
                    message = (errors.read() or "插件执行失败或长时间没有输出")[-1000:]
                    for secret in secrets:
                        message = message.replace(secret, "[已隐藏凭据]")
                    raise RuntimeError(message)
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()

    def cipher(self) -> Fernet:
        key = self.settings.auth_secret_key
        if not key or key == "pictureshow-local-dev-secret-change-me":
            raise ValueError("请先配置安全的 AUTH_SECRET_KEY，才能保存插件凭据")
        derived = hashlib.sha256(("pictureshow-acquisition-plugin-v1:" + key).encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(derived))

    def save_credential(self, db: Session, workspace_id: int, key: str, name: str, values: dict[str, object]) -> AcquisitionPluginCredential:
        manifest = self.active.get(key)
        if manifest is None:
            raise ValueError("插件未启用")
        declared = {item["key"]: item for item in manifest.get("credentials", [])}
        if set(values) - set(declared):
            raise ValueError("包含插件未声明的凭据字段")
        for field, spec in declared.items():
            if spec.get("required") and not values.get(field):
                raise ValueError(f"请填写{spec['label']}")
        account = db.scalar(select(AcquisitionPluginCredential).where(
            AcquisitionPluginCredential.workspace_id == workspace_id,
            AcquisitionPluginCredential.script_key == key, AcquisitionPluginCredential.name == name))
        if account is None:
            account = AcquisitionPluginCredential(workspace_id=workspace_id, script_key=key, name=name, encrypted_json="")
            db.add(account)
        account.encrypted_json = self.cipher().encrypt(json.dumps(values, ensure_ascii=False).encode("utf-8")).decode("ascii")
        account.status = "untested"
        db.commit()
        db.refresh(account)
        return account

    def credentials(self, account: AcquisitionPluginCredential) -> dict[str, object]:
        return json.loads(self.cipher().decrypt(account.encrypted_json.encode("ascii")))


@dataclass
class PluginAdapter(SourceAdapter):
    manager: PluginManager
    manifest: dict[str, object]
    credentials: dict[str, object]
    last_state: dict[str, object] | None = None

    def enumerate_pages(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool):
        request = {"crawl_url": crawl_url, "parameters": parameters, "known_external_keys": sorted(known_external_keys),
            "incremental": incremental, "credentials": self.credentials}
        stream = self.manager.run(self.manifest, "enumerate_pages", request, stream=True)
        try:
            for raw in stream:
                if not isinstance(raw, dict):
                    raise ValueError("插件页面输出无效")
                if isinstance(raw.get("plugin_state"), dict):
                    self.last_state = raw["plugin_state"]
                items = tuple(RemoteItem(**item) for item in raw["items"])
                yield RemotePage(page_number=int(raw["page_number"]), items=items, stop_reason=raw.get("stop_reason"))
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

    def download(self, item: dict[str, object], temporary_dir: Path) -> Path:
        result = self.manager.run(self.manifest, "download", {"item": item, "credentials": self.credentials,
            "temporary_dir": str(temporary_dir)})
        if not isinstance(result, dict) or not isinstance(result.get("path"), str):
            raise ValueError("插件下载结果缺少文件路径")
        path = Path(result["path"]).resolve()
        if not path.is_relative_to(temporary_dir.resolve()) or not path.is_file():
            raise ValueError("插件下载文件必须位于指定临时目录")
        return path
