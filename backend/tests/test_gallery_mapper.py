from __future__ import annotations

from datetime import datetime

from app.mappers.gallery import gallery_photo_to_detail, gallery_photo_to_list_item
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person, SamplePhoto


def make_gallery_photo(photo_id: int, sha256: str) -> GalleryPhoto:
    return GalleryPhoto(
        id=photo_id,
        filename="photo.jpg",
        sha256=sha256,
        object_key=f"gallery/{sha256}.jpg",
        size_bytes=1024,
        is_rich_text=False,
        display_index=0,
        person_tags=[],
        tags=[],
        promoted_samples=[],
        created_at=datetime.now(),
    )


def test_gallery_media_urls_include_content_version() -> None:
    sha256 = "a" * 64

    item = gallery_photo_to_list_item(make_gallery_photo(42, sha256))

    assert item.thumbnail_url == f"/api/gallery/photos/42/thumbnail?v={sha256}"
    assert item.animated_thumbnail_url == f"/api/gallery/photos/42/animated-thumbnail?v={sha256}"
    assert item.original_url == f"/api/gallery/photos/42/original?v={sha256}"
    assert item.size_bytes == 1024


def test_gallery_thumbnail_url_changes_when_photo_id_is_reused() -> None:
    old_item = gallery_photo_to_list_item(make_gallery_photo(42, "a" * 64))
    replacement_item = gallery_photo_to_list_item(make_gallery_photo(42, "b" * 64))

    assert old_item.thumbnail_url != replacement_item.thumbnail_url
    assert old_item.animated_thumbnail_url != replacement_item.animated_thumbnail_url
    assert old_item.original_url != replacement_item.original_url


def test_gallery_detail_orders_faces_and_maps_exact_promoted_face() -> None:
    photo = make_gallery_photo(42, "a" * 64)
    photo.width = 1200
    photo.height = 800
    photo.faces = [
        FaceRecord(id=9, bbox_left=500, bbox_top=300, bbox_right=600, bbox_bottom=400, needs_review=False),
        FaceRecord(id=4, bbox_left=100, bbox_top=100, bbox_right=200, bbox_bottom=200, needs_review=True),
    ]
    photo.promoted_samples = [SamplePhoto(id=77, person_id=5, status="ready", source_gallery_face_id=9)]

    detail = gallery_photo_to_detail(photo, (800, 1200))

    assert detail.display_width == 800
    assert detail.display_height == 1200
    assert [face.id for face in detail.faces] == [4, 9]
    assert [face.face_index for face in detail.faces] == [1, 2]
    assert detail.faces[0].promoted_sample_id is None
    assert detail.faces[1].promoted_sample_id == 77


def test_gallery_detail_binding_source_uses_person_tag_not_prediction_mismatch() -> None:
    photo = make_gallery_photo(42, "a" * 64)
    bound = Person(id=16, name="ning", display_name="宁艺卓", is_unknown=False)
    unknown = Person(id=1, name="unknown", display_name="未知人物", is_unknown=True)
    confirmed = FaceRecord(
        id=4,
        bbox_left=100,
        bbox_top=100,
        bbox_right=200,
        bbox_bottom=200,
        matched_person_id=16,
        needs_review=False,
    )
    confirmed.matched_person = bound
    pending = FaceRecord(
        id=9,
        bbox_left=500,
        bbox_top=300,
        bbox_right=600,
        bbox_bottom=400,
        matched_person_id=1,
        needs_review=True,
    )
    pending.matched_person = unknown
    photo.faces = [confirmed, pending]
    photo.person_tags = [
        GalleryPhotoPersonTag(person_id=16, source="face_manual", person=bound),
        GalleryPhotoPersonTag(person_id=1, source="unknown", person=unknown),
    ]

    detail = gallery_photo_to_detail(photo)

    by_id = {face.id: face for face in detail.faces}
    assert by_id[4].binding_source == "manual"
    assert by_id[9].binding_source == "unknown"
