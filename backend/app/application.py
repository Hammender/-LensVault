from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.lifecycle import initialize_database, initialize_runtime
from app.services.container import ServiceContainer


def create_app(
    *,
    settings: Settings,
    services: ServiceContainer,
    engine: Engine,
    session_factory: Callable[[], Session],
    logger: logging.Logger,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        initialize_database(engine)
        initialize_runtime(settings, services, session_factory, logger)
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
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
