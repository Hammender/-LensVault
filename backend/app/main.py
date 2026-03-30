from __future__ import annotations

from io import BytesIO

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import Face, Person, PersonEmbedding, Photo, PhotoTag, Task
from app.schemas import (
    AddPhotoTagRequest,
    AssignClusterRequest,
    ClusterGroup,
    ClusterItem,
    MergePersonsRequest,
    PaginatedPhotos,
    PersonCreate,
    PersonRead,
    PersonUpdate,
    PhotoDetail,
    PhotoListItem,
    PhotoTagRead,
    TaskRead,
)
from app.services.face import FaceService
from app.services.importer import ImportService, person_photo_count_subquery
from app.services.storage import MinioStorage
from app.services.tasks import create_task, update_task


settings = get_settings()
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
import_service = ImportService(storage, face_service)


@app.on_event("startup")
def on_startup() -> None:
    storage.ensure_bucket()


def _photo_to_list_item(photo: Photo) -> PhotoListItem:
    tags = [
        PhotoTagRead(person_id=tag.person_id, person_name=tag.person.name, source=tag.source)
        for tag in sorted(photo.tags, key=lambda item: item.person.name.lower())
    ]
    return PhotoListItem(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        tags=tags,
        thumbnail_url=f"/api/photos/{photo.id}/thumbnail",
        original_url=f"/api/photos/{photo.id}/original",
    )


def _process_import_task(task_id: str, uploads: list[tuple[str, bytes, str | None]]) -> None:
    db = SessionLocal()
    try:
        update_task(db, task_id, status="running", progress=0.05, message="Processing uploads")
        total = max(len(uploads), 1)
        for index, (filename, payload, content_type) in enumerate(uploads, start=1):
            import_service.import_photo(db, filename, payload, content_type)
            update_task(
                db,
                task_id,
                status="running",
                progress=index / total,
                message=f"Processed {index}/{total} images",
            )
        update_task(db, task_id, status="completed", progress=1.0, message="Import completed")
    except Exception as exc:
        update_task(db, task_id, status="failed", message=str(exc))
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/persons", response_model=PersonRead)
def create_person(payload: PersonCreate, db: Session = Depends(get_db)) -> PersonRead:
    person = Person(name=payload.name, note=payload.note)
    db.add(person)
    db.commit()
    db.refresh(person)
    return PersonRead.model_validate({**person.__dict__, "photo_count": 0})


@app.get("/api/persons", response_model=list[PersonRead])
def list_persons(db: Session = Depends(get_db)) -> list[PersonRead]:
    counts = person_photo_count_subquery()
    rows = db.execute(
        select(Person, func.coalesce(counts.c.photo_count, 0))
        .outerjoin(counts, counts.c.person_id == Person.id)
        .order_by(Person.name.asc())
    ).all()
    return [
        PersonRead.model_validate({**person.__dict__, "photo_count": photo_count})
        for person, photo_count in rows
    ]


@app.patch("/api/persons/{person_id}", response_model=PersonRead)
def update_person(person_id: int, payload: PersonUpdate, db: Session = Depends(get_db)) -> PersonRead:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if payload.name is not None:
        person.name = payload.name
    person.note = payload.note
    db.add(person)
    db.commit()
    db.refresh(person)
    count = db.scalar(select(func.count(PhotoTag.id)).where(PhotoTag.person_id == person.id)) or 0
    return PersonRead.model_validate({**person.__dict__, "photo_count": count})


