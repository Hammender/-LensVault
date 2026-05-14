from __future__ import annotations

import json
from io import BytesIO
import logging
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, SessionLocal, engine, ensure_legacy_columns, get_db
from app.models import (
    FaceRecord,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GalleryPhotoTag,
    Person,
    PersonTag,
    SamplePhoto,
    Tag,
    Task,
    UploadHistory,
    VideoCategoryTag,
    VideoItem,
    VideoItemCategoryTag,
    VideoItemPerson,
    VideoPerson,
    VideoUploadSession,
)
from app.schemas import (
    FaceRead,
    GalleryPersonTagRead,
    GalleryPhotoDetail,
    GalleryPhotoListItem,
    GalleryPhotoBatchDeleteRequest,
    GalleryPhotoRichTextUpdate,
    GalleryPhotoPersonTagCreate,
    GalleryPhotoTagCreate,
    GalleryTagRead,
    PaginatedGalleryPhotos,
    PersonBatchDeleteRequest,
    PersonCreate,
    PersonRead,
    PersonRenameRequest,
    PersonStatistics,
    PersonTagCreate,
    PersonUpdate,
    SamplePhotoRead,
    TagCreate,
    TagRead,
    TagStatistics,
    TagUpdate,
    TaskRead,
    UploadHistoryRead,
    PaginatedVideos,
    VideoCategoryTagCreate,
    VideoCategoryTagRead,
    VideoCategoryTagUpdate,
    VideoItemDetail,
    VideoItemListItem,
    VideoMetadataUpdate,
    VideoPersonBindCreate,
    VideoPersonRead,
    VideoPersonUpdate,
    VideoTagBindCreate,
    VideoUploadCompleteRequest,
    VideoUploadPartRead,
    VideoUploadSessionCreate,
    VideoUploadSessionRead,
)
from app.services.face import FaceService
from app.services.importer import PictureService
from app.services.milvus import MilvusVectorStore
from app.services.ocr import OcrService
from app.services.storage import MinioStorage
from app.services.tasks import create_task, fail_incomplete_tasks, update_task
from app.services.videos import VideoService

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
logger = logging.getLogger(__name__)
logging.getLogger("app").setLevel(logging.INFO)

settings = get_settings()
ensure_legacy_columns()
Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = MinioStorage(settings)
face_service = FaceService(settings)
vector_store = MilvusVectorStore(settings)
ocr_service = OcrService()
picture_service = PictureService(storage, face_service, vector_store, ocr_service, settings)
video_service = VideoService(storage)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Application startup begin")
    storage.ensure_bucket()
    vector_store.ensure_collections()
    face_service.warmup()
    ocr_status = ocr_service.engine_status()
    logger.info(
        "OCR engines status rapidocr_ready=%s tesseract_ready=%s rapidocr_error=%s tesseract_error=%s",
        ocr_status["rapidocr_ready"],
        ocr_status["tesseract_ready"],
        ocr_status["rapidocr_error"] or "-",
        ocr_status["tesseract_error"] or "-",
    )
    db = SessionLocal()
    try:
        picture_service.ensure_system_tags(db)
        recovered = fail_incomplete_tasks(db, "gallery_import")
        recovered += fail_incomplete_tasks(db, "gallery_rich_import")
        recovered += fail_incomplete_tasks(db, "gallery_zip_import")
        recovered += fail_incomplete_tasks(db, "person_import")
        if recovered > 0:
            logger.warning("Recovered interrupted gallery tasks count=%d", recovered)
    finally:
        db.close()
    logger.info(
        "Startup dependencies ready minio_bucket=%s milvus_known=%s milvus_unknown=%s",
        settings.minio_bucket,
        settings.milvus_known_collection,
        settings.milvus_unknown_collection,
    )


def _gallery_photo_to_list_item(photo: GalleryPhoto) -> GalleryPhotoListItem:
    persons = [
        GalleryPersonTagRead(
            person_id=tag.person_id,
            person_name=tag.person.display_name,
            is_unknown=tag.person.is_unknown,
            source=tag.source,
        )
        for tag in sorted(photo.person_tags, key=lambda item: (item.person.is_unknown, item.person.display_name.lower()))
    ]
    tags = [
        GalleryTagRead(id=item.tag.id, name=item.tag.name, is_system=item.tag.is_system)
        for item in sorted(photo.tags, key=lambda link: link.tag.name.lower())
    ]
    return GalleryPhotoListItem(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        is_rich_text=photo.is_rich_text,
        rich_text=photo.rich_text,
        ocr_status=photo.ocr_status,
        persons=persons,
        tags=tags,
        thumbnail_url=f"/api/gallery/photos/{photo.id}/thumbnail",
        original_url=f"/api/gallery/photos/{photo.id}/original",
    )


def _gallery_photo_to_detail(photo: GalleryPhoto) -> GalleryPhotoDetail:
    item = _gallery_photo_to_list_item(photo)
    faces = [
        FaceRead(
            id=face.id,
            bbox_left=face.bbox_left,
            bbox_top=face.bbox_top,
            bbox_right=face.bbox_right,
            bbox_bottom=face.bbox_bottom,
            matched_person_id=face.matched_person_id,
            match_score=face.match_score,
            needs_review=face.needs_review,
            vector_collection=face.vector_collection,
        )
        for face in photo.faces
    ]
    return GalleryPhotoDetail(
        **item.model_dump(),
        faces=faces,
        created_at=photo.created_at,
        content_type=photo.content_type,
    )


