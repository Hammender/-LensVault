from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, ImageSequence


ANIMATED_THUMBNAIL_MAX_EDGE = 720


@dataclass(frozen=True)
class RenderedGalleryThumbnail:
    payload: bytes
    media_type: str
    is_animated: bool


@dataclass(frozen=True)
class RenderedAcquisitionPreview:
    payload: bytes
    media_type: str


def animated_thumbnail_cache_key(
    workspace_id: int | None,
    photo_id: int,
    sha256: str,
) -> str:
    workspace_key = str(workspace_id) if workspace_id is not None else "shared"
    return f"derived/gallery-thumbnails/{workspace_key}/{photo_id}-{sha256}-720.webp"


def render_gallery_thumbnail(payload: bytes) -> RenderedGalleryThumbnail:
    """生成最大边长 720px 的图库预览，并在存在多帧时保留动画。"""
    with Image.open(BytesIO(payload)) as source:
        frame_count = getattr(source, "n_frames", 1)
        if not getattr(source, "is_animated", False) or frame_count <= 1:
            image = source.convert("RGB")
            image.thumbnail((ANIMATED_THUMBNAIL_MAX_EDGE, ANIMATED_THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=92)
            return RenderedGalleryThumbnail(output.getvalue(), "image/jpeg", False)

        frames: list[Image.Image] = []
        durations: list[int] = []
        default_duration = int(source.info.get("duration", 100))
        loop = int(source.info.get("loop", 0))
        for frame in ImageSequence.Iterator(source):
            rendered = frame.convert("RGBA")
            rendered.thumbnail((ANIMATED_THUMBNAIL_MAX_EDGE, ANIMATED_THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
            frames.append(rendered)
            durations.append(int(frame.info.get("duration", default_duration)))

        output = BytesIO()
        frames[0].save(
            output,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            quality=85,
            method=4,
        )
        return RenderedGalleryThumbnail(output.getvalue(), "image/webp", True)


def render_acquisition_preview(
    payload: bytes,
    max_edge: int,
) -> RenderedAcquisitionPreview:
    """按需生成采集列表缩略图；动图仅渲染首帧。"""
    with Image.open(BytesIO(payload)) as source:
        frame_count = getattr(source, "n_frames", 1)
        is_animated = bool(getattr(source, "is_animated", False) and frame_count > 1)
        if not is_animated:
            source.draft("RGB", (max_edge, max_edge))
        source.seek(0)
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        return RenderedAcquisitionPreview(output.getvalue(), "image/jpeg")
