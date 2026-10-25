from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType


_TEST_RUNTIME_PATH = Path(tempfile.mkdtemp(prefix="pictureshow-contract-"))


class StubService:
    """仅用于导入应用和生成契约，不执行任何外部服务初始化。"""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


SERVICE_CLASSES = (
    ("app.services.storage", "MinioStorage"),
    ("app.services.face", "FaceService"),
    ("app.services.qdrant", "QdrantVectorStore"),
    ("app.services.ocr", "OcrService"),
    ("app.services.importer", "PictureService"),
    ("app.services.videos", "VideoService"),
    ("app.services.subtitles", "SubtitleService"),
)


def _configure_test_environment() -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_RUNTIME_PATH / 'app.db').as_posix()}"
    os.environ["DATA_DIR"] = str(_TEST_RUNTIME_PATH)


def load_test_main() -> ModuleType:
    """使用临时数据库和服务桩重新导入 app.main。"""
    _configure_test_environment()
    original_modules: dict[str, ModuleType | None] = {}
    for module_name, class_name in SERVICE_CLASSES:
        original_modules[module_name] = sys.modules.get(module_name)
        module = ModuleType(module_name)
        setattr(module, class_name, StubService)
        if module_name == "app.services.importer":
            # background_tasks 会从真实 importer 导入 PersonImportPartialError；桩模块也要带上。
            class PersonImportPartialError(Exception):
                pass

            setattr(module, "PersonImportPartialError", PersonImportPartialError)
        sys.modules[module_name] = module

    sys.modules.pop("app.main", None)
    try:
        return __import__("app.main", fromlist=["app"])
    finally:
        for module_name, original in original_modules.items():
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original
