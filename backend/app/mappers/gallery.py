from __future__ import annotations

from app.services.provenance import source_summary
from app.services.face_case_snapshots import face_revision, recognition_key

from app.models import FaceRecord, GalleryPhoto
from app.schemas import FaceRead, GalleryPersonTagRead, GalleryPhotoDetail, GalleryPhotoListItem, GalleryTagRead


def _face_binding_source(face: FaceRecord, person_tag_sources: dict[int, str]) -> str:
    person = face.matched_person
    if person is not None and person.is_unknown:
        return "unknown"
    if person is not None and person_tag_sources.get(face.matched_person_id) == "face_manual":
        return "manual"
    return "auto"


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
        source_summary=source_summary(photo),
        id=photo.id,
        filename=photo.filename,
        size_bytes=photo.size_bytes,
        width=photo.width,
        height=photo.height,
        taken_at=photo.taken_at,
        is_rich_text=photo.is_rich_text,
        rich_text=photo.rich_text,
        ocr_status=photo.ocr_status,
        persons=persons,
        tags=tags,
        thumbnail_url=f"/api/gallery/photos/{photo.id}/thumbnail?v={photo.sha256}",
        animated_thumbnail_url=f"/api/gallery/photos/{photo.id}/animated-thumbnail?v={photo.sha256}",
        original_url=f"/api/gallery/photos/{photo.id}/original?v={photo.sha256}",
    )


def gallery_photo_to_detail(
    photo: GalleryPhoto,
    display_size: tuple[int, int] | None = None,
) -> GalleryPhotoDetail:
    item = gallery_photo_to_list_item(photo)
    promoted_by_face = {
        sample.source_gallery_face_id: sample.id
        for sample in getattr(photo, "promoted_samples", [])
        if sample.status == "ready" and sample.source_gallery_face_id is not None
    }
    ordered_faces = sorted(
        photo.faces,
        key=lambda face: (float(face.bbox_top), float(face.bbox_left), face.id),
    )
    person_tag_sources = {tag.person_id: tag.source for tag in photo.person_tags}
    faces = [
        FaceRead(
            id=face.id,
            face_revision=face_revision(face),
            recognition_case_id=getattr(photo, "_recognition_cases", {}).get(recognition_key(face)),
            face_index=index,
            bbox_left=face.bbox_left,
            bbox_top=face.bbox_top,
            bbox_right=face.bbox_right,
            bbox_bottom=face.bbox_bottom,
            matched_person_id=face.matched_person_id,
            matched_person_name=face.matched_person.display_name if face.matched_person else None,
            matched_person_is_unknown=bool(face.matched_person and face.matched_person.is_unknown),
            binding_source=_face_binding_source(face, person_tag_sources),
            predicted_person_id=face.predicted_person_id,
            predicted_person_name=face.predicted_person.display_name if face.predicted_person else None,
            match_score=face.match_score,
            predicted_match_source=face.predicted_match_source,
            predicted_sample_photo_id=face.predicted_sample_photo_id,
            second_person_id=face.second_person_id,
            second_person_name=face.second_person.display_name if face.second_person else None,
            second_match_score=face.second_match_score,
            second_match_source=face.second_match_source,
            second_sample_photo_id=face.second_sample_photo_id,
            match_margin=face.match_margin,
            rejection_reason=face.rejection_reason,
            recognition_adapter_id=face.recognition_adapter_id,
            decision_threshold=face.decision_threshold,
            decision_min_margin=face.decision_min_margin,
            embedding_version=face.embedding_version,
            face_size=face.face_size,
            blur_score=face.blur_score,
            pose_yaw=face.pose_yaw,
            needs_review=face.needs_review,
            vector_collection=face.vector_collection,
            promoted_sample_id=promoted_by_face.get(face.id),
        )
        for index, face in enumerate(ordered_faces, start=1)
    ]
    return GalleryPhotoDetail(
        **item.model_dump(),
        faces=faces,
        display_width=display_size[0] if display_size else photo.width,
        display_height=display_size[1] if display_size else photo.height,
        created_at=photo.created_at,
        content_type=photo.content_type,
        recognition_summary=getattr(photo, "recognition_summary", None),
    )
