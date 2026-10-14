from __future__ import annotations

from datetime import datetime
from io import BytesIO
import json
import logging
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api._helpers import get_workspace_object
from app.core.timezones import shanghai_isoformat, shanghai_now
from app.background_tasks import process_person_import_task
from app.services.import_spool import spool_upload
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.http.media import stream_storage_object
from app.mappers.people import person_to_read, sample_photo_to_read
from app.models import Person, PersonTag, SamplePhoto, Tag
from app.schemas import (
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
from app.services.tasks import create_task

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/persons", response_model=list[PersonRead])
def list_persons(
    is_unknown: bool | None = None,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[PersonRead]:
    query = select(Person).where(Person.workspace_id == current.workspace_id).order_by(Person.is_unknown.asc(), Person.display_name.asc())
    if is_unknown is not None:
        query = query.where(Person.is_unknown.is_(is_unknown))
    return [person_to_read(db, person) for person in db.scalars(query).all()]


@router.post("/api/persons", response_model=PersonRead)
def create_person(
    payload: PersonCreate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PersonRead:
    normalized = payload.name.strip()
    if db.scalar(select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized)) is not None:
        raise HTTPException(status_code=409, detail="人物名称已存在")
    person = Person(workspace_id=current.workspace_id, name=normalized, display_name=normalized, note=payload.note, is_unknown=False)
    db.add(person)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized)) is not None:
            raise HTTPException(status_code=409, detail="人物名称已存在") from exc
        raise
    db.refresh(person)
    return person_to_read(db, person)


@router.post("/api/persons/batch-delete")
def batch_delete_persons(
    payload: PersonBatchDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, int]:
    persons = db.scalars(select(Person).where(Person.workspace_id == current.workspace_id, Person.id.in_(payload.person_ids))).all()
    if not persons:
        return {"deleted": 0}
    return {"deleted": request.app.state.services.pictures.delete_persons(db, persons)}


