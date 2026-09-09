from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


def _tags(conn: sqlite3.Connection, photo_id: int) -> set[tuple[int, str]]:
    return {(int(row[0]), str(row[1])) for row in conn.execute(
        "SELECT person_id,source FROM gallery_photo_person_tags WHERE gallery_photo_id=?",
        (photo_id,),
    )}


def main() -> None:
    parser = argparse.ArgumentParser(description="核验全图库人物标签重整结果。")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--old-db", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("E:/dockerVolums/picture-show/sqllite/app.db"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    old = sqlite3.connect(args.old_db)
    current = sqlite3.connect(args.database)
    failures: list[dict[str, object]] = []
    category_counts: dict[str, int] = {}
    debug_face_bindings = int(current.execute(
        "SELECT COUNT(*) FROM face_records f JOIN persons p ON p.id=f.matched_person_id "
        "WHERE p.display_name IN ('临时调试人物1','临时调试人物2')"
    ).fetchone()[0])
    for plan in report["plans"]:
        photo_id = int(plan["gallery_photo_id"])
        category = str(plan["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
        actual = _tags(current, photo_id)
        desired = {
            (1384 if tag["source"] == "debug_1" else 1385 if tag["source"] == "debug_2" else int(tag["person_id"]),
             "debug" if tag["source"] in {"debug_1", "debug_2"} else str(tag["source"]))
            for tag in plan["desired_tags"]
        }
        if actual != desired:
            failures.append({"photo_id": photo_id, "category": category, "expected": sorted(desired), "actual": sorted(actual)})
    old_unknown_photo_ids = {
        int(row[0]) for row in old.execute(
            "SELECT DISTINCT t.gallery_photo_id FROM gallery_photo_person_tags t JOIN persons p ON p.id=t.person_id WHERE p.is_unknown=1"
        )
    }
    current_unknown_photo_ids = {
        int(row[0]) for row in current.execute(
            "SELECT DISTINCT t.gallery_photo_id FROM gallery_photo_person_tags t JOIN persons p ON p.id=t.person_id WHERE p.is_unknown=1"
        )
    }
    report_out = {
        "passed": not failures and debug_face_bindings == 0,
        "failures": failures[:100],
        "category_counts": category_counts,
        "photo_count": len(report["plans"]),
        "tag_mismatch_count": len(failures),
        "debug_face_bindings": debug_face_bindings,
        "old_unknown_photo_count": len(old_unknown_photo_ids),
        "current_unknown_photo_count": len(current_unknown_photo_ids),
        "current_unknown_tag_count": int(current.execute(
            "SELECT COUNT(*) FROM gallery_photo_person_tags t JOIN persons p ON p.id=t.person_id WHERE p.is_unknown=1"
        ).fetchone()[0]),
        "unknown_only_photo_count": int(current.execute(
            "SELECT COUNT(*) FROM (SELECT t.gallery_photo_id FROM gallery_photo_person_tags t "
            "JOIN persons p ON p.id=t.person_id GROUP BY t.gallery_photo_id "
            "HAVING SUM(p.is_unknown)=COUNT(*))"
        ).fetchone()[0]),
    }
    args.output.write_text(json.dumps(report_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report_out, ensure_ascii=False, indent=2))
    if not report_out["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
