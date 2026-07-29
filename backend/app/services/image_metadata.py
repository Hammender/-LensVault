from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps


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
