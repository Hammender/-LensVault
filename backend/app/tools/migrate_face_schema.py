from __future__ import annotations

import json

from sqlalchemy import inspect

from app.db import engine
from app.lifecycle import ensure_face_recognition_columns


FACE_COLUMNS = {
    "predicted_person_id",
    "second_person_id",
    "second_match_score",
    "match_margin",
    "rejection_reason",
    "recognition_adapter_id",
    "decision_threshold",
    "decision_min_margin",
    "embedding_version",
    "face_size",
    "blur_score",
    "pose_yaw",
}


def main() -> None:
    before = {column["name"] for column in inspect(engine).get_columns("face_records")}
    ensure_face_recognition_columns(engine)
    after = {column["name"] for column in inspect(engine).get_columns("face_records")}
    missing = sorted(FACE_COLUMNS - after)
    result = {
        "added_columns": sorted((after - before) & FACE_COLUMNS),
        "existing_columns": sorted(before & FACE_COLUMNS),
        "missing_columns": missing,
        "success": not missing,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if missing:
        raise SystemExit("人脸识别字段迁移未完成。")


if __name__ == "__main__":
    main()
