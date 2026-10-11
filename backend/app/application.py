from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging
import time
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.lifecycle import initialize_database, initialize_runtime
from app.services.container import ServiceContainer


def _configure_application_logging() -> None:
    app_logger = logging.getLogger("app")
    if not any(getattr(handler, "pictureshow_console", False) for handler in app_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.pictureshow_console = True
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)


class SlowRequestMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started_at = time.perf_counter()
        method = scope["method"]
        path = scope["path"]
        logger = logging.getLogger("app.http")
        loop = asyncio.get_running_loop()
        pending = loop.call_later(1.0, logger.warning, "请求仍在等待 method=%s path=%s", method, path)
        try:
            await self.app(scope, receive, send)
        finally:
            pending.cancel()
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            if elapsed_ms >= 1000:
                logger.warning("请求已完成 method=%s path=%s duration_ms=%.0f", method, path, elapsed_ms)


def create_app(
    *,
    settings: Settings,
    services: ServiceContainer,
    engine: Engine,
    session_factory: Callable[[], Session],
    logger: logging.Logger,
) -> FastAPI:
    _configure_application_logging()
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        initialize_database(engine)
        initialize_runtime(settings, services, session_factory, logger)
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(SlowRequestMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.services = services
    app.state.engine = engine
    app.state.session_factory = session_factory
    return app
