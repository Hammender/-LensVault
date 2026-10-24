from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.application import SlowRequestMiddleware, _configure_application_logging, create_app
from app.core.config import Settings
from app.lifecycle import initialize_database


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
    assert calls == ["storage", "vector_store", "face"]
    assert recovered_types == [
        "gallery_import",
        "gallery_rich_import",
        "gallery_zip_import",
        "video_zip_import",
        "person_import",
        "video_subtitle_generation",
        "gallery_similarity_scan",
        "acquisition_similarity_scan",
        "acquisition_similarity_scan_mirror_pending",
        "acquisition_similarity_scan_normal_gallery",
        "acquisition_similarity_scan_mirror_gallery",
    ]
    engine.dispose()


def test_application_logging_uses_one_console_output(monkeypatch, capsys) -> None:
    root = logging.getLogger()
    app_logger = logging.getLogger("app")
    old_handler = logging.StreamHandler()
    old_handler.pictureshow_console = True
    monkeypatch.setattr(app_logger, "handlers", [old_handler])
    monkeypatch.setattr(app_logger, "propagate", True)
    monkeypatch.setattr(root, "handlers", [logging.StreamHandler()])
    _configure_application_logging()
    _configure_application_logging()

    logging.getLogger("app.http").info("测试请求耗时")

    assert capsys.readouterr().err.count("测试请求耗时") == 1


def test_request_wait_and_completion_are_info_logs(monkeypatch) -> None:
    async def run():
        loop = asyncio.get_running_loop()
        pending_messages = []
        messages = []
        logger = logging.getLogger("app.http")
        monkeypatch.setattr(logger, "info", lambda *args: messages.append(args))
        monkeypatch.setattr(logger, "warning", lambda *_: (_ for _ in ()).throw(AssertionError("耗时记录不应使用 WARNING")))
        monkeypatch.setattr(loop, "call_later", lambda delay, callback, *args: pending_messages.append((callback, args)) or SimpleNamespace(cancel=lambda: None))
        times = iter([0.0, 2.0])
        monkeypatch.setattr("app.application.time", SimpleNamespace(perf_counter=lambda: next(times)))

        async def app(_scope, _receive, _send):
            callback, args = pending_messages[0]
            callback(*args)

        await SlowRequestMiddleware(app)({"type": "http", "method": "POST", "path": "/api/acquisition/assets/reject"}, None, None)
        assert len(messages) == 2
        assert messages[0][0].startswith("请求仍在等待")
        assert messages[1][0].startswith("请求已完成")

    asyncio.run(run())


