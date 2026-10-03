"""插件包校验、版本管理和子进程适配器。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AcquisitionPluginCredential, AcquisitionPluginVersion, AcquisitionRun, AcquisitionScript
from app.services.acquisition_adapters.contracts import (
    RemotePage,
    ScriptDefinition,
    SourceAdapter,
    parse_max_download_workers,
    remote_item_from_plugin,
    script_parameter_from_manifest,
)
from app.services.acquisition_adapters.registry import SCRIPT_REGISTRY
from app.services.acquisition_plugins.catalog import PluginCatalog
from app.services.acquisition_plugins.context import PluginExecutionContext
from app.services.acquisition_plugins.runtime import PluginAborted, PluginRunner, check_abort

logger = logging.getLogger(__name__)

STALE_PREPARE_ERROR = "服务重启前环境准备未完成，请重新准备"
PREVIEW_TIMEOUT_SECONDS = 45
DOWNLOAD_TIMEOUT_SECONDS = 3600
ENUMERATE_IDLE_TIMEOUT_SECONDS = 300
OTHER_TIMEOUT_SECONDS = 120


def _serialized(action):
    @wraps(action)
    def wrapped(self, db, *args, **kwargs):
        with self.catalog.lock:
            # 管理接口在取得锁前读取的版本行可能已经过期。
            if args and isinstance(args[0], AcquisitionPluginVersion):
                if db.get(AcquisitionPluginVersion, args[0].id, populate_existing=True) is None:
                    raise ValueError("插件版本不存在")
            return action(self, db, *args, **kwargs)
    return wrapped


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
        script_parameter_from_manifest(item)
    parse_max_download_workers(manifest.get("max_download_workers"))
    for item in manifest.get("credentials", []):
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", item["key"]):
            raise ValueError("凭据字段标识无效")
        if not isinstance(item.get("label"), str) or not item["label"]:
            raise ValueError("凭据字段必须提供名称")
        for flag in ("required", "secret"):
            if flag in item and not isinstance(item[flag], bool):
                raise ValueError(f"凭据字段 {flag} 必须是布尔值")
    for requirement in manifest.get("requirements", []):
        if not isinstance(requirement, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~]{1,2}[A-Za-z0-9.*+-]+)?", requirement):
            raise ValueError("依赖声明只能包含包名和版本约束")
    return manifest


class PluginManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(getattr(settings, "data_dir", tempfile.gettempdir())) / "acquisition" / "plugins"
        self.catalog = PluginCatalog()
        self.runner = PluginRunner()
        self.preparing_ids = self.catalog.preparing_ids

    @property
    def active(self):
        return self.catalog.active

    @active.setter
    def active(self, value):
        self.catalog.replace(value, self.catalog.known_keys)

    @property
    def known_keys(self):
        return self.catalog.known_keys

    @contextmanager
    def lease(self, key: str, version: str | None = None):
        with self.catalog.lock:
            definition = self.get_definition(key, version)
            if definition is None:
                raise ValueError("插件未启用或版本不可用")
            lease = self.catalog.lease(definition.adapter.manifest)
            manifest = lease.__enter__()
        try:
            yield manifest
        finally:
            lease.__exit__(None, None, None)

    def _folder(self, key: str, version: str) -> Path:
        if not KEY_PATTERN.fullmatch(key) or not VERSION_PATTERN.fullmatch(version):
            raise ValueError("插件标识或版本无效")
        return self.root / key / version

    def _delete_plugin_folder(self, folder: Path) -> None:
        resolved = folder.resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError("插件目录无效")
        if not resolved.exists():
            return
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()

    def _rollback_saved_version(
        self, db: Session, row: AcquisitionPluginVersion, key: str, created_script: bool, folder: Path,
    ) -> None:
        """目录没落盘时撤回刚提交的版本，避免列表里出现无法准备的插件。"""
        try:
            db.delete(row)
            db.flush()
            if created_script and db.scalar(
                select(AcquisitionPluginVersion.id).where(AcquisitionPluginVersion.script_key == key)
            ) is None:
                script = db.get(AcquisitionScript, key)
                if script is not None:
                    db.delete(script)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("回滚未完成的插件安装失败 key=%s", key)
        self._delete_plugin_folder(folder)

    @_serialized
    def refresh(self, db: Session) -> None:
        rows = db.scalars(select(AcquisitionPluginVersion)).all()
        active = {}
        for row in rows:
            if row.status == "active" and self._folder(row.script_key, row.version).is_dir():
                active[row.script_key] = json.loads(row.manifest_json)
        self.catalog.replace(active, {row.script_key for row in rows})

    @_serialized
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
                # 上次写入在提交前失败时，目录会留下，但版本行已回滚。清掉这个空安装，允许重新上传。
                logger.warning("删除缺少数据库记录的插件目录 %s", folder)
                self._delete_plugin_folder(folder)
            script = db.get(AcquisitionScript, key)
            created_script = script is None
            if created_script:
                script = AcquisitionScript(key=key, name=str(manifest["name"]), version=version,
                    page_format_key=str(manifest["page_format_key"]), description=str(manifest["description"]),
                    parameter_schema_json=json.dumps(manifest.get("parameters", []), ensure_ascii=False), enabled=False)
                db.add(script)
            elif script.page_format_key != manifest["page_format_key"]:
                raise ValueError("新版本的网页格式与已安装版本不一致")
            try:
                if created_script:
                    # 模型和版本之间没有 relationship。同一事务一起提交时，SQLAlchemy 会先插入版本行，
                    # SQLite 打开外键后会因脚本行还不存在而失败。
                    db.flush()
                shutil.copy2(WORKER, stage / "_pictureshow_worker.py")
                row = AcquisitionPluginVersion(script_key=key, version=version,
                    manifest_json=json.dumps(manifest, ensure_ascii=False), package_sha256=hashlib.sha256(payload).hexdigest())
                db.add(row)
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                logger.exception("插件版本写入失败 key=%s version=%s", key, version)
                if "UNIQUE" in str(getattr(exc, "orig", exc)).upper():
                    raise ValueError("该插件版本已上传；版本不可覆盖") from exc
                raise ValueError("插件版本保存失败，请稍后重试") from exc
            except OSError as exc:
                db.rollback()
                logger.exception("插件包写入临时目录失败 key=%s version=%s", key, version)
                raise ValueError("插件文件无法保存到数据目录") from exc
            try:
                folder.parent.mkdir(parents=True, exist_ok=True)
                if folder.exists():
                    self._delete_plugin_folder(folder)
                shutil.move(str(stage), str(folder))
            except OSError as exc:
                logger.exception("插件目录保存失败 key=%s version=%s", key, version)
                self._rollback_saved_version(db, row, key, created_script, folder)
                raise ValueError("插件文件无法保存到数据目录") from exc
            db.refresh(row)
            self.refresh(db)
            return row

    def recover_stuck_prepares(self, db: Session) -> int:
        rows = db.scalars(
            select(AcquisitionPluginVersion).where(AcquisitionPluginVersion.status == "preparing")
        ).all()
        for row in rows:
            row.status = "failed"
            row.last_error = STALE_PREPARE_ERROR
        if rows:
            db.commit()
        return len(rows)

    def prepare(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status not in {"uploaded", "failed", "preparing"}:
            raise ValueError("当前插件版本不需要准备环境")
        row.status = "preparing"
        row.last_error = None
        db.commit()
        folder = self._folder(row.script_key, row.version)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(folder / ".venv")],
                check=True, timeout=300, capture_output=True,
            )
            python = self._python(folder)
            requirements = json.loads(row.manifest_json).get("requirements", [])
            if requirements:
                subprocess.run(
                    [str(python), "-m", "pip", "install", "--disable-pip-version-check", *requirements],
                    check=True, timeout=600, capture_output=True,
                )
            row.status = "ready"
            row.last_error = None
        except Exception as exc:
            stderr = _prepare_stderr(exc)
            logger.exception(
                "插件环境准备失败 key=%s version=%s\n%s",
                row.script_key, row.version, stderr,
            )
            row.status = "failed"
            row.last_error = f"插件依赖准备失败：{type(exc).__name__}"[:500]
            raise ValueError(row.last_error) from exc
        finally:
            db.commit()

    @staticmethod
    def _python(folder: Path) -> Path:
        return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @_serialized
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

    @_serialized
    def disable(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status != "active":
            raise ValueError("该版本未启用")
        row.status = "ready"
        db.get(AcquisitionScript, row.script_key).enabled = False
        db.commit()
        self.refresh(db)

    @_serialized
    def uninstall(self, db: Session, row: AcquisitionPluginVersion) -> None:
        if row.status == "active":
            raise ValueError("请先停用插件并等待环境准备结束")
        if self.catalog.in_use(row.script_key, row.version):
            raise ValueError("仍有调用正在使用该插件版本")
        if row.id in self.preparing_ids:
            raise ValueError("环境正在准备，请等待结束或重启后再卸载")
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
        return self.definition_from_manifest(manifest, credentials)

    def definition_from_manifest(self, manifest, credentials=None):
        manifest = deepcopy(manifest)
        return ScriptDefinition(key=str(manifest["key"]), name=str(manifest["name"]), version=str(manifest["version"]),
            page_format_key=str(manifest["page_format_key"]), description=str(manifest["description"]),
            adapter=PluginAdapter(self, manifest, credentials or {}),
            parameters=tuple(script_parameter_from_manifest(item) for item in manifest.get("parameters", [])),
            max_download_workers=parse_max_download_workers(manifest.get("max_download_workers")))

    def run(self, manifest: dict[str, object], operation: str, request: dict[str, object], *,
            stream: bool = False, abort_event: threading.Event | None = None,
            timeout: float | None = None, deadline: float | None = None):
        folder = self._folder(str(manifest["key"]), str(manifest["version"]))
        python = self._python(folder)
        if not python.is_file():
            raise ValueError("插件运行环境尚未准备")
        check_abort(abort_event, deadline)
        payload = json.dumps({**request, "entrypoint": manifest["entrypoint"], "operation": operation}, ensure_ascii=False)
        command = [str(python.absolute()), str(WORKER.resolve()), str(folder.resolve())]
        secrets = [str(value) for value in (request.get("credentials") or {}).values() if isinstance(value, str) and value]
        if timeout is None:
            timeout = DOWNLOAD_TIMEOUT_SECONDS if operation == "download" else OTHER_TIMEOUT_SECONDS
        timeout = _capped_timeout(timeout, deadline)
        try:
            if stream:
                return self._stream(command, payload, folder, secrets, abort_event, timeout, deadline)
            return self._run_once(command, payload, folder, secrets, abort_event, timeout)
        except subprocess.TimeoutExpired as exc:
            if deadline is not None:
                raise PluginAborted("试采超时，请缩小范围后重试") from exc
            raise RuntimeError("插件执行超时") from exc

    def _run_once(self, command, payload, folder, secrets, abort_event, timeout):
        return self.runner.run_once(command, payload, folder, secrets, abort_event, timeout)

    def _stream(self, command, payload, folder, secrets, abort_event, idle_timeout, deadline):
        try:
            yield from self.runner.stream(command, payload, folder, secrets, abort_event, idle_timeout, deadline)
        except subprocess.TimeoutExpired as exc:
            if deadline is not None:
                raise PluginAborted("试采超时，请缩小范围后重试") from exc
            raise RuntimeError("插件执行超时") from exc

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
        try:
            return json.loads(self.cipher().decrypt(account.encrypted_json.encode("ascii")))
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("账号凭据无法解密，请重新保存账号配置") from exc


@dataclass
class PluginAdapter(SourceAdapter):
    manager: PluginManager
    manifest: dict[str, object]
    credentials: dict[str, object]
    last_state: dict[str, object] | None = None
    abort_event: threading.Event | None = None
    deadline: float | None = None
    context: PluginExecutionContext | None = None

    def _execution_options(self):
        if self.context is not None:
            return self.context.credentials, self.context.abort_event, self.context.deadline
        return self.credentials, self.abort_event, self.deadline

    def enumerate_pages(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool):
        credentials, abort_event, deadline = self._execution_options()
        request = {"crawl_url": crawl_url, "parameters": parameters, "known_external_keys": sorted(known_external_keys),
            "incremental": incremental, "credentials": credentials}
        stream = self.manager.run(
            self.manifest, "enumerate_pages", request, stream=True,
            abort_event=abort_event, timeout=ENUMERATE_IDLE_TIMEOUT_SECONDS, deadline=deadline,
        )
        try:
            for raw in stream:
                if not isinstance(raw, dict):
                    raise ValueError("插件页面输出无效")
                if isinstance(raw.get("plugin_state"), dict):
                    self.last_state = raw["plugin_state"]
                items_raw = raw.get("items")
                if not isinstance(items_raw, list):
                    raise ValueError("插件页面输出无效")
                items = tuple(remote_item_from_plugin(item) for item in items_raw)
                yield RemotePage(page_number=int(raw["page_number"]), items=items, stop_reason=raw.get("stop_reason"))
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

    def download(self, item: dict[str, object], temporary_dir: Path) -> Path:
        credentials, abort_event, deadline = self._execution_options()
        result = self.manager.run(
            self.manifest, "download",
            {"item": item, "credentials": credentials, "temporary_dir": str(temporary_dir)},
            abort_event=abort_event, timeout=DOWNLOAD_TIMEOUT_SECONDS, deadline=deadline,
        )
        if not isinstance(result, dict) or not isinstance(result.get("path"), str):
            raise ValueError("插件下载结果缺少文件路径")
        path = Path(result["path"]).resolve()
        if not path.is_relative_to(temporary_dir.resolve()) or not path.is_file():
            raise ValueError("插件下载文件必须位于指定临时目录")
        return path


def _prepare_stderr(exc: BaseException) -> str:
    output = getattr(exc, "stderr", None)
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    if isinstance(output, str) and output.strip():
        return output[-4000:]
    return str(exc)


def _capped_timeout(timeout: float, deadline: float | None) -> float:
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PluginAborted("试采超时，请缩小范围后重试")
    return min(timeout, remaining)
