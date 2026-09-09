from __future__ import annotations

import argparse
from collections import defaultdict
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, SamplePhoto
from app.services.storage import MinioStorage
from app.tools.analyze_face_migration_audit import _match_faces


def _crop(payload: bytes, bbox: list[float] | tuple[float, ...] | None) -> Image.Image:
    with Image.open(BytesIO(payload)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if bbox is None:
        return image
    left, top, right, bottom = bbox
    pad = max(right - left, bottom - top) * 0.25
    return image.crop((
        max(0, int(left - pad)),
        max(0, int(top - pad)),
        min(image.width, int(right + pad)),
        min(image.height, int(bottom + pad)),
    ))


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    image.thumbnail((size[0] - 8, size[1] - 8), Image.Resampling.LANCZOS)
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="为全图库预演中的已知人物变化生成逐项人工对照表。")
    parser.add_argument("--audit-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    latest: dict[int, dict[str, object]] = {}
    for line in args.audit_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[int(row["gallery_photo_id"])] = row

    cases: list[dict[str, object]] = []
    for photo_id, row in sorted(latest.items()):
        if row.get("status") != "success":
            continue
        before = row["before"]
        after = row["after"]
        before_unknown_ids = {
            tag["person_id"] for tag in before["person_tags"] if tag["source"] == "unknown"
        }
        after_unknown_ids = {
            tag["person_id"] for tag in after["person_tags"] if tag["source"] == "unknown"
        }
        matches, _removed, _added = _match_faces(before["faces"], after["faces"])
        for old, new in matches:
            old_person_id = old.get("matched_person_id")
            new_person_id = new.get("matched_person_id")
            if (
                old_person_id is None
                or new_person_id is None
                or old_person_id == new_person_id
                or old_person_id in before_unknown_ids
                or new_person_id in after_unknown_ids
                or old.get("needs_review")
                or new.get("needs_review")
            ):
                continue
            cases.append({
                "case_id": len(cases) + 1,
                "gallery_photo_id": photo_id,
                "bbox": new["bbox"],
                "old_person_id": old_person_id,
                "new_person_id": new_person_id,
                "new_score": new.get("score"),
                "new_margin": new.get("margin"),
                "verdict": None,
                "review_note": None,
            })

    person_ids = {
        int(case[key]) for case in cases for key in ("old_person_id", "new_person_id")
    }
    photo_ids = {int(case["gallery_photo_id"]) for case in cases}
    with SessionLocal() as db:
        photos = {
            photo.id: photo for photo in db.scalars(
                select(GalleryPhoto).where(GalleryPhoto.id.in_(photo_ids))
            ).all()
        }
        samples = db.scalars(
            select(SamplePhoto).where(
                SamplePhoto.person_id.in_(person_ids), SamplePhoto.status == "ready"
            ).order_by(SamplePhoto.person_id, SamplePhoto.id)
        ).all()
        samples_by_person: dict[int, list[tuple[SamplePhoto, FaceRecord | None]]] = defaultdict(list)
        for sample in samples:
            sample_face = db.scalar(
                select(FaceRecord).where(FaceRecord.sample_photo_id == sample.id).order_by(FaceRecord.id)
            )
            samples_by_person[sample.person_id].append((sample, sample_face))

    args.output.mkdir(parents=True, exist_ok=True)
    storage = MinioStorage(get_settings())
    payloads: dict[str, bytes] = {}

    def payload(key: str) -> bytes:
        if key not in payloads:
            payloads[key] = storage.get_bytes(key)
        return payloads[key]

    tile_size = (220, 160)
    row_height = 194
    page_size = 8
    for page_index in range((len(cases) + page_size - 1) // page_size):
        page_cases = cases[page_index * page_size:(page_index + 1) * page_size]
        sheet = Image.new("RGB", (tile_size[0] * 5, row_height * len(page_cases)), "white")
        draw = ImageDraw.Draw(sheet)
        for row_index, case in enumerate(page_cases):
            photo = photos[int(case["gallery_photo_id"])]
            images = [_crop(payload(photo.object_key), case["bbox"])]
            for person_key in ("new_person_id", "new_person_id", "old_person_id", "old_person_id"):
                person_samples = samples_by_person.get(int(case[person_key]), [])
                sample_index = 0 if len(images) % 2 == 1 else 1
                if sample_index >= len(person_samples):
                    images.append(Image.new("RGB", tile_size, "#dddddd"))
                    continue
                sample, sample_face = person_samples[sample_index]
                bbox = None if sample_face is None else [
                    sample_face.bbox_left,
                    sample_face.bbox_top,
                    sample_face.bbox_right,
                    sample_face.bbox_bottom,
                ]
                images.append(_crop(payload(sample.object_key), bbox))
            y = row_index * row_height
            for column, image in enumerate(images):
                sheet.paste(_fit(image, tile_size), (column * tile_size[0], y + 30))
            draw.text(
                (4, y + 5),
                f"#{case['case_id']} photo={case['gallery_photo_id']} new={case['new_person_id']} "
                f"old={case['old_person_id']} score={float(case['new_score'] or 0):.3f} "
                f"margin={float(case['new_margin'] or 0):.3f}",
                fill="black",
            )
        sheet.save(args.output / f"known-change-{page_index + 1:02d}.jpg", quality=92)
    (args.output / "review-manifest.json").write_text(
        json.dumps({
            "columns": ["query", "new-1", "new-2", "old-1", "old-2"],
            "cases": cases,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "cases": len(cases),
        "pages": (len(cases) + page_size - 1) // page_size,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
