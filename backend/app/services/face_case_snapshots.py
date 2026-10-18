"""识别事件身份及详情版本，不依赖当前人物绑定来判定事件重复。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.models.gallery import FaceRecord
from app.core.timezones import shanghai_isoformat


def json_value(value):
    return shanghai_isoformat(value) if isinstance(value, datetime) else value


def recognition_snapshot(face: FaceRecord) -> dict:
    excluded = {"matched_person_id", "needs_review", "vector_collection"}
    return {
        column.name: json_value(getattr(face, column.name))
        for column in FaceRecord.__table__.columns if column.name not in excluded
    }


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def recognition_key(face: FaceRecord) -> str:
    return digest(recognition_snapshot(face))


def face_revision(face: FaceRecord) -> str:
    return digest([recognition_key(face), face.matched_person_id, face.needs_review])