def _video_person_to_read(person: VideoPerson) -> VideoPersonRead:
    return VideoPersonRead(
        id=person.id,
        name=person.name,
        note=person.note,
        avatar_url=f"/api/video-people/{person.id}/avatar" if person.avatar_object_key else None,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


def _video_category_to_read(tag: VideoCategoryTag) -> VideoCategoryTagRead:
    return VideoCategoryTagRead.model_validate(tag)


def _video_play_url(video: VideoItem) -> str:
    fallback_url = f"/api/videos/{video.id}/stream"
    if not settings.video_use_presigned_play_url:
        return fallback_url
    try:
        return storage.presigned_get_url(video.object_key, settings.video_presigned_url_expires_seconds)
    except Exception:
        logger.exception("Failed to create video presigned URL video_id=%s", video.id)
        return fallback_url


def _video_cover_url(video: VideoItem) -> str | None:
    if not video.cover_object_key:
        return None
    return f"/api/videos/{video.id}/cover"


def _video_to_list_item(video: VideoItem) -> VideoItemListItem:
    categories = sorted((link.tag for link in video.category_links), key=lambda item: item.name.lower())
    people = sorted((link.person for link in video.person_links), key=lambda item: item.name.lower())
    return VideoItemListItem(
        id=video.id,
        title=video.title,
        description=video.description,
        filename=video.filename,
        content_type=video.content_type,
        size_bytes=video.size_bytes,
        duration_seconds=video.duration_seconds,
        width=video.width,
        height=video.height,
        original_video_codec=video.original_video_codec,
        original_audio_codec=video.original_audio_codec,
        video_codec=video.video_codec,
        audio_codec=video.audio_codec,
        status=video.status,
        category_tags=[_video_category_to_read(tag) for tag in categories],
        people=[_video_person_to_read(person) for person in people],
        stream_url=f"/api/videos/{video.id}/stream",
        play_url=_video_play_url(video),
        cover_url=_video_cover_url(video),
        faststart_applied=video.faststart_applied,
        processed_at=video.processed_at,
        processing_error=video.processing_error,
        created_at=video.created_at,
        updated_at=video.updated_at,
    )


def _video_to_detail(video: VideoItem) -> VideoItemDetail:
    item = _video_to_list_item(video)
    return VideoItemDetail(**item.model_dump(), sha256=video.sha256)


def _video_session_to_read(session: VideoUploadSession) -> VideoUploadSessionRead:
    uploaded_parts = sorted(part.part_index for part in session.parts)
    return VideoUploadSessionRead(
        id=session.id,
        filename=session.filename,
        title=session.title,
        description=session.description,
        content_type=session.content_type,
        size_bytes=session.size_bytes,
        part_size=session.part_size,
        total_parts=session.total_parts,
        uploaded_parts=uploaded_parts,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _parse_range_header(range_header: str | None, size: int) -> tuple[int, int] | None:
    if not range_header:
        return None
    unit, _, range_value = range_header.partition("=")
    if unit.strip().lower() != "bytes" or "," in range_value:
        raise HTTPException(status_code=416, detail="Invalid range", headers={"Content-Range": f"bytes */{size}"})
    start_text, _, end_text = range_value.partition("-")
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid range", headers={"Content-Range": f"bytes */{size}"}) from exc
    if start < 0 or end < start or start >= size:
        raise HTTPException(status_code=416, detail="Invalid range", headers={"Content-Range": f"bytes */{size}"})
    return start, min(end, size - 1)


def _iter_minio_response(response, chunk_size: int = 1024 * 1024):
    try:
        for chunk in response.stream(chunk_size):
            yield chunk
    finally:
        response.close()
        response.release_conn()


def _sample_photo_to_read(photo: SamplePhoto) -> SamplePhotoRead:
    return SamplePhotoRead(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        status=photo.status,
        error_message=photo.error_message,
        thumbnail_url=f"/api/persons/{photo.person_id}/samples/{photo.id}/thumbnail",
        original_url=f"/api/persons/{photo.person_id}/samples/{photo.id}/original",
        created_at=photo.created_at,
    )


def _person_to_read(db: Session, person: Person) -> PersonRead:
    sample_count = db.scalar(select(func.count(SamplePhoto.id)).where(SamplePhoto.person_id == person.id)) or 0
    gallery_count = (
        db.scalar(
            select(func.count(func.distinct(GalleryPhotoPersonTag.gallery_photo_id))).where(
                GalleryPhotoPersonTag.person_id == person.id
            )
        )
        or 0
    )
    return PersonRead(
        id=person.id,
        name=person.name,
        display_name=person.display_name,
        note=person.note,
        is_unknown=person.is_unknown,
        unknown_serial=person.unknown_serial,
        sample_count=sample_count,
        gallery_photo_count=gallery_count,
        created_at=person.created_at,
    )


def _parse_tag_names(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    names: list[str] = []
    for value in raw:
        for piece in value.split(","):
            normalized = piece.strip()
            if normalized:
                names.append(normalized)
    return list(dict.fromkeys(names))


def _parse_gallery_metadata(raw: str | None, file_count: int) -> list[dict[str, list[str] | str | None]]:
    defaults: list[dict[str, list[str] | str | None]] = [
        {"person_names": [], "tag_names": [], "rich_text": None} for _ in range(file_count)
    ]
    if not raw:
        return defaults
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    if not isinstance(payload, list):
        return defaults
    for index, item in enumerate(payload[:file_count]):
        if not isinstance(item, dict):
            continue
        person_names = item.get("person_names")
        tag_names = item.get("tag_names")
        if isinstance(person_names, list):
            defaults[index]["person_names"] = [str(name).strip() for name in person_names if str(name).strip()]
        if isinstance(tag_names, list):
            defaults[index]["tag_names"] = [str(name).strip() for name in tag_names if str(name).strip()]
        rich_text = item.get("rich_text")
        if rich_text is not None:
            defaults[index]["rich_text"] = str(rich_text).strip() or None
    return defaults


def _safe_zip_name(value: str | None, fallback: str) -> str:
    normalized = (value or "").strip()
    for char in '<>:"/\\|?*\0':
        normalized = normalized.replace(char, "_")
    normalized = normalized.strip(" .")
    return normalized or fallback


def _unique_zip_path(path: str, used_paths: set[str]) -> str:
    if path not in used_paths:
        used_paths.add(path)
        return path
    stem, dot, suffix = path.rpartition(".")
    base = stem if dot else path
    extension = f".{suffix}" if dot else ""
    counter = 2
    while True:
        candidate = f"{base}_{counter}{extension}"
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        counter += 1


def _apply_gallery_filters(query, person_ids: list[int], tag_ids: list[int], exclude_person_ids: list[int], exclude_tag_ids: list[int]):
    if person_ids:
        matched_persons = (
            select(GalleryPhotoPersonTag.gallery_photo_id)
            .where(GalleryPhotoPersonTag.person_id.in_(person_ids))
            .group_by(GalleryPhotoPersonTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.in_(select(matched_persons.c.gallery_photo_id)))

    if tag_ids:
        matched_tags = (
            select(GalleryPhotoTag.gallery_photo_id)
            .where(GalleryPhotoTag.tag_id.in_(tag_ids))
            .group_by(GalleryPhotoTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.in_(select(matched_tags.c.gallery_photo_id)))

    if exclude_person_ids:
        excluded_persons = (
            select(GalleryPhotoPersonTag.gallery_photo_id)
            .where(GalleryPhotoPersonTag.person_id.in_(exclude_person_ids))
            .group_by(GalleryPhotoPersonTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.notin_(select(excluded_persons.c.gallery_photo_id)))

    if exclude_tag_ids:
        excluded_tags = (
            select(GalleryPhotoTag.gallery_photo_id)
            .where(GalleryPhotoTag.tag_id.in_(exclude_tag_ids))
            .group_by(GalleryPhotoTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.notin_(select(excluded_tags.c.gallery_photo_id)))

    return query


def _process_gallery_import_task(
    task_id: str,
    uploads: list[tuple[str, bytes, str | None]],
    metadata_by_index: list[dict[str, list[str] | str | None]],
    rich_mode: bool,
) -> None:
    logger.info("Gallery import task started task_id=%s files=%d rich_mode=%s", task_id, len(uploads), rich_mode)
    db = SessionLocal()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="正在识别上传图片")
        total = max(len(uploads), 1)
        total_known = 0
        total_unknown_created = 0
        total_unknown_reused = 0
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
                metadata.get("tag_names", []),  # type: ignore[arg-type]
                rich_mode,
                metadata.get("rich_text"),  # type: ignore[arg-type]
            )
            for raw_name in metadata.get("person_names", []):  # type: ignore[assignment]
                person_name = raw_name.strip()
                if not person_name:
                    continue
                person = db.scalar(select(Person).where(Person.name == person_name))
                if person is None:
                    person = Person(name=person_name, display_name=person_name, note=None, is_unknown=False)
                    db.add(person)
                    db.flush()
                    logger.info(
                        "Created person from gallery upload task_id=%s photo_id=%s person_id=%s name=%s",
                        task_id,
                        photo.id,
                        person.id,
                        person_name,
                    )
                picture_service._ensure_gallery_person_tag(db, photo.id, person.id, "manual_upload")
                picture_service._apply_person_tags_to_gallery_photo(db, photo.id, person.id)
            db.commit()
            total_known += summary.known_matches
            total_unknown_created += summary.unknown_created
            total_unknown_reused += summary.unknown_reused
            total_duplicated += summary.duplicated
            logger.info(
                "Gallery import progress task_id=%s index=%d/%d photo_id=%s known=%d unknown_created=%d unknown_reused=%d duplicated=%d",
                task_id,
                index,
                total,
                photo.id,
                total_known,
                total_unknown_created,
                total_unknown_reused,
                total_duplicated,
            )
            update_task(
                db,
                task_id,
                status="running",
                progress=index / total,
                message=(
                    f"已处理 {index}/{total} 张，识别 {total_known} 个已知人物，"
                    f"新增 {total_unknown_created} 个未知人物，重复跳过 {total_duplicated} 张"
                ),
            )
        final_message = (
            f"导入完成：识别 {total_known} 个已知人物，新增 {total_unknown_created} 个未知人物，"
            f"复用 {total_unknown_reused} 个未知人物，重复跳过 {total_duplicated} 张"
        )
        update_task(db, task_id, status="completed", progress=1.0, message=final_message)
        # 记录上传历史
        try:
            history = UploadHistory(
                upload_type="rich" if rich_mode else "gallery",
                total_count=total,
                success_count=total - total_duplicated,
                duplicate_count=total_duplicated,
            )
            db.add(history)
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
            "Gallery import task completed task_id=%s known=%d unknown_created=%d unknown_reused=%d duplicated=%d",
            task_id,
            total_known,
            total_unknown_created,
            total_unknown_reused,
            total_duplicated,
        )
    except Exception as exc:
        logger.exception("Gallery import task failed task_id=%s", task_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Failed to rollback task session task_id=%s", task_id)
        try:
            failed_db = SessionLocal()
            try:
                update_task(failed_db, task_id, status="failed", message=str(exc))
            finally:
                failed_db.close()
        except Exception:
            logger.exception("Failed to persist task failed status task_id=%s", task_id)
    finally:
        db.close()
        logger.debug("Gallery import task db session closed task_id=%s", task_id)


def _process_person_import_task(task_id: str, zip_bytes: bytes) -> None:
    logger.info("Person import task started task_id=%s bytes=%d", task_id, len(zip_bytes))
    db = SessionLocal()
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

        result = picture_service.import_persons_from_zip(db, zip_bytes, progress_callback)

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
        try:
            failed_db = SessionLocal()
            try:
                update_task(failed_db, task_id, status="failed", message=str(exc))
            finally:
                failed_db.close()
        except Exception:
            logger.exception("Failed to persist task failed status task_id=%s", task_id)
    finally:
        db.close()
        logger.debug("Person import task db session closed task_id=%s", task_id)


def _process_gallery_zip_import_task(task_id: str, zip_bytes: bytes) -> None:
    logger.info("Gallery zip import task started task_id=%s bytes=%d", task_id, len(zip_bytes))
    db = SessionLocal()
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

        result = picture_service.import_gallery_from_zip(db, zip_bytes, progress_callback)
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
        try:
            failed_db = SessionLocal()
            try:
                update_task(failed_db, task_id, status="failed", message=str(exc))
            finally:
                failed_db.close()
        except Exception:
            logger.exception("Failed to persist task failed status task_id=%s", task_id)
    finally:
        db.close()
        logger.debug("Gallery zip import task db session closed task_id=%s", task_id)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/persons", response_model=list[PersonRead])
def list_persons(is_unknown: bool | None = None, db: Session = Depends(get_db)) -> list[PersonRead]:
    query = select(Person).order_by(Person.is_unknown.asc(), Person.display_name.asc())
    if is_unknown is not None:
        query = query.where(Person.is_unknown.is_(is_unknown))
    persons = db.scalars(query).all()
    return [_person_to_read(db, person) for person in persons]


@app.post("/api/persons", response_model=PersonRead)
def create_person(payload: PersonCreate, db: Session = Depends(get_db)) -> PersonRead:
    normalized = payload.name.strip()
    if db.scalar(select(Person).where(Person.name == normalized)) is not None:
        raise HTTPException(status_code=409, detail="Person already exists")
    person = Person(name=normalized, display_name=normalized, note=payload.note, is_unknown=False)
    db.add(person)
    db.commit()
    db.refresh(person)
    return _person_to_read(db, person)


@app.post("/api/persons/batch-delete")
def batch_delete_persons(payload: PersonBatchDeleteRequest, db: Session = Depends(get_db)) -> dict[str, int]:
    persons = db.scalars(select(Person).where(Person.id.in_(payload.person_ids))).all()
    if not persons:
        return {"deleted": 0}
    deleted = picture_service.delete_persons(db, persons)
    return {"deleted": deleted}


@app.get("/api/persons/export")
def export_persons(db: Session = Depends(get_db)) -> StreamingResponse:
    from datetime import datetime as dt
    from zipfile import ZIP_DEFLATED, ZipFile

    persons = db.scalars(
        select(Person).where(Person.is_unknown == False).order_by(Person.display_name)
    ).all()

    export_persons: list[dict] = []
    buf = BytesIO()

    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for person in persons:
            samples = db.scalars(
                select(SamplePhoto).where(SamplePhoto.person_id == person.id).order_by(SamplePhoto.filename)
            ).all()
            tag_links = db.scalars(select(PersonTag).where(PersonTag.person_id == person.id)).all()
            tag_names: list[str] = []
            for tag_link in tag_links:
                tag_link.tag
                tag_names.append(tag_link.tag.name)

            export_samples: list[dict] = []
            for sample in samples:
                image_bytes = storage.get_bytes(sample.object_key)
                zip_path = f"samples/{person.name}/{sample.filename}"
                zf.writestr(zip_path, image_bytes)
                export_samples.append({
                    "filename": sample.filename,
                    "sha256": sample.sha256,
                    "content_type": sample.content_type,
                    "object_key": sample.object_key,
                    "width": sample.width,
                    "height": sample.height,
                    "taken_at": sample.taken_at.isoformat() if sample.taken_at else None,
                })

            export_persons.append({
                "name": person.name,
                "display_name": person.display_name,
                "note": person.note,
                "is_unknown": person.is_unknown,
                "tags": sorted(set(tag_names)),
                "samples": export_samples,
            })

        manifest = {
            "version": 1,
            "exported_at": dt.utcnow().isoformat(),
            "persons": export_persons,
        }
        zf.writestr("metadata.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="person_samples_{timestamp}.zip"'},
    )


@app.post("/api/persons/import", response_model=TaskRead)
async def import_persons(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TaskRead:
    zip_bytes = await file.read()
    task = create_task(db, "person_import", "已排队样本库导入")
    logger.info("Person import enqueued task_id=%s bytes=%d", task.id, len(zip_bytes))
    background_tasks.add_task(_process_person_import_task, task.id, zip_bytes)
    return TaskRead.model_validate(task)


@app.get("/api/persons/{person_id}", response_model=PersonRead)
def get_person(person_id: int, db: Session = Depends(get_db)) -> PersonRead:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return _person_to_read(db, person)


@app.patch("/api/persons/{person_id}", response_model=PersonRead)
def update_person(person_id: int, payload: PersonUpdate, db: Session = Depends(get_db)) -> PersonRead:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if payload.name is not None:
        normalized = payload.name.strip()
        duplicate = db.scalar(select(Person).where(Person.name == normalized, Person.id != person_id))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Person already exists")
        person.name = normalized
        person.display_name = normalized
        person.is_unknown = False
    if payload.note is not None:
        person.note = payload.note
    db.add(person)
    db.commit()
    db.refresh(person)
    return _person_to_read(db, person)


@app.post("/api/persons/{person_id}/rename", response_model=PersonRead)
def rename_person(person_id: int, payload: PersonRenameRequest, db: Session = Depends(get_db)) -> PersonRead:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    try:
        person = picture_service.rename_person(db, person, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _person_to_read(db, person)


@app.delete("/api/persons/{person_id}")
def delete_person(person_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    picture_service.delete_persons(db, [person])
    return {"status": "ok"}


@app.get("/api/persons/{person_id}/samples", response_model=list[SamplePhotoRead])
def list_person_samples(person_id: int, db: Session = Depends(get_db)) -> list[SamplePhotoRead]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    photos = db.scalars(select(SamplePhoto).where(SamplePhoto.person_id == person_id).order_by(SamplePhoto.created_at.desc())).all()
    return [_sample_photo_to_read(photo) for photo in photos]


@app.get("/api/persons/{person_id}/tags", response_model=list[TagRead])
def list_person_tags(person_id: int, db: Session = Depends(get_db)) -> list[TagRead]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return [TagRead.model_validate(tag) for tag in picture_service.list_person_tags(db, person_id)]


@app.post("/api/persons/{person_id}/tags", response_model=list[TagRead])
def bind_person_tag(person_id: int, payload: PersonTagCreate, db: Session = Depends(get_db)) -> list[TagRead]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if payload.tag_id is not None:
        tag = db.get(Tag, payload.tag_id)
        if tag is None:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = picture_service._find_or_create_tag(db, payload.name or "")
    picture_service.bind_person_tag(db, person, tag)
    return [TagRead.model_validate(item) for item in picture_service.list_person_tags(db, person_id)]


@app.delete("/api/persons/{person_id}/tags/{tag_id}", response_model=list[TagRead])
def unbind_person_tag(person_id: int, tag_id: int, db: Session = Depends(get_db)) -> list[TagRead]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    picture_service.unbind_person_tag(db, person, tag_id)
    return [TagRead.model_validate(item) for item in picture_service.list_person_tags(db, person_id)]


@app.post("/api/persons/{person_id}/samples", response_model=list[SamplePhotoRead])
async def add_person_samples(
    person_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> list[SamplePhotoRead]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    samples = picture_service.add_person_samples(db, person, uploads)
    return [_sample_photo_to_read(sample) for sample in samples]


@app.delete("/api/persons/{person_id}/samples/{sample_photo_id}")
def delete_person_sample(person_id: int, sample_photo_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    picture_service.delete_sample_photo(db, photo)
    return {"status": "ok"}


@app.get("/api/persons/{person_id}/samples/{sample_photo_id}/original")
def get_sample_original(person_id: int, sample_photo_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    payload = storage.get_bytes(photo.object_key)
    headers = {"Content-Disposition": f'inline; filename="{photo.filename}"'}
    return StreamingResponse(BytesIO(payload), media_type=photo.content_type or "application/octet-stream", headers=headers)


@app.get("/api/persons/{person_id}/samples/{sample_photo_id}/thumbnail")
def get_sample_thumbnail(person_id: int, sample_photo_id: int, width: int = 480, db: Session = Depends(get_db)) -> Response:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    payload = storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@app.get("/api/tags", response_model=list[TagRead])
def list_tags(db: Session = Depends(get_db)) -> list[TagRead]:
    tags = db.scalars(select(Tag).order_by(Tag.name.asc())).all()
    return [TagRead.model_validate(tag) for tag in tags]


@app.post("/api/tags", response_model=TagRead)
def create_tag(payload: TagCreate, db: Session = Depends(get_db)) -> TagRead:
    normalized = payload.name.strip()
    existing = db.scalar(select(Tag).where(Tag.name == normalized))
    if existing is not None:
        return TagRead.model_validate(existing)
    tag = Tag(name=normalized)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)


@app.patch("/api/tags/{tag_id}", response_model=TagRead)
def update_tag(tag_id: int, payload: TagUpdate, db: Session = Depends(get_db)) -> TagRead:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    normalized = payload.name.strip()
    duplicate = db.scalar(select(Tag).where(Tag.name == normalized, Tag.id != tag_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")
    tag.name = normalized
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.is_system:
        raise HTTPException(status_code=400, detail="System tag cannot be deleted")
    db.delete(tag)
    db.commit()
    return {"status": "ok"}


@app.post("/api/gallery/photos/import", response_model=TaskRead)
async def import_gallery_photos(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    metadata = _parse_gallery_metadata(metadata_json, len(uploads))
    task = create_task(db, "gallery_import", f"已排队 {len(uploads)} 张普通图片")
    logger.info(
        "Gallery import enqueued task_id=%s files=%d metadata_items=%d rich_mode=false",
        task.id,
        len(uploads),
        len(metadata),
    )
    background_tasks.add_task(_process_gallery_import_task, task.id, uploads, metadata, False)
    return TaskRead.model_validate(task)


@app.post("/api/gallery/rich-photos/import", response_model=TaskRead)
async def import_gallery_rich_photos(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    metadata = _parse_gallery_metadata(metadata_json, len(uploads))
    task = create_task(db, "gallery_rich_import", f"已排队 {len(uploads)} 张图文图片")
    logger.info(
        "Gallery rich import enqueued task_id=%s files=%d metadata_items=%d rich_mode=true",
        task.id,
        len(uploads),
        len(metadata),
    )
    background_tasks.add_task(_process_gallery_import_task, task.id, uploads, metadata, True)
    return TaskRead.model_validate(task)


@app.get("/api/gallery/photos/export")
def export_gallery_photos(
    scope: str = Query(default="all", pattern="^(all|filtered)$"),
    person_ids: list[int] = Query(default=[]),
    tag_ids: list[int] = Query(default=[]),
    exclude_person_ids: list[int] = Query(default=[]),
    exclude_tag_ids: list[int] = Query(default=[]),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    from datetime import datetime as dt
    from zipfile import ZIP_DEFLATED, ZipFile

    base_query = select(GalleryPhoto).order_by(GalleryPhoto.taken_at.desc().nullslast(), GalleryPhoto.created_at.desc())
    if scope == "filtered":
        query = _apply_gallery_filters(base_query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids)
    else:
        query = base_query

    photos = db.scalars(query).unique().all()
    for photo in photos:
        photo.person_tags
        photo.tags
        for person_tag in photo.person_tags:
            person_tag.person
        for tag_link in photo.tags:
            tag_link.tag

    manifest_photos: list[dict] = []
    used_paths: set[str] = set()
    buf = BytesIO()

    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for photo in photos:
            image_bytes = storage.get_bytes(photo.object_key)
            normal_tags = sorted({link.tag.name for link in photo.tags if not link.tag.is_system})
            folder_names = normal_tags or ["_未分类"]
            filename = _safe_zip_name(f"{photo.id}_{photo.filename}", f"{photo.id}_photo")
            zip_paths: list[str] = []
            for tag_name in folder_names:
                folder = _safe_zip_name(tag_name, "_未分类")
                zip_path = _unique_zip_path(f"gallery/by_tag/{folder}/{filename}", used_paths)
                zf.writestr(zip_path, image_bytes)
                zip_paths.append(zip_path)

            manifest_photos.append(
                {
                    "id": photo.id,
                    "filename": photo.filename,
                    "sha256": photo.sha256,
                    "content_type": photo.content_type,
                    "width": photo.width,
                    "height": photo.height,
                    "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
                    "is_rich_text": photo.is_rich_text,
                    "rich_text": photo.rich_text,
                    "ocr_status": photo.ocr_status,
                    "tags": normal_tags,
                    "persons": [
                        {
                            "name": person_tag.person.name,
                            "display_name": person_tag.person.display_name,
                            "is_unknown": person_tag.person.is_unknown,
                            "source": person_tag.source,
                        }
                        for person_tag in sorted(
                            photo.person_tags,
                            key=lambda item: (item.person.is_unknown, item.person.display_name.lower()),
                        )
                    ],
                    "paths": zip_paths,
                }
            )

        manifest = {
            "version": 1,
            "kind": "gallery_export",
            "scope": scope,
            "exported_at": dt.utcnow().isoformat(),
            "photos": manifest_photos,
        }
        zf.writestr("metadata.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="gallery_export_{timestamp}.zip"'},
    )


@app.post("/api/gallery/photos/import-zip", response_model=TaskRead)
async def import_gallery_export_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TaskRead:
    zip_bytes = await file.read()
    task = create_task(db, "gallery_zip_import", "已排队展示图 ZIP 导入")
    logger.info("Gallery zip import enqueued task_id=%s bytes=%d", task.id, len(zip_bytes))
    background_tasks.add_task(_process_gallery_zip_import_task, task.id, zip_bytes)
    return TaskRead.model_validate(task)


@app.get("/api/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskRead:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)


@app.get("/api/gallery/photos", response_model=PaginatedGalleryPhotos)
def list_gallery_photos(
    person_ids: list[int] = Query(default=[]),
    tag_ids: list[int] = Query(default=[]),
    exclude_person_ids: list[int] = Query(default=[]),
    exclude_tag_ids: list[int] = Query(default=[]),
    offset: int = 0,
    limit: int = 24,
    db: Session = Depends(get_db),
) -> PaginatedGalleryPhotos:
    query = select(GalleryPhoto).order_by(GalleryPhoto.taken_at.desc().nullslast(), GalleryPhoto.created_at.desc())
    count_query = select(func.count(GalleryPhoto.id))
    query = _apply_gallery_filters(query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids)
    count_query = _apply_gallery_filters(count_query, person_ids, tag_ids, exclude_person_ids, exclude_tag_ids)

    photos = db.scalars(query.offset(offset).limit(limit)).unique().all()
    for photo in photos:
        photo.person_tags
        photo.tags
        for person_tag in photo.person_tags:
            person_tag.person
        for tag_link in photo.tags:
            tag_link.tag
    total = db.scalar(count_query) or 0
    return PaginatedGalleryPhotos(items=[_gallery_photo_to_list_item(photo) for photo in photos], total=total, offset=offset, limit=limit)


@app.get("/api/gallery/photos/{photo_id}", response_model=GalleryPhotoDetail)
def get_gallery_photo(photo_id: int, db: Session = Depends(get_db)) -> GalleryPhotoDetail:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo.person_tags
    photo.tags
    photo.faces
    for tag in photo.person_tags:
        tag.person
    for tag_link in photo.tags:
        tag_link.tag
    return _gallery_photo_to_detail(photo)


@app.post("/api/gallery/photos/batch-delete")
def batch_delete_gallery_photos(payload: GalleryPhotoBatchDeleteRequest, db: Session = Depends(get_db)) -> dict[str, int]:
    photos = db.scalars(select(GalleryPhoto).where(GalleryPhoto.id.in_(payload.photo_ids))).all()
    if not photos:
        return {"deleted": 0}
    deleted = picture_service.delete_gallery_photos(db, photos)
    return {"deleted": deleted}


@app.delete("/api/gallery/photos/{photo_id}")
def delete_gallery_photo(photo_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    picture_service.delete_gallery_photos(db, [photo])
    return {"status": "ok"}


@app.get("/api/gallery/photos/{photo_id}/original")
def get_gallery_original(photo_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    payload = storage.get_bytes(photo.object_key)
    headers = {"Content-Disposition": f'inline; filename="{photo.filename}"'}
    return StreamingResponse(BytesIO(payload), media_type=photo.content_type or "application/octet-stream", headers=headers)


@app.get("/api/gallery/photos/{photo_id}/thumbnail")
def get_gallery_thumbnail(photo_id: int, width: int = 480, db: Session = Depends(get_db)) -> Response:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    payload = storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@app.post("/api/gallery/photos/{photo_id}/persons", response_model=GalleryPhotoDetail)
def add_gallery_photo_person(
    photo_id: int,
    payload: GalleryPhotoPersonTagCreate,
    db: Session = Depends(get_db),
) -> GalleryPhotoDetail:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    person = db.get(Person, payload.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    picture_service._ensure_gallery_person_tag(db, photo_id, person.id, "manual")
    picture_service._apply_person_tags_to_gallery_photo(db, photo_id, person.id)

    faces = db.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo_id)).all()
    if len(faces) == 1:
        face = faces[0]
        vector = None
        if face.vector_collection == "unknown":
            vector = vector_store.get_face_vector(settings.milvus_unknown_collection, face.id)
        elif face.vector_collection == "known":
            vector = vector_store.get_face_vector(settings.milvus_known_collection, face.id)
        picture_service.move_gallery_face_to_known(db, face, person, vector)

    db.commit()
    return get_gallery_photo(photo_id, db)


@app.delete("/api/gallery/photos/{photo_id}/persons/{person_id}", response_model=GalleryPhotoDetail)
def delete_gallery_photo_person(photo_id: int, person_id: int, db: Session = Depends(get_db)) -> GalleryPhotoDetail:
    link = db.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo_id,
            GalleryPhotoPersonTag.person_id == person_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Person tag not found")
    
    person_tags = db.scalars(select(PersonTag).where(PersonTag.person_id == person_id)).all()
    tag_ids = [pt.tag_id for pt in person_tags]
    
    db.delete(link)
    
    for tag_id in tag_ids:
        gallery_tag = db.scalar(
            select(GalleryPhotoTag).where(
                GalleryPhotoTag.gallery_photo_id == photo_id,
                GalleryPhotoTag.tag_id == tag_id,
            )
        )
        if gallery_tag is None or gallery_tag.source != "person":
            continue
        
        still_required = db.scalar(
            select(func.count(PersonTag.id))
            .join(Person, Person.id == PersonTag.person_id)
            .join(
                GalleryPhotoPersonTag,
                GalleryPhotoPersonTag.person_id == PersonTag.person_id,
            )
            .where(
                PersonTag.tag_id == tag_id,
                GalleryPhotoPersonTag.gallery_photo_id == photo_id,
                PersonTag.person_id != person_id,
            )
        ) or 0
        
        if still_required == 0:
            db.delete(gallery_tag)
    
    db.commit()
    return get_gallery_photo(photo_id, db)


@app.post("/api/gallery/photos/{photo_id}/tags", response_model=GalleryPhotoDetail)
def add_gallery_photo_tag(photo_id: int, payload: GalleryPhotoTagCreate, db: Session = Depends(get_db)) -> GalleryPhotoDetail:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    if payload.tag_id is not None:
        tag = db.get(Tag, payload.tag_id)
        if tag is None:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = picture_service._find_or_create_tag(db, payload.name or "")
    picture_service._ensure_gallery_tag(db, photo_id, tag, source="manual")
    db.commit()
    return get_gallery_photo(photo_id, db)


@app.delete("/api/gallery/photos/{photo_id}/tags/{tag_id}", response_model=GalleryPhotoDetail)
def delete_gallery_photo_tag(photo_id: int, tag_id: int, db: Session = Depends(get_db)) -> GalleryPhotoDetail:
    link = db.scalar(
        select(GalleryPhotoTag).where(
            GalleryPhotoTag.gallery_photo_id == photo_id,
            GalleryPhotoTag.tag_id == tag_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if link.tag.is_system:
        raise HTTPException(status_code=400, detail="System tag cannot be removed")
    db.delete(link)
    db.commit()
    return get_gallery_photo(photo_id, db)


@app.patch("/api/gallery/photos/{photo_id}/rich-text", response_model=GalleryPhotoDetail)
def update_gallery_photo_rich_text(photo_id: int, payload: GalleryPhotoRichTextUpdate, db: Session = Depends(get_db)) -> GalleryPhotoDetail:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    if not photo.is_rich_text:
        raise HTTPException(status_code=400, detail="Photo is not rich-text type")
    value = (payload.rich_text or "").strip()
    photo.rich_text = value or None
    photo.ocr_status = "manual" if value else "empty"
    db.add(photo)
    db.commit()
    return get_gallery_photo(photo_id, db)


@app.post("/api/gallery/photos/{photo_id}/re-recognize", response_model=GalleryPhotoDetail)
def re_recognize_gallery_photo(photo_id: int, db: Session = Depends(get_db)) -> GalleryPhotoDetail:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo = picture_service.re_recognize_gallery_photo(db, photo)
    return _gallery_photo_to_detail(photo)


@app.post("/api/gallery/photos/re-recognize-unknown")
def re_recognize_unknown_gallery_photos(db: Session = Depends(get_db)) -> dict[str, int]:
    return picture_service.re_recognize_unknown_gallery_photos(db)


@app.get("/api/video-category-tags", response_model=list[VideoCategoryTagRead])
def list_video_category_tags(db: Session = Depends(get_db)) -> list[VideoCategoryTagRead]:
    tags = db.scalars(select(VideoCategoryTag).order_by(VideoCategoryTag.name.asc())).all()
    return [_video_category_to_read(tag) for tag in tags]


@app.post("/api/video-category-tags", response_model=VideoCategoryTagRead)
def create_video_category_tag(payload: VideoCategoryTagCreate, db: Session = Depends(get_db)) -> VideoCategoryTagRead:
    try:
        tag = video_service.find_or_create_category_tag(db, payload.name)
        db.commit()
        db.refresh(tag)
        return _video_category_to_read(tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/video-category-tags/{tag_id}", response_model=VideoCategoryTagRead)
def update_video_category_tag(
    tag_id: int,
    payload: VideoCategoryTagUpdate,
    db: Session = Depends(get_db),
) -> VideoCategoryTagRead:
    tag = db.get(VideoCategoryTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Video category tag not found")
    normalized = payload.name.strip()
    duplicate = db.scalar(select(VideoCategoryTag).where(VideoCategoryTag.name == normalized, VideoCategoryTag.id != tag_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="Video category tag already exists")
    tag.name = normalized
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _video_category_to_read(tag)


@app.delete("/api/video-category-tags/{tag_id}")
def delete_video_category_tag(tag_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    tag = db.get(VideoCategoryTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Video category tag not found")
    db.delete(tag)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/video-people", response_model=list[VideoPersonRead])
def list_video_people(db: Session = Depends(get_db)) -> list[VideoPersonRead]:
    people = db.scalars(select(VideoPerson).order_by(VideoPerson.name.asc())).all()
    return [_video_person_to_read(person) for person in people]


@app.post("/api/video-people", response_model=VideoPersonRead)
async def create_video_person(
    name: str = Form(...),
    note: str | None = Form(default=None),
    avatar: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> VideoPersonRead:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Video person name is required")
    if db.scalar(select(VideoPerson).where(VideoPerson.name == normalized)):
        raise HTTPException(status_code=409, detail="Video person already exists")
    avatar_key = None
    avatar_type = None
    if avatar is not None and avatar.filename:
        try:
            avatar_key, avatar_type = video_service.save_person_avatar(await avatar.read(), avatar.filename, avatar.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    person = VideoPerson(name=normalized, note=note, avatar_object_key=avatar_key, avatar_content_type=avatar_type)
    db.add(person)
    db.commit()
    db.refresh(person)
    return _video_person_to_read(person)


@app.patch("/api/video-people/{person_id}", response_model=VideoPersonRead)
async def update_video_person(
    person_id: int,
    name: str | None = Form(default=None),
    note: str | None = Form(default=None),
    avatar: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> VideoPersonRead:
    person = db.get(VideoPerson, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Video person not found")
    if name is not None:
        normalized = name.strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="Video person name is required")
        duplicate = db.scalar(select(VideoPerson).where(VideoPerson.name == normalized, VideoPerson.id != person_id))
        if duplicate:
            raise HTTPException(status_code=409, detail="Video person already exists")
        person.name = normalized
    person.note = note
    old_avatar_key = None
    if avatar is not None and avatar.filename:
        try:
            avatar_key, avatar_type = video_service.save_person_avatar(await avatar.read(), avatar.filename, avatar.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        old_avatar_key = person.avatar_object_key
        person.avatar_object_key = avatar_key
        person.avatar_content_type = avatar_type
    db.add(person)
    db.commit()
    db.refresh(person)
    if old_avatar_key:
        storage.remove_object(old_avatar_key)
    return _video_person_to_read(person)


@app.delete("/api/video-people/{person_id}")
def delete_video_person(person_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    person = db.get(VideoPerson, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Video person not found")
    avatar_key = person.avatar_object_key
    db.delete(person)
    db.commit()
    if avatar_key:
        storage.remove_object(avatar_key)
    return {"status": "deleted"}


@app.get("/api/video-people/{person_id}/avatar")
def get_video_person_avatar(person_id: int, db: Session = Depends(get_db)) -> Response:
    person = db.get(VideoPerson, person_id)
    if person is None or not person.avatar_object_key:
        raise HTTPException(status_code=404, detail="Video person avatar not found")
    payload = storage.get_bytes(person.avatar_object_key)
    return Response(content=payload, media_type=person.avatar_content_type or "application/octet-stream")


@app.post("/api/videos/upload-sessions", response_model=VideoUploadSessionRead)
def create_video_upload_session(payload: VideoUploadSessionCreate, db: Session = Depends(get_db)) -> VideoUploadSessionRead:
    try:
        session = video_service.create_upload_session(db, payload)
        return _video_session_to_read(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/videos/upload-sessions/{session_id}", response_model=VideoUploadSessionRead)
def get_video_upload_session(session_id: str, db: Session = Depends(get_db)) -> VideoUploadSessionRead:
    session = db.get(VideoUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    return _video_session_to_read(session)


@app.put("/api/videos/upload-sessions/{session_id}/parts/{part_index}", response_model=VideoUploadPartRead)
async def upload_video_part(
    session_id: str,
    part_index: int,
    file: UploadFile = File(...),
    sha256: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> VideoUploadPartRead:
    session = db.get(VideoUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    try:
        part = video_service.put_upload_part(db, session, part_index, await file.read(), sha256)
        return VideoUploadPartRead(
            session_id=part.session_id,
            part_index=part.part_index,
            size_bytes=part.size_bytes,
            sha256=part.sha256,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/videos/upload-sessions/{session_id}/complete", response_model=VideoItemDetail)
def complete_video_upload(
    session_id: str,
    payload: VideoUploadCompleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> VideoItemDetail:
    session = db.get(VideoUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    try:
        video = video_service.complete_upload(db, session, payload)
        background_tasks.add_task(video_service.optimize_video_faststart, video.id)
        return _video_to_detail(video)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/videos/upload-sessions/{session_id}")
def cancel_video_upload(session_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    session = db.get(VideoUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Video upload session not found")
    video_service.cancel_upload(db, session)
    return {"status": "cancelled"}


@app.get("/api/videos", response_model=PaginatedVideos)
def list_videos(
    category_tag_ids: list[int] = Query(default=[]),
    person_ids: list[int] = Query(default=[]),
    query_text: str | None = Query(default=None, alias="query"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedVideos:
    query = select(VideoItem).order_by(VideoItem.created_at.desc())
    count_query = select(func.count(VideoItem.id))
    if query_text and query_text.strip():
        keyword = f"%{query_text.strip()}%"
        query = query.where((VideoItem.title.like(keyword)) | (VideoItem.description.like(keyword)) | (VideoItem.filename.like(keyword)))
        count_query = count_query.where(
            (VideoItem.title.like(keyword)) | (VideoItem.description.like(keyword)) | (VideoItem.filename.like(keyword))
        )
    if category_tag_ids:
        matched_categories = (
            select(VideoItemCategoryTag.video_id)
            .where(VideoItemCategoryTag.tag_id.in_(category_tag_ids))
            .group_by(VideoItemCategoryTag.video_id)
            .having(func.count(func.distinct(VideoItemCategoryTag.tag_id)) == len(set(category_tag_ids)))
            .subquery()
        )
        query = query.where(VideoItem.id.in_(select(matched_categories.c.video_id)))
        count_query = count_query.where(VideoItem.id.in_(select(matched_categories.c.video_id)))
    if person_ids:
        matched_people = (
            select(VideoItemPerson.video_id)
            .where(VideoItemPerson.person_id.in_(person_ids))
            .group_by(VideoItemPerson.video_id)
            .having(func.count(func.distinct(VideoItemPerson.person_id)) == len(set(person_ids)))
            .subquery()
        )
        query = query.where(VideoItem.id.in_(select(matched_people.c.video_id)))
        count_query = count_query.where(VideoItem.id.in_(select(matched_people.c.video_id)))
    total = db.scalar(count_query) or 0
    videos = db.scalars(query.offset(offset).limit(limit)).unique().all()
    return PaginatedVideos(items=[_video_to_list_item(video) for video in videos], total=total, offset=offset, limit=limit)


@app.get("/api/videos/{video_id}", response_model=VideoItemDetail)
def get_video(video_id: int, db: Session = Depends(get_db)) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return _video_to_detail(video)


@app.patch("/api/videos/{video_id}", response_model=VideoItemDetail)
def update_video(video_id: int, payload: VideoMetadataUpdate, db: Session = Depends(get_db)) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    if payload.title is not None:
        video.title = payload.title.strip()
    if payload.description is not None:
        video.description = payload.description
    db.add(video)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    video_service.delete_video(db, video)
    return {"status": "deleted"}


@app.get("/api/videos/{video_id}/cover")
def get_video_cover(video_id: int, db: Session = Depends(get_db)) -> Response:
    video = db.get(VideoItem, video_id)
    if video is None or not video.cover_object_key:
        raise HTTPException(status_code=404, detail="Video cover not found")
    payload = storage.get_bytes(video.cover_object_key)
    return Response(content=payload, media_type=video.cover_content_type or "image/jpeg")


@app.put("/api/videos/{video_id}/cover", response_model=VideoItemDetail)
async def replace_video_cover(
    video_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        updated = video_service.save_video_cover(db, video, await file.read(), file.filename or "cover.jpg", file.content_type)
        return _video_to_detail(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/videos/{video_id}/category-tags", response_model=VideoItemDetail)
def add_video_category_tag(video_id: int, payload: VideoTagBindCreate, db: Session = Depends(get_db)) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        tag = db.get(VideoCategoryTag, payload.tag_id) if payload.tag_id else video_service.find_or_create_category_tag(db, payload.name or "")
        if tag is None:
            raise HTTPException(status_code=404, detail="Video category tag not found")
        existing = db.scalar(select(VideoItemCategoryTag).where(VideoItemCategoryTag.video_id == video.id, VideoItemCategoryTag.tag_id == tag.id))
        if existing is None:
            db.add(VideoItemCategoryTag(video_id=video.id, tag_id=tag.id))
        db.commit()
        db.refresh(video)
        return _video_to_detail(video)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/videos/{video_id}/category-tags/{tag_id}", response_model=VideoItemDetail)
def remove_video_category_tag(video_id: int, tag_id: int, db: Session = Depends(get_db)) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    link = db.scalar(select(VideoItemCategoryTag).where(VideoItemCategoryTag.video_id == video_id, VideoItemCategoryTag.tag_id == tag_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Video category tag link not found")
    db.delete(link)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@app.post("/api/videos/{video_id}/people", response_model=VideoItemDetail)
def add_video_person(video_id: int, payload: VideoPersonBindCreate, db: Session = Depends(get_db)) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    person = db.get(VideoPerson, payload.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Video person not found")
    existing = db.scalar(select(VideoItemPerson).where(VideoItemPerson.video_id == video.id, VideoItemPerson.person_id == person.id))
    if existing is None:
        db.add(VideoItemPerson(video_id=video.id, person_id=person.id))
        db.commit()
        db.refresh(video)
    return _video_to_detail(video)


@app.delete("/api/videos/{video_id}/people/{person_id}", response_model=VideoItemDetail)
def remove_video_person(video_id: int, person_id: int, db: Session = Depends(get_db)) -> VideoItemDetail:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    link = db.scalar(select(VideoItemPerson).where(VideoItemPerson.video_id == video_id, VideoItemPerson.person_id == person_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Video person link not found")
    db.delete(link)
    db.commit()
    db.refresh(video)
    return _video_to_detail(video)


@app.get("/api/videos/{video_id}/stream")
def stream_video(video_id: int, request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    video = db.get(VideoItem, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    stat = storage.stat_object(video.object_key)
    size = stat.size
    range_tuple = _parse_range_header(request.headers.get("range"), size)
    filename = quote(video.filename)
    if range_tuple is None:
        response = storage.get_stream(video.object_key)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        }
        return StreamingResponse(_iter_minio_response(response), media_type=video.content_type or "video/mp4", headers=headers)
    start, end = range_tuple
    length = end - start + 1
    response = storage.get_stream(video.object_key, offset=start, length=length)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(length),
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
    }
    return StreamingResponse(
        _iter_minio_response(response),
        status_code=206,
        media_type=video.content_type or "video/mp4",
        headers=headers,
    )


@app.get("/api/statistics/tags", response_model=list[TagStatistics])
def get_tag_statistics(
    is_system: bool | None = Query(default=None, description="Filter by system tag status"),
    db: Session = Depends(get_db),
) -> list[TagStatistics]:
    """Get photo count statistics for each tag."""
    query = (
        select(
            Tag.id,
            Tag.name,
            Tag.is_system,
            func.count(GalleryPhotoTag.gallery_photo_id).label("photo_count"),
        )
        .outerjoin(GalleryPhotoTag, Tag.id == GalleryPhotoTag.tag_id)
        .group_by(Tag.id)
    )
    if is_system is not None:
        query = query.where(Tag.is_system == is_system)
    results = db.execute(query).all()
    return [
        TagStatistics(
            tag_id=row.id,
            tag_name=row.name,
            is_system=row.is_system,
            photo_count=row.photo_count,
        )
        for row in results
    ]


@app.get("/api/statistics/upload-history", response_model=list[UploadHistoryRead])
def get_upload_history(
    upload_type: str | None = Query(default=None, description="Filter by upload type: gallery or rich"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[UploadHistoryRead]:
    """Get upload history records."""
    query = select(UploadHistory).order_by(UploadHistory.created_at.desc())
    if upload_type:
        query = query.where(UploadHistory.upload_type == upload_type)
    query = query.offset(offset).limit(limit)
    results = db.scalars(query).all()
    return [UploadHistoryRead.model_validate(r) for r in results]


@app.get("/api/statistics/upload-summary")
def get_upload_summary(
    db: Session = Depends(get_db),
) -> dict:
    """Get summary statistics of uploads."""
    total_uploads = db.scalar(select(func.count(UploadHistory.id)))
    total_photos = db.scalar(select(func.sum(UploadHistory.total_count))) or 0
    total_success = db.scalar(select(func.sum(UploadHistory.success_count))) or 0
    total_duplicates = db.scalar(select(func.sum(UploadHistory.duplicate_count))) or 0
    
    by_type = {}
    for upload_type in ["gallery", "rich"]:
        count = db.scalar(
            select(func.count(UploadHistory.id)).where(UploadHistory.upload_type == upload_type)
        )
        photos = db.scalar(
            select(func.sum(UploadHistory.total_count)).where(UploadHistory.upload_type == upload_type)
        ) or 0
        by_type[upload_type] = {"count": count, "photos": photos}
    
    return {
        "total_uploads": total_uploads,
        "total_photos": total_photos,
        "total_success": total_success,
        "total_duplicates": total_duplicates,
        "by_type": by_type,
    }


@app.get("/api/statistics/persons", response_model=list[PersonStatistics])
def get_person_statistics(
    is_unknown: bool | None = Query(default=None, description="Filter by unknown person status"),
    db: Session = Depends(get_db),
) -> list[PersonStatistics]:
    """Get photo count statistics for each person."""
    # Create subqueries for counts to avoid cartesian product inflation
    photo_count_sq = (
        select(
            GalleryPhotoPersonTag.person_id,
            func.count(GalleryPhotoPersonTag.gallery_photo_id).label("count")
        )
        .group_by(GalleryPhotoPersonTag.person_id)
        .subquery()
    )
    
    sample_count_sq = (
        select(
            SamplePhoto.person_id,
            func.count(SamplePhoto.id).label("count")
        )
        .group_by(SamplePhoto.person_id)
        .subquery()
    )

    query = (
        select(
            Person.id,
            Person.name,
            Person.display_name,
            Person.is_unknown,
            func.coalesce(photo_count_sq.c.count, 0).label("photo_count"),
            func.coalesce(sample_count_sq.c.count, 0).label("sample_count"),
        )
        .outerjoin(photo_count_sq, Person.id == photo_count_sq.c.person_id)
        .outerjoin(sample_count_sq, Person.id == sample_count_sq.c.person_id)
    )
    
    if is_unknown is not None:
        query = query.where(Person.is_unknown == is_unknown)
    
    query = query.order_by(Person.is_unknown.asc(), func.coalesce(photo_count_sq.c.count, 0).desc())
    results = db.execute(query).all()
    
    return [
        PersonStatistics(
            person_id=row.id,
            person_name=row.name,
            display_name=row.display_name,
            is_unknown=row.is_unknown,
            photo_count=row.photo_count,
            sample_count=row.sample_count,
        )
        for row in results
    ]
