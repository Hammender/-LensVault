from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.config import Settings


def import_directory(settings: Settings, task_id: str) -> Path:
    directory = Path(settings.data_dir) / "tmp" / "imports" / task_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def spool_upload(settings: Settings, task_id: str, index: int, upload, max_bytes: int | None = None) -> Path:
    filename = Path(upload.filename or "upload").name or "upload"
    target = import_directory(settings, task_id) / f"{index:04d}_{filename}"
    written = 0
    with target.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if max_bytes is not None and written > max_bytes:
                raise ValueError("上传文件超过大小上限")
            handle.write(chunk)
    return target


def cleanup_import(settings: Settings, task_id: str) -> None:
    directory = Path(settings.data_dir) / "tmp" / "imports" / task_id
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


def cleanup_stale_imports(settings: Settings, max_age_seconds: int = 24 * 60 * 60) -> None:
    root = Path(settings.data_dir) / "tmp" / "imports"
    if not root.exists():
        return
    cutoff = time.time() - max_age_seconds
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue
