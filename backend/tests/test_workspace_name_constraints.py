from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Person, VideoCategoryTag, VideoPerson, Workspace
from app.schemas import PersonCreate, VideoCategoryTagCreate
from tests.support.app_loader import load_test_main


def _create_workspaces(db_session) -> tuple[Workspace, Workspace]:
    first = Workspace(name="工作区一", kind="private")
    second = Workspace(name="工作区二", kind="private")
    db_session.add_all([first, second])
    db_session.commit()
    return first, second


def test_person_name_is_unique_only_within_workspace(db_session) -> None:
    module = load_test_main()
    first, second = _create_workspaces(db_session)
    db_session.add(Person(workspace_id=first.id, name="赵美延", display_name="赵美延", is_unknown=False))
    db_session.commit()

    created = module.create_person(
        PersonCreate(name="赵美延"),
        db=db_session,
        current=SimpleNamespace(workspace_id=second.id),
    )

    assert created.name == "赵美延"
    assert db_session.scalar(
        select(Person).where(Person.workspace_id == second.id, Person.name == "赵美延")
    ) is not None
    with pytest.raises(HTTPException) as exc_info:
        module.create_person(
            PersonCreate(name="赵美延"),
            db=db_session,
            current=SimpleNamespace(workspace_id=second.id),
        )
    assert exc_info.value.status_code == 409


def test_video_names_are_unique_only_within_workspace(db_session) -> None:
    module = load_test_main()
    first, second = _create_workspaces(db_session)
    db_session.add_all(
        [
            VideoCategoryTag(workspace_id=first.id, name="演唱会"),
            VideoPerson(workspace_id=first.id, name="赵美延"),
        ]
    )
    db_session.commit()

    def find_or_create_category_tag(db, name: str, workspace_id: int) -> VideoCategoryTag:
        normalized = name.strip()
        tag = db.scalar(
            select(VideoCategoryTag).where(
                VideoCategoryTag.workspace_id == workspace_id,
                VideoCategoryTag.name == normalized,
            )
        )
        if tag is None:
            tag = VideoCategoryTag(workspace_id=workspace_id, name=normalized)
            db.add(tag)
            db.flush()
        return tag

    module.video_service = SimpleNamespace(find_or_create_category_tag=find_or_create_category_tag)
    category = module.create_video_category_tag(
        VideoCategoryTagCreate(name="演唱会"),
        db=db_session,
        current=SimpleNamespace(workspace_id=second.id),
    )
    video_person = asyncio.run(
        module.create_video_person(
            name="赵美延",
            note=None,
            avatar=None,
            db=db_session,
            current=SimpleNamespace(workspace_id=second.id),
        )
    )

    assert category.name == "演唱会"
    assert video_person.name == "赵美延"
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            module.create_video_person(
                name="赵美延",
                note=None,
                avatar=None,
                db=db_session,
                current=SimpleNamespace(workspace_id=second.id),
            )
        )
    assert exc_info.value.status_code == 409
