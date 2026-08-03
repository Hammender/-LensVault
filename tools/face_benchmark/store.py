from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS persons (
    source_person_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    is_unknown INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS samples (
    source_sample_id INTEGER PRIMARY KEY,
    source_person_id INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('face', 'detection')),
    source_photo_id INTEGER NOT NULL,
    source_face_id INTEGER,
    sample_bucket TEXT NOT NULL,
    split TEXT NOT NULL CHECK(split IN ('calibration', 'holdout')),
    image_path TEXT NOT NULL,
    original_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    bbox_json TEXT,
    metadata_json TEXT NOT NULL,
    suggested_person_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'labeled', 'skipped')),
    truth_person_id INTEGER,
    truth_is_unknown INTEGER,
    true_face_count INTEGER,
    notes TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_kind_status ON items(kind, status);
CREATE INDEX IF NOT EXISTS ix_items_split ON items(split);
"""


def connect_benchmark(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_benchmark(path: Path) -> sqlite3.Connection:
    connection = connect_benchmark(path)
    connection.executescript(SCHEMA)
    return connection
