from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import random
import shutil
import sqlite3
from typing import Any

from minio import Minio
from PIL import Image, ImageOps

from .config import SourceConfig
from .geometry import face_crop_box, parse_bbox
from .sampling import sample_detection_photos, stratified_face_sample
from .store import initialize_benchmark


def open_source_database(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"主数据库不存在：{path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def load_candidates(
    connection: sqlite3.Connection,
    workspace_id: int | None,
    recognition_threshold: float,
    min_margin: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    scope = "gp.workspace_id IS NULL" if workspace_id is None else "gp.workspace_id = ?"
    params: tuple[object, ...] = () if workspace_id is None else (workspace_id,)
    people = [dict(row) for row in connection.execute(
        "SELECT id AS source_person_id, display_name, is_unknown FROM persons "
        + ("WHERE workspace_id IS NULL" if workspace_id is None else "WHERE workspace_id = ?"),
        params,
    )]
    tags: dict[int, list[tuple[int, str]]] = {}
    tag_sql = f"""
        SELECT gpt.gallery_photo_id, p.id, p.display_name
        FROM gallery_photo_person_tags gpt
        JOIN gallery_photos gp ON gp.id = gpt.gallery_photo_id
        JOIN persons p ON p.id = gpt.person_id
        WHERE {scope} AND p.is_unknown = 0
        ORDER BY gpt.gallery_photo_id, p.id
    """
    for row in connection.execute(tag_sql, params):
        tags.setdefault(int(row[0]), []).append((int(row[1]), str(row[2])))

    face_sql = f"""
        SELECT fr.id AS face_id, gp.id AS photo_id, gp.filename, gp.object_key, gp.sha256,
               fr.bbox_left, fr.bbox_top, fr.bbox_right, fr.bbox_bottom,
               fr.detection_score, fr.match_score, fr.second_match_score, fr.match_margin,
               fr.face_size, fr.blur_score, fr.pose_yaw,
               mp.id AS matched_person_id, mp.display_name AS matched_person_name,
               COALESCE(mp.is_unknown, 1) AS matched_is_unknown
        FROM face_records fr
        JOIN gallery_photos gp ON gp.id = fr.gallery_photo_id
        LEFT JOIN persons mp ON mp.id = fr.matched_person_id
        WHERE {scope} AND gp.is_rich_text = 0
          AND NOT EXISTS (
              SELECT 1 FROM sample_photos sp
              WHERE sp.source_gallery_photo_id = gp.id OR sp.sha256 = gp.sha256
          )
        ORDER BY fr.id
    """
    faces: list[dict[str, Any]] = []
    for source_row in connection.execute(face_sql, params):
        row = dict(source_row)
        known_tags = tags.get(int(row["photo_id"]), [])
        suggested_id: int | None = None
        suggested_name: str | None = None
        suggestion_source: str | None = None
        if len(known_tags) == 1:
            suggested_id, suggested_name = known_tags[0]
            suggestion_source = "gallery_person_tag"
        elif (
            not bool(row["matched_is_unknown"])
            and row["match_score"] is not None
            and float(row["match_score"]) >= recognition_threshold
            and (row["match_margin"] is None or float(row["match_margin"]) >= min_margin)
        ):
            suggested_id = int(row["matched_person_id"])
            suggested_name = str(row["matched_person_name"])
            suggestion_source = "face_record"
        row.update(
            suggested_person_id=suggested_id,
            suggested_person_name=suggested_name,
            suggestion_source=suggestion_source,
            gallery_person_ids=[person_id for person_id, _ in known_tags],
        )
        faces.append(row)

    photo_sql = f"""
        SELECT gp.id AS photo_id, gp.filename, gp.object_key, gp.sha256,
               COUNT(fr.id) AS face_count, MIN(fr.face_size) AS min_face_size,
               MAX(ABS(COALESCE(fr.pose_yaw, 0))) AS max_abs_pose
        FROM gallery_photos gp
        LEFT JOIN face_records fr ON fr.gallery_photo_id = gp.id
        WHERE {scope} AND gp.is_rich_text = 0
        GROUP BY gp.id
        ORDER BY gp.id
    """
    photos = [dict(row) for row in connection.execute(photo_sql, params)]
    sample_scope = "sp.workspace_id IS NULL" if workspace_id is None else "sp.workspace_id = ?"
    samples = [dict(row) for row in connection.execute(
        f"""
        SELECT sp.id AS source_sample_id, sp.person_id AS source_person_id,
               sp.filename, sp.object_key, sp.sha256
        FROM sample_photos sp
        JOIN persons p ON p.id = sp.person_id
        WHERE {sample_scope} AND sp.status = 'ready' AND p.is_unknown = 0
        ORDER BY sp.id
        """,
        params,
    )]
    return faces, photos, samples, people


def _split_for(item_key: str, seed: int) -> str:
    value = int(sha256(f"{seed}:{item_key}".encode()).hexdigest()[:8], 16) % 10
    return "holdout" if value < 3 else "calibration"


def _photo_split(photo_id: int, seed: int) -> str:
    return _split_for(f"photo:{photo_id}", seed)


def _normalized_jpeg(payload: bytes) -> Image.Image:
    with Image.open(BytesIO(payload)) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=94, optimize=True)


