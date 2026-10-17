from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GalleryPhotoPersonTag, Person, SamplePhoto
from app.schemas import PersonRead, SamplePhotoRead


def sample_photo_to_read(photo: SamplePhoto) -> SamplePhotoRead:
    return SamplePhotoRead(
        id=photo.id,
        filename=photo.filename,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        status=photo.status,
        error_message=photo.error_message,
        quality_status=photo.quality_status,
        quality_warnings=photo.quality_warnings,
        source_type=photo.source_type,
        source_gallery_photo_id=photo.source_gallery_photo_id,
        source_gallery_face_id=photo.source_gallery_face_id,
        thumbnail_url=f"/api/persons/{photo.person_id}/samples/{photo.id}/thumbnail",
        original_url=f"/api/persons/{photo.person_id}/samples/{photo.id}/original",
        created_at=photo.created_at,
    )


def person_to_read(db: Session, person: Person) -> PersonRead:
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
        tag_ids=sorted(link.tag_id for link in person.labels),
        created_at=person.created_at,
    )
