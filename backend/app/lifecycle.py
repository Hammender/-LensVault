from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timezones import shanghai_now
from app.models import VideoItem, Workspace
from app.native_runtime import configure_native_compute_runtime
from app.services.acquisition_adapters import SCRIPT_REGISTRY
from app.services.container import ServiceContainer
from app.services.tasks import fail_incomplete_tasks


INCOMPLETE_TASK_TYPES = (
    "gallery_import",
    "gallery_rich_import",
    "gallery_zip_import",
    "person_import",
    "video_subtitle_generation",
    "gallery_similarity_scan",
    "acquisition_similarity_scan",
    "acquisition_similarity_scan_mirror_pending",
    "acquisition_similarity_scan_normal_gallery",
    "acquisition_similarity_scan_mirror_gallery",
)

ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


def _upsert_acquisition_scripts(connection) -> None:
    """把采集脚本注册表同步进 acquisition_scripts 表（幂等 upsert）。"""
    for definition in SCRIPT_REGISTRY.values():
        values = {
            "key": definition.key,
            "name": definition.name,
            "version": definition.version,
            "page_format_key": definition.page_format_key,
            "description": definition.description,
            "parameter_schema_json": json.dumps(
                [item.as_dict() for item in definition.parameters], ensure_ascii=False
            ),
            "now": shanghai_now(),
        }
        connection.execute(
            text(
                "INSERT INTO acquisition_scripts (key, name, version, page_format_key, description, parameter_schema_json, enabled, created_at, updated_at) "
                "VALUES (:key, :name, :version, :page_format_key, :description, :parameter_schema_json, 1, :now, :now) "
                "ON CONFLICT(key) DO UPDATE SET name=excluded.name, version=excluded.version, "
                "page_format_key=excluded.page_format_key, description=excluded.description, "
                "parameter_schema_json=excluded.parameter_schema_json, enabled=1, updated_at=:now"
            ),
            values,
        )


def seed_acquisition_scripts(engine: Engine) -> None:
    """启动期同步采集脚本种子数据，保证注册表与代码内定义一致。"""
    if "acquisition_scripts" not in inspect(engine).get_table_names():
        return
    with engine.begin() as connection:
        _upsert_acquisition_scripts(connection)


def _alembic_config(database_url: str) -> Config:
    """构建指向指定数据库的 Alembic 配置（URL 不落盘，运行时注入）。"""
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def run_database_migrations(engine: Engine) -> str:
    """执行 Alembic 迁移，返回迁移结果。

    - fresh-database：空库，从基线建全量表并升级到最新；
    - legacy-stamped：存量库无 alembic_version（本机已不应再出现），仅 stamp head 并警告；
    - up-to-date：常规启动，升级到最新迁移版本。
    """
    logger = logging.getLogger(__name__)
    table_names = set(inspect(engine).get_table_names())
    business_tables = table_names - {"alembic_version"}
    config = _alembic_config(engine.url.render_as_string(hide_password=False))
    if not business_tables:
        command.upgrade(config, "head")
        return "fresh-database"
    if "alembic_version" not in table_names:
        logger.warning(
            "数据库迁移：检测到业务表但无 alembic_version，将 stamp 到 head。"
            "若结构落后于模型，请手工检查后处理。"
        )
        command.stamp(config, "head")
        return "legacy-stamped"
    command.upgrade(config, "head")
    return "up-to-date"


def initialize_database(engine: Engine) -> None:
    """启动期数据库初始化：执行 Alembic 迁移并同步采集脚本种子。"""
    logger = logging.getLogger(__name__)
    migration_outcome = run_database_migrations(engine)
    if migration_outcome == "legacy-stamped":
        logger.info("数据库迁移：存量库已登记 Alembic 基线（stamp head）")
    elif migration_outcome == "fresh-database":
        logger.info("数据库迁移：全新库已通过 Alembic 建表")
    seed_acquisition_scripts(engine)


def initialize_runtime(
    settings: Settings,
    services: ServiceContainer,
    session_factory: Callable[[], Session],
    logger: logging.Logger,
) -> None:
    logger.info("应用启动：开始检查存储、向量库、人脸识别和 OCR 依赖")
    library_threads = configure_native_compute_runtime(settings.image_compute_library_threads)
    logger.info("原生计算线程已封顶：library_threads=%s", library_threads)
    services.storage.ensure_bucket()
    services.vector_store.ensure_collections()
    services.face.warmup()
    ocr_status = services.ocr.engine_status()
    logger.info(
        "OCR 引擎状态：rapidocr_ready=%s tesseract_ready=%s rapidocr_error=%s tesseract_error=%s",
        ocr_status["rapidocr_ready"],
        ocr_status["tesseract_ready"],
        ocr_status["rapidocr_error"] or "-",
        ocr_status["tesseract_error"] or "-",
    )

    db = session_factory()
    try:
        for workspace in db.scalars(select(Workspace)).all():
            services.pictures.ensure_system_tags(db, workspace.id)
        recovered = sum(fail_incomplete_tasks(db, task_type) for task_type in INCOMPLETE_TASK_TYPES)
        if recovered > 0:
            logger.warning("应用启动：已恢复未完成任务 count=%d", recovered)
        acquisition = getattr(services, "acquisition", None)
        interrupted_runs = acquisition.recover_runs(db) if acquisition is not None else 0
        import_recovery = (
            acquisition.recover_imports(db) if acquisition is not None else {"recovered": 0, "failed": 0}
        )
        reconciled_items = acquisition.reconcile_run_metrics(db) if acquisition is not None else 0
        expired_exports = acquisition.cleanup_expired_exports(db) if acquisition is not None else 0
        if (
            interrupted_runs
            or expired_exports
            or import_recovery["recovered"]
            or import_recovery["failed"]
            or reconciled_items
        ):
            logger.warning(
                "应用启动：已处理采集状态 interrupted=%d import_recovered=%d import_failed=%d "
                "metrics_reconciled=%d expired_exports=%d",
                interrupted_runs,
                import_recovery["recovered"],
                import_recovery["failed"],
                reconciled_items,
                expired_exports,
            )
        videos_missing_sha = db.scalars(select(VideoItem).where(VideoItem.sha256.is_(None))).all()
        if videos_missing_sha:
            backfilled_count = 0
            for video in videos_missing_sha:
                try:
                    video.sha256 = services.videos.hash_object(video.object_key)
                    backfilled_count += 1
                except Exception:
                    logger.warning(
                        "应用启动：计算视频 SHA256 失败 video_id=%s object_key=%s",
                        video.id,
                        video.object_key,
                    )
            if backfilled_count > 0:
                db.commit()
                logger.info("应用启动：已补齐存量视频 SHA256 count=%d", backfilled_count)
    finally:
        db.close()

    logger.info(
        "应用启动完成：minio_bucket=%s qdrant_sample_collection=%s",
        settings.minio_bucket,
        settings.qdrant_known_collection,
    )