@app.post("/api/persons/merge", response_model=PersonRead)
def merge_persons(payload: MergePersonsRequest, db: Session = Depends(get_db)) -> PersonRead:
    target = db.get(Person, payload.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target person not found")
    for source_id in payload.source_ids:
        if source_id == payload.target_id:
            continue
        for tag in db.scalars(select(PhotoTag).where(PhotoTag.person_id == source_id)).all():
            existing = db.scalar(select(PhotoTag).where(PhotoTag.photo_id == tag.photo_id, PhotoTag.person_id == target.id))
            if existing is None:
                db.add(PhotoTag(photo_id=tag.photo_id, person_id=target.id, source="merge"))
            db.delete(tag)
        for face in db.scalars(select(Face).where(Face.matched_person_id == source_id)).all():
            face.matched_person_id = target.id
        source = db.get(Person, source_id)
        if source is not None:
            db.delete(source)
    db.commit()
    db.refresh(target)
    count = db.scalar(select(func.count(PhotoTag.id)).where(PhotoTag.person_id == target.id)) or 0
    return PersonRead.model_validate({**target.__dict__, "photo_count": count})


@app.post("/api/persons/{person_id}/samples", response_model=PersonRead)
async def add_person_samples(person_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db)) -> PersonRead:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    import_service.add_person_samples(db, person, uploads)
    count = db.scalar(select(func.count(PhotoTag.id)).where(PhotoTag.person_id == person.id)) or 0
    db.refresh(person)
    return PersonRead.model_validate({**person.__dict__, "photo_count": count})


