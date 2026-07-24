from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.services.thumbnails import ANIMATED_THUMBNAIL_MAX_EDGE, animated_thumbnail_cache_key, render_gallery_thumbnail


def animated_image_bytes(image_format: str) -> bytes:
    frames = [
        Image.new("RGBA", (1600, 900), "#d84315"),
        Image.new("RGBA", (1600, 900), "#1565c0"),
    ]
    output = BytesIO()
    frames[0].save(
        output,
        format=image_format,
        save_all=True,
        append_images=frames[1:],
        duration=[120, 260],
        loop=2,
    )
    return output.getvalue()


def test_render_gallery_thumbnail_preserves_gif_animation() -> None:
    thumbnail = render_gallery_thumbnail(animated_image_bytes("GIF"))

    assert thumbnail.media_type == "image/webp"
    assert thumbnail.is_animated is True
    with Image.open(BytesIO(thumbnail.payload)) as image:
        assert image.is_animated is True
        assert image.n_frames == 2
        assert max(image.size) == ANIMATED_THUMBNAIL_MAX_EDGE
        assert image.info["loop"] == 2


def test_render_gallery_thumbnail_preserves_webp_animation() -> None:
    thumbnail = render_gallery_thumbnail(animated_image_bytes("WEBP"))

    assert thumbnail.media_type == "image/webp"
    with Image.open(BytesIO(thumbnail.payload)) as image:
        assert image.is_animated is True
        assert image.n_frames == 2
        assert max(image.size) == ANIMATED_THUMBNAIL_MAX_EDGE


def test_render_gallery_thumbnail_keeps_static_images_as_jpeg() -> None:
    source = BytesIO()
    Image.new("RGB", (1600, 900), "#2e7d32").save(source, format="PNG")

    thumbnail = render_gallery_thumbnail(source.getvalue())

    assert thumbnail.media_type == "image/jpeg"
    assert thumbnail.is_animated is False
    with Image.open(BytesIO(thumbnail.payload)) as image:
        assert image.format == "JPEG"
        assert max(image.size) == ANIMATED_THUMBNAIL_MAX_EDGE


def test_animated_thumbnail_cache_key_scopes_workspace_and_source() -> None:
    key = animated_thumbnail_cache_key(8, 42, "a" * 64)

    assert key == f"derived/gallery-thumbnails/8/42-{'a' * 64}-720.webp"
