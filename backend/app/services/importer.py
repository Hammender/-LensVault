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

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.timezones import as_shanghai_naive, shanghai_now
from app.models import FaceRecognitionCorrection, FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, PersonTag, SamplePhoto, Tag
from app.services.face import DetectedFace, FaceService
from app.services.image_metadata import parse_image_metadata
from app.services.qdrant import QdrantVectorStore
from app.services.ocr import OcrService
from app.services.storage import MinioStorage
from app.services.thumbnails import animated_thumbnail_cache_key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_RECOGNITION_NOT_PRECOMPUTED = object()


@dataclass
class GalleryImportSummary:
    known_matches: int = 0
    unknown_faces: int = 0
    duplicated: int = 0


@dataclass(frozen=True)
class PersonMatch:
    person_id: int | None
    score: float | None
    second_person_id: int | None = None
    second_score: float | None = None

    @property
    def margin(self) -> float | None:
        if self.score is None or self.second_score is None:
            return None
        return self.score - self.second_score


@dataclass(frozen=True)
class MatchDecision:
    accepted: bool
    rejection_reason: str | None


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

    def _match_face(self, detected: DetectedFace, workspace_id: int | None) -> PersonMatch:
        by_person: dict[int, float] = {}
        embeddings = (detected.embedding, *detected.embedding_variants)
        for embedding in embeddings:
            hits = self.vector_store.search_candidates(
                self.settings.qdrant_known_collection,
                embedding,
                workspace_id=workspace_id,
                embedding_version=self.settings.face_embedding_version,
                limit=self.settings.face_search_limit,
            )
            for hit in hits:
                by_person[hit.person_id] = max(by_person.get(hit.person_id, -1.0), hit.score)
        ranked = sorted(by_person.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            logger.info(
                "Face match evaluated embedding_candidates=%d person_id=None score=None margin=None",
                len(embeddings),
            )
            return PersonMatch(None, None)
        second = ranked[1] if len(ranked) > 1 else (None, None)
        match = PersonMatch(ranked[0][0], ranked[0][1], second[0], second[1])
        logger.info(
            "Face match evaluated embedding_candidates=%d person_id=%s score=%.4f "
            "second_person_id=%s second_score=%s margin=%s",
            len(embeddings),
            match.person_id,
            match.score,
            match.second_person_id,
            f"{match.second_score:.4f}" if match.second_score is not None else "None",
            f"{match.margin:.4f}" if match.margin is not None else "None",
        )
        return match

    def _recognition_plan(
        self,
        db: Session,
        payload: bytes,
        workspace_id: int | None,
    ) -> list[tuple[DetectedFace, PersonMatch]]:
        def selected_plan(
            source: str,
            selected: list[tuple[DetectedFace, PersonMatch]],
            *,
            reason: str | None = None,
        ) -> list[tuple[DetectedFace, PersonMatch]]:
            best_match = max(
                (match for _, match in selected),
                key=lambda match: match.score if match.score is not None else -1.0,
                default=PersonMatch(None, None),
            )
            logger.info(
                "Recognition plan selected source=%s faces=%d reason=%s person_id=%s score=%s margin=%s",
                source,
                len(selected),
                reason or "best_available",
                best_match.person_id,
                f"{best_match.score:.4f}" if best_match.score is not None else "None",
                f"{best_match.margin:.4f}" if best_match.margin is not None else "None",
            )
            return selected

        detected_faces = self.face_service.detect_faces(payload)
        plan = [(detected, self._match_face(detected, workspace_id)) for detected in detected_faces]
        if not plan:
            return selected_plan("primary", plan, reason="no_faces")
        primary_accepted = self._plan_has_accepted_match(db, plan, workspace_id)
        logger.info(
            "Primary recognition evaluated faces=%d accepted=%s",
            len(plan),
            primary_accepted,
        )
        if primary_accepted:
            return selected_plan("primary", plan, reason="accepted_match")
        if not self.settings.face_rotation_fallback_enabled:
            return selected_plan("primary", plan, reason="fallback_disabled")
        fallback = getattr(self.face_service, "detect_faces_with_rotation_fallback", None)
        if not callable(fallback):
            return selected_plan("primary", plan, reason="fallback_unavailable")
        logger.info("Rotation fallback triggered reason=all_primary_matches_rejected faces=%d", len(plan))
        fallback_faces = fallback(payload)
        fallback_plan = [(detected, self._match_face(detected, workspace_id)) for detected in fallback_faces]
        fallback_accepted = self._plan_has_accepted_match(db, fallback_plan, workspace_id)
        logger.info(
            "Fallback recognition evaluated faces=%d accepted=%s",
            len(fallback_plan),
            fallback_accepted,
        )
        if fallback_accepted:
            return selected_plan("fallback", fallback_plan, reason="accepted_match")
        primary_score = max(
            (match.score if match.score is not None else -1.0 for _, match in plan),
            default=-1.0,
        )
        fallback_score = max(
            (match.score if match.score is not None else -1.0 for _, match in fallback_plan),
            default=-1.0,
        )
        use_fallback = bool(fallback_plan and fallback_score > primary_score)
        selection = fallback_plan if use_fallback else plan
        logger.info(
            "Recognition plan compared primary_score=%.4f fallback_score=%.4f",
            primary_score,
            fallback_score,
        )
        return selected_plan(
            "fallback" if use_fallback else "primary",
            selection,
            reason="higher_rejected_score",
        )

    def _plan_has_accepted_match(
        self,
        db: Session,
        plan: list[tuple[DetectedFace, PersonMatch]],
        workspace_id: int | None,
    ) -> bool:
        for _, match in plan:
            matched_person = None
            if match.person_id is not None:
                matched_person = db.scalar(
                    select(Person).where(Person.id == match.person_id, Person.workspace_id == workspace_id)
                )
            if self._evaluate_match(match, matched_person).accepted:
                return True
        return False

    def _is_confident_match(self, match: PersonMatch, matched_person: Person | None) -> bool:
        return self._evaluate_match(match, matched_person).accepted

    def _evaluate_match(self, match: PersonMatch, matched_person: Person | None) -> MatchDecision:
        if match.person_id is None or match.score is None:
            return MatchDecision(False, "no_candidate")
        if matched_person is None:
            return MatchDecision(False, "candidate_not_found")
        if match.score < self.settings.face_recognition_threshold:
            return MatchDecision(False, "below_threshold")
        if match.margin is not None and match.margin < self.settings.face_recognition_min_margin:
            return MatchDecision(False, "insufficient_margin")
        return MatchDecision(True, None)

    def _quality_warnings(self, detected: DetectedFace) -> list[str]:
        warnings: list[str] = []
        if detected.face_size < self.settings.face_sample_warning_size:
            warnings.append(f"人脸尺寸较小（{detected.face_size:.0f}px）")
        if detected.score is not None and detected.score < self.settings.face_sample_min_detection_score:
            warnings.append(f"检测置信度较低（{detected.score:.3f}）")
        if detected.blur_score is not None and detected.blur_score < self.settings.face_sample_blur_warning:
            warnings.append(f"图像可能模糊（{detected.blur_score:.1f}）")
        if detected.pose_yaw is not None and abs(detected.pose_yaw) > 35:
            warnings.append(f"侧脸角度较大（{detected.pose_yaw:.0f}°）")
        return warnings

    def _face_fields(
        self,
        detected: DetectedFace,
        match: PersonMatch | None = None,
        decision: MatchDecision | None = None,
    ) -> dict[str, object]:
        return {
            "bbox_left": detected.bbox[0],
            "bbox_top": detected.bbox[1],
            "bbox_right": detected.bbox[2],
            "bbox_bottom": detected.bbox[3],
            "detection_score": detected.score,
            "predicted_person_id": match.person_id if match else None,
            "second_person_id": match.second_person_id if match else None,
            "second_match_score": match.second_score if match else None,
            "match_margin": match.margin if match else None,
            "rejection_reason": decision.rejection_reason if decision else None,
            "recognition_adapter_id": self.settings.face_adapter_id,
            "decision_threshold": self.settings.face_recognition_threshold if match else None,
            "decision_min_margin": self.settings.face_recognition_min_margin if match else None,
            "embedding_version": self.settings.face_embedding_version,
            "face_size": detected.face_size,
            "blur_score": detected.blur_score,
            "pose_yaw": detected.pose_yaw,
        }

    @staticmethod
    def _is_preserved_person_tag_source(source: str) -> bool:
        return source in {"manual", "import", "import_unknown"}

    def _recompute_person_centroid(self, db: Session, person_id: int, workspace_id: int | None) -> None:
        face_ids = db.scalars(
            select(FaceRecord.id)
            .join(SamplePhoto, SamplePhoto.id == FaceRecord.sample_photo_id)
            .where(
                SamplePhoto.person_id == person_id,
                SamplePhoto.status == "ready",
                FaceRecord.vector_collection == "known",
            )
        ).all()
        vectors = [
            vector
            for face_id in face_ids
            if (vector := self.vector_store.get_face_vector(self.settings.qdrant_known_collection, face_id)) is not None
        ]
        if not vectors:
            self.vector_store.delete_centroid(
                self.settings.qdrant_known_collection,
                workspace_id,
                person_id,
                self.settings.face_embedding_version,
            )
            return
        centroid = np.mean(np.stack(vectors), axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        self.vector_store.upsert_centroid(
            self.settings.qdrant_known_collection,
            person_id,
            centroid,
            workspace_id=workspace_id,
            embedding_version=self.settings.face_embedding_version,
        )

    def _unknown_person_internal_name(self, workspace_id: int | None) -> str:
        workspace_key = "global" if workspace_id is None else str(workspace_id)
        return f"__system_unknown_person__:{workspace_key}"

    def _build_object_key(self, workspace_id: int | None, prefix: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        tenant_prefix = f"workspaces/{workspace_id}/" if workspace_id is not None else ""
        return f"{tenant_prefix}{prefix}/{uuid4().hex}{suffix}"

    def find_or_create_tag(self, db: Session, name: str, workspace_id: int | None) -> Tag:
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

    def ensure_gallery_person_tag(self, db: Session, gallery_photo_id: int, person_id: int, source: str) -> None:
        existing = db.scalar(
            select(GalleryPhotoPersonTag).where(
                GalleryPhotoPersonTag.gallery_photo_id == gallery_photo_id,
                GalleryPhotoPersonTag.person_id == person_id,
            )
        )
        if existing is None:
            db.add(GalleryPhotoPersonTag(gallery_photo_id=gallery_photo_id, person_id=person_id, source=source))
            return
        source_priority = {"unknown": 0, "auto": 0, "import_unknown": 1, "import": 1, "manual": 2}
        if source_priority.get(source, 0) > source_priority.get(existing.source, 0):
            existing.source = source

    def ensure_gallery_tag(self, db: Session, gallery_photo_id: int, tag: Tag, source: str = "manual") -> None:
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

    def apply_person_tags_to_gallery_photo(self, db: Session, gallery_photo_id: int, person_id: int) -> None:
        links = db.scalars(select(PersonTag).where(PersonTag.person_id == person_id)).all()
        for link in links:
            link.tag
            self.ensure_gallery_tag(db, gallery_photo_id, link.tag, source="person")

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

    def is_singleton_unknown_person(self, person: Person) -> bool:
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

    def add_person_samples(
        self,
        db: Session,
        person: Person,
        uploads: list[tuple[str, bytes, str | None]],
        *,
        source_gallery_photo_id: int | None = None,
        prepared_faces: list[list[DetectedFace] | None] | None = None,
    ) -> list[SamplePhoto]:
        if person.is_unknown:
            raise ValueError("系统未知人物不能上传样本图")
        logger.info("Start add_person_samples person_id=%s uploads=%d", person.id, len(uploads))
        sample_photos: list[SamplePhoto] = []
        if prepared_faces is not None and len(prepared_faces) != len(uploads):
            raise ValueError("预检测人脸结果与上传文件数量不一致")
        for upload_index, (filename, payload, content_type) in enumerate(uploads):
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
                source_type="gallery_face" if source_gallery_photo_id is not None else "upload",
                source_gallery_photo_id=source_gallery_photo_id,
            )
            db.add(sample)
            db.flush()

            detected_faces = prepared_faces[upload_index] if prepared_faces is not None else None
            if detected_faces is None:
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
            if detected.face_size < self.settings.face_sample_min_size:
                sample.status = "low_quality"
                sample.quality_status = "rejected"
                sample.error_message = f"人脸尺寸过小（{detected.face_size:.0f}px，最低 {self.settings.face_sample_min_size}px）"
                sample_photos.append(sample)
                continue
            warnings = self._quality_warnings(detected)
            sample.quality_status = "warning" if warnings else "good"
            sample.quality_warnings = json.dumps(warnings, ensure_ascii=False) if warnings else None
            face = FaceRecord(
                workspace_id=person.workspace_id,
                sample_photo_id=sample.id,
                matched_person_id=person.id,
                match_score=1.0,
                needs_review=False,
                vector_collection="known",
                **self._face_fields(detected),
            )
            db.add(face)
            db.flush()
            self.vector_store.upsert_face(
                self.settings.qdrant_known_collection,
                face.id,
                person.id,
                detected.embedding,
                workspace_id=person.workspace_id,
                sample_photo_id=sample.id,
                embedding_version=self.settings.face_embedding_version,
            )
            logger.info(
                "Sample indexed to known collection person_id=%s sample_id=%s face_id=%s collection=%s",
                person.id,
                sample.id,
                face.id,
                self.settings.qdrant_known_collection,
            )
            sample.status = "ready"
            sample_photos.append(sample)

        db.flush()
        if any(item.status == "ready" for item in sample_photos):
            self._recompute_person_centroid(db, person.id, person.workspace_id)

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
        source_object_key: str | None = None,
        *,
        ingest_source: str = "manual_upload",
        recognition_plan: list[tuple[DetectedFace, PersonMatch]] | None | object = _RECOGNITION_NOT_PRECOMPUTED,
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
            select(GalleryPhoto).where(
                GalleryPhoto.workspace_id == workspace_id,
                GalleryPhoto.sha256 == sha256,
                GalleryPhoto.is_rich_text == is_rich_text,
            )
        )
        if existing is not None:
            summary.duplicated = 1
            logger.info(
                "Gallery duplicate skipped filename=%s sha256=%s rich_text=%s existing_photo_id=%s",
                filename,
                sha256,
                is_rich_text,
                existing.id,
            )
            return existing, summary

        width, height, taken_at = parse_image_metadata(payload)
        object_key = self._build_object_key(workspace_id, "gallery", filename)
        if source_object_key:
            self.storage.copy_object(object_key, source_object_key)
        else:
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
            ingest_source=ingest_source,
            rich_text=rich_text.strip() if rich_text else None,
            ocr_status="manual" if rich_text and rich_text.strip() else None,
        )
        db.add(photo)
        db.flush()

        if is_rich_text:
            rich_tag = self.find_or_create_tag(db, self.rich_text_tag_name, workspace_id)
            rich_tag.is_system = True
            self.ensure_gallery_tag(db, photo.id, rich_tag, source="system")
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
            tag = self.find_or_create_tag(db, tag_name, workspace_id)
            self.ensure_gallery_tag(db, photo.id, tag, source="manual")
        if tag_names:
            logger.info("Gallery manual tags applied photo_id=%s tags=%d", photo.id, len(tag_names))

        if recognition_plan is _RECOGNITION_NOT_PRECOMPUTED:
            try:
                recognition_plan = self._recognition_plan(db, payload, workspace_id)
            except Exception:
                logger.exception(
                    "Gallery face detection failed, keep photo without faces photo_id=%s filename=%s",
                    photo.id,
                    filename,
                )
                recognition_plan = None
        if recognition_plan is None:
            db.commit()
            db.refresh(photo)
            return photo, summary
        logger.info(
            "Gallery face detection result photo_id=%s filename=%s faces=%d",
            photo.id,
            filename,
            len(recognition_plan),
        )
        for detected, match in recognition_plan:
            try:
                with db.begin_nested():
                    matched_person = None
                    if match.person_id is not None:
                        matched_person = db.scalar(select(Person).where(Person.id == match.person_id, Person.workspace_id == workspace_id))
                    decision = self._evaluate_match(match, matched_person)
                    if decision.accepted:
                        face = FaceRecord(
                            workspace_id=workspace_id,
                            gallery_photo_id=photo.id,
                            matched_person_id=matched_person.id,
                            match_score=match.score,
                            needs_review=False,
                            vector_collection=None,
                            **self._face_fields(detected, match, decision),
                        )
                        db.add(face)
                        db.flush()
                        self.ensure_gallery_person_tag(db, photo.id, matched_person.id, "auto")
                        self.apply_person_tags_to_gallery_photo(db, photo.id, matched_person.id)
                        summary.known_matches += 1
                        logger.info(
                            "Gallery known face matched photo_id=%s face_id=%s person_id=%s score=%.4f",
                            photo.id,
                            face.id,
                            matched_person.id,
                            match.score,
                        )
                        continue

                    person = self.get_or_create_unknown_person(db, workspace_id)
                    summary.unknown_faces += 1
                    logger.info(
                        "Gallery unknown face tagged photo_id=%s person_id=%s matched_score=%s",
                        photo.id,
                        person.id,
                        f"{match.score:.4f}" if match.score is not None else "None",
                    )

                    face = FaceRecord(
                        workspace_id=workspace_id,
                        gallery_photo_id=photo.id,
                        matched_person_id=person.id,
                        match_score=match.score,
                        needs_review=True,
                        vector_collection=None,
                        **self._face_fields(detected, match, decision),
                    )
                    db.add(face)
                    db.flush()
                    self.ensure_gallery_person_tag(db, photo.id, person.id, "unknown")
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

    def prepare_gallery_recognition(
        self,
        db: Session,
        payload: bytes,
        workspace_id: int,
    ) -> list[tuple[DetectedFace, PersonMatch]]:
        return self._recognition_plan(db, payload, workspace_id)

    def rename_person(self, db: Session, person: Person, new_name: str) -> Person:
        if self.is_singleton_unknown_person(person):
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
        workspace_id = sample_photo.workspace_id
        person_id = sample_photo.person_id
        face_ids = [face.id for face in sample_photo.faces if face.vector_collection == "known"]
        self.vector_store.delete_faces(self.settings.qdrant_known_collection, face_ids)
        object_key = sample_photo.object_key
        db.delete(sample_photo)
        db.flush()
        self._recompute_person_centroid(db, person_id, workspace_id)
        db.commit()
        self.storage.remove_object(object_key)
        logger.info(
            "Delete sample photo sample_id=%s person_id=%s known_faces_deleted=%d",
            sample_photo.id,
            sample_photo.person_id,
            len(face_ids),
        )

    def delete_gallery_photos(self, db: Session, photos: list[GalleryPhoto]) -> int:
        from app.services.similarity import cleanup_deleted_similarity_photos, mark_similarity_scans_stale

        deleted = 0
        photo_ids = [photo.id for photo in photos]
        workspace_ids = {int(photo.workspace_id) for photo in photos if photo.workspace_id is not None}
        cleanup_deleted_similarity_photos(db, self.vector_store, photo_ids)
        for workspace_id in workspace_ids:
            mark_similarity_scans_stale(db, workspace_id)
        for photo in photos:
            self.storage.remove_object(animated_thumbnail_cache_key(photo.workspace_id, photo.id, photo.sha256))
            self.storage.remove_object(photo.object_key)
            db.delete(photo)
            deleted += 1
            logger.info("Delete gallery photo photo_id=%s", photo.id)
        db.commit()
        return deleted

    def delete_persons(self, db: Session, persons: list[Person]) -> int:
        deleted = 0
        for person in persons:
            if self.is_singleton_unknown_person(person):
                logger.info("Skip deleting singleton unknown person person_id=%s", person.id)
                continue
            known_face_ids = [face.id for face in person.faces if face.vector_collection == "known"]
            self.vector_store.delete_faces(self.settings.qdrant_known_collection, known_face_ids)
            self.vector_store.delete_centroid(
                self.settings.qdrant_known_collection,
                person.workspace_id,
                person.id,
                self.settings.face_embedding_version,
            )
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
        if face.matched_person_id != person.id:
            db.add(FaceRecognitionCorrection(
                workspace_id=face.workspace_id,
                gallery_photo_id=face.gallery_photo_id,
                face_record_id=face.id,
                predicted_person_id=face.predicted_person_id,
                predicted_score=face.match_score,
                second_person_id=face.second_person_id,
                second_score=face.second_match_score,
                corrected_person_id=person.id,
                embedding_version=face.embedding_version or self.settings.face_embedding_version,
                promoted_to_sample=False,
            ))
        face.vector_collection = None
        face.matched_person_id = person.id
        face.needs_review = False
        if face.gallery_photo_id is not None:
            db.flush()
            self._remove_unknown_person_tag_if_resolved(db, face.gallery_photo_id, face.workspace_id)
        logger.info(
            "Confirmed gallery face as known face_id=%s photo_id=%s person_id=%s previous_collection=%s",
            face.id,
            face.gallery_photo_id,
            person.id,
            previous_collection,
        )

    @staticmethod
    def _square_face_crop_box(face: FaceRecord, image_width: int, image_height: int, factor: float) -> tuple[int, int, int, int]:
        face_width = max(1.0, float(face.bbox_right - face.bbox_left))
        face_height = max(1.0, float(face.bbox_bottom - face.bbox_top))
        side = max(1, min(int(round(max(face_width, face_height) * factor)), image_width, image_height))
        center_x = (float(face.bbox_left) + float(face.bbox_right)) / 2
        center_y = (float(face.bbox_top) + float(face.bbox_bottom)) / 2
        left = min(max(0, int(round(center_x - side / 2))), image_width - side)
        top = min(max(0, int(round(center_y - side / 2))), image_height - side)
        return left, top, left + side, top + side

    @staticmethod
    def _apply_exif_orientation(image: Image.Image, orientation: int) -> Image.Image:
        operations = {
            2: Image.Transpose.FLIP_LEFT_RIGHT,
            3: Image.Transpose.ROTATE_180,
            4: Image.Transpose.FLIP_TOP_BOTTOM,
            5: Image.Transpose.TRANSPOSE,
            6: Image.Transpose.ROTATE_270,
            7: Image.Transpose.TRANSVERSE,
            8: Image.Transpose.ROTATE_90,
        }
        operation = operations.get(orientation)
        return image.transpose(operation) if operation is not None else image

    def _gallery_face_crop(self, payload: bytes, face: FaceRecord, factor: float) -> bytes:
        source = Image.open(BytesIO(payload))
        orientation = int(source.getexif().get(274, 1))
        image = source.convert("RGB")
        box = self._square_face_crop_box(face, image.width, image.height, factor)
        crop = self._apply_exif_orientation(image.crop(box), orientation)
        buffer = BytesIO()
        crop.save(buffer, format="JPEG", quality=95)
        return buffer.getvalue()

    def promote_gallery_face_to_sample(self, db: Session, photo: GalleryPhoto, face: FaceRecord, person: Person) -> SamplePhoto:
        existing = db.scalar(
            select(SamplePhoto).where(
                SamplePhoto.person_id == person.id,
                SamplePhoto.source_gallery_photo_id == photo.id,
            )
        )
        if existing is not None:
            raise ValueError("该图片已经加入过此人物的样本库")
        payload = self.storage.get_bytes(photo.object_key)
        crop_payload: bytes | None = None
        detected_faces: list[DetectedFace] = []
        for factor in (2.0, 3.0):
            candidate_payload = self._gallery_face_crop(payload, face, factor)
            try:
                candidate_faces = self.face_service.detect_faces(candidate_payload)
            except Exception as exc:
                raise ValueError(f"人脸检测失败：{exc}") from exc
            if len(candidate_faces) == 0:
                continue
            if len(candidate_faces) != 1:
                raise ValueError(f"扩大裁剪后检测到 {len(candidate_faces)} 张人脸，仅支持单人样本")
            crop_payload = candidate_payload
            detected_faces = candidate_faces
            break
        if crop_payload is None:
            raise ValueError("按人脸区域扩大裁剪后仍未检测到人脸（已尝试约 2 倍和 3 倍范围）")
        if detected_faces[0].face_size < self.settings.face_sample_min_size:
            raise ValueError(
                f"人脸尺寸过小（{detected_faces[0].face_size:.0f}px，最低 {self.settings.face_sample_min_size}px）"
            )
        samples = self.add_person_samples(
            db,
            person,
            [(f"gallery-{photo.id}-face.jpg", crop_payload, "image/jpeg")],
            source_gallery_photo_id=photo.id,
            prepared_faces=[detected_faces],
        )
        if not samples:
            raise ValueError("相同的人脸样本已经存在")
        sample = samples[0]
        if sample.status != "ready":
            error = sample.error_message or sample.status
            self.delete_sample_photo(db, sample)
            raise ValueError(error)
        correction = db.scalar(
            select(FaceRecognitionCorrection)
            .where(FaceRecognitionCorrection.face_record_id == face.id)
            .order_by(FaceRecognitionCorrection.id.desc())
        )
        if correction is not None:
            correction.promoted_to_sample = True
            db.add(correction)
            db.commit()
        return sample

    def bind_person_tag(self, db: Session, person: Person, tag: Tag) -> None:
        if self.is_singleton_unknown_person(person):
            raise ValueError("系统未知人物不能维护普通标签")
        self._ensure_person_tag(db, person.id, tag)
        photo_ids = db.scalars(
            select(GalleryPhotoPersonTag.gallery_photo_id).where(GalleryPhotoPersonTag.person_id == person.id)
        ).all()
        for photo_id in photo_ids:
            self.ensure_gallery_tag(db, photo_id, tag, source="person")
        db.commit()
        logger.info(
            "Bound person tag person_id=%s tag_id=%s affected_gallery_photos=%d",
            person.id,
            tag.id,
            len(photo_ids),
        )

    def unbind_person_tag(self, db: Session, person: Person, tag_id: int) -> None:
        if self.is_singleton_unknown_person(person):
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

    def re_recognize_gallery_photo(self, db: Session, photo: GalleryPhoto, *, commit: bool = True) -> GalleryPhoto:
        logger.info("Start re_recognize_gallery_photo photo_id=%s", photo.id)
        payload = self.storage.get_bytes(photo.object_key)
        recognition_plan = self._recognition_plan(db, payload, photo.workspace_id)
        old_person_ids = {tag.person_id for tag in photo.person_tags}
        preserved_person_links = [
            (tag.person_id, tag.source)
            for tag in photo.person_tags
            if self._is_preserved_person_tag_source(tag.source)
        ]
        old_auto_links = [
            tag for tag in photo.person_tags if not self._is_preserved_person_tag_source(tag.source)
        ]
        for link in old_auto_links:
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
            len(old_auto_links),
            len(old_person_gallery_tags),
        )
        for face in photo.faces:
            db.delete(face)
        db.flush()

        summary = GalleryImportSummary()
        logger.info("Re-recognize detection result photo_id=%s faces=%d", photo.id, len(recognition_plan))
        for detected, match in recognition_plan:
            try:
                with db.begin_nested():
                    matched_person_id, matched_score = match.person_id, match.score
                    matched_person = None
                    if matched_person_id is not None:
                        matched_person = db.scalar(
                            select(Person).where(Person.id == matched_person_id, Person.workspace_id == photo.workspace_id)
                        )
                    decision = self._evaluate_match(match, matched_person)
                    if decision.accepted:
                        face = FaceRecord(
                            workspace_id=photo.workspace_id,
                            gallery_photo_id=photo.id,
                            **self._face_fields(detected, match, decision),
                            matched_person_id=matched_person.id,
                            match_score=matched_score,
                            needs_review=False,
                            vector_collection=None,
                        )
                        db.add(face)
                        db.flush()
                        self.ensure_gallery_person_tag(db, photo.id, matched_person.id, "auto")
                        self.apply_person_tags_to_gallery_photo(db, photo.id, matched_person.id)
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
                        **self._face_fields(detected, match, decision),
                        matched_person_id=person.id,
                        match_score=matched_score,
                        needs_review=True,
                        vector_collection=None,
                    )
                    db.add(face)
                    db.flush()
                    self.ensure_gallery_person_tag(db, photo.id, person.id, "unknown")
                    logger.info(
                        "Re-recognize unknown face tagged photo_id=%s face_id=%s person_id=%s",
                        photo.id,
                        face.id,
                        person.id,
                    )
            except Exception:
                logger.exception("Re-recognize face process failed photo_id=%s", photo.id)
                raise

        for person_id, source in preserved_person_links:
            self.ensure_gallery_person_tag(db, photo.id, person_id, source)
            self.apply_person_tags_to_gallery_photo(db, photo.id, person_id)
        db.flush()
        new_person_ids = set(
            db.scalars(
                select(GalleryPhotoPersonTag.person_id).where(
                    GalleryPhotoPersonTag.gallery_photo_id == photo.id
                )
            ).all()
        )
        changed_person_ids = old_person_ids.symmetric_difference(new_person_ids)
        if changed_person_ids and photo.workspace_id is not None:
            from app.services.similarity import mark_similarity_scans_stale

            mark_similarity_scans_stale(db, int(photo.workspace_id), changed_person_ids)
        if commit:
            db.commit()
        else:
            db.flush()
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
        photo.recognition_summary = {
            "faces": len(recognition_plan),
            "known": summary.known_matches,
            "unknown": summary.unknown_faces,
            "manual_tags_preserved": sum(1 for _, source in preserved_person_links if source == "manual"),
            "import_tags_preserved": sum(1 for _, source in preserved_person_links if source.startswith("import")),
        }
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
                    tag = self.find_or_create_tag(db, tag_name.strip(), workspace_id)
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
                    if detected.face_size < self.settings.face_sample_min_size:
                        sample_photo.status = "low_quality"
                        sample_photo.quality_status = "rejected"
                        sample_photo.error_message = (
                            f"人脸尺寸过小（{detected.face_size:.0f}px，最低 {self.settings.face_sample_min_size}px）"
                        )
                        result["added_samples"] += 1
                        processed_samples += 1
                        if progress_callback:
                            progress_callback(processed_samples, total_samples)
                        continue
                    face = FaceRecord(
                        workspace_id=workspace_id,
                        sample_photo_id=sample_photo.id,
                        matched_person_id=person.id,
                        match_score=1.0,
                        needs_review=False,
                        vector_collection="known",
                        **self._face_fields(detected),
                    )
                    db.add(face)
                    db.flush()
                    self.vector_store.upsert_face(
                        self.settings.qdrant_known_collection,
                        face.id,
                        person.id,
                        detected.embedding,
                        workspace_id=workspace_id,
                        sample_photo_id=sample_photo.id,
                        embedding_version=self.settings.face_embedding_version,
                    )
                    sample_photo.status = "ready"
                    warnings = self._quality_warnings(detected)
                    sample_photo.quality_warnings = json.dumps(warnings, ensure_ascii=False) if warnings else None
                    sample_photo.quality_status = "warning" if warnings else "good"
                    result["added_samples"] += 1
                    processed_samples += 1
                    if progress_callback:
                        progress_callback(processed_samples, total_samples)

                db.flush()
                self._recompute_person_centroid(db, person.id, workspace_id)
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
            if not isinstance(manifest, dict) or manifest.get("kind") not in (None, "gallery_export"):
                raise ValueError("metadata.json 不是有效的展示图库清单")
            photos = manifest.get("photos", [])
            if not isinstance(photos, list):
                raise ValueError("metadata.json 格式不正确")

            version = manifest.get("version", 1)
            if version not in (1, 2):
                raise ValueError(f"不支持的展示图导出版本：{version}")
            if version == 2:
                indexes = [item.get("display_index") if isinstance(item, dict) else None for item in photos]
                if (
                    any(not isinstance(value, int) or isinstance(value, bool) for value in indexes)
                    or sorted(indexes) != list(range(len(photos)))
                ):
                    raise ValueError("版本 2 metadata.json 的 display_index 必须从 0 连续且不得重复")
                photos = sorted(photos, key=lambda item: item["display_index"])

            total = len(photos)
            display_batch_at = shanghai_now()
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

                payload_sha256 = hashlib.sha256(payload).hexdigest()
                declared_sha256 = str(photo_data.get("sha256") or "").strip().lower()
                if declared_sha256 and declared_sha256 != payload_sha256:
                    logger.warning(
                        "Gallery zip import skipped sha mismatch photo=%s declared=%s actual=%s",
                        photo_data.get("filename"),
                        declared_sha256,
                        payload_sha256,
                    )
                    result["skipped_photos"] += 1
                    if progress_callback:
                        progress_callback(index, total)
                    continue
                sha256 = declared_sha256 or payload_sha256
                is_rich_text = bool(photo_data.get("is_rich_text"))
                photo = db.scalar(
                    select(GalleryPhoto).where(
                        GalleryPhoto.workspace_id == workspace_id,
                        GalleryPhoto.sha256 == sha256,
                        GalleryPhoto.is_rich_text == is_rich_text,
                    )
                )
                is_existing = photo is not None
                raw_tags = photo_data.get("tags", [])
                raw_persons = photo_data.get("persons", [])
                if not isinstance(raw_tags, list) or not isinstance(raw_persons, list):
                    logger.warning("Gallery zip import skipped invalid manifest entry photo=%s", photo_data.get("filename"))
                    result["skipped_photos"] += 1
                    if progress_callback:
                        progress_callback(index, total)
                    continue
                tag_names = [
                    str(name).strip()
                    for name in raw_tags
                    if str(name).strip() and str(name).strip() != self.rich_text_tag_name
                ]

                if photo is None:
                    filename = str(photo_data.get("filename") or Path(str(zip_paths[0])).name)
                    object_key = self._build_object_key(workspace_id, "gallery", filename)
                    self.storage.put_bytes(object_key, payload, photo_data.get("content_type"))
                    photo = GalleryPhoto(
                        workspace_id=workspace_id,
                        filename=filename,
                        content_type=photo_data.get("content_type"),
                        sha256=sha256,
                        object_key=object_key,
                        width=photo_data.get("width"),
                        height=photo_data.get("height"),
                        is_rich_text=is_rich_text,
                        ingest_source="gallery_zip",
                    )
                    db.add(photo)
                    db.flush()
                    result["added_photos"] += 1
                else:
                    result["updated_existing"] += 1

                taken_at = None
                if photo_data.get("taken_at"):
                    try:
                        taken_at = as_shanghai_naive(datetime.fromisoformat(str(photo_data["taken_at"])))
                    except (TypeError, ValueError):
                        logger.warning("Gallery zip import ignored invalid taken_at photo=%s", photo_data.get("filename"))
                photo.filename = str(photo_data.get("filename") or photo.filename)
                photo.content_type = photo_data.get("content_type")
                photo.width = photo_data.get("width")
                photo.height = photo_data.get("height")
                photo.taken_at = taken_at
                photo.is_rich_text = is_rich_text
                rich_text = photo_data.get("rich_text")
                photo.rich_text = str(rich_text) if rich_text is not None else None
                photo.ocr_status = str(photo_data["ocr_status"]) if photo_data.get("ocr_status") else None
                photo.display_batch_at = display_batch_at
                photo.display_index = index - 1

                db.execute(delete(FaceRecord).where(FaceRecord.gallery_photo_id == photo.id))
                db.execute(delete(GalleryPhotoPersonTag).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id))
                db.execute(delete(GalleryPhotoTag).where(GalleryPhotoTag.gallery_photo_id == photo.id))
                db.flush()

                if is_rich_text:
                    rich_tag = self.find_or_create_tag(db, self.rich_text_tag_name, workspace_id)
                    rich_tag.is_system = True
                    self.ensure_gallery_tag(db, photo.id, rich_tag, source="system")

                for tag_name in tag_names:
                    tag = self.find_or_create_tag(db, tag_name, workspace_id)
                    existing_tag_link = db.scalar(
                        select(GalleryPhotoTag).where(
                            GalleryPhotoTag.gallery_photo_id == photo.id,
                            GalleryPhotoTag.tag_id == tag.id,
                        )
                    )
                    self.ensure_gallery_tag(db, photo.id, tag, source="manual")
                    if existing_tag_link is None:
                        result["tags_added"] += 1

                for person_data in raw_persons:
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
                    source = "import_unknown" if person.is_unknown else "import"
                    self.ensure_gallery_person_tag(db, photo.id, person.id, source)
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
