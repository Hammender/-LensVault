from __future__ import annotations

from app.native_runtime import apply_native_thread_environment

apply_native_thread_environment()

import logging

from app.application import create_app
from app.api import videos as videos_api
from app.api._helpers import get_workspace_object as _get_workspace_object
from app.api.provenance import router as provenance_router
from app.api.acquisition import router as acquisition_router
from app.api.acquisition_plugins import router as acquisition_plugins_router
from app.api.gallery import (
    imports_router as gallery_imports_router,
    list_gallery_similarity_groups,
    preview_normal_near_duplicate_auto_delete,
    router as gallery_router,
    update_gallery_similarity_group,
)
from app.api.people import create_person, router as people_router
from app.api.face_cases import router as face_cases_router
from app.api.statistics import router as statistics_router
from app.api.subtitles import router as subtitle_service_router
from app.api.system import router as system_router
from app.api.videos import (
    create_video_category_tag as _create_video_category_tag,
    create_video_person as _create_video_person,
    router as videos_router,
)
from app.api.workspaces import router as workspaces_router
from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.dependencies.context import (
    AUTH_COOKIE_NAME,
    PERMISSION_FIELDS,
    CurrentContext,
    enforce_request_permission as _enforce_request_permission,
    ensure_private_workspace as _ensure_private_workspace,
    require_context,
    require_workspace_owner,
)
from app.schemas import GallerySimilarityGroupUpdate
from app.services.container import build_service_container

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
logger = logging.getLogger(__name__)
logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").disabled = True
logging.getLogger("uvicorn.access").propagate = False

settings = get_settings()
services = build_service_container(settings)
video_service = services.videos
app = create_app(
    settings=settings,
    services=services,
    engine=engine,
    session_factory=SessionLocal,
    logger=logger,
)
app.include_router(acquisition_router)
app.include_router(acquisition_plugins_router)
app.include_router(system_router)
app.include_router(workspaces_router)
app.include_router(people_router)
app.include_router(gallery_imports_router)
app.include_router(subtitle_service_router)
app.include_router(gallery_router)
app.include_router(face_cases_router)
app.include_router(provenance_router)
app.include_router(videos_router)


def _call_video_compatibility_handler(handler, *args, **kwargs):
    original_service = videos_api.video_service
    videos_api.video_service = video_service
    try:
        return handler(*args, **kwargs)
    finally:
        videos_api.video_service = original_service


def create_video_category_tag(*args, **kwargs):
    return _call_video_compatibility_handler(_create_video_category_tag, *args, **kwargs)


async def create_video_person(*args, **kwargs):
    return await _call_video_compatibility_handler(_create_video_person, *args, **kwargs)

app.include_router(statistics_router)
