from __future__ import annotations

from app.mappers.gallery import gallery_photo_to_list_item
from app.models import GalleryPhoto


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
