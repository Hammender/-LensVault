from __future__ import annotations

from app.models import Task

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timezones import shanghai_now
from app.models import GalleryPhoto, GallerySimilarityScan, Person, UploadHistory
from app.services.similarity import (
    mark_similarity_scans_stale,
    select_exact_mirror_auto_delete_photo_ids,
    select_normal_near_duplicate_auto_delete_photo_ids,
)
from app.services.import_spool import cleanup_import
from app.services.tasks import record_task_progress, update_task


def _upload_bytes(payload: bytes | Path) -> bytes:
    if isinstance(payload, Path):
        return payload.read_bytes()
    return payload


def _upload_sha256(payload: bytes | Path) -> str:
    digest = hashlib.sha256()
    if isinstance(payload, Path):
        with payload.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    digest.update(payload)
    return digest.hexdigest()

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
    metadata_by_index: list[dict[str, list[int] | list[str] | str | None]],
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

        requested_person_ids = {
            person_id
            for metadata in metadata_by_index
            for person_id in metadata.get("person_ids", [])
            if isinstance(person_id, int)
        }
        persons_by_id = {
            person.id: person
            for person in db.scalars(
                select(Person).where(
                    Person.id.in_(requested_person_ids),
                    Person.workspace_id == workspace_id,
                    Person.is_unknown.is_(False),
                )
            ).all()
        } if requested_person_ids else {}
        if set(persons_by_id) != requested_person_ids:
            raise ValueError("所选人物不存在，请先在样本库创建人物后再上传。")

        upload_hashes = [_upload_sha256(payload) for _, payload, _ in uploads]
        existing_hashes = set(
            db.scalars(
                select(GalleryPhoto.sha256).where(
                    GalleryPhoto.workspace_id == workspace_id,
                    GalleryPhoto.is_rich_text == rich_mode,
                    GalleryPhoto.sha256.in_(upload_hashes),
                )
            ).all()
        ) if upload_hashes else set()
        seen_hashes = set(existing_hashes)
        recognition_indexes: list[int] = []
        for index, sha256 in enumerate(upload_hashes):
            if sha256 in seen_hashes:
                continue
            seen_hashes.add(sha256)
            recognition_indexes.append(index)

        recognition_results: dict[int, object | None] = {}

        def prepare_recognition(index: int) -> tuple[int, object]:
            recognition_db = session_factory()
            try:
                return index, picture_service.prepare_gallery_recognition(
                    recognition_db,
                    _upload_bytes(uploads[index][1]),
                    workspace_id,
                )
            finally:
                recognition_db.close()

        configured_workers = max(1, min(int(picture_service.settings.gallery_recognition_workers), 8))
        worker_count = min(configured_workers, max(len(recognition_indexes), 1))
        if recognition_indexes:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="gallery-recognition") as executor:
                futures = {executor.submit(prepare_recognition, index): index for index in recognition_indexes}
                completed = 0
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        result_index, plan = future.result()
                        recognition_results[result_index] = plan
                    except Exception:
                        recognition_results[index] = None
                        logger.exception(
                            "Gallery recognition failed task_id=%s index=%d filename=%s",
                            task_id,
                            index + 1,
                            uploads[index][0],
                        )
                    completed += 1
                    record_task_progress(
                        session_factory,
                        task_id,
                        status="running",
                        progress=0.05 + 0.65 * (completed / len(recognition_indexes)),
                        message=f"已识别 {completed}/{len(recognition_indexes)} 张待导入图片",
                    )
        else:
            update_task(db, task_id, status="running", progress=0.7, message="图片均已存在，正在整理上传结果")

        for index, (filename, stored_payload, content_type) in enumerate(uploads, start=1):
            payload = _upload_bytes(stored_payload)
            metadata = metadata_by_index[index - 1] if index - 1 < len(metadata_by_index) else {"person_ids": [], "tag_names": []}
            logger.info(
                "Gallery import processing task_id=%s index=%d/%d filename=%s bytes=%d manual_persons=%d manual_tags=%d",
                task_id,
                index,
                total,
                filename,
                len(payload),
                len(metadata.get("person_ids", [])),
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
                recognition_plan=recognition_results.get(index - 1),
                actor_id=db.get(Task, task_id).created_by,
                actor_name=db.get(Task, task_id).actor_name,
            )
            for person_id in metadata.get("person_ids", []):
                if not isinstance(person_id, int):
                    continue
                person = persons_by_id[person_id]
                picture_service.ensure_gallery_person_tag(db, photo.id, person.id, "manual")
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
            if isinstance(stored_payload, Path):
                stored_payload.unlink(missing_ok=True)
            record_task_progress(
                session_factory,
                task_id,
                status="running",
                progress=0.7 + 0.3 * (index / total),
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
        settings = getattr(picture_service, "settings", None)
        if getattr(settings, "data_dir", None):
            cleanup_import(settings, task_id)
        logger.debug("Gallery import task db session closed task_id=%s", task_id)


def process_person_import_task(
    session_factory: SessionFactory,
    picture_service: Any,
    task_id: str,
    zip_source: bytes | Path,
    workspace_id: int,
) -> None:
    logger.info("Person import task started task_id=%s", task_id)
    db = session_factory()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在解析导入数据")

        def progress_callback(processed: int, total: int) -> None:
            progress = 0.05 + 0.9 * (processed / max(total, 1))
            record_task_progress(
                session_factory,
                task_id,
                status="running",
                progress=min(progress, 1.0),
                message=f"正在处理 {processed}/{total} 个样本",
            )

        result = picture_service.import_persons_from_zip(db, zip_source, workspace_id, progress_callback)
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
        settings = getattr(picture_service, "settings", None)
        if getattr(settings, "data_dir", None):
            cleanup_import(settings, task_id)
        logger.debug("Person import task db session closed task_id=%s", task_id)


def process_gallery_zip_import_task(
    session_factory: SessionFactory,
    picture_service: Any,
    task_id: str,
    zip_source: bytes | Path,
    workspace_id: int,
    *,
    person_tags: str = "all",
    unknown_tag_source: str = "import_unknown",
    recognize: bool = False,
) -> None:
    logger.info(
        "Gallery zip import task started task_id=%s person_tags=%s unknown_tag_source=%s recognize=%s",
        task_id,
        person_tags,
        unknown_tag_source,
        recognize,
    )
    db = session_factory()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在解析展示图 ZIP")

        def progress_callback(processed: int, total: int) -> None:
            progress = 0.05 + 0.9 * (processed / max(total, 1))
            action = "正在还原并识别展示图" if recognize else "正在还原展示图"
            record_task_progress(
                session_factory,
                task_id,
                status="running",
                progress=min(progress, 1.0),
                message=f"{action} {processed}/{total}",
            )

        task = db.get(Task, task_id)
        result = picture_service.import_gallery_from_zip(
            db,
            zip_source,
            workspace_id,
            progress_callback,
            actor_id=task.created_by,
            actor_name=task.actor_name,
            person_tags=person_tags,
            unknown_tag_source=unknown_tag_source,
            recognize=recognize,
        )
        if result["added_photos"] or result["updated_existing"] or result["persons_added"]:
            mark_similarity_scans_stale(db, workspace_id)
            db.commit()
        message = (
            f"导入完成：新增 {result['added_photos']} 张，"
            f"更新 {result['updated_existing']} 张已有图，"
            f"跳过 {result['skipped_photos']} 张，"
            f"绑定 {result['tags_added']} 个普通标签，"
            f"绑定 {result['persons_added']} 个人物标签"
            f"（{result.get('option_summary', '人物：全部导入；未知：受保护')}）"
        )
        if recognize:
            message += (
                f"；识别已知 {result.get('recognized_known', 0)} 张人脸，"
                f"未知 {result.get('recognized_unknown', 0)} 张"
            )
        update_task(db, task_id, status="completed", progress=1.0, message=message)
        db.add(
            UploadHistory(
                workspace_id=workspace_id,
                upload_type="gallery_zip",
                total_count=result["added_photos"] + result["updated_existing"] + result["skipped_photos"],
                success_count=result["added_photos"] + result["updated_existing"],
                duplicate_count=result["updated_existing"],
            )
        )
        db.commit()
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
        settings = getattr(picture_service, "settings", None)
        if getattr(settings, "data_dir", None):
            cleanup_import(settings, task_id)
        logger.debug("Gallery zip import task db session closed task_id=%s", task_id)


def process_gallery_similarity_scan_task(
    session_factory: SessionFactory,
    similarity_service: Any,
    picture_service: Any,
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
            record_task_progress(
                session_factory,
                task_id,
                status="running",
                progress=min(progress, 0.99),
                message=message,
            )

        similarity_service.run_scan(db, scan, progress_callback)
        auto_deleted = 0
        if scan.auto_delete_exact_mirror:
            if scan.scan_type == "normal":
                photo_ids = select_normal_near_duplicate_auto_delete_photo_ids(
                    db,
                    scan,
                    similarity_service.storage,
                    similarity_service.settings,
                )
            else:
                photo_ids = select_exact_mirror_auto_delete_photo_ids(db, scan)
            if photo_ids:
                photos = db.scalars(
                    select(GalleryPhoto).where(
                        GalleryPhoto.workspace_id == scan.workspace_id,
                        GalleryPhoto.id.in_(photo_ids),
                    )
                ).all()
                auto_deleted = picture_service.delete_gallery_photos(db, photos)
                db.refresh(scan)
                scan.auto_deleted_count += auto_deleted
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
            message=(
                f"扫描完成：比较 {scan.candidate_pair_count} 对图片，生成 {scan.group_count} 个相似组"
                + (f"，自动整理删除 {auto_deleted} 张图片" if scan.auto_delete_exact_mirror else "")
            ),
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
