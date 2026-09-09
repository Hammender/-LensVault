from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person
from app.tools.analyze_face_migration_audit import _match_faces


UNKNOWN_NAME = "未知人物"
DEBUG_1 = "临时调试人物1"
DEBUG_2 = "临时调试人物2"


def _tags(conn: sqlite3.Connection, photo_id: int) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(
        "SELECT person_id,source FROM gallery_photo_person_tags WHERE gallery_photo_id=? ORDER BY person_id",
        (photo_id,),
    )]


def _faces(conn: sqlite3.Connection, photo_id: int) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute(
        "SELECT id,bbox_left,bbox_top,bbox_right,bbox_bottom,matched_person_id,predicted_person_id,needs_review,rejection_reason "
        "FROM face_records WHERE gallery_photo_id=? ORDER BY id",
        (photo_id,),
    )]
    for row in rows:
        row["bbox"] = [row.pop("bbox_left"), row.pop("bbox_top"), row.pop("bbox_right"), row.pop("bbox_bottom")]
    return rows


def _classify(old: sqlite3.Connection, current: sqlite3.Connection, known_person_ids: set[int], photo_id: int) -> dict[str, object]:
    old_tags = _tags(old, photo_id)
    current_tags = _tags(current, photo_id)
    old_faces = _faces(old, photo_id)
    current_faces = _faces(current, photo_id)
    old_unknown = any(tag["source"] == "unknown" for tag in old_tags)
    old_known = {int(tag["person_id"]) for tag in old_tags if tag["source"] != "unknown"}
    protected_sources = {"manual", "face_manual", "import", "import_unknown"}
    has_protected = any(tag["source"] in protected_sources for tag in old_tags)
    known_current = {
        int(face["predicted_person_id"])
        for face in current_faces
        if face["predicted_person_id"] in known_person_ids
        and face["needs_review"] == 0
        and face["matched_person_id"] == face["predicted_person_id"]
    }
    current_unknown = any(tag["source"] == "unknown" for tag in current_tags)
    if old_unknown:
        category = "legacy_unknown_restore"
        desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in old_tags]
    elif has_protected:
        if known_current == old_known:
            category = "preserved_sources_equal"
            desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in old_tags]
        else:
            category = "preserved_sources_conflict"
            desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in current_tags]
            desired_tags.append({"person_id": -1, "source": "debug_1"})
    elif old_known:
        if known_current == old_known:
            category = "auto_equal"
            desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in old_tags]
        else:
            category = "auto_conflict"
            desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in current_tags]
            desired_tags.append({"person_id": -2, "source": "debug_2"})
    elif current_unknown:
        category = "ordinary_unknown_cleanup"
        desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in current_tags if tag["source"] != "unknown"]
    else:
        category = "unchanged"
        desired_tags = [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in current_tags]
    return {
        "gallery_photo_id": photo_id,
        "category": category,
        "old_tags": [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in old_tags],
        "current_tags": [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in current_tags],
        "old_known_person_ids": sorted(old_known),
        "current_known_person_ids": sorted(known_current),
        "desired_tags": desired_tags,
        "old_face_count": len(old_faces),
        "current_face_count": len(current_faces),
    }


def _ensure_person(db, workspace_id: int | None, name: str) -> Person:
    person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.display_name == name))
    if person is None:
        person = Person(workspace_id=workspace_id, name=name, display_name=name, is_unknown=False)
        db.add(person)
        db.flush()
    return person


def _apply_plan(db, old_conn: sqlite3.Connection, plan: dict[str, object], debug1: Person, debug2: Person) -> None:
    photo = db.get(GalleryPhoto, int(plan["gallery_photo_id"]))
    if photo is None:
        raise RuntimeError(f"图库照片不存在：{plan['gallery_photo_id']}")
    for link in list(photo.person_tags):
        db.delete(link)
    db.flush()
    for tag in plan["desired_tags"]:
        if tag["source"] == "debug_1":
            person_id, source = debug1.id, "debug"
        elif tag["source"] == "debug_2":
            person_id, source = debug2.id, "debug"
        else:
            person_id, source = int(tag["person_id"]), str(tag["source"])
        if db.get(Person, person_id) is None:
            raise RuntimeError(f"人物不存在：{person_id}")
        db.add(GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=person_id, source=source))
    db.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="按迁移前快照和 AdaFace 当前结果重整全图库人物标签。")
    parser.add_argument("--old-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式执行必须同时提供 --apply --confirm。")
    old_conn = sqlite3.connect(args.old_db)
    current_conn = sqlite3.connect("E:/dockerVolums/picture-show/sqllite/app.db")
    photo_ids = [int(row[0]) for row in current_conn.execute("SELECT id FROM gallery_photos ORDER BY id")]
    known_person_ids = {int(row[0]) for row in current_conn.execute("SELECT id FROM persons WHERE is_unknown=0")}
    plans = [_classify(old_conn, current_conn, known_person_ids, photo_id) for photo_id in photo_ids]
    current_conn.close()
    counts: dict[str, int] = {}
    for plan in plans:
        counts[plan["category"]] = counts.get(plan["category"], 0) + 1
    if args.apply:
        with SessionLocal() as db:
            sample_photo = db.get(GalleryPhoto, photo_ids[0])
            workspace_id = sample_photo.workspace_id if sample_photo else None
            debug1 = _ensure_person(db, workspace_id, DEBUG_1)
            debug2 = _ensure_person(db, workspace_id, DEBUG_2)
            for plan in plans:
                _apply_plan(db, old_conn, plan, debug1, debug2)
            db.commit()
    old_conn.close()
    report = {"mode": "apply" if args.apply else "dry-run", "photo_count": len(plans), "category_counts": counts, "plans": plans}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "photo_count": len(plans), "category_counts": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
