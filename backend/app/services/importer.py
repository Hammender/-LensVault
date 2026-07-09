from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import json
import logging
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, PersonTag, SamplePhoto, Tag
from app.services.face import FaceService
from app.services.qdrant import QdrantVectorStore
from app.services.ocr import OcrService
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
    unknown_faces: int = 0
    duplicated: int = 0


class PictureService:
    def __init__(
        self,
        storage: MinioStorage,
        face_service: FaceService,
        vector_store: QdrantVectorStore,
        ocr_service: OcrService,
        settings: Settings | None = None,
    ) -> None:
        self.storage = storage
        self.face_service = face_service
        self.vector_store = vector_store
        self.ocr_service = ocr_service
        self.settings = settings or get_settings()
        self.rich_text_tag_name = "图文"
        self.unknown_person_name = "未知人物"

    def _unknown_person_internal_name(self, workspace_id: int | None) -> str:
        workspace_key = "global" if workspace_id is None else str(workspace_id)
        return f"__system_unknown_person__:{workspace_key}"

    def _build_object_key(self, workspace_id: int | None, prefix: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        tenant_prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{tenant_prefix}{prefix}/{uuid4().hex}{suffix}"

    def _find_or_create_tag(self, db: Session, name: str, workspace_id: int | None) -> Tag:
        normalized = name.strip()
        tag = db.scalar(select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == normalized))
        if tag is None:
            tag = Tag(workspace_id=workspace_id, name=normalized)
            db.add(tag)
            db.flush()
        return tag

    def ensure_system_tags(self, db: Session, workspace_id: int | None) -> None:
        rich_tag = db.scalar(select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == self.rich_text_tag_name))
        if rich_tag is None:
            db.add(Tag(workspace_id=workspace_id, name=self.rich_text_tag_name, is_system=True))
            db.commit()
            logger.info("Created system tag name=%s", self.rich_text_tag_name)
            return
        if not rich_tag.is_system:
            rich_tag.is_system = True
            db.add(rich_tag)
            db.commit()
            logger.info("Updated tag to system tag name=%s tag_id=%s", self.rich_text_tag_name, rich_tag.id)

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

    def get_or_create_unknown_person(self, db: Session, workspace_id: int | None) -> Person:
        internal_name = self._unknown_person_internal_name(workspace_id)
        person = db.scalar(
            select(Person).where(
                Person.workspace_id == workspace_id,
                Person.name == internal_name,
            )
        )
        if person is None:
            person = db.scalar(
                select(Person).where(
                    Person.workspace_id == workspace_id,
                    Person.is_unknown.is_(True),
                    Person.unknown_serial == 0,
                )
            )
        if person is None:
            person = db.scalar(
                select(Person).where(
                    Person.workspace_id == workspace_id,
                    Person.is_unknown.is_(True),
                    Person.display_name == self.unknown_person_name,
                )
            )
        if person is None:
            person = db.scalar(
                select(Person).where(
                    Person.workspace_id == workspace_id,
                    Person.name == self.unknown_person_name,
                )
            )
        if person is None:
            person = Person(
                workspace_id=workspace_id,
                name=internal_name,
                display_name=self.unknown_person_name,
                is_unknown=True,
                unknown_serial=None,
                note="系统占位未知人物，不保存样本向量",
            )
            db.add(person)
            db.flush()
            logger.info("Created singleton unknown person person_id=%s workspace_id=%s", person.id, workspace_id)
            return person
        if (
            not person.is_unknown
            or person.name != internal_name
            or person.display_name != self.unknown_person_name
            or person.unknown_serial is not None
        ):
            person.is_unknown = True
            person.name = internal_name
            person.display_name = self.unknown_person_name
            person.unknown_serial = None
            if not person.note:
                person.note = "系统占位未知人物，不保存样本向量"
            db.add(person)
            db.flush()
            logger.info("Normalized singleton unknown person person_id=%s workspace_id=%s", person.id, workspace_id)
        return person

    def _is_singleton_unknown_person(self, person: Person) -> bool:
        return (
            person.is_unknown
            and person.display_name == self.unknown_person_name
            and (
                person.name.startswith("__system_unknown_person__:")
                or person.name == self.unknown_person_name
            )
        )

    def _remove_unknown_person_tag_if_resolved(self, db: Session, gallery_photo_id: int, workspace_id: int | None) -> None:
        internal_name = self._unknown_person_internal_name(workspace_id)
        unknown = db.scalar(
            select(Person).where(
                Person.workspace_id == workspace_id,
                Person.is_unknown.is_(True),
                Person.name == internal_name,
            )
        )
        if unknown is None:
            unknown = db.scalar(
                select(Person).where(
                    Person.workspace_id == workspace_id,
                    Person.is_unknown.is_(True),
                    Person.display_name == self.unknown_person_name,
                )
            )
        if unknown is None:
            return
        unresolved_count = db.scalar(
            select(func.count(FaceRecord.id)).where(
                FaceRecord.gallery_photo_id == gallery_photo_id,
                FaceRecord.matched_person_id == unknown.id,
                FaceRecord.needs_review.is_(True),
            )
        ) or 0
        if unresolved_count > 0:
            return
        link = db.scalar(
            select(GalleryPhotoPersonTag).where(
                GalleryPhotoPersonTag.gallery_photo_id == gallery_photo_id,
                GalleryPhotoPersonTag.person_id == unknown.id,
            )
        )
        if link is not None:
            db.delete(link)

    def add_person_samples(self, db: Session, person: Person, uploads: list[tuple[str, bytes, str | None]]) -> list[SamplePhoto]:
        if person.is_unknown:
            raise ValueError("系统未知人物不能上传样本图")
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
            duplicate = db.scalar(
                select(SamplePhoto).where(SamplePhoto.workspace_id == person.workspace_id, SamplePhoto.sha256 == sha256)
            )
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
            object_key = self._build_object_key(person.workspace_id, "samples", filename)
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
                workspace_id=person.workspace_id,
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
                workspace_id=person.workspace_id,
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
            self.vector_store.upsert_face(self.settings.qdrant_known_collection, face.id, person.id, detected.embedding)
            logger.info(
                "Sample indexed to known collection person_id=%s sample_id=%s face_id=%s collection=%s",
                person.id,
                sample.id,
                face.id,
                self.settings.qdrant_known_collection,
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
        is_rich_text: bool = False,
        rich_text: str | None = None,
        workspace_id: int | None = None,
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
        existing = db.scalar(
            select(GalleryPhoto).where(GalleryPhoto.workspace_id == workspace_id, GalleryPhoto.sha256 == sha256)
        )
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
        object_key = self._build_object_key(workspace_id, "gallery", filename)
        self.storage.put_bytes(object_key, payload, content_type)
        logger.debug(
            "Stored gallery object filename=%s object_key=%s size=%sx%s",
            filename,
            object_key,
            width,
            height,
        )

        photo = GalleryPhoto(
            workspace_id=workspace_id,
            filename=filename,
            content_type=content_type,
            sha256=sha256,
            object_key=object_key,
            width=width,
            height=height,
            taken_at=taken_at,
            is_rich_text=is_rich_text,
            rich_text=rich_text.strip() if rich_text else None,
            ocr_status="manual" if rich_text and rich_text.strip() else None,
        )
        db.add(photo)
        db.flush()

        if is_rich_text:
            rich_tag = self._find_or_create_tag(db, self.rich_text_tag_name, workspace_id)
            rich_tag.is_system = True
            self._ensure_gallery_tag(db, photo.id, rich_tag, source="system")
            if not photo.rich_text:
                extracted = self.ocr_service.extract_text(payload)
                photo.rich_text = extracted
                photo.ocr_status = "ok" if extracted else "failed"
                logger.info(
                    "Gallery rich text OCR completed photo_id=%s status=%s chars=%d",
                    photo.id,
                    photo.ocr_status,
                    len(photo.rich_text or ""),
                )

        for tag_name in tag_names or []:
            if not tag_name.strip():
                continue
            tag = self._find_or_create_tag(db, tag_name, workspace_id)
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
                        self.settings.qdrant_known_collection,
                        detected.embedding,
                    )
                    matched_person = None
                    if matched_person_id is not None:
                        matched_person = db.scalar(select(Person).where(Person.id == matched_person_id, Person.workspace_id == workspace_id))
                    if (
                        matched_score is not None
                        and matched_score >= self.settings.face_recognition_threshold
                        and matched_person is not None
                    ):
                        face = FaceRecord(
                            workspace_id=workspace_id,
                            gallery_photo_id=photo.id,
                            bbox_left=detected.bbox[0],
                            bbox_top=detected.bbox[1],
                            bbox_right=detected.bbox[2],
                            bbox_bottom=detected.bbox[3],
                            detection_score=detected.score,
                            matched_person_id=matched_person.id,
                            match_score=matched_score,
                            needs_review=False,
                            vector_collection=None,
                        )
                        db.add(face)
                        db.flush()
                        self._ensure_gallery_person_tag(db, photo.id, matched_person.id, "auto")
                        self._apply_person_tags_to_gallery_photo(db, photo.id, matched_person.id)
                        summary.known_matches += 1
                        logger.info(
                            "Gallery known face matched photo_id=%s face_id=%s person_id=%s score=%.4f",
                            photo.id,
                            face.id,
                            matched_person.id,
                            matched_score,
                        )
                        continue

                    person = self.get_or_create_unknown_person(db, workspace_id)
                    summary.unknown_faces += 1
                    logger.info(
                        "Gallery unknown face tagged photo_id=%s person_id=%s matched_score=%s",
                        photo.id,
                        person.id,
                        f"{matched_score:.4f}" if matched_score is not None else "None",
                    )

                    face = FaceRecord(
                        workspace_id=workspace_id,
                        gallery_photo_id=photo.id,
                        bbox_left=detected.bbox[0],
                        bbox_top=detected.bbox[1],
                        bbox_right=detected.bbox[2],
                        bbox_bottom=detected.bbox[3],
                        detection_score=detected.score,
                        matched_person_id=person.id,
                        match_score=matched_score,
                        needs_review=True,
                        vector_collection=None,
                    )
                    db.add(face)
                    db.flush()
                    self._ensure_gallery_person_tag(db, photo.id, person.id, "unknown")
                    logger.info(
                        "Gallery unknown face recorded photo_id=%s face_id=%s person_id=%s",
                        photo.id,
                        face.id,
                        person.id,
                    )
            except Exception:
                logger.exception("Face process failed, skip this face photo_id=%s filename=%s", photo.id, filename)
                continue

        db.commit()
        db.refresh(photo)
        logger.info(
            "Completed import_gallery_photo photo_id=%s known=%d unknown_faces=%d duplicated=%d",
            photo.id,
            summary.known_matches,
            summary.unknown_faces,
            summary.duplicated,
        )
        return photo, summary

    def rename_person(self, db: Session, person: Person, new_name: str) -> Person:
        if self._is_singleton_unknown_person(person):
            raise ValueError("系统未知人物不能直接改名，请在图片详情中重新识别或改为已有正式人物")
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("人物名称不能为空")
        existing = db.scalar(
            select(Person).where(Person.workspace_id == person.workspace_id, Person.name == new_name, Person.id != person.id)
        )
        if existing is not None:
            raise ValueError("人物名称已存在")

        logger.info(
            "Start rename_person person_id=%s old_name=%s new_name=%s",
            person.id,
            person.name,
            new_name,
        )

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
        self.vector_store.delete_faces(self.settings.qdrant_known_collection, face_ids)
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
            self.vector_store.delete_faces(self.settings.qdrant_known_collection, known_face_ids)
            self.storage.remove_object(photo.object_key)
            db.delete(photo)
            deleted += 1
            logger.info(
                "Delete gallery photo photo_id=%s legacy_known_vectors_deleted=%d",
                photo.id,
                len(known_face_ids),
            )
        db.commit()
        return deleted

    def delete_persons(self, db: Session, persons: list[Person]) -> int:
        deleted = 0
        for person in persons:
            if self._is_singleton_unknown_person(person):
                logger.info("Skip deleting singleton unknown person person_id=%s", person.id)
                continue
            known_face_ids = [face.id for face in person.faces if face.vector_collection == "known"]
            self.vector_store.delete_faces(self.settings.qdrant_known_collection, known_face_ids)
            for sample in person.sample_photos:
                self.storage.remove_object(sample.object_key)
            db.delete(person)
            deleted += 1
            logger.info(
                "Delete person person_id=%s known_vectors_deleted=%d samples_deleted=%d",
                person.id,
                len(known_face_ids),
                len(person.sample_photos),
            )
        db.commit()
        return deleted

    def move_gallery_face_to_known(self, db: Session, face: FaceRecord, person: Person) -> None:
        if person.is_unknown:
            raise ValueError("不能将图库人脸确认到未知人物")
        previous_collection = face.vector_collection
        face.vector_collection = None
        face.matched_person_id = person.id
        face.match_score = 1.0
        face.needs_review = False
        if previous_collection == "known":
            self.vector_store.delete_faces(self.settings.qdrant_known_collection, [face.id])
        if face.gallery_photo_id is not None:
            self._remove_unknown_person_tag_if_resolved(db, face.gallery_photo_id, face.workspace_id)
        logger.info(
            "Confirmed gallery face as known face_id=%s photo_id=%s person_id=%s previous_collection=%s",
            face.id,
            face.gallery_photo_id,
            person.id,
            previous_collection,
        )

    def bind_person_tag(self, db: Session, person: Person, tag: Tag) -> None:
        if self._is_singleton_unknown_person(person):
            raise ValueError("系统未知人物不能维护普通标签")
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
        if self._is_singleton_unknown_person(person):
            raise ValueError("系统未知人物不能维护普通标签")
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

    def re_recognize_unknown_gallery_photos(self, db: Session, workspace_id: int | None) -> dict[str, int]:
        photo_ids = db.scalars(
            select(func.distinct(GalleryPhotoPersonTag.gallery_photo_id))
            .join(GalleryPhoto, GalleryPhoto.id == GalleryPhotoPersonTag.gallery_photo_id)
            .join(Person, Person.id == GalleryPhotoPersonTag.person_id)
            .where(GalleryPhoto.workspace_id == workspace_id, Person.workspace_id == workspace_id, Person.is_unknown.is_(True))
            .order_by(GalleryPhotoPersonTag.gallery_photo_id.asc())
        ).all()
        succeeded = 0
        failed = 0
        for photo_id in photo_ids:
            photo = db.get(GalleryPhoto, photo_id)
            if photo is None:
                failed += 1
                continue
            try:
                self.re_recognize_gallery_photo(db, photo)
                succeeded += 1
            except Exception:
                failed += 1
                db.rollback()
                logger.exception("Re-recognize unknown batch failed photo_id=%s", photo_id)
        logger.info(
            "Completed re_recognize_unknown_gallery_photos matched=%d succeeded=%d failed=%d",
            len(photo_ids),
            succeeded,
            failed,
        )
        return {"total": len(photo_ids), "succeeded": succeeded, "failed": failed}

    def re_recognize_gallery_photo(self, db: Session, photo: GalleryPhoto) -> GalleryPhoto:
        logger.info("Start re_recognize_gallery_photo photo_id=%s", photo.id)
        payload = self.storage.get_bytes(photo.object_key)
        old_known_face_ids = [face.id for face in photo.faces if face.vector_collection == "known"]
        self.vector_store.delete_faces(self.settings.qdrant_known_collection, old_known_face_ids)
        logger.info(
            "Deleted old gallery vectors from known collection photo_id=%s known=%d",
            photo.id,
            len(old_known_face_ids),
        )
        old_person_ids = set(tag.person_id for tag in photo.person_tags)
        for person_id in old_person_ids:
            link = db.scalar(
                select(GalleryPhotoPersonTag).where(
                    GalleryPhotoPersonTag.gallery_photo_id == photo.id,
                    GalleryPhotoPersonTag.person_id == person_id,
                )
            )
            if link is not None:
                db.delete(link)
        old_person_gallery_tags = db.scalars(
            select(GalleryPhotoTag).where(
                GalleryPhotoTag.gallery_photo_id == photo.id,
                GalleryPhotoTag.source == "person",
            )
        ).all()
        for tag_link in old_person_gallery_tags:
            db.delete(tag_link)
        logger.info(
            "Cleared old person tags photo_id=%s persons=%d inherited_tags=%d",
            photo.id,
            len(old_person_ids),
            len(old_person_gallery_tags),
        )
        for face in photo.faces:
            db.delete(face)
        db.flush()

        summary = GalleryImportSummary()
        try:
            detected_faces = self.face_service.detect_faces(payload)
        except Exception:
            logger.exception("Re-recognize face detection failed photo_id=%s", photo.id)
            db.commit()
            db.refresh(photo)
            return photo
        logger.info("Re-recognize detection result photo_id=%s faces=%d", photo.id, len(detected_faces))
        for detected in detected_faces:
            try:
                with db.begin_nested():
                    matched_person_id, matched_score = self.vector_store.search(
                        self.settings.qdrant_known_collection,
                        detected.embedding,
                    )
                    matched_person = None
                    if matched_person_id is not None:
                        matched_person = db.scalar(
                            select(Person).where(Person.id == matched_person_id, Person.workspace_id == photo.workspace_id)
                        )
                    if (
                        matched_score is not None
                        and matched_score >= self.settings.face_recognition_threshold
                        and matched_person is not None
                    ):
                        face = FaceRecord(
                            workspace_id=photo.workspace_id,
                            gallery_photo_id=photo.id,
                            bbox_left=detected.bbox[0],
                            bbox_top=detected.bbox[1],
                            bbox_right=detected.bbox[2],
                            bbox_bottom=detected.bbox[3],
                            detection_score=detected.score,
                            matched_person_id=matched_person.id,
                            match_score=matched_score,
                            needs_review=False,
                            vector_collection=None,
                        )
                        db.add(face)
                        db.flush()
                        self._ensure_gallery_person_tag(db, photo.id, matched_person.id, "auto")
                        self._apply_person_tags_to_gallery_photo(db, photo.id, matched_person.id)
                        summary.known_matches += 1
                        logger.info(
                            "Re-recognize known face matched photo_id=%s face_id=%s person_id=%s score=%.4f",
                            photo.id,
                            face.id,
                            matched_person.id,
                            matched_score,
                        )
                        continue

                    person = self.get_or_create_unknown_person(db, photo.workspace_id)
                    summary.unknown_faces += 1

                    face = FaceRecord(
                        workspace_id=photo.workspace_id,
                        gallery_photo_id=photo.id,
                        bbox_left=detected.bbox[0],
                        bbox_top=detected.bbox[1],
                        bbox_right=detected.bbox[2],
                        bbox_bottom=detected.bbox[3],
                        detection_score=detected.score,
                        matched_person_id=person.id,
                        match_score=matched_score,
                        needs_review=True,
                        vector_collection=None,
                    )
                    db.add(face)
                    db.flush()
                    self._ensure_gallery_person_tag(db, photo.id, person.id, "unknown")
                    logger.info(
                        "Re-recognize unknown face tagged photo_id=%s face_id=%s person_id=%s",
                        photo.id,
                        face.id,
                        person.id,
                    )
            except Exception:
                logger.exception("Re-recognize face process failed photo_id=%s", photo.id)
                continue

        db.commit()
        db.refresh(photo)
        photo.person_tags
        photo.tags
        for tag in photo.person_tags:
            tag.person
        for tag_link in photo.tags:
            tag_link.tag
        logger.info(
            "Completed re_recognize_gallery_photo photo_id=%s known=%d unknown_faces=%d",
            photo.id,
            summary.known_matches,
            summary.unknown_faces,
        )
        return photo

    def import_persons_from_zip(self, db: Session, zip_bytes: bytes, workspace_id: int | None, progress_callback=None) -> dict:
        logger.info("Start person import from zip bytes=%d", len(zip_bytes))
        result = {"created_persons": 0, "existing_persons": 0, "added_samples": 0, "skipped_samples": 0, "tags_added": 0}

        with ZipFile(BytesIO(zip_bytes)) as zf:
            manifest = json.loads(zf.read("metadata.json"))
            total_persons = len(manifest.get("persons", []))
            total_samples = sum(len(p.get("samples", [])) for p in manifest.get("persons", []))

            processed_samples = 0
            for person_index, person_data in enumerate(manifest["persons"]):
                person_name = person_data["name"].strip()
                existing = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == person_name))

                if existing is None:
                    person = Person(
                        workspace_id=workspace_id,
                        name=person_name,
                        display_name=person_data.get("display_name", person_name),
                        note=person_data.get("note"),
                        is_unknown=False,
                    )
                    db.add(person)
                    db.flush()
                    result["created_persons"] += 1
                    logger.info("Created person from import name=%s person_id=%s", person_name, person.id)
                else:
                    person = existing
                    result["existing_persons"] += 1
                    logger.info("Matched existing person name=%s person_id=%s", person_name, person.id)

                for tag_name in person_data.get("tags", []):
                    tag = self._find_or_create_tag(db, tag_name.strip(), workspace_id)
                    existing_link = db.scalar(
                        select(PersonTag).where(PersonTag.person_id == person.id, PersonTag.tag_id == tag.id)
                    )
                    if existing_link is None:
                        db.add(PersonTag(person_id=person.id, tag_id=tag.id))
                        result["tags_added"] += 1
                db.flush()

                samples_dir = f"samples/{person_name}"
                for sample_data in person_data.get("samples", []):
                    sha256 = sample_data["sha256"]
                    duplicate = db.scalar(
                        select(SamplePhoto).where(SamplePhoto.workspace_id == workspace_id, SamplePhoto.sha256 == sha256)
                    )
                    if duplicate is not None:
                        result["skipped_samples"] += 1
                        processed_samples += 1
                        if progress_callback:
                            progress_callback(processed_samples, total_samples)
                        continue

                    filename = sample_data["filename"]
                    content_type = sample_data.get("content_type")
                    zip_path = f"{samples_dir}/{filename}"

                    try:
                        payload = zf.read(zip_path)
                    except KeyError:
                        logger.warning("Sample file not found in zip path=%s", zip_path)
                        result["skipped_samples"] += 1
                        processed_samples += 1
                        if progress_callback:
                            progress_callback(processed_samples, total_samples)
                        continue

                    width = sample_data.get("width")
                    height = sample_data.get("height")
                    taken_at = None
                    if sample_data.get("taken_at"):
                        try:
                            taken_at = datetime.fromisoformat(sample_data["taken_at"])
                        except (ValueError, TypeError):
                            pass

                    object_key = self._build_object_key(workspace_id, "samples", filename)
                    self.storage.put_bytes(object_key, payload, content_type)
                    sample_photo = SamplePhoto(
                        workspace_id=workspace_id,
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
                    db.add(sample_photo)
                    db.flush()

                    try:
                        detected_faces = self.face_service.detect_faces(payload)
                    except Exception as exc:
                        logger.exception("Sample face detection failed person_id=%s filename=%s", person.id, filename)
                        sample_photo.status = "error"
                        sample_photo.error_message = str(exc)
                        result["added_samples"] += 1
                        processed_samples += 1
                        if progress_callback:
                            progress_callback(processed_samples, total_samples)
                        continue

                    if len(detected_faces) == 0:
                        sample_photo.status = "no_face"
                        sample_photo.error_message = "未检测到人脸"
                        result["added_samples"] += 1
                        processed_samples += 1
                        if progress_callback:
                            progress_callback(processed_samples, total_samples)
                        continue

                    if len(detected_faces) != 1:
                        sample_photo.status = "multi_face"
                        sample_photo.error_message = f"检测到 {len(detected_faces)} 张人脸，仅支持单人样本"
                        result["added_samples"] += 1
                        processed_samples += 1
                        if progress_callback:
                            progress_callback(processed_samples, total_samples)
                        continue

                    detected = detected_faces[0]
                    face = FaceRecord(
                        workspace_id=workspace_id,
                        sample_photo_id=sample_photo.id,
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
                    self.vector_store.upsert_face(
                        self.settings.qdrant_known_collection, face.id, person.id, detected.embedding
                    )
                    sample_photo.status = "ready"
                    result["added_samples"] += 1
                    processed_samples += 1
                    if progress_callback:
                        progress_callback(processed_samples, total_samples)

                db.commit()

        logger.info(
            "Completed person import created=%d existing=%d added=%d skipped=%d tags=%d",
            result["created_persons"],
            result["existing_persons"],
            result["added_samples"],
            result["skipped_samples"],
            result["tags_added"],
        )
        return result

    def import_gallery_from_zip(self, db: Session, zip_bytes: bytes, workspace_id: int | None, progress_callback=None) -> dict:
        logger.info("Start gallery import from zip bytes=%d", len(zip_bytes))
        result = {
            "added_photos": 0,
            "updated_existing": 0,
            "skipped_photos": 0,
            "tags_added": 0,
            "persons_added": 0,
        }

        with ZipFile(BytesIO(zip_bytes)) as zf:
            try:
                manifest = json.loads(zf.read("metadata.json"))
            except KeyError as exc:
                raise ValueError("ZIP 中缺少 metadata.json") from exc
            photos = manifest.get("photos", [])
            if not isinstance(photos, list):
                raise ValueError("metadata.json 格式不正确")

            total = len(photos)
            for index, photo_data in enumerate(photos, start=1):
                if not isinstance(photo_data, dict):
                    result["skipped_photos"] += 1
                    if progress_callback:
                        progress_callback(index, total)
                    continue

                zip_paths = photo_data.get("paths") or []
                if not isinstance(zip_paths, list):
                    zip_paths = []
                payload = None
                for zip_path in zip_paths:
                    try:
                        payload = zf.read(str(zip_path))
                        break
                    except KeyError:
                        continue
                if payload is None:
                    logger.warning("Gallery zip import skipped missing file photo=%s", photo_data.get("filename"))
                    result["skipped_photos"] += 1
                    if progress_callback:
                        progress_callback(index, total)
                    continue

                sha256 = photo_data.get("sha256") or hashlib.sha256(payload).hexdigest()
                photo = db.scalar(
                    select(GalleryPhoto).where(GalleryPhoto.workspace_id == workspace_id, GalleryPhoto.sha256 == sha256)
                )
                is_existing = photo is not None
                tag_names = [
                    str(name).strip()
                    for name in photo_data.get("tags", [])
                    if str(name).strip() and str(name).strip() != self.rich_text_tag_name
                ]

                if photo is None:
                    filename = str(photo_data.get("filename") or Path(str(zip_paths[0])).name)
                    photo, summary = self.import_gallery_photo(
                        db,
                        filename,
                        payload,
                        photo_data.get("content_type"),
                        tag_names,
                        bool(photo_data.get("is_rich_text")),
                        photo_data.get("rich_text"),
                        workspace_id,
                    )
                    if summary.duplicated:
                        result["updated_existing"] += 1
                    else:
                        result["added_photos"] += 1
                else:
                    result["updated_existing"] += 1

                if photo_data.get("is_rich_text"):
                    photo.is_rich_text = True
                    rich_text = photo_data.get("rich_text")
                    if rich_text is not None:
                        photo.rich_text = str(rich_text)
                    if photo_data.get("ocr_status"):
                        photo.ocr_status = str(photo_data.get("ocr_status"))
                    rich_tag = self._find_or_create_tag(db, self.rich_text_tag_name, workspace_id)
                    rich_tag.is_system = True
                    self._ensure_gallery_tag(db, photo.id, rich_tag, source="system")

                for tag_name in tag_names:
                    tag = self._find_or_create_tag(db, tag_name, workspace_id)
                    existing_tag_link = db.scalar(
                        select(GalleryPhotoTag).where(
                            GalleryPhotoTag.gallery_photo_id == photo.id,
                            GalleryPhotoTag.tag_id == tag.id,
                        )
                    )
                    self._ensure_gallery_tag(db, photo.id, tag, source="manual")
                    if existing_tag_link is None:
                        result["tags_added"] += 1

                for person_data in photo_data.get("persons", []):
                    if not isinstance(person_data, dict):
                        continue
                    person_name = str(person_data.get("name") or person_data.get("display_name") or "").strip()
                    manifest_is_unknown = bool(person_data.get("is_unknown"))
                    if manifest_is_unknown:
                        person = self.get_or_create_unknown_person(db, workspace_id)
                    else:
                        if not person_name:
                            continue
                        person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == person_name))
                        if person is None:
                            person = Person(
                                workspace_id=workspace_id,
                                name=person_name,
                                display_name=str(person_data.get("display_name") or person_name).strip() or person_name,
                                note=None,
                                is_unknown=False,
                            )
                            db.add(person)
                            db.flush()
                        else:
                            person.display_name = str(person_data.get("display_name") or person.display_name).strip() or person.display_name
                            person.is_unknown = False
                            person.unknown_serial = None
                    existing_person_link = db.scalar(
                        select(GalleryPhotoPersonTag).where(
                            GalleryPhotoPersonTag.gallery_photo_id == photo.id,
                            GalleryPhotoPersonTag.person_id == person.id,
                        )
                    )
                    source = str(person_data.get("source") or ("unknown" if person.is_unknown else "import"))
                    self._ensure_gallery_person_tag(db, photo.id, person.id, source)
                    if not person.is_unknown:
                        self._apply_person_tags_to_gallery_photo(db, photo.id, person.id)
                    if existing_person_link is None:
                        result["persons_added"] += 1
                db.add(photo)
                db.commit()
                if progress_callback:
                    progress_callback(index, total)
                logger.info(
                    "Gallery zip import progress index=%d/%d photo_id=%s existing=%s",
                    index,
                    total,
                    photo.id,
                    is_existing,
                )

        logger.info("Completed gallery import from zip result=%s", result)
        return result
