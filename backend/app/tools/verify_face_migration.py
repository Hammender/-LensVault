from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.services.qdrant import QdrantVectorStore


PRESERVED_SOURCES = ("manual", "face_manual", "import", "import_unknown")


def _scalar(connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...] = ()) -> int:
    return int(connection.execute(sql, parameters).fetchone()[0])


def _rows(connection: sqlite3.Connection, sql: str) -> set[tuple[object, ...]]:
    return {tuple(row) for row in connection.execute(sql)}


def main() -> None:
    parser = argparse.ArgumentParser(description="对照迁移前备份，核验 AdaFace 全图库迁移结果。")
    parser.add_argument("--backup-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise SystemExit("当前工具只支持 SQLite 数据库。")
    current_path = Path(url.database).resolve()
    backup_path = args.backup_db.resolve()
    failures: list[str] = []

    with sqlite3.connect(current_path) as current, sqlite3.connect(backup_path) as before:
        current_integrity = current.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = list(current.execute("PRAGMA foreign_key_check"))
        if current_integrity != "ok":
            failures.append(f"当前数据库完整性检查失败：{current_integrity}")
        if foreign_key_errors:
            failures.append(f"当前数据库存在 {len(foreign_key_errors)} 条外键错误")

        gallery_columns = "id, workspace_id, filename, content_type, sha256, object_key, width, height, taken_at, is_rich_text"
        gallery_unchanged = _rows(current, f"SELECT {gallery_columns} FROM gallery_photos") == _rows(
            before, f"SELECT {gallery_columns} FROM gallery_photos"
        )
        if not gallery_unchanged:
            failures.append("图库图片资产字段与迁移前备份不一致")

        sample_columns = (
            "id, workspace_id, person_id, filename, content_type, sha256, object_key, width, height, "
            "taken_at, status, error_message, quality_status, quality_warnings, source_type, "
            "source_gallery_photo_id, created_at"
        )
        sample_assets_unchanged = _rows(current, f"SELECT {sample_columns} FROM sample_photos") == _rows(
            before, f"SELECT {sample_columns} FROM sample_photos"
        )
        if not sample_assets_unchanged:
            failures.append("样本资产字段与迁移前备份不一致")

        sources = ",".join(f"'{source}'" for source in PRESERVED_SOURCES)
        preserved_before = _rows(
            before,
            f"SELECT gallery_photo_id, person_id, source FROM gallery_photo_person_tags WHERE source IN ({sources})",
        )
        preserved_after = _rows(
            current,
            f"SELECT gallery_photo_id, person_id, source FROM gallery_photo_person_tags WHERE source IN ({sources})",
        )
        missing_preserved = preserved_before - preserved_after
        if missing_preserved:
            failures.append(f"丢失 {len(missing_preserved)} 条人工或导入人物标签")

        ready_sample_refs_before = _scalar(
            before,
            "SELECT COUNT(*) FROM sample_photos WHERE status='ready' AND source_gallery_face_id IS NOT NULL",
        )
        ready_sample_refs_after = _scalar(
            current,
            "SELECT COUNT(*) FROM sample_photos WHERE status='ready' AND source_gallery_face_id IS NOT NULL",
        )
        invalid_sample_refs = _scalar(
            current,
            "SELECT COUNT(*) FROM sample_photos s "
            "LEFT JOIN face_records f ON f.id=s.source_gallery_face_id "
            "WHERE s.status='ready' AND s.source_gallery_face_id IS NOT NULL "
            "AND (f.id IS NULL OR f.gallery_photo_id<>s.source_gallery_photo_id OR f.matched_person_id<>s.person_id)",
        )
        if ready_sample_refs_after != ready_sample_refs_before:
            failures.append("提升样本的人脸来源引用数量发生变化")
        if invalid_sample_refs:
            failures.append(f"存在 {invalid_sample_refs} 条无效提升样本人脸引用")

        counts = {
            "gallery_photos": _scalar(current, "SELECT COUNT(*) FROM gallery_photos"),
            "face_records": _scalar(current, "SELECT COUNT(*) FROM face_records"),
            "sample_photos": _scalar(current, "SELECT COUNT(*) FROM sample_photos"),
            "face_recognition_corrections": _scalar(current, "SELECT COUNT(*) FROM face_recognition_corrections"),
            "person_tags": _scalar(current, "SELECT COUNT(*) FROM gallery_photo_person_tags"),
        }
        expected_ready_samples = _scalar(current, "SELECT COUNT(*) FROM sample_photos WHERE status='ready'")
        expected_centroids = _scalar(
            current,
            "SELECT COUNT(DISTINCT person_id) FROM sample_photos WHERE status='ready'",
        )
        face_versions = [
            {"adapter_id": row[0], "embedding_version": row[1], "count": int(row[2])}
            for row in current.execute(
                "SELECT recognition_adapter_id, embedding_version, COUNT(*) FROM face_records "
                "WHERE gallery_photo_id IS NOT NULL GROUP BY recognition_adapter_id, embedding_version "
                "ORDER BY COUNT(*) DESC"
            )
        ]
        tag_sources = {
            str(row[0]): int(row[1])
            for row in current.execute(
                "SELECT source, COUNT(*) FROM gallery_photo_person_tags GROUP BY source ORDER BY source"
            )
        }

    vector_store = QdrantVectorStore(settings)
    inspection = vector_store.inspect_collection(
        settings.qdrant_known_collection,
        embedding_version=settings.face_embedding_version,
        include_vectors=False,
    ).as_dict()
    qdrant_ready = (
        inspection["exists"]
        and inspection["vector_size"] == settings.qdrant_vector_dimension
        and inspection["distance"] == "Cosine"
        and inspection["searchable_samples"] == expected_ready_samples
        and inspection["searchable_centroids"] == expected_centroids
        and inspection["invalid_payload_points"] == 0
        and inspection["invalid_vector_points"] == 0
    )
    inspection["ready_for_activation"] = qdrant_ready
    if not qdrant_ready:
        failures.append("当前 Qdrant 集合未通过启用检查")
    report = {
        "passed": not failures,
        "failures": failures,
        "current_database": str(current_path),
        "backup_database": str(backup_path),
        "sqlite_integrity_check": current_integrity,
        "foreign_key_errors": len(foreign_key_errors),
        "gallery_assets_unchanged": gallery_unchanged,
        "sample_assets_unchanged": sample_assets_unchanged,
        "preserved_tags_before": len(preserved_before),
        "preserved_tags_after": len(preserved_after),
        "missing_preserved_tags": len(missing_preserved),
        "ready_sample_face_refs_before": ready_sample_refs_before,
        "ready_sample_face_refs_after": ready_sample_refs_after,
        "invalid_sample_face_refs": invalid_sample_refs,
        "counts": counts,
        "tag_sources": tag_sources,
        "gallery_face_versions": face_versions,
        "qdrant": inspection,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
