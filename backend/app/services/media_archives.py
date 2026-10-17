"""图片与视频素材包的路径及清单大小校验。"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from zipfile import ZipFile

CHUNK = 1024 * 1024
MAX_MANIFEST = 16 * CHUNK
MAX_FILE = 64 * 1024 * CHUNK
MAX_TOTAL = 1024 * 1024 * CHUNK


def safe_entry(archive: ZipFile, name: str, maximum=MAX_FILE):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ValueError("素材包内路径无效")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("素材包内路径不安全")
    info = archive.getinfo(name)
    if info.is_dir() or info.file_size > maximum or info.flag_bits & 1:
        raise ValueError("素材包文件大小或格式不支持")
    return info


def read_json_entry(archive: ZipFile, name="metadata.json"):
    info = safe_entry(archive, name, MAX_MANIFEST)
    return json.loads(archive.read(info))

