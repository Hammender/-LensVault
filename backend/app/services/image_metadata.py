from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps


def load_rgb_image(payload: bytes) -> Image.Image:
    with Image.open(BytesIO(payload)) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def parse_image_metadata_from_image(image: Image.Image) -> tuple[int, int, datetime | None]:
    width, height = image.size
    taken_at = None
    try:
        exif = image.getexif()
        timestamp = exif.get(36867) or exif.get(306)
        if timestamp:
            taken_at = datetime.strptime(str(timestamp), "%Y:%m:%d %H:%M:%S")
    except Exception:
        taken_at = None
    return width, height, taken_at


def parse_image_metadata(payload: bytes) -> tuple[int, int, datetime | None]:
    image = load_rgb_image(payload)
    try:
        return parse_image_metadata_from_image(image)
    finally:
        image.close()
