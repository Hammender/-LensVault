from __future__ import annotations

from app.models import GalleryPhoto
from app.schemas import FaceRead, GalleryPersonTagRead, GalleryPhotoDetail, GalleryPhotoListItem, GalleryTagRead


def gallery_photo_to_list_item(photo: GalleryPhoto) -> GalleryPhotoListItem:
    promoted_by_person = {
        sample.person_id: sample.id for sample in getattr(photo, "promoted_samples", []) if sample.status == "ready"
    }
    persons = [
        GalleryPersonTagRead(
            person_id=tag.person_id,
            person_name=tag.person.display_name,
            is_unknown=tag.person.is_unknown,
            source=tag.source,
            promoted_sample_id=promoted_by_person.get(tag.person_id),
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


def gallery_photo_to_detail(photo: GalleryPhoto) -> GalleryPhotoDetail:
    item = gallery_photo_to_list_item(photo)
    faces = [
        FaceRead(
            id=face.id,
            bbox_left=face.bbox_left,
            bbox_top=face.bbox_top,
            bbox_right=face.bbox_right,
            bbox_bottom=face.bbox_bottom,
            matched_person_id=face.matched_person_id,
            match_score=face.match_score,
            second_person_id=face.second_person_id,
            second_match_score=face.second_match_score,
            match_margin=face.match_margin,
            embedding_version=face.embedding_version,
            face_size=face.face_size,
            blur_score=face.blur_score,
            pose_yaw=face.pose_yaw,
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
        recognition_summary=getattr(photo, "recognition_summary", None),
    )