@router.get("/api/persons/export")
def export_persons(
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    persons = db.scalars(
        select(Person).where(Person.workspace_id == current.workspace_id, Person.is_unknown == False).order_by(Person.display_name)
    ).all()
    export_data: list[dict] = []
    storage = request.app.state.services.storage
    settings = getattr(request.app.state, "settings", None)
    data_dir = getattr(settings, "data_dir", None)
    temp_root = Path(data_dir) / "tmp" / "exports" if data_dir else Path(tempfile.gettempdir()) / "pictureshow-exports"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(prefix="person-export-", suffix=".zip", dir=temp_root)
    os.close(temp_fd)
    archive_path = Path(temp_name)

    def write_object(archive: ZipFile, zip_path: str, object_key: str) -> None:
        response = storage.get_stream(object_key)
        try:
            with archive.open(zip_path, "w") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
        finally:
            response.close()
            response.release_conn()

    try:
        with ZipFile(archive_path, "w", ZIP_DEFLATED, allowZip64=True) as archive:
            for person in persons:
                samples = db.scalars(select(SamplePhoto).where(SamplePhoto.person_id == person.id).order_by(SamplePhoto.filename)).all()
                tag_names = [tag_link.tag.name for tag_link in db.scalars(select(PersonTag).where(PersonTag.person_id == person.id)).all()]
                export_samples: list[dict] = []
                for sample in samples:
                    write_object(archive, f"samples/{person.name}/{sample.filename}", sample.object_key)
                    export_samples.append(
                        {
                            "filename": sample.filename,
                            "sha256": sample.sha256,
                            "content_type": sample.content_type,
                            "object_key": sample.object_key,
                            "width": sample.width,
                            "height": sample.height,
                            "taken_at": sample.taken_at.isoformat() if sample.taken_at else None,
                        }
                    )
                export_data.append(
                    {
                        "name": person.name,
                        "display_name": person.display_name,
                        "note": person.note,
                        "is_unknown": person.is_unknown,
                        "tags": sorted(set(tag_names)),
                        "samples": export_samples,
                    }
                )
            archive.writestr(
                "metadata.json",
                json.dumps({"version": 1, "exported_at": shanghai_isoformat(shanghai_now()), "persons": export_data}, ensure_ascii=False, indent=2),
            )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    def iterate_archive():
        try:
            with archive_path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    yield chunk
        finally:
            archive_path.unlink(missing_ok=True)

    timestamp = shanghai_now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iterate_archive(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="person_samples_{timestamp}.zip"'},
    )


@router.post("/api/persons/import", response_model=TaskRead)
async def import_persons(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TaskRead:
    task = create_task(db, "person_import", "已排队样本库导入", current.workspace_id)
    zip_path = await spool_upload(request.app.state.settings, task.id, 0, file)
    logger.info("Person import enqueued task_id=%s path=%s", task.id, zip_path.name)
    background_tasks.add_task(
        process_person_import_task,
        request.app.state.session_factory,
        request.app.state.services.pictures,
        task.id,
        zip_path,
        current.workspace_id,
    )
    return TaskRead.model_validate(task)


@router.get("/api/persons/{person_id}", response_model=PersonRead)
def get_person(person_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> PersonRead:
    return person_to_read(db, get_workspace_object(db, Person, person_id, current.workspace_id, "Person"))


@router.patch("/api/persons/{person_id}", response_model=PersonRead)
def update_person(
    person_id: int,
    payload: PersonUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PersonRead:
    picture_service = request.app.state.services.pictures
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    normalized_name: str | None = None
    if payload.name is not None:
        if picture_service.is_singleton_unknown_person(person):
            raise HTTPException(status_code=400, detail="系统未知人物不能直接改名")
        normalized_name = payload.name.strip()
        duplicate = db.scalar(select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized_name, Person.id != person_id))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="人物名称已存在")
        person.name = normalized_name
        person.display_name = normalized_name
        person.is_unknown = False
    if payload.note is not None:
        person.note = payload.note
    db.add(person)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if normalized_name is not None and db.scalar(
            select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized_name, Person.id != person_id)
        ) is not None:
            raise HTTPException(status_code=409, detail="人物名称已存在") from exc
        raise
    db.refresh(person)
    return person_to_read(db, person)


@router.post("/api/persons/{person_id}/rename", response_model=PersonRead)
def rename_person(
    person_id: int,
    payload: PersonRenameRequest,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> PersonRead:
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    try:
        person = request.app.state.services.pictures.rename_person(db, person, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409 if str(exc) == "人物名称已存在" else 400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        normalized = payload.name.strip()
        if db.scalar(select(Person).where(Person.workspace_id == current.workspace_id, Person.name == normalized, Person.id != person_id)) is not None:
            raise HTTPException(status_code=409, detail="人物名称已存在") from exc
        raise
    return person_to_read(db, person)


@router.delete("/api/persons/{person_id}")
def delete_person(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    picture_service = request.app.state.services.pictures
    if picture_service.is_singleton_unknown_person(person):
        raise HTTPException(status_code=400, detail="系统未知人物不能删除")
    picture_service.delete_persons(db, [person])
    return {"status": "ok"}


@router.get("/api/persons/{person_id}/samples", response_model=list[SamplePhotoRead])
def list_person_samples(person_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> list[SamplePhotoRead]:
    get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    photos = db.scalars(select(SamplePhoto).where(SamplePhoto.person_id == person_id).order_by(SamplePhoto.created_at.desc())).all()
    return [sample_photo_to_read(photo) for photo in photos]


@router.get("/api/persons/{person_id}/tags", response_model=list[TagRead])
def list_person_tags(person_id: int, request: Request, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> list[TagRead]:
    get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    return [TagRead.model_validate(tag) for tag in request.app.state.services.pictures.list_person_tags(db, person_id)]


@router.post("/api/persons/{person_id}/tags", response_model=list[TagRead])
def bind_person_tag(
    person_id: int,
    payload: PersonTagCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[TagRead]:
    picture_service = request.app.state.services.pictures
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    if picture_service.is_singleton_unknown_person(person):
        raise HTTPException(status_code=400, detail="系统未知人物不能维护普通标签")
    if payload.tag_id is not None:
        tag = db.get(Tag, payload.tag_id)
        if tag is None or tag.workspace_id != current.workspace_id:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = picture_service.find_or_create_tag(db, payload.name or "", current.workspace_id)
    try:
        picture_service.bind_person_tag(db, person, tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [TagRead.model_validate(item) for item in picture_service.list_person_tags(db, person_id)]


@router.delete("/api/persons/{person_id}/tags/{tag_id}", response_model=list[TagRead])
def unbind_person_tag(
    person_id: int,
    tag_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[TagRead]:
    picture_service = request.app.state.services.pictures
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    if picture_service.is_singleton_unknown_person(person):
        raise HTTPException(status_code=400, detail="系统未知人物不能维护普通标签")
    try:
        picture_service.unbind_person_tag(db, person, tag_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [TagRead.model_validate(item) for item in picture_service.list_person_tags(db, person_id)]


@router.post("/api/persons/{person_id}/samples", response_model=list[SamplePhotoRead])
async def add_person_samples(
    person_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[SamplePhotoRead]:
    person = get_workspace_object(db, Person, person_id, current.workspace_id, "Person")
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    try:
        samples = request.app.state.services.pictures.add_person_samples(db, person, uploads)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [sample_photo_to_read(sample) for sample in samples]


@router.delete("/api/persons/{person_id}/samples/{sample_photo_id}")
def delete_person_sample(
    person_id: int,
    sample_photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict[str, str]:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.workspace_id != current.workspace_id or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    request.app.state.services.pictures.delete_sample_photo(db, photo)
    return {"status": "ok"}


@router.get("/api/persons/{person_id}/samples/{sample_photo_id}/original")
def get_sample_original(
    person_id: int,
    sample_photo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> StreamingResponse:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.workspace_id != current.workspace_id or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    return stream_storage_object(request.app.state.services.storage, request, photo.object_key, photo.filename, photo.content_type)


@router.get("/api/persons/{person_id}/samples/{sample_photo_id}/thumbnail")
def get_sample_thumbnail(
    person_id: int,
    sample_photo_id: int,
    request: Request,
    width: int = 480,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> Response:
    photo = db.get(SamplePhoto, sample_photo_id)
    if photo is None or photo.workspace_id != current.workspace_id or photo.person_id != person_id:
        raise HTTPException(status_code=404, detail="Sample photo not found")
    payload = request.app.state.services.storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@router.get("/api/tags", response_model=list[TagRead])
def list_tags(db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> list[TagRead]:
    return [TagRead.model_validate(tag) for tag in db.scalars(select(Tag).where(Tag.workspace_id == current.workspace_id).order_by(Tag.name.asc())).all()]


@router.post("/api/tags", response_model=TagRead)
def create_tag(payload: TagCreate, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> TagRead:
    normalized = payload.name.strip()
    existing = db.scalar(select(Tag).where(Tag.workspace_id == current.workspace_id, Tag.name == normalized))
    if existing is not None:
        return TagRead.model_validate(existing)
    tag = Tag(workspace_id=current.workspace_id, name=normalized)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)


@router.patch("/api/tags/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> TagRead:
    tag = get_workspace_object(db, Tag, tag_id, current.workspace_id, "Tag")
    normalized = payload.name.strip()
    duplicate = db.scalar(select(Tag).where(Tag.workspace_id == current.workspace_id, Tag.name == normalized, Tag.id != tag_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")
    tag.name = normalized
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)


@router.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)) -> dict[str, str]:
    tag = get_workspace_object(db, Tag, tag_id, current.workspace_id, "Tag")
    if tag.is_system:
        raise HTTPException(status_code=400, detail="System tag cannot be deleted")
    db.delete(tag)
    db.commit()
    return {"status": "ok"}