@app.post("/api/photos/import", response_model=TaskRead)
async def import_photos(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> TaskRead:
    uploads = [(file.filename, await file.read(), file.content_type) for file in files]
    task = create_task(db, "import", f"Queued {len(uploads)} uploads")
    background_tasks.add_task(_process_import_task, task.id, uploads)
    return TaskRead.model_validate(task)


@app.get("/api/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskRead:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)


@app.get("/api/tags", response_model=list[PersonRead])
def list_tags(db: Session = Depends(get_db)) -> list[PersonRead]:
    return list_persons(db)


@app.get("/api/photos", response_model=PaginatedPhotos)
def list_photos(
    person_ids: list[int] = Query(default=[]),
    offset: int = 0,
    limit: int = 40,
    db: Session = Depends(get_db),
) -> PaginatedPhotos:
    query = select(Photo).order_by(Photo.taken_at.desc().nullslast(), Photo.created_at.desc())
    count_query = select(func.count(Photo.id))

    if person_ids:
        tagged = (
            select(PhotoTag.photo_id)
            .where(PhotoTag.person_id.in_(person_ids))
            .group_by(PhotoTag.photo_id)
            .having(func.count(func.distinct(PhotoTag.person_id)) == len(person_ids))
            .subquery()
        )
        query = query.where(Photo.id.in_(select(tagged.c.photo_id)))
        count_query = count_query.where(Photo.id.in_(select(tagged.c.photo_id)))

    photos = db.scalars(query.offset(offset).limit(limit)).unique().all()
    for photo in photos:
        photo.tags
        for tag in photo.tags:
            tag.person
    total = db.scalar(count_query) or 0
    return PaginatedPhotos(items=[_photo_to_list_item(photo) for photo in photos], total=total, offset=offset, limit=limit)


@app.get("/api/photos/{photo_id}", response_model=PhotoDetail)
def get_photo(photo_id: int, db: Session = Depends(get_db)) -> PhotoDetail:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo.tags
    for tag in photo.tags:
        tag.person
    photo.faces
    item = _photo_to_list_item(photo)
    return PhotoDetail(
        **item.model_dump(),
        faces=[
            {
                "id": face.id,
                "bbox_left": face.bbox_left,
                "bbox_top": face.bbox_top,
                "bbox_right": face.bbox_right,
                "bbox_bottom": face.bbox_bottom,
                "matched_person_id": face.matched_person_id,
                "match_score": face.match_score,
                "needs_review": face.needs_review,
                "cluster_key": face.cluster_key,
            }
            for face in photo.faces
        ],
        object_key=photo.object_key,
        content_type=photo.content_type,
        created_at=photo.created_at,
    )


@app.get("/api/photos/{photo_id}/original")
def get_original(photo_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    payload = storage.get_bytes(photo.object_key)
    headers = {"Content-Disposition": f'inline; filename="{photo.filename}"'}
    return StreamingResponse(BytesIO(payload), media_type=photo.content_type or "application/octet-stream", headers=headers)


@app.get("/api/photos/{photo_id}/thumbnail")
def get_thumbnail(photo_id: int, width: int = 480, db: Session = Depends(get_db)) -> Response:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    payload = storage.get_bytes(photo.object_key)
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")


@app.get("/api/clusters", response_model=list[ClusterGroup])
def list_clusters(db: Session = Depends(get_db)) -> list[ClusterGroup]:
    rows = db.execute(
        select(Face.cluster_key, func.count(Face.id))
        .where(Face.cluster_key.is_not(None), Face.needs_review.is_(True))
        .group_by(Face.cluster_key)
        .order_by(func.count(Face.id).desc())
    ).all()
    groups: list[ClusterGroup] = []
    for cluster_key, count in rows:
        sample_face = db.scalar(select(Face).where(Face.cluster_key == cluster_key).order_by(Face.id.asc()))
        if sample_face is None or cluster_key is None:
            continue
        groups.append(
            ClusterGroup(
                cluster_key=cluster_key,
                count=count,
                sample=ClusterItem(
                    cluster_key=cluster_key,
                    face_ids=[sample_face.id],
                    photo_id=sample_face.photo_id,
                    thumbnail_url=f"/api/photos/{sample_face.photo_id}/thumbnail",
                ),
            )
        )
    return groups


@app.post("/api/clusters/{cluster_key}/assign", response_model=PersonRead)
def assign_cluster(cluster_key: str, payload: AssignClusterRequest, db: Session = Depends(get_db)) -> PersonRead:
    person = db.scalar(select(Person).where(Person.name == payload.person_name))
    if person is None:
        person = Person(name=payload.person_name, note=payload.note)
        db.add(person)
        db.commit()
        db.refresh(person)
    import_service.assign_cluster(db, cluster_key, person)
    count = db.scalar(select(func.count(PhotoTag.id)).where(PhotoTag.person_id == person.id)) or 0
    return PersonRead.model_validate({**person.__dict__, "photo_count": count})


@app.delete("/api/photos/{photo_id}/tags/{person_id}")
def remove_photo_tag(photo_id: int, person_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    tag = db.scalar(select(PhotoTag).where(PhotoTag.photo_id == photo_id, PhotoTag.person_id == person_id))
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
    return {"status": "ok"}


@app.post("/api/photos/{photo_id}/tags", response_model=PhotoDetail)
def add_photo_tag(photo_id: int, payload: AddPhotoTagRequest, db: Session = Depends(get_db)) -> PhotoDetail:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    person = db.get(Person, payload.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")

    existing = db.scalar(select(PhotoTag).where(PhotoTag.photo_id == photo_id, PhotoTag.person_id == payload.person_id))
    if existing is None:
        db.add(PhotoTag(photo_id=photo_id, person_id=payload.person_id, source="manual"))

    faces = db.scalars(select(Face).where(Face.photo_id == photo_id)).all()
    if len(faces) == 1:
        face = faces[0]
        face.matched_person_id = person.id
        face.match_score = 1.0
        face.needs_review = False
        face.cluster_key = None
        embedding_exists = db.scalar(
            select(PersonEmbedding).where(
                PersonEmbedding.person_id == person.id,
                PersonEmbedding.source_photo_id == photo_id,
            )
        )
        if embedding_exists is None:
            db.add(PersonEmbedding(person_id=person.id, vector=face.embedding, source_photo_id=photo_id))

    db.commit()
    return get_photo(photo_id, db)


@app.post("/api/photos/{photo_id}/reprocess", response_model=PhotoDetail)
def reprocess_photo(photo_id: int, db: Session = Depends(get_db)) -> PhotoDetail:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo = import_service.reprocess_photo(db, photo)
    return get_photo(photo.id, db)
