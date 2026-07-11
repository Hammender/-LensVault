from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.application import create_app
from app.core.config import Settings


class FakeStorage:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def ensure_bucket(self) -> None:
        self.calls.append("storage")


class FakeVectorStore:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def ensure_collections(self) -> None:
        self.calls.append("vector_store")


class FakeFaceService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def warmup(self) -> None:
        self.calls.append("face")


class FakeOcrService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def engine_status(self) -> dict[str, bool | str | None]:
        self.calls.append("ocr")
        return {
            "rapidocr_ready": True,
            "tesseract_ready": False,
            "rapidocr_error": None,
            "tesseract_error": "未配置",
        }


class FakePictureService:
    def ensure_system_tags(self, _db: object, _workspace_id: int) -> None:
        raise AssertionError("空数据库不应初始化工作空间标签")


def test_create_app_uses_injected_lifecycle_dependencies(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    engine = create_engine(f"sqlite:///{(tmp_path / 'factory.db').as_posix()}")
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    settings = Settings(database_url=str(engine.url), data_dir=tmp_path)
    services = SimpleNamespace(
        storage=FakeStorage(calls),
        vector_store=FakeVectorStore(calls),
        face=FakeFaceService(calls),
        ocr=FakeOcrService(calls),
        pictures=FakePictureService(),
    )

    recovered_types: list[str] = []

    def fake_fail_incomplete_tasks(_db: object, task_type: str) -> int:
        recovered_types.append(task_type)
        return 0

    monkeypatch.setattr("app.lifecycle.fail_incomplete_tasks", fake_fail_incomplete_tasks)
    app = create_app(
        settings=settings,
        services=services,
        engine=engine,
        session_factory=session_factory,
        logger=logging.getLogger("test.application"),
    )

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.services is services
            assert app.state.engine is engine

    asyncio.run(run_lifespan())

    assert inspect(engine).has_table("video_items")
    assert calls == ["storage", "vector_store", "face", "ocr"]
    assert recovered_types == [
        "gallery_import",
        "gallery_rich_import",
        "gallery_zip_import",
        "person_import",
        "video_subtitle_generation",
    ]
    engine.dispose()