def _crop_face(image: Image.Image, row: dict[str, Any]) -> Image.Image:
    bbox = parse_bbox([row[key] for key in ("bbox_left", "bbox_top", "bbox_right", "bbox_bottom")])
    return image.crop(face_crop_box(bbox, image.width, image.height))


def create_snapshot(
    config: SourceConfig,
    output_root: Path,
    *,
    workspace_id: int | None,
    face_target: int = 1000,
    detection_target: int = 150,
    seed: int = 20260731,
    snapshot_id: str | None = None,
) -> Path:
    snapshot_id = snapshot_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    final_dir = output_root.resolve() / snapshot_id
    work_dir = output_root.resolve() / f".{snapshot_id}.building"
    if final_dir.exists() or work_dir.exists():
        raise RuntimeError(f"快照目录已存在：{final_dir}")
    work_dir.mkdir(parents=True)
    try:
        with open_source_database(config.database_path) as source_db:
            faces, photos, samples, people = load_candidates(
                source_db, workspace_id, config.recognition_threshold, config.min_margin
            )
        selected_faces = stratified_face_sample(
            faces,
            target=face_target,
            seed=seed,
            recognition_threshold=config.recognition_threshold,
            min_margin=config.min_margin,
        )
        selected_photos = sample_detection_photos(photos, target=detection_target, seed=seed)
        client = Minio(
            config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_secure,
        )
        payload_cache: dict[str, bytes] = {}

        def fetch(object_key: str) -> bytes:
            if object_key not in payload_cache:
                response = client.get_object(config.minio_bucket, object_key)
                try:
                    payload_cache[object_key] = response.read()
                finally:
                    response.close()
                    response.release_conn()
            return payload_cache[object_key]

        benchmark = initialize_benchmark(work_dir / "benchmark.db")
        benchmark.executemany(
            "INSERT INTO persons(source_person_id, display_name, is_unknown) VALUES (?, ?, ?)",
            [(row["source_person_id"], row["display_name"], row["is_unknown"]) for row in people],
        )
        for sample in samples:
            payload = fetch(str(sample["object_key"]))
            relative = f"samples/{sample['source_sample_id']}.jpg"
            _save_jpeg(_normalized_jpeg(payload), work_dir / relative)
            benchmark.execute(
                "INSERT INTO samples(source_sample_id, source_person_id, image_path, sha256) VALUES (?, ?, ?, ?)",
                (sample["source_sample_id"], sample["source_person_id"], relative, sample["sha256"]),
            )

        originals: dict[int, str] = {}
        for row in [*selected_faces, *selected_photos]:
            photo_id = int(row["photo_id"])
            if photo_id in originals:
                continue
            relative = f"originals/{photo_id}.jpg"
            _save_jpeg(_normalized_jpeg(fetch(str(row["object_key"]))), work_dir / relative)
            originals[photo_id] = relative

        selection_lines: list[str] = []
        for row in selected_faces:
            photo_id, face_id = int(row["photo_id"]), int(row["face_id"])
            relative = f"faces/{face_id}.jpg"
            with Image.open(work_dir / originals[photo_id]) as image:
                _save_jpeg(_crop_face(image, row), work_dir / relative)
            bbox = [row[key] for key in ("bbox_left", "bbox_top", "bbox_right", "bbox_bottom")]
            metadata = {key: row.get(key) for key in (
                "filename", "detection_score", "match_score", "second_match_score", "match_margin",
                "face_size", "blur_score", "pose_yaw", "suggestion_source", "suggested_person_name",
                "gallery_person_ids",
            )}
            split = _photo_split(photo_id, seed)
            benchmark.execute(
                """INSERT INTO items(
                    kind, source_photo_id, source_face_id, sample_bucket, split, image_path,
                    original_path, source_sha256, bbox_json, metadata_json, suggested_person_id
                ) VALUES ('face', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    photo_id, face_id, row["sample_bucket"], split, relative, originals[photo_id],
                    row["sha256"], json.dumps(bbox), json.dumps(metadata, ensure_ascii=False),
                    row.get("suggested_person_id"),
                ),
            )
            selection_lines.append(json.dumps({"kind": "face", "face_id": face_id, "photo_id": photo_id, "bucket": row["sample_bucket"], "split": split}, ensure_ascii=False))

        for row in selected_photos:
            photo_id = int(row["photo_id"])
            split = _photo_split(photo_id, seed)
            metadata = {key: row.get(key) for key in ("filename", "face_count", "min_face_size", "max_abs_pose")}
            benchmark.execute(
                """INSERT INTO items(
                    kind, source_photo_id, sample_bucket, split, image_path, original_path,
                    source_sha256, metadata_json
                ) VALUES ('detection', ?, 'detection', ?, ?, ?, ?, ?)""",
                (photo_id, split, originals[photo_id], originals[photo_id], row["sha256"], json.dumps(metadata, ensure_ascii=False)),
            )
            selection_lines.append(json.dumps({"kind": "detection", "photo_id": photo_id, "split": split}, ensure_ascii=False))

        meta = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "workspace_id": workspace_id,
            "seed": seed,
            "face_items": len(selected_faces),
            "detection_items": len(selected_photos),
            "sample_photos": len(samples),
            "source_database": str(config.database_path),
            "source_access": "sqlite-read-only,minio-get-only",
        }
        benchmark.executemany("INSERT INTO snapshot_meta(key, value) VALUES (?, ?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in meta.items()])
        benchmark.commit()
        benchmark.close()
        selection = "\n".join(selection_lines) + "\n"
        (work_dir / "selection.jsonl").write_text(selection, encoding="utf-8")
        meta["selection_sha256"] = sha256(selection.encode()).hexdigest()
        checksums = {
            str(path.relative_to(work_dir)): sha256(path.read_bytes()).hexdigest()
            for folder in ("faces", "originals", "samples")
            for path in sorted((work_dir / folder).glob("*.jpg"))
        }
        checksum_payload = json.dumps(checksums, ensure_ascii=False, sort_keys=True, indent=2)
        (work_dir / "file-checksums.json").write_text(checksum_payload, encoding="utf-8")
        meta["file_checksums_sha256"] = sha256(checksum_payload.encode()).hexdigest()
        (work_dir / "snapshot.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        output_root.mkdir(parents=True, exist_ok=True)
        os.replace(work_dir, final_dir)
        return final_dir
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
