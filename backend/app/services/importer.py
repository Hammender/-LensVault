from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import logging
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, PersonTag, SamplePhoto, Tag
from app.services.face import FaceService
from app.services.milvus import MilvusVectorStore
from app.services.storage import MinioStorage

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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


@dataclass
class GalleryImportSummary:
    known_matches: int = 0
    unknown_created: int = 0
    unknown_reused: int = 0
    duplicated: int = 0


class PictureService:
    def __init__(
        self,
        storage: MinioStorage,
        face_service: FaceService,
        vector_store: MilvusVectorStore,
        settings: Settings | None = None,
    ) -> None:
        self.storage = storage
        self.face_service = face_service
        self.vector_store = vector_store
        self.settings = settings or get_settings()

    def _build_object_key(self, prefix: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        return f"{prefix}/{uuid4().hex}{suffix}"

    def _find_or_create_tag(self, db: Session, name: str) -> Tag:
        normalized = name.strip()
        tag = db.scalar(select(Tag).where(Tag.name == normalized))
        if tag is None:
            tag = Tag(name=normalized)
            db.add(tag)
            db.flush()
        return tag

    def _ensure_gallery_person_tag(self, db: Session, gallery_photo_id: int, person_id: int, source: str) -> None:
        existing = db.scalar(
            select(GalleryPhotoPersonTag).where(
                GalleryPhotoPersonTag.gallery_photo_id == gallery_photo_id,
                GalleryPhotoPersonTag.person_id == person_id,
            )
        )
        if existing is None:
            db.add(GalleryPhotoPersonTag(gallery_photo_id=gallery_photo_id, person_id=person_id, source=source))

    def _ensure_gallery_tag(self, db: Session, gallery_photo_id: int, tag: Tag, source: str = "manual") -> None:
        existing = db.scalar(
            select(GalleryPhotoTag).where(
                GalleryPhotoTag.gallery_photo_id == gallery_photo_id,
                GalleryPhotoTag.tag_id == tag.id,
            )
        )
        if existing is None:
            db.add(GalleryPhotoTag(gallery_photo_id=gallery_photo_id, tag_id=tag.id, source=source))
        elif existing.source != "manual" and source == "manual":
            existing.source = "manual"

    def _ensure_person_tag(self, db: Session, person_id: int, tag: Tag) -> None:
        existing = db.scalar(
            select(PersonTag).where(
                PersonTag.person_id == person_id,
                PersonTag.tag_id == tag.id,
            )
        )
        if existing is None:
            db.add(PersonTag(person_id=person_id, tag_id=tag.id))

    def _apply_person_tags_to_gallery_photo(self, db: Session, gallery_photo_id: int, person_id: int) -> None:
        links = db.scalars(select(PersonTag).where(PersonTag.person_id == person_id)).all()
        for link in links:
            link.tag
            self._ensure_gallery_tag(db, gallery_photo_id, link.tag, source="person")

    def _next_unknown_serial(self, db: Session) -> int:
        # Serial must be globally monotonic even after unknown persons are renamed to known.
        current = db.scalar(select(func.max(Person.unknown_serial)))
        return int(current or 0) + 1

    def create_unknown_person(self, db: Session) -> Person:
        serial = self._next_unknown_serial(db)
        display_name = f"未知人物-{serial:04d}"
        person = Person(
            name=display_name,
            display_name=display_name,
            is_unknown=True,
            unknown_serial=serial,
            note="系统自动创建的未知人物",
        )
        db.add(person)
        db.flush()
        logger.info("Created unknown person person_id=%s serial=%04d", person.id, serial)
        return person

    def add_person_samples(self, db: Session, person: Person, uploads: list[tuple[str, bytes, str | None]]) -> list[SamplePhoto]:
        logger.info("Start add_person_samples person_id=%s uploads=%d", person.id, len(uploads))
        sample_photos: list[SamplePhoto] = []
        for filename, payload, content_type in uploads:
            logger.info(
                "Processing sample upload person_id=%s filename=%s bytes=%d content_type=%s",
                person.id,
                filename,
                len(payload),
                content_type,
            )
            sha256 = hashlib.sha256(payload).hexdigest()
            duplicate = db.scalar(select(SamplePhoto).where(SamplePhoto.sha256 == sha256))
            if duplicate is not None:
                logger.info(
                    "Sample duplicate skipped person_id=%s filename=%s sha256=%s duplicate_sample_id=%s",
                    person.id,
                    filename,
                    sha256,
                    duplicate.id,
                )
                continue
            width, height, taken_at = parse_image_metadata(payload)
            object_key = self._build_object_key("samples", filename)
            self.storage.put_bytes(object_key, payload, content_type)
            logger.debug(
                "Stored sample object person_id=%s filename=%s object_key=%s size=%sx%s",
                person.id,
                filename,
                object_key,
                width,
                height,
            )

            sample = SamplePhoto(
                person_id=person.id,
                filename=filename,
                content_type=content_type,
                sha256=sha256,
                object_key=object_key,
                width=width,
                height=height,
                taken_at=taken_at,
                status="processing",
            )
            db.add(sample)
            db.flush()

            try:
                detected_faces = self.face_service.detect_faces(payload)
            except Exception as exc:
                logger.exception(
                    "Sample face detection failed person_id=%s sample_id=%s filename=%s",
                    person.id,
                    sample.id,
                    filename,
                )
                sample.status = "error"
                sample.error_message = str(exc)
                sample_photos.append(sample)
                continue

            logger.info(
                "Sample face detection result person_id=%s sample_id=%s filename=%s faces=%d",
                person.id,
                sample.id,
                filename,
                len(detected_faces),
            )
            if len(detected_faces) == 0:
                sample.status = "no_face"
                sample.error_message = "未检测到人脸"
                sample_photos.append(sample)
                continue

            if len(detected_faces) != 1:
                sample.status = "multi_face"
                sample.error_message = f"检测到 {len(detected_faces)} 张人脸，仅支持单人样本"
                sample_photos.append(sample)
                continue

            detected = detected_faces[0]
            face = FaceRecord(
                sample_photo_id=sample.id,
                bbox_left=detected.bbox[0],
                bbox_top=detected.bbox[1],
                bbox_right=detected.bbox[2],
                bbox_bottom=detected.bbox[3],
                detection_score=detected.score,
                matched_person_id=person.id,
                match_score=1.0,
                needs_review=False,
                vector_collection="known",
            )
            db.add(face)
            db.flush()
            self.vector_store.upsert_face(self.settings.milvus_known_collection, face.id, person.id, detected.embedding)
            logger.info(
                "Sample indexed to known collection person_id=%s sample_id=%s face_id=%s collection=%s",
                person.id,
                sample.id,
                face.id,
                self.settings.milvus_known_collection,
            )
            sample.status = "ready"
            sample_photos.append(sample)

        db.commit()
        ready_count = sum(1 for item in sample_photos if item.status == "ready")
        logger.info(
            "Completed add_person_samples person_id=%s accepted=%d ready=%d",
            person.id,
            len(sample_photos),
            ready_count,
        )
        return sample_photos

    def import_gallery_photo(
        self,
        db: Session,
        filename: str,
        payload: bytes,
        content_type: str | None = None,
        tag_names: list[str] | None = None,
    ) -> tuple[GalleryPhoto, GalleryImportSummary]:
        summary = GalleryImportSummary()
        logger.info(
            "Start import_gallery_photo filename=%s bytes=%d content_type=%s manual_tags=%d",
            filename,
            len(payload),
            content_type,
            len(tag_names or []),
        )
        sha256 = hashlib.sha256(payload).hexdigest()
        existing = db.scalar(select(GalleryPhoto).where(GalleryPhoto.sha256 == sha256))
        if existing is not None:
            summary.duplicated = 1
            logger.info(
                "Gallery duplicate skipped filename=%s sha256=%s existing_photo_id=%s",
                filename,
                sha256,
                existing.id,
            )
            return existing, summary

        width, height, taken_at = parse_image_metadata(payload)
        object_key = self._build_object_key("gallery", filename)
        self.storage.put_bytes(object_key, payload, content_type)
        logger.debug(
            "Stored gallery object filename=%s object_key=%s size=%sx%s",
            filename,
            object_key,
            width,
            height,
        )

        photo = GalleryPhoto(
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

        for tag_name in tag_names or []:
            if not tag_name.strip():
                continue
            tag = self._find_or_create_tag(db, tag_name)
            self._ensure_gallery_tag(db, photo.id, tag, source="manual")
        if tag_names:
            logger.info("Gallery manual tags applied photo_id=%s tags=%d", photo.id, len(tag_names))

        try:
            detected_faces = self.face_service.detect_faces(payload)
        except Exception:
            logger.exception(
                "Gallery face detection failed, keep photo without faces photo_id=%s filename=%s",
                photo.id,
                filename,
            )
            db.commit()
            db.refresh(photo)
            return photo, summary
        logger.info("Gallery face detection result photo_id=%s filename=%s faces=%d", photo.id, filename, len(detected_faces))
        for detected in detected_faces:
            try:
                with db.begin_nested():
                    matched_person_id, matched_score = self.vector_store.search(
                        self.settings.milvus_known_collection,
                        detected.embedding,
                    )
                    if matched_score is not None and matched_score >= self.settings.face_recognition_threshold and matched_person_id is not None:
                        face = FaceRecord(
                            gallery_photo_id=photo.id,
                            bbox_left=detected.bbox[0],
                            bbox_top=detected.bbox[1],
                            bbox_right=detected.bbox[2],
                            bbox_bottom=detected.bbox[3],
                            detection_score=detected.score,
                            matched_person_id=matched_person_id,
                            match_score=matched_score,
                            needs_review=False,
                            vector_collection="known",
                        )
                        db.add(face)
                        db.flush()
                        self.vector_store.upsert_face(self.settings.milvus_known_collection, face.id, matched_person_id, detected.embedding)
                        self._ensure_gallery_person_tag(db, photo.id, matched_person_id, "auto")
                        self._apply_person_tags_to_gallery_photo(db, photo.id, matched_person_id)
                        summary.known_matches += 1
                        logger.info(
                            "Gallery known face matched photo_id=%s face_id=%s person_id=%s score=%.4f",
                            photo.id,
                            face.id,
                            matched_person_id,
                            matched_score,
                        )
                        continue

                    unknown_person_id, unknown_score = self.vector_store.search(
                        self.settings.milvus_unknown_collection,
                        detected.embedding,
                    )
                    if unknown_score is not None and unknown_score >= self.settings.face_unknown_match_threshold and unknown_person_id is not None:
                        person = db.get(Person, unknown_person_id)
                        if person is None:
                            person = self.create_unknown_person(db)
                            summary.unknown_created += 1
                            logger.warning(
                                "Unknown vector hit missing person, created new person old_person_id=%s new_person_id=%s score=%.4f",
                                unknown_person_id,
                                person.id,
                                unknown_score,
                            )
                        else:
                            summary.unknown_reused += 1
                            logger.info(
                                "Gallery unknown reused photo_id=%s person_id=%s score=%.4f",
                                photo.id,
                                person.id,
                                unknown_score,
                            )
                    else:
                        person = self.create_unknown_person(db)
                        summary.unknown_created += 1
                        logger.info(
                            "Gallery unknown created photo_id=%s person_id=%s unknown_score=%s",
                            photo.id,
                            person.id,
                            f"{unknown_score:.4f}" if unknown_score is not None else "None",
                        )

                    face = FaceRecord(
                        gallery_photo_id=photo.id,
                        bbox_left=detected.bbox[0],
                        bbox_top=detected.bbox[1],
                        bbox_right=detected.bbox[2],
                        bbox_bottom=detected.bbox[3],
                        detection_score=detected.score,
                        matched_person_id=person.id,
                        match_score=unknown_score,
                        needs_review=True,
                        vector_collection="unknown",
                    )
                    db.add(face)
                    db.flush()
                    self.vector_store.upsert_face(self.settings.milvus_unknown_collection, face.id, person.id, detected.embedding)
                    self._ensure_gallery_person_tag(db, photo.id, person.id, "unknown")
                    self._apply_person_tags_to_gallery_photo(db, photo.id, person.id)
                    logger.info(
                        "Gallery unknown face indexed photo_id=%s face_id=%s person_id=%s collection=%s",
                        photo.id,
                        face.id,
                        person.id,
                        self.settings.milvus_unknown_collection,
                    )
            except Exception:
                logger.exception("Face process failed, skip this face photo_id=%s filename=%s", photo.id, filename)
                continue

        db.commit()
        db.refresh(photo)
        logger.info(
            "Completed import_gallery_photo photo_id=%s known=%d unknown_created=%d unknown_reused=%d duplicated=%d",
            photo.id,
            summary.known_matches,
            summary.unknown_created,
            summary.unknown_reused,
            summary.duplicated,
        )
        return photo, summary

    def rename_person(self, db: Session, person: Person, new_name: str) -> Person:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("人物名称不能为空")
        existing = db.scalar(select(Person).where(Person.name == new_name, Person.id != person.id))
        if existing is not None:
            raise ValueError("人物名称已存在")

        unknown_faces = db.scalars(
            select(FaceRecord).where(
                FaceRecord.matched_person_id == person.id,
                FaceRecord.vector_collection == "unknown",
            )
        ).all()
        logger.info(
            "Start rename_person person_id=%s old_name=%s new_name=%s unknown_faces=%d",
            person.id,
            person.name,
            new_name,
            len(unknown_faces),
        )
        for face in unknown_faces:
            vector = self.vector_store.get_face_vector(self.settings.milvus_unknown_collection, face.id)
            if vector is not None:
                self.vector_store.upsert_face(self.settings.milvus_known_collection, face.id, person.id, vector)
                self.vector_store.delete_faces(self.settings.milvus_unknown_collection, [face.id])
                face.vector_collection = "known"
                face.needs_review = False
                logger.debug("Promoted unknown face to known face_id=%s person_id=%s", face.id, person.id)

        person.name = new_name
        person.display_name = new_name
        person.is_unknown = False
        person.note = None if person.note == "系统自动创建的未知人物" else person.note
        db.add(person)
        db.commit()
        db.refresh(person)
        logger.info("Completed rename_person person_id=%s name=%s", person.id, person.name)
        return person

    def delete_sample_photo(self, db: Session, sample_photo: SamplePhoto) -> None:
        face_ids = [face.id for face in sample_photo.faces if face.vector_collection == "known"]
        self.vector_store.delete_faces(self.settings.milvus_known_collection, face_ids)
        self.storage.remove_object(sample_photo.object_key)
        logger.info(
            "Delete sample photo sample_id=%s person_id=%s known_faces_deleted=%d",
            sample_photo.id,
            sample_photo.person_id,
            len(face_ids),
        )
        db.delete(sample_photo)
        db.commit()

    def delete_gallery_photos(self, db: Session, photos: list[GalleryPhoto]) -> int:
        deleted = 0
        for photo in photos:
            known_face_ids = [face.id for face in photo.faces if face.vector_collection == "known"]
            unknown_face_ids = [face.id for face in photo.faces if face.vector_collection == "unknown"]
            self.vector_store.delete_faces(self.settings.milvus_known_collection, known_face_ids)
            self.vector_store.delete_faces(self.settings.milvus_unknown_collection, unknown_face_ids)
            self.storage.remove_object(photo.object_key)
            db.delete(photo)
            deleted += 1
            logger.info(
                "Delete gallery photo photo_id=%s known_faces_deleted=%d unknown_faces_deleted=%d",
                photo.id,
                len(known_face_ids),
                len(unknown_face_ids),
            )
        db.commit()
        return deleted

    def delete_persons(self, db: Session, persons: list[Person]) -> int:
        deleted = 0
        for person in persons:
            known_face_ids = [face.id for face in person.faces if face.vector_collection == "known"]
            unknown_face_ids = [face.id for face in person.faces if face.vector_collection == "unknown"]
            self.vector_store.delete_faces(self.settings.milvus_known_collection, known_face_ids)
            self.vector_store.delete_faces(self.settings.milvus_unknown_collection, unknown_face_ids)
            for sample in person.sample_photos:
                self.storage.remove_object(sample.object_key)
            db.delete(person)
            deleted += 1
            logger.info(
                "Delete person person_id=%s known_faces_deleted=%d unknown_faces_deleted=%d samples_deleted=%d",
                person.id,
                len(known_face_ids),
                len(unknown_face_ids),
                len(person.sample_photos),
            )
        db.commit()
        return deleted

    def move_gallery_face_to_known(self, db: Session, face: FaceRecord, person: Person, vector: np.ndarray | None) -> None:
        previous_collection = face.vector_collection
        face.vector_collection = "known"
        face.matched_person_id = person.id
        face.match_score = 1.0
        face.needs_review = False
        if vector is None:
            logger.warning(
                "Skip vector move due to missing embedding face_id=%s photo_id=%s person_id=%s previous_collection=%s",
                face.id,
                face.gallery_photo_id,
                person.id,
                previous_collection,
            )
            return
        if previous_collection == "unknown":
            self.vector_store.delete_faces(self.settings.milvus_unknown_collection, [face.id])
        self.vector_store.upsert_face(self.settings.milvus_known_collection, face.id, person.id, vector)
        logger.info(
            "Moved gallery face to known face_id=%s photo_id=%s person_id=%s from=%s to=known",
            face.id,
            face.gallery_photo_id,
            person.id,
            previous_collection,
        )

    def bind_person_tag(self, db: Session, person: Person, tag: Tag) -> None:
        self._ensure_person_tag(db, person.id, tag)
        photo_ids = db.scalars(
            select(GalleryPhotoPersonTag.gallery_photo_id).where(GalleryPhotoPersonTag.person_id == person.id)
        ).all()
        for photo_id in photo_ids:
            self._ensure_gallery_tag(db, photo_id, tag, source="person")
        db.commit()
        logger.info(
            "Bound person tag person_id=%s tag_id=%s affected_gallery_photos=%d",
            person.id,
            tag.id,
            len(photo_ids),
        )

    def unbind_person_tag(self, db: Session, person: Person, tag_id: int) -> None:
        link = db.scalar(select(PersonTag).where(PersonTag.person_id == person.id, PersonTag.tag_id == tag_id))
        if link is not None:
            db.delete(link)
        photo_ids = db.scalars(
            select(GalleryPhotoPersonTag.gallery_photo_id).where(GalleryPhotoPersonTag.person_id == person.id)
        ).all()
        for photo_id in photo_ids:
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
                    PersonTag.person_id != person.id,
                )
            ) or 0
            if still_required == 0:
                db.delete(gallery_tag)
        db.commit()
        logger.info(
            "Unbound person tag person_id=%s tag_id=%s affected_gallery_photos=%d",
            person.id,
            tag_id,
            len(photo_ids),
        )

    def list_person_tags(self, db: Session, person_id: int) -> list[Tag]:
        links = db.scalars(select(PersonTag).where(PersonTag.person_id == person_id)).all()
        tags: list[Tag] = []
        for link in links:
            link.tag
            tags.append(link.tag)
        return sorted(tags, key=lambda item: item.name.lower())
