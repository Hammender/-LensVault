from __future__ import annotations

import hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Face, Person, PersonEmbedding, Photo, PhotoTag
from app.services.face import FaceService, bytes_to_vector, vector_to_bytes
from app.services.storage import MinioStorage


def parse_image_metadata(payload: bytes) -> tuple[int, int, datetime | None]:
    image = Image.open(BytesIO(payload))
    width, height = image.size
    taken_at = None
    try:
        exif = ImageOps.exif_transpose(image).getexif()
        timestamp = exif.get(36867) or exif.get(306)
        if timestamp:
            taken_at = datetime.strptime(timestamp, "%Y:%m:%d %H:%M:%S")
    except Exception:
        taken_at = None
    return width, height, taken_at


class ImportService:
    def __init__(self, storage: MinioStorage, face_service: FaceService) -> None:
        self.storage = storage
        self.face_service = face_service

    def _build_object_key(self, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        return f"{uuid4().hex}{suffix}"

    def _known_embeddings(self, db: Session) -> list[tuple[int, object]]:
        rows = db.execute(select(PersonEmbedding.person_id, PersonEmbedding.vector)).all()
        return [(person_id, bytes_to_vector(payload)) for person_id, payload in rows]

    def import_photo(self, db: Session, filename: str, payload: bytes, content_type: str | None = None) -> Photo:
        sha256 = hashlib.sha256(payload).hexdigest()
        existing = db.scalar(select(Photo).where(Photo.sha256 == sha256))
        if existing is not None:
            return existing

        width, height, taken_at = parse_image_metadata(payload)
        object_key = self._build_object_key(filename)
        self.storage.put_bytes(object_key, payload, content_type)

        photo = Photo(
            filename=filename,
            content_type=content_type,
            sha256=sha256,
            object_key=object_key,
            width=width,
            height=height,
            taken_at=taken_at,
        )
        db.add(photo)
        db.flush()

        known_embeddings = self._known_embeddings(db)
        detected_faces = self.face_service.detect_faces(payload)
        unknown_embeddings: list[tuple[int, object]] = []

        for detected in detected_faces:
            person_id, score = self.face_service.match_embedding(detected.embedding, known_embeddings)
            face = Face(
                photo_id=photo.id,
                bbox_left=detected.bbox[0],
                bbox_top=detected.bbox[1],
                bbox_right=detected.bbox[2],
                bbox_bottom=detected.bbox[3],
                detection_score=detected.score,
                embedding=vector_to_bytes(detected.embedding),
                matched_person_id=person_id,
                match_score=score,
                needs_review=person_id is None,
            )
            db.add(face)
            db.flush()

            if person_id is not None:
                self._ensure_photo_tag(db, photo.id, person_id, "auto")
            else:
                unknown_embeddings.append((face.id, detected.embedding))

        assignments = self.face_service.cluster_unknown_embeddings(unknown_embeddings)
        for face_id, cluster_key in assignments.items():
            face = db.get(Face, face_id)
            if face is not None:
                face.cluster_key = cluster_key

        db.commit()
        db.refresh(photo)
        return photo

    def add_person_samples(self, db: Session, person: Person, uploads: list[tuple[str, bytes, str | None]]) -> None:
        for filename, payload, content_type in uploads:
            photo = self.import_photo(db, filename, payload, content_type)
            faces = db.scalars(select(Face).where(Face.photo_id == photo.id)).all()
            for face in faces:
                embedding = PersonEmbedding(person_id=person.id, vector=face.embedding, source_photo_id=photo.id)
                db.add(embedding)
                face.matched_person_id = person.id
                face.match_score = 1.0
                face.needs_review = False
                self._ensure_photo_tag(db, photo.id, person.id, "sample")
        db.commit()

    def assign_cluster(self, db: Session, cluster_key: str, person: Person) -> int:
        faces = db.scalars(select(Face).where(Face.cluster_key == cluster_key)).all()
        for face in faces:
            face.matched_person_id = person.id
            face.match_score = max(face.match_score or 0.0, 1.0)
            face.needs_review = False
            self._ensure_photo_tag(db, face.photo_id, person.id, "cluster")
            db.add(PersonEmbedding(person_id=person.id, vector=face.embedding, source_photo_id=face.photo_id))
        db.commit()
        return len(faces)

    def reprocess_photo(self, db: Session, photo: Photo) -> Photo:
        db.query(Face).filter(Face.photo_id == photo.id).delete()
        db.query(PhotoTag).filter(PhotoTag.photo_id == photo.id).delete()
        payload = self.storage.get_bytes(photo.object_key)
        known_embeddings = self._known_embeddings(db)
        detected_faces = self.face_service.detect_faces(payload)
        unknown_embeddings: list[tuple[int, object]] = []
        for detected in detected_faces:
            person_id, score = self.face_service.match_embedding(detected.embedding, known_embeddings)
            face = Face(
                photo_id=photo.id,
                bbox_left=detected.bbox[0],
                bbox_top=detected.bbox[1],
                bbox_right=detected.bbox[2],
                bbox_bottom=detected.bbox[3],
                detection_score=detected.score,
                embedding=vector_to_bytes(detected.embedding),
                matched_person_id=person_id,
                match_score=score,
                needs_review=person_id is None,
            )
            db.add(face)
            db.flush()
            if person_id is not None:
                self._ensure_photo_tag(db, photo.id, person_id, "reprocess")
            else:
                unknown_embeddings.append((face.id, detected.embedding))
        assignments = self.face_service.cluster_unknown_embeddings(unknown_embeddings)
        for face_id, cluster_key in assignments.items():
            face = db.get(Face, face_id)
            if face is not None:
                face.cluster_key = cluster_key
        db.commit()
        db.refresh(photo)
        return photo

    def _ensure_photo_tag(self, db: Session, photo_id: int, person_id: int, source: str) -> None:
        existing = db.scalar(select(PhotoTag).where(PhotoTag.photo_id == photo_id, PhotoTag.person_id == person_id))
        if existing is None:
            db.add(PhotoTag(photo_id=photo_id, person_id=person_id, source=source))


def person_photo_count_subquery():
    return (
        select(PhotoTag.person_id, func.count(PhotoTag.photo_id).label("photo_count"))
        .group_by(PhotoTag.person_id)
        .subquery()
    )
