from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def stable_cache_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


class CacheStore:
    def __init__(self, root: Path, *, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled

    def load(self, namespace: str, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.root / namespace / f"{key}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return value if isinstance(value, dict) and value.get("cache_key") == key else None

    def save(self, namespace: str, key: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        directory = self.root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        content = json.dumps({"cache_key": key, **payload}, ensure_ascii=False, separators=(",", ":"))
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, directory / f"{key}.json")
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
