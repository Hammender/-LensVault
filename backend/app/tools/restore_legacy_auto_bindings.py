from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person
from app.tools.analyze_face_migration_audit import _match_faces


def _latest_apply_rows(path: Path) -> dict[int, dict[str, object]]:
    rows: dict[int, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("mode") == "apply":
            rows[int(row["gallery_photo_id"])] = row
    return rows


def _load_old_tags(connection: sqlite3.Connection, photo_id: int) -> list[dict[str, object]]:
    connection.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in connection.execute(
            "SELECT person_id, source, created_at FROM gallery_photo_person_tags "
            "WHERE gallery_photo_id=? ORDER BY person_id",
            (photo_id,),
        )
    ]


def _load_old_faces(connection: sqlite3.Connection, photo_id: int) -> list[dict[str, object]]:
    connection.row_factory = sqlite3.Row
    rows = [
        dict(row) for row in connection.execute(
            "SELECT id,bbox_left,bbox_top,bbox_right,bbox_bottom,matched_person_id,needs_review "
            "FROM face_records WHERE gallery_photo_id=? ORDER BY id",
            (photo_id,),
        )
    ]
    for row in rows:
        row["bbox"] = [row.pop("bbox_left"), row.pop("bbox_top"), row.pop("bbox_right"), row.pop("bbox_bottom")]
    return rows


def _select_targets(old_db: sqlite3.Connection, audit: dict[int, dict[str, object]]) -> dict[int, set[int]]:
    targets: dict[int, set[int]] = {}
    old_db.row_factory = sqlite3.Row
    old_auto = old_db.execute(
        "SELECT gallery_photo_id,person_id FROM gallery_photo_person_tags t "
        "JOIN persons p ON p.id=t.person_id WHERE t.source='auto' AND p.is_unknown=0"
    ).fetchall()
    with SessionLocal() as db:
        for row in old_auto:
            photo_id = int(row["gallery_photo_id"])
            person_id = int(row["person_id"])
            audit_row = audit.get(photo_id)
            if not audit_row or audit_row.get("status") != "success":
                continue
            before = audit_row["before"]
            after = audit_row["after"]
            after_known_person_ids = {
                int(tag["person_id"])
                for tag in after["person_tags"]
                if tag["source"] != "unknown"
            }
            if person_id in after_known_person_ids:
                continue
            old_face_ids = {
                int(face["matched_person_id"])
                for face in before["faces"]
                if face.get("matched_person_id") == person_id and not face.get("needs_review")
            }
            if not old_face_ids:
                continue
            if any(
                face.get("predicted_person_id") == person_id
                and face.get("needs_review")
                and face.get("rejection_reason") in {"below_threshold", "insufficient_margin"}
                for face in after["faces"]
            ):
                targets.setdefault(photo_id, set()).add(person_id)
    return targets


def _current_snapshot(db, photo_id: int) -> dict[str, object]:
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise RuntimeError(f"图库照片不存在：{photo_id}")
    return {
        "person_tags": [
            {"person_id": tag.person_id, "source": tag.source}
            for tag in sorted(photo.person_tags, key=lambda item: item.person_id)
        ],
        "faces": [
            {
                "face_record_id": face.id,
                "bbox": [face.bbox_left, face.bbox_top, face.bbox_right, face.bbox_bottom],
                "matched_person_id": face.matched_person_id,
                "needs_review": face.needs_review,
            }
            for face in sorted(photo.faces, key=lambda item: item.id)
        ],
    }


def _plan_one(db, old_db: sqlite3.Connection, photo_id: int, target_person_ids: set[int]) -> dict[str, object]:
    current = _current_snapshot(db, photo_id)
    old_tags = _load_old_tags(old_db, photo_id)
    old_faces = _load_old_faces(old_db, photo_id)
    current_faces = current["faces"]
    matches, removed, added = _match_faces(
        old_faces,
        [
            {
                "face_record_id": face["face_record_id"],
                "bbox": face["bbox"],
                "matched_person_id": face["matched_person_id"],
                "needs_review": face["needs_review"],
            }
            for face in current_faces
        ],
    )
    face_updates: list[dict[str, object]] = []
    for old_face, new_face in matches:
        if old_face.get("matched_person_id") in target_person_ids:
            face_updates.append({
                "face_record_id": new_face.get("face_record_id"),
                "old_face_record_id": old_face.get("id"),
                "matched_person_id": old_face.get("matched_person_id"),
                "needs_review": old_face.get("needs_review"),
            })
    return {
        "gallery_photo_id": photo_id,
        "target_person_ids": sorted(target_person_ids),
        "before_current": current,
        "legacy_person_tags": [
            {"person_id": tag["person_id"], "source": tag["source"]}
            for tag in old_tags
        ],
        "face_updates": face_updates,
        "old_faces": len(old_faces),
        "current_faces": len(current_faces),
        "unmatched_old_faces": removed,
        "unmatched_current_faces": added,
    }


def _apply_one(db, plan: dict[str, object], old_db: sqlite3.Connection) -> None:
    photo_id = int(plan["gallery_photo_id"])
    photo = db.get(GalleryPhoto, photo_id)
    if photo is None:
        raise RuntimeError(f"图库照片不存在：{photo_id}")
    for tag in list(photo.person_tags):
        db.delete(tag)
    db.flush()
    for tag in _load_old_tags(old_db, photo_id):
        person = db.get(Person, int(tag["person_id"]))
        if person is None:
            raise RuntimeError(f"迁移前人物不存在：photo_id={photo_id}, person_id={tag['person_id']}")
        db.add(GalleryPhotoPersonTag(
            gallery_photo_id=photo_id,
            person_id=person.id,
            source=str(tag["source"]),
        ))
    for update in plan["face_updates"]:
        face = db.get(FaceRecord, int(update["face_record_id"]))
        if face is None or face.gallery_photo_id != photo_id:
            raise RuntimeError(f"当前人脸不存在或不属于照片：photo_id={photo_id}, face_id={update['face_record_id']}")
        face.matched_person_id = update["matched_person_id"]
        face.needs_review = bool(update["needs_review"])
        if face.matched_person_id is not None:
            face.vector_collection = None
    db.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="按迁移前快照精确恢复分级筛选出的旧自动人物绑定。")
    parser.add_argument("--old-db", type=Path, required=True)
    parser.add_argument("--audit-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式恢复必须同时提供 --apply --confirm。")
    audit = _latest_apply_rows(args.audit_file)
    old_connection = sqlite3.connect(args.old_db)
    targets = _select_targets(old_connection, audit)
    plans: list[dict[str, object]] = []
    with SessionLocal() as db:
        for photo_id, person_ids in sorted(targets.items()):
            plans.append(_plan_one(db, old_connection, photo_id, person_ids))
        if args.apply:
            for plan in plans:
                _apply_one(db, plan, old_connection)
            db.commit()
    old_connection.close()
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "target_photos": len(plans),
        "target_faces": sum(len(plan["face_updates"]) for plan in plans),
        "unknown_tags_in_legacy": sum(
            1 for plan in plans for tag in plan["legacy_person_tags"] if tag["source"] == "unknown"
        ),
        "plans": plans,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "target_photos", "target_faces", "unknown_tags_in_legacy")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
