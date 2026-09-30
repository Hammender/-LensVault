"""采集插件及工作区凭据管理接口。"""

from __future__ import annotations

import json
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.context import CurrentContext, require_context, require_permission, require_workspace_owner
from app.models import AcquisitionCategory, AcquisitionPluginCredential, AcquisitionPluginVersion, AcquisitionRun, AcquisitionSource, AcquisitionSourceScript
from app.services.acquisition_plugins.manager import MAX_PACKAGE_BYTES, PluginAdapter


router = APIRouter(prefix="/api/acquisition/plugins", tags=["采集插件"])


class CredentialSave(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    values: dict[str, object]


class PluginPreviewRequest(BaseModel):
    category_id: int
    credential_id: int | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    limit: int = Field(default=3, ge=1, le=5)


def _manager(request: Request):
    return request.app.state.services.acquisition.plugins


def _admin(current: CurrentContext) -> None:
    if not current.user.is_admin:
        raise HTTPException(status_code=403, detail="仅系统管理员可以管理采集插件")


def _version(db: Session, key: str, version: str) -> AcquisitionPluginVersion:
    row = db.scalar(select(AcquisitionPluginVersion).where(
        AcquisitionPluginVersion.script_key == key, AcquisitionPluginVersion.version == version))
    if row is None:
        raise HTTPException(status_code=404, detail="插件版本不存在")
    return row


def _version_read(row: AcquisitionPluginVersion) -> dict[str, object]:
    manifest = json.loads(row.manifest_json)
    return {"key": row.script_key, "name": manifest["name"], "version": row.version,
            "description": manifest["description"], "status": row.status,
            "requirements": manifest.get("requirements", []),
            "credentials": manifest.get("credentials", []), "created_at": row.created_at}


@router.get("")
def list_plugins(db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    return [_version_read(row) for row in db.scalars(
        select(AcquisitionPluginVersion).order_by(AcquisitionPluginVersion.script_key, AcquisitionPluginVersion.created_at.desc()))]


@router.post("")
async def upload_plugin(request: Request, file: UploadFile = File(...),
                        db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    _admin(current)
    payload = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        return _version_read(_manager(request).upload(db, payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _prepare_task(session_factory, manager, row_id: int) -> None:
    with session_factory() as db:
        row = db.get(AcquisitionPluginVersion, row_id)
        if row is not None:
            try:
                manager.prepare(db, row)
            except ValueError:
                pass  # 状态已记录；不把安装器输出暴露给浏览器。


@router.post("/{key}/versions/{version}/prepare")
def prepare_plugin(key: str, version: str, background: BackgroundTasks, request: Request,
                   db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    _admin(current)
    row = _version(db, key, version)
    if row.status not in {"uploaded", "failed"}:
        raise HTTPException(status_code=409, detail="该插件版本当前无法准备环境")
    row.status = "preparing"
    db.commit()
    background.add_task(_prepare_task, request.app.state.session_factory, _manager(request), row.id)
    return {"status": "queued"}


@router.post("/{key}/versions/{version}/activate")
def activate_plugin(key: str, version: str, request: Request, db: Session = Depends(get_db),
                    current: CurrentContext = Depends(require_context)):
    _admin(current)
    try:
        row = _version(db, key, version)
        _manager(request).activate(db, row)
        return _version_read(row)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{key}/versions/{version}/disable")
def disable_plugin(key: str, version: str, request: Request, db: Session = Depends(get_db),
                   current: CurrentContext = Depends(require_context)):
    _admin(current)
    try:
        row = _version(db, key, version)
        _manager(request).disable(db, row)
        return _version_read(row)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{key}/versions/{version}")
def uninstall_plugin(key: str, version: str, request: Request, db: Session = Depends(get_db),
                     current: CurrentContext = Depends(require_context)):
    _admin(current)
    try:
        _manager(request).uninstall(db, _version(db, key, version))
        return {"status": "removed"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{key}/guide")
def plugin_guide(key: str, request: Request, current: CurrentContext = Depends(require_context)):
    manager = _manager(request)
    manifest = manager.active.get(key)
    if manifest is None:
        raise HTTPException(status_code=404, detail="插件未启用")
    path = manager._folder(key, str(manifest["version"])) / "README.md"
    return {"text": path.read_text(encoding="utf-8")}


@router.post("/{key}/preview")
def preview_plugin(key: str, payload: PluginPreviewRequest, request: Request,
                   db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    require_permission(current, "can_add_gallery")
    manager = _manager(request)
    if key == "telegram-channel-mtproto":
        raise HTTPException(status_code=409, detail="Telegram 请使用正式运行中的消息数量限制进行小量采集")
    if key not in manager.active:
        raise HTTPException(status_code=409, detail="插件未启用")
    category = db.get(AcquisitionCategory, payload.category_id)
    source = db.get(AcquisitionSource, category.source_id) if category else None
    if category is None or source is None or source.workspace_id != current.workspace_id or not category.enabled or not source.enabled:
        raise HTTPException(status_code=404, detail="采集分类不可用")
    binding = db.scalar(select(AcquisitionSourceScript).where(
        AcquisitionSourceScript.source_id == source.id,
        AcquisitionSourceScript.script_key == key,
        AcquisitionSourceScript.enabled.is_(True)))
    if binding is None:
        raise HTTPException(status_code=409, detail="该插件未绑定到目标站点")
    fields = manager.active[key].get("credentials", [])
    credentials = {}
    if fields:
        account = db.get(AcquisitionPluginCredential, payload.credential_id) if payload.credential_id else None
        if account is None or account.workspace_id != current.workspace_id or account.script_key != key or account.status != "valid":
            raise HTTPException(status_code=409, detail="请先选择已通过连接测试的账号")
        credentials = manager.credentials(account)
    service = request.app.state.services.acquisition
    definition = manager.get_definition(key, credentials=credentials)
    try:
        defaults = json.loads(binding.default_parameters_json or "{}")
        parameters = definition.validate_parameters({**defaults, **payload.parameters})
        adapter = definition.adapter
        assert isinstance(adapter, PluginAdapter)
        results = []
        pages = adapter.enumerate_pages(category.crawl_url, parameters, set(), False)
        try:
            for page in pages:
                for item in page.items:
                    if item.ignored_reason:
                        continue
                    downloaded = service._download_and_analyze(item, category.crawl_url, adapter)
                    try:
                        results.append({"title": item.title, "source_url": item.source_url,
                                        "media_type": downloaded.media_type, "filename": downloaded.filename,
                                        "size_bytes": downloaded.size_bytes})
                    finally:
                        if downloaded.file_path is not None:
                            shutil.rmtree(downloaded.file_path.parent, ignore_errors=True)
                    if len(results) >= payload.limit:
                        break
                if len(results) >= payload.limit or page.reached_collection_end:
                    break
        finally:
            pages.close()
        return {"items": results}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{key}/credentials")
def list_credentials(key: str, db: Session = Depends(get_db),
                     current: CurrentContext = Depends(require_context)):
    rows = db.scalars(select(AcquisitionPluginCredential).where(
        AcquisitionPluginCredential.workspace_id == current.workspace_id,
        AcquisitionPluginCredential.script_key == key).order_by(AcquisitionPluginCredential.name)).all()
    return [{"id": row.id, "name": row.name, "status": row.status,
             "last_tested_at": row.last_tested_at} for row in rows]


@router.post("/{key}/credentials")
def save_credential(key: str, payload: CredentialSave, request: Request,
                    db: Session = Depends(get_db), current: CurrentContext = Depends(require_workspace_owner)):
    try:
        row = _manager(request).save_credential(db, current.workspace_id, key, payload.name.strip(), payload.values)
        return {"id": row.id, "name": row.name, "status": row.status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/credentials/{credential_id}/test")
def test_credential(credential_id: int, request: Request, db: Session = Depends(get_db),
                    current: CurrentContext = Depends(require_workspace_owner)):
    row = db.get(AcquisitionPluginCredential, credential_id)
    if row is None or row.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="账号配置不存在")
    manager = _manager(request)
    manifest = manager.active.get(row.script_key)
    if manifest is None:
        raise HTTPException(status_code=409, detail="插件未启用")
    reason = None
    secrets: list[str] = []
    try:
        credentials = manager.credentials(row)
        secrets = [value for value in credentials.values() if isinstance(value, str) and value]
        result = manager.run(manifest, "test_connection", {"credentials": credentials})
        row.status = "valid" if isinstance(result, dict) and result.get("ok") is True else "invalid"
        if row.status == "invalid" and isinstance(result, dict):
            reason = str(result.get("reason") or "站点未确认登录状态")
    except Exception as exc:
        row.status = "invalid"
        reason = str(exc) or "连接测试失败"
    if reason:
        for secret in secrets:
            reason = reason.replace(secret, "[已隐藏凭据]")
        reason = reason[:300]
    from app.core.timezones import shanghai_now
    row.last_tested_at = shanghai_now()
    db.commit()
    return {"id": row.id, "name": row.name, "status": row.status, "reason": reason}


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: int, db: Session = Depends(get_db),
                      current: CurrentContext = Depends(require_workspace_owner)):
    row = db.get(AcquisitionPluginCredential, credential_id)
    if row is None or row.workspace_id != current.workspace_id:
        raise HTTPException(status_code=404, detail="账号配置不存在")
    active_run = db.scalar(select(AcquisitionRun.id).where(
        AcquisitionRun.credential_id == credential_id,
        AcquisitionRun.status.in_(("pending", "running"))))
    if active_run is not None:
        raise HTTPException(status_code=409, detail="仍有采集任务正在使用该账号")
    db.delete(row)
    db.commit()
    return {"status": "removed"}
