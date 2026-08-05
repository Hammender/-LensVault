from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timezones import shanghai_now
from app.models import GallerySimilarityScan, Person, UploadHistory
from app.services.similarity import mark_similarity_scans_stale
from app.services.tasks import update_task

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _mark_task_failed(session_factory: SessionFactory, task_id: str, error: Exception) -> None:
    try:
        failed_db = session_factory()
        try:
            update_task(failed_db, task_id, status="failed", message=str(error))
        finally:
            failed_db.close()
    except Exception:
        logger.exception("Failed to persist task failed status task_id=%s", task_id)


def process_gallery_import_task(
    session_factory: SessionFactory,
    picture_service: Any,
    task_id: str,
    uploads: list[tuple[str, bytes, str | None]],
    metadata_by_index: list[dict[str, list[str] | str | None]],
    rich_mode: bool,
    workspace_id: int,
) -> None:
    logger.info("Gallery import task started task_id=%s files=%d rich_mode=%s", task_id, len(uploads), rich_mode)
    db = session_factory()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在识别上传图片")
        total = max(len(uploads), 1)
        total_known = 0
        total_unknown_faces = 0
        total_duplicated = 0
        for index, (filename, payload, content_type) in enumerate(uploads, start=1):
            metadata = metadata_by_index[index - 1] if index - 1 < len(metadata_by_index) else {"person_names": [], "tag_names": []}
            logger.info(
                "Gallery import processing task_id=%s index=%d/%d filename=%s bytes=%d manual_persons=%d manual_tags=%d",
                task_id,
                index,
                total,
                filename,
                len(payload),
                len(metadata.get("person_names", [])),
                len(metadata.get("tag_names", [])),
            )
            photo, summary = picture_service.import_gallery_photo(
                db,
                filename,
                payload,
                content_type,
                metadata.get("tag_names", []),
                rich_mode,
                metadata.get("rich_text"),
                workspace_id,
            )
            for raw_name in metadata.get("person_names", []):
                person_name = raw_name.strip()
                if not person_name:
                    continue
                person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == person_name))
                if person is None:
                    person = Person(
                        workspace_id=workspace_id,
                        name=person_name,
                        display_name=person_name,
                        note=None,
                        is_unknown=False,
                    )
                    db.add(person)
                    db.flush()
                    logger.info(
                        "Created person from gallery upload task_id=%s photo_id=%s person_id=%s name=%s",
                        task_id,
                        photo.id,
                        person.id,
                        person_name,
                    )
                picture_service.ensure_gallery_person_tag(db, photo.id, person.id, "manual_upload")
                picture_service.apply_person_tags_to_gallery_photo(db, photo.id, person.id)
            db.commit()
            total_known += summary.known_matches
            total_unknown_faces += summary.unknown_faces
            total_duplicated += summary.duplicated
            logger.info(
                "Gallery import progress task_id=%s index=%d/%d photo_id=%s known=%d unknown_faces=%d duplicated=%d",
                task_id,
                index,
                total,
                photo.id,
                total_known,
                total_unknown_faces,
                total_duplicated,
            )
            update_task(
                db,
                task_id,
                status="running",
                progress=index / total,
                message=(
                    f"已处理 {index}/{total} 张，识别 {total_known} 个已知人物，"
                    f"标记 {total_unknown_faces} 张未知人脸，重复跳过 {total_duplicated} 张"
                ),
            )
        final_message = (
            f"导入完成：识别 {total_known} 个已知人物，标记 {total_unknown_faces} 张未知人脸，"
            f"重复跳过 {total_duplicated} 张"
        )
        if total - total_duplicated > 0:
            mark_similarity_scans_stale(db, workspace_id)
            db.commit()
        update_task(db, task_id, status="completed", progress=1.0, message=final_message)
        try:
            db.add(
                UploadHistory(
                    workspace_id=workspace_id,
                    upload_type="rich" if rich_mode else "gallery",
                    total_count=total,
                    success_count=total - total_duplicated,
                    duplicate_count=total_duplicated,
                )
            )
            db.commit()
            logger.info(
                "Upload history recorded upload_type=%s total=%d success=%d duplicate=%d",
                "rich" if rich_mode else "gallery",
                total,
                total - total_duplicated,
                total_duplicated,
            )
        except Exception:
            logger.exception("Failed to record upload history")
            db.rollback()
        logger.info(
            "Gallery import task completed task_id=%s known=%d unknown_faces=%d duplicated=%d",
            task_id,
            total_known,
            total_unknown_faces,
            total_duplicated,
        )
    except Exception as exc:
        logger.exception("Gallery import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        _mark_task_failed(session_factory, task_id, exc)
    finally:
        db.close()
        logger.debug("Gallery import task db session closed task_id=%s", task_id)


def process_person_import_task(
    session_factory: SessionFactory,
    picture_service: Any,
    task_id: str,
    zip_bytes: bytes,
    workspace_id: int,
) -> None:
    logger.info("Person import task started task_id=%s bytes=%d", task_id, len(zip_bytes))
    db = session_factory()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在解析导入数据")

        def progress_callback(processed: int, total: int) -> None:
            progress = 0.05 + 0.9 * (processed / max(total, 1))
            update_task(
                db,
                task_id,
                status="running",
                progress=min(progress, 1.0),
                message=f"正在处理 {processed}/{total} 个样本",
            )

        result = picture_service.import_persons_from_zip(db, zip_bytes, workspace_id, progress_callback)
        message = (
            f"导入完成：创建 {result['created_persons']} 个人物，"
            f"匹配 {result['existing_persons']} 个已有，"
            f"新增 {result['added_samples']} 个样本，"
            f"跳过 {result['skipped_samples']} 个重复，"
            f"绑定 {result['tags_added']} 个标签"
        )
        update_task(db, task_id, status="completed", progress=1.0, message=message)
        logger.info("Person import task completed task_id=%s %s", task_id, message)
    except Exception as exc:
        logger.exception("Person import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        _mark_task_failed(session_factory, task_id, exc)
    finally:
        db.close()
        logger.debug("Person import task db session closed task_id=%s", task_id)


def process_gallery_zip_import_task(
    session_factory: SessionFactory,
    picture_service: Any,
    task_id: str,
    zip_bytes: bytes,
    workspace_id: int,
) -> None:
    logger.info("Gallery zip import task started task_id=%s bytes=%d", task_id, len(zip_bytes))
    db = session_factory()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在解析展示图 ZIP")

        def progress_callback(processed: int, total: int) -> None:
            progress = 0.05 + 0.9 * (processed / max(total, 1))
            update_task(
                db,
                task_id,
                status="running",
                progress=min(progress, 1.0),
                message=f"正在还原展示图 {processed}/{total}",
            )

        result = picture_service.import_gallery_from_zip(db, zip_bytes, workspace_id, progress_callback)
        if result["added_photos"] or result["updated_existing"] or result["persons_added"]:
            mark_similarity_scans_stale(db, workspace_id)
            db.commit()
        message = (
            f"导入完成：新增 {result['added_photos']} 张，"
            f"更新 {result['updated_existing']} 张已有图，"
            f"跳过 {result['skipped_photos']} 张，"
            f"绑定 {result['tags_added']} 个普通标签，"
            f"绑定 {result['persons_added']} 个人物标签"
        )
        update_task(db, task_id, status="completed", progress=1.0, message=message)
        logger.info("Gallery zip import task completed task_id=%s %s", task_id, message)
    except Exception as exc:
        logger.exception("Gallery zip import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        _mark_task_failed(session_factory, task_id, exc)
    finally:
        db.close()
        logger.debug("Gallery zip import task db session closed task_id=%s", task_id)


def process_gallery_similarity_scan_task(
    session_factory: SessionFactory,
    similarity_service: Any,
    scan_id: str,
    task_id: str,
) -> None:
    db = session_factory()
    try:
        scan = db.get(GallerySimilarityScan, scan_id)
        if scan is None:
            raise RuntimeError("相似图片扫描记录不存在")
        scan.status = "running"
        db.add(scan)
        db.commit()
        update_task(db, task_id, status="running", progress=0.02, message="正在准备相似图片扫描")

        def progress_callback(progress: float, message: str) -> None:
            update_task(db, task_id, status="running", progress=min(progress, 0.99), message=message)

        similarity_service.run_scan(db, scan, progress_callback)
        scan.status = "completed"
        scan.is_stale = False
        scan.completed_at = shanghai_now()
        db.add(scan)
        db.commit()
        update_task(
            db,
            task_id,
            status="completed",
            progress=1.0,
            message=f"扫描完成：比较 {scan.candidate_pair_count} 对图片，生成 {scan.group_count} 个相似组",
        )
    except Exception:
        logger.exception("Gallery similarity scan failed scan_id=%s task_id=%s", scan_id, task_id)
        db.rollback()
        user_message = "相似图片扫描失败，请稍后重新扫描；详细原因已记录。"
        scan = db.get(GallerySimilarityScan, scan_id)
        if scan is not None:
            scan.status = "failed"
            scan.error_message = user_message
            db.add(scan)
            db.commit()
        try:
            update_task(db, task_id, status="failed", message=user_message)
        except Exception:
            logger.exception("Failed to update gallery similarity task task_id=%s", task_id)
    finally:
        db.close()
