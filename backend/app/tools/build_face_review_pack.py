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
from app.tools.calibrate_adaface_migration import _flip_rows


THRESHOLD = 0.395
MARGIN = 0.065


def _accepted(row: dict[str, object], threshold: float, margin: float) -> bool:
    return bool(
        row.get("score") is not None
        and float(row["score"]) >= threshold
        and (row.get("margin") is None or float(row["margin"]) >= margin)
    )


def _crop(payload: bytes, bbox: tuple[float, float, float, float] | None) -> Image.Image:
    with Image.open(BytesIO(payload)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if bbox is None:
        return image
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    pad = max(width, height) * 0.25
    box = (
        max(0, int(left - pad)),
        max(0, int(top - pad)),
        min(image.width, int(right + pad)),
        min(image.height, int(bottom + pad)),
    )
    return image.crop(box)


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    image.thumbnail((size[0] - 8, size[1] - 8), Image.Resampling.LANCZOS)
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 AdaFace 本地人工抽查联系表。")
    parser.add_argument("--adaface-report", type=Path, required=True)
    parser.add_argument("--buffalo-report", type=Path, required=True)
    parser.add_argument("--unknown-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adaface = {int(row["face_record_id"]): row for row in _flip_rows(args.adaface_report)}
    buffalo = {int(row["face_record_id"]): row for row in _flip_rows(args.buffalo_report)}
    unknown_report = json.loads(args.unknown_report.read_text(encoding="utf-8"))
    unknown_rows = list(unknown_report["details"][0]["rows"])
    all_face_ids = sorted(set(adaface) | {int(row["old_face_record_id"]) for row in unknown_rows})
    with SessionLocal() as db:
        faces = {
            face.id: face for face in db.scalars(
                select(FaceRecord).where(FaceRecord.id.in_(all_face_ids))
            ).all()
        }
        photos = {
            photo.id: photo for photo in db.scalars(
                select(GalleryPhoto).where(
                    GalleryPhoto.id.in_({face.gallery_photo_id for face in faces.values() if face.gallery_photo_id})
                )
            ).all()
        }
        sample_rows = db.scalars(
            select(SamplePhoto).where(SamplePhoto.status == "ready").order_by(SamplePhoto.person_id, SamplePhoto.id)
        ).all()
        samples_by_person: dict[int, list[tuple[SamplePhoto, FaceRecord | None]]] = defaultdict(list)
        for sample in sample_rows:
            face = db.scalar(select(FaceRecord).where(FaceRecord.sample_photo_id == sample.id))
            samples_by_person[sample.person_id].append((sample, face))

    cases: list[dict[str, object]] = []
    used: set[tuple[str, int]] = set()

    def add_correction(category: str, predicate, limit: int) -> None:
        added = 0
        for face_id in sorted(adaface):
            row = adaface[face_id]
            baseline = buffalo.get(face_id)
            face = faces.get(face_id)
            if face is None or baseline is None or not predicate(row, baseline, face):
                continue
            key = ("correction", face_id)
            if key in used:
                continue
            used.add(key)
            cases.append({
                "source": "correction",
                "category": category,
                "face_record_id": face_id,
                "gallery_photo_id": row["gallery_photo_id"],
                "predicted_person_id": row["predicted_person_id"],
                "expected_person_id": row["corrected_person_id"],
                "score": row["score"],
                "margin": row["margin"],
            })
            added += 1
            if added >= limit:
                break

    add_correction(
        "wrong_identity",
        lambda row, _baseline, _face: _accepted(row, THRESHOLD, MARGIN)
        and row["predicted_person_id"] != row["corrected_person_id"],
        20,
    )
    add_correction(
        "newly_recovered",
        lambda row, baseline, _face: _accepted(row, THRESHOLD, MARGIN)
        and row["predicted_person_id"] == row["corrected_person_id"]
        and not (
            _accepted(baseline, 0.41, 0.039)
            and baseline["predicted_person_id"] == baseline["corrected_person_id"]
        ),
        25,
    )
    add_correction(
        "small_face",
        lambda row, _baseline, face: face.face_size is not None and face.face_size < 80
        and _accepted(row, THRESHOLD, MARGIN),
        20,
    )
    add_correction(
        "blur_or_profile",
        lambda row, _baseline, face: _accepted(row, THRESHOLD, MARGIN)
        and (
            (face.blur_score is not None and face.blur_score < 45)
            or (face.pose_yaw is not None and abs(face.pose_yaw) >= 45)
        ),
        20,
    )
    for row in sorted(unknown_rows, key=lambda item: (-float(item.get("score") or -1), int(item["old_face_record_id"]))):
        if len([case for case in cases if case["category"] == "unknown_gallery_candidate"]) >= 20:
            break
        if not row.get("accepted") or row.get("predicted_person_id") is None:
            continue
        face_id = int(row["old_face_record_id"])
        key = ("unknown", face_id)
        if key in used or face_id not in faces:
            continue
        used.add(key)
        cases.append({
            "source": "unknown_gallery",
            "category": "unknown_gallery_candidate",
            "face_record_id": face_id,
            "gallery_photo_id": row["gallery_photo_id"],
            "predicted_person_id": row["predicted_person_id"],
            "expected_person_id": None,
            "score": row["score"],
            "margin": row["margin"],
        })
    add_correction(
        "random_correct",
        lambda row, _baseline, _face: _accepted(row, THRESHOLD, MARGIN)
        and row["predicted_person_id"] == row["corrected_person_id"],
        max(0, 100 - len(cases)),
    )
    cases = cases[:100]
    if len(cases) < 100:
        raise SystemExit(f"只能生成 {len(cases)} 条唯一抽查案例")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    storage = MinioStorage(get_settings())
    object_cache: dict[str, bytes] = {}

    def get_payload(key: str) -> bytes:
        if key not in object_cache:
            object_cache[key] = storage.get_bytes(key)
        return object_cache[key]

    tile_size = (220, 150)
    row_height = 182
    columns = 5
    for case_index, case in enumerate(cases):
        case["case_id"] = case_index + 1
        case["verdict"] = None
        case["review_note"] = None
    for page_index in range(10):
        page_cases = cases[page_index * 10:(page_index + 1) * 10]
        sheet = Image.new("RGB", (tile_size[0] * columns, row_height * len(page_cases)), "white")
        draw = ImageDraw.Draw(sheet)
        for row_index, case in enumerate(page_cases):
            face = faces[int(case["face_record_id"])]
            photo = photos[int(case["gallery_photo_id"])]
            query = _crop(
                get_payload(photo.object_key),
                (face.bbox_left, face.bbox_top, face.bbox_right, face.bbox_bottom),
            )
            images = [query]
            predicted_id = int(case["predicted_person_id"])
            expected_id = case["expected_person_id"]
            for person_id in (predicted_id, predicted_id, expected_id, expected_id):
                samples = samples_by_person.get(int(person_id), []) if person_id is not None else []
                sample_index = 0 if len(images) % 2 == 1 else 1
                if sample_index >= len(samples):
                    images.append(Image.new("RGB", tile_size, "#dddddd"))
                    continue
                sample, sample_face = samples[sample_index]
                bbox = None if sample_face is None else (
                    sample_face.bbox_left,
                    sample_face.bbox_top,
                    sample_face.bbox_right,
                    sample_face.bbox_bottom,
                )
                images.append(_crop(get_payload(sample.object_key), bbox))
            y = row_index * row_height
            for column, image in enumerate(images):
                sheet.paste(_fit(image, tile_size), (column * tile_size[0], y + 28))
            draw.text(
                (4, y + 4),
                f"#{case['case_id']} {case['category']} pred={predicted_id} "
                f"expected={expected_id} score={float(case['score']):.3f} margin={float(case['margin'] or 0):.3f}",
                fill="black",
            )
        sheet.save(output / f"review-{page_index + 1:02d}.jpg", quality=92)
    (output / "review-manifest.json").write_text(
        json.dumps({
            "columns": ["query", "predicted-1", "predicted-2", "expected-1", "expected-2"],
            "threshold": THRESHOLD,
            "margin": MARGIN,
            "cases": cases,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "cases": len(cases), "pages": 10}, ensure_ascii=False))


if __name__ == "__main__":
    main()
