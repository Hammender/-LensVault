from __future__ import annotations

import json
from io import BytesIO
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, SessionLocal, engine, ensure_legacy_columns, get_db
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, SamplePhoto, Tag, Task
from app.schemas import (
    FaceRead,
    GalleryPersonTagRead,
    GalleryPhotoDetail,
    GalleryPhotoListItem,
    GalleryPhotoBatchDeleteRequest,
    GalleryPhotoPersonTagCreate,
    GalleryPhotoTagCreate,
    GalleryTagRead,
    PaginatedGalleryPhotos,
    PersonBatchDeleteRequest,
    PersonCreate,
    PersonRead,
    PersonRenameRequest,
    PersonTagCreate,
    PersonUpdate,
    SamplePhotoRead,
    TagCreate,
    TagRead,
    TagUpdate,
    TaskRead,
)
from app.services.face import FaceService
from app.services.importer import PictureService
from app.services.milvus import MilvusVectorStore
from app.services.storage import MinioStorage
from app.services.tasks import create_task, fail_incomplete_tasks, update_task

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
picture_service = PictureService(storage, face_service, vector_store, settings)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Application startup begin")
    storage.ensure_bucket()
    vector_store.ensure_collections()
    face_service.warmup()
    db = SessionLocal()
    try:
        recovered = fail_incomplete_tasks(db, "gallery_import")
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
    tags = [GalleryTagRead(id=item.tag.id, name=item.tag.name) for item in sorted(photo.tags, key=lambda link: link.tag.name.lower())]
    return GalleryPhotoListItem(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
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


def _parse_gallery_metadata(raw: str | None, file_count: int) -> list[dict[str, list[str]]]:
    defaults = [{"person_names": [], "tag_names": []} for _ in range(file_count)]
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
    return defaults


def _process_gallery_import_task(
    task_id: str,
    uploads: list[tuple[str, bytes, str | None]],
    metadata_by_index: list[dict[str, list[str]]],
) -> None:
    logger.info("Gallery import task started task_id=%s files=%d", task_id, len(uploads))
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
                metadata.get("tag_names", []),
            )
            for raw_name in metadata.get("person_names", []):
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
    task = create_task(db, "gallery_import", f"已排队 {len(uploads)} 张图片")
    logger.info(
        "Gallery import enqueued task_id=%s files=%d metadata_items=%d",
        task.id,
        len(uploads),
        len(metadata),
    )
    background_tasks.add_task(_process_gallery_import_task, task.id, uploads, metadata)
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
    offset: int = 0,
    limit: int = 24,
    db: Session = Depends(get_db),
) -> PaginatedGalleryPhotos:
    query = select(GalleryPhoto).order_by(GalleryPhoto.taken_at.desc().nullslast(), GalleryPhoto.created_at.desc())
    count_query = select(func.count(GalleryPhoto.id))

    if person_ids:
        matched_persons = (
            select(GalleryPhotoPersonTag.gallery_photo_id)
            .where(GalleryPhotoPersonTag.person_id.in_(person_ids))
            .group_by(GalleryPhotoPersonTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.in_(select(matched_persons.c.gallery_photo_id)))
        count_query = count_query.where(GalleryPhoto.id.in_(select(matched_persons.c.gallery_photo_id)))

    if tag_ids:
        matched_tags = (
            select(GalleryPhotoTag.gallery_photo_id)
            .where(GalleryPhotoTag.tag_id.in_(tag_ids))
            .group_by(GalleryPhotoTag.gallery_photo_id)
            .subquery()
        )
        query = query.where(GalleryPhoto.id.in_(select(matched_tags.c.gallery_photo_id)))
        count_query = count_query.where(GalleryPhoto.id.in_(select(matched_tags.c.gallery_photo_id)))

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
    db.delete(link)
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
    db.delete(link)
    db.commit()
    return get_gallery_photo(photo_id, db)
