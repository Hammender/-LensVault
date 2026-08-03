from __future__ import annotations

import sqlite3

import pytest

from tools.face_benchmark.sampling import sample_detection_photos, stratified_face_sample
from tools.face_benchmark.snapshot import _photo_split, load_candidates, open_source_database


def _face(face_id: int, person_id: int | None, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "face_id": face_id,
        "suggested_person_id": person_id,
        "match_score": 0.65 if person_id else 0.38,
        "match_margin": 0.2,
        "face_size": 140,
        "blur_score": 100,
        "pose_yaw": 0,
    }
    row.update(overrides)
    return row


def test_stratified_sample_is_deterministic_and_covers_people() -> None:
    rows = [_face(index, (index % 8) + 1) for index in range(1, 41)]
    rows.extend(_face(index, None, face_size=50) for index in range(41, 61))

    first = stratified_face_sample(rows, target=40, seed=17, recognition_threshold=0.45, min_margin=0.08)
    second = stratified_face_sample(rows, target=40, seed=17, recognition_threshold=0.45, min_margin=0.08)

    assert [row["face_id"] for row in first] == [row["face_id"] for row in second]
    assert len({int(row["face_id"]) for row in first}) == 40
    assert {int(row["suggested_person_id"]) for row in first if row["suggested_person_id"]} == set(range(1, 9))
    assert {row["sample_bucket"] for row in first} >= {"known", "unknown_boundary", "hard", "random"}


def test_detection_sampling_keeps_hard_images_and_is_deterministic() -> None:
    rows = [
        {"photo_id": index, "face_count": 2 if index < 4 else 1, "min_face_size": 50 if index == 4 else 120, "max_abs_pose": 0}
        for index in range(1, 11)
    ]

    result = sample_detection_photos(rows, target=6, seed=9)

    assert [row["photo_id"] for row in result] == [row["photo_id"] for row in sample_detection_photos(rows, target=6, seed=9)]
    selected_ids = {int(row["photo_id"]) for row in result}
    assert len(selected_ids & {1, 2, 3, 4}) == 3


def test_source_database_is_query_only(tmp_path) -> None:
    database = tmp_path / "source.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    with open_source_database(database) as readonly:
        assert readonly.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO marker DEFAULT VALUES")


def test_source_photo_split_is_stable() -> None:
    assert _photo_split(42, 20260731) == _photo_split(42, 20260731)
    assert _photo_split(42, 20260731) in {"calibration", "holdout"}


def test_candidate_loader_prefers_single_gallery_person_tag(tmp_path) -> None:
    database = tmp_path / "source.db"
    db = sqlite3.connect(database)
    db.executescript(
        """
        CREATE TABLE persons (id INTEGER PRIMARY KEY, workspace_id INTEGER, display_name TEXT, is_unknown INTEGER);
        CREATE TABLE gallery_photos (id INTEGER PRIMARY KEY, workspace_id INTEGER, filename TEXT, object_key TEXT, sha256 TEXT, is_rich_text INTEGER);
        CREATE TABLE gallery_photo_person_tags (gallery_photo_id INTEGER, person_id INTEGER);
        CREATE TABLE face_records (
            id INTEGER PRIMARY KEY, gallery_photo_id INTEGER, bbox_left REAL, bbox_top REAL,
            bbox_right REAL, bbox_bottom REAL, detection_score REAL, match_score REAL,
            second_match_score REAL, match_margin REAL, face_size REAL, blur_score REAL,
            pose_yaw REAL, matched_person_id INTEGER
        );
        CREATE TABLE sample_photos (
            id INTEGER PRIMARY KEY, workspace_id INTEGER, person_id INTEGER, filename TEXT,
            object_key TEXT, sha256 TEXT, status TEXT, source_gallery_photo_id INTEGER
        );
        INSERT INTO persons VALUES (1, 7, '正确人物', 0), (2, 7, '错误预测', 0);
        INSERT INTO gallery_photos VALUES (10, 7, 'a.jpg', 'gallery/a.jpg', 'gallery-sha', 0);
        INSERT INTO gallery_photo_person_tags VALUES (10, 1);
        INSERT INTO face_records VALUES (20, 10, 0, 0, 100, 100, 0.9, 0.8, 0.5, 0.3, 100, 90, 0, 2);
        INSERT INTO sample_photos VALUES (30, 7, 1, 's.jpg', 'samples/s.jpg', 'sample-sha', 'ready', NULL);
        """
    )
    db.commit()
    db.close()

    with open_source_database(database) as readonly:
        faces, photos, samples, people = load_candidates(readonly, 7, 0.45, 0.08)

    assert faces[0]["suggested_person_id"] == 1
    assert faces[0]["suggestion_source"] == "gallery_person_tag"
    assert len(photos) == len(samples) == 1
    assert len(people) == 2
