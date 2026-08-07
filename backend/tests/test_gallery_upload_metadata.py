from __future__ import annotations

import asyncio
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import gallery as gallery_api
from app.api.gallery import _parse_gallery_metadata, _validate_gallery_person_ids
from app.db import Base
from app.models import Person, Task, Workspace


def test_metadata_accepts_multiple_person_ids_and_deduplicates_values() -> None:
    metadata = _parse_gallery_metadata(
        json.dumps([{"person_ids": [3, 5, 3], "tag_names": ["活动", " 活动 ", "夜景"]}]),
        1,
    )

    assert metadata == [{"person_ids": [3, 5], "tag_names": ["活动", "夜景"], "rich_text": None}]


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        json.dumps({"person_ids": []}),
        json.dumps([]),
        json.dumps([{"person_names": ["张三"]}]),
        json.dumps([{"person_ids": ["3"]}]),
        json.dumps([{"person_ids": [True]}]),
        json.dumps([{"person_ids": [], "tag_names": [3]}]),
        json.dumps([{"person_ids": [], "rich_text": 3}]),
    ],
)
def test_old_protocol_and_invalid_metadata_are_rejected(raw: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _parse_gallery_metadata(raw, 1)

    assert exc_info.value.status_code == 422


def test_person_ids_must_be_formal_people_in_current_workspace() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        current_workspace = Workspace(name="当前空间")
        other_workspace = Workspace(name="其他空间")
        db.add_all([current_workspace, other_workspace])
        db.flush()
        valid_a = Person(workspace_id=current_workspace.id, name="张三", display_name="张三", is_unknown=False)
        valid_b = Person(workspace_id=current_workspace.id, name="李四", display_name="李四", is_unknown=False)
        unknown = Person(workspace_id=current_workspace.id, name="未知人物", display_name="未知人物", is_unknown=True)
        cross_workspace = Person(workspace_id=other_workspace.id, name="王五", display_name="王五", is_unknown=False)
        db.add_all([valid_a, valid_b, unknown, cross_workspace])
        db.commit()

        _validate_gallery_person_ids(
            db,
            [{"person_ids": [valid_a.id, valid_b.id], "tag_names": [], "rich_text": None}],
            current_workspace.id,
        )
        for invalid_id in (999999, unknown.id, cross_workspace.id):
            with pytest.raises(HTTPException) as exc_info:
                _validate_gallery_person_ids(
                    db,
                    [{"person_ids": [valid_a.id, invalid_id], "tag_names": [], "rich_text": None}],
                    current_workspace.id,
                )
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail == "所选人物不存在，请先在样本库创建人物后再上传。"

        assert db.scalar(select(Task)) is None
        assert db.scalars(select(Person)).all() == [valid_a, valid_b, unknown, cross_workspace]
    engine.dispose()


def test_invalid_person_is_rejected_before_file_read_or_task_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        workspace = Workspace(name="当前空间")
        db.add(workspace)
        db.commit()
        upload = UploadFile(file=BytesIO(b"image-content"), filename="photo.jpg")

        def fail_create_task(*args: object, **kwargs: object) -> None:
            raise AssertionError("无效人物不应创建上传任务")

        monkeypatch.setattr(gallery_api, "create_task", fail_create_task)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                gallery_api.import_gallery_photos(
                    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                    background_tasks=BackgroundTasks(),
                    files=[upload],
                    metadata_json=json.dumps([{"person_ids": [999999]}]),
                    db=db,
                    current=SimpleNamespace(workspace_id=workspace.id),
                )
            )

        assert exc_info.value.status_code == 422
        assert upload.file.tell() == 0
        assert db.scalar(select(Task)) is None
    engine.dispose()
