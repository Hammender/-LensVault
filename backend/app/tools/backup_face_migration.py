from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.services.qdrant import QdrantVectorStore


TABLES = (
    "gallery_photos",
    "gallery_photo_person_tags",
    "face_records",
    "sample_photos",
    "face_recognition_corrections",
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, object]]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(sql)]


def main() -> None:
    parser = argparse.ArgumentParser(description="为人脸模型迁移创建 SQLite 一致备份和逐图快照。")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise SystemExit("当前工具只支持 SQLite 数据库。")
    source_path = Path(url.database).resolve()
    if not source_path.is_file():
        raise SystemExit(f"SQLite 数据库不存在：{source_path}")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = (args.output or settings.data_dir / "face-migration" / timestamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    backup_path = output / "app-before.db"

    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)

    with sqlite3.connect(backup_path) as backup:
        integrity = backup.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise SystemExit(f"SQLite 备份完整性检查失败：{integrity}")
        counts = {
            table: int(backup.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in TABLES
        }
        tags_by_photo: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in _rows(
            backup,
            "SELECT id, gallery_photo_id, person_id, source, created_at "
            "FROM gallery_photo_person_tags ORDER BY gallery_photo_id, person_id",
        ):
            tags_by_photo[int(row["gallery_photo_id"])].append(row)
        faces_by_photo: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in _rows(
            backup,
            "SELECT * FROM face_records WHERE gallery_photo_id IS NOT NULL "
            "ORDER BY gallery_photo_id, id",
        ):
            faces_by_photo[int(row["gallery_photo_id"])].append(row)
        samples_by_photo: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in _rows(
            backup,
            "SELECT id, workspace_id, person_id, status, source_type, source_gallery_photo_id, "
            "source_gallery_face_id FROM sample_photos WHERE source_gallery_photo_id IS NOT NULL "
            "ORDER BY source_gallery_photo_id, id",
        ):
            samples_by_photo[int(row["source_gallery_photo_id"])].append(row)
        snapshot_path = output / "gallery-before.jsonl"
        with snapshot_path.open("w", encoding="utf-8") as handle:
            for photo in _rows(
                backup,
                "SELECT id, workspace_id, filename, sha256, object_key, is_rich_text "
                "FROM gallery_photos ORDER BY id",
            ):
                photo_id = int(photo["id"])
                handle.write(json.dumps({
                    "photo": photo,
                    "person_tags": tags_by_photo.get(photo_id, []),
                    "faces": faces_by_photo.get(photo_id, []),
                    "promoted_samples": samples_by_photo.get(photo_id, []),
                }, ensure_ascii=False, separators=(",", ":")) + "\n")

    store = QdrantVectorStore(settings)
    inspection = store.inspect_collection(
        settings.qdrant_known_collection,
        embedding_version=settings.face_embedding_version,
        include_vectors=False,
    )
    face_config = {
        "face_model_name": settings.face_model_name,
        "face_adapter_id": settings.face_adapter_id,
        "face_recognition_model_path": settings.face_recognition_model_path,
        "face_embedding_version": settings.face_embedding_version,
        "face_detection_size": settings.face_detection_size,
        "face_flip_augmentation": settings.face_flip_augmentation,
        "face_recognition_threshold": settings.face_recognition_threshold,
        "face_recognition_min_margin": settings.face_recognition_min_margin,
        "face_centroid_mode": settings.face_centroid_mode,
        "face_match_max_bonus": settings.face_match_max_bonus,
        "qdrant_known_collection": settings.qdrant_known_collection,
        "qdrant_vector_dimension": settings.qdrant_vector_dimension,
    }
    (output / "face-config-before.json").write_text(
        json.dumps(face_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "qdrant-before.json").write_text(
        json.dumps(inspection.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_database": str(source_path),
        "backup_database": str(backup_path),
        "database_size": backup_path.stat().st_size,
        "database_sha256": _file_sha256(backup_path),
        "snapshot_file": str(snapshot_path),
        "snapshot_size": snapshot_path.stat().st_size,
        "snapshot_sha256": _file_sha256(snapshot_path),
        "table_counts": counts,
        "sqlite_integrity_check": "ok",
        "qdrant": inspection.as_dict(),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
