from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.models import (
    FaceRecord,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GalleryPhotoTag,
    Person,
    PersonTag,
    SamplePhoto,
    Tag,
    Workspace,
)
from app.services.importer import PictureService
from app.tools.restore_debug1_legacy_tags import RestoreContext, apply_restore, plan_restore, restore_debug1_legacy_tags


def _picture_service() -> PictureService:
    return PictureService(
        storage=SimpleNamespace(),
        face_service=SimpleNamespace(),
        vector_store=SimpleNamespace(),
        ocr_service=SimpleNamespace(),
        settings=SimpleNamespace(face_embedding_version="test-v1"),
    )


def _setup(db_session):
    workspace = Workspace(name="测试空间")
    debug1 = Person(name="临时调试人物1", display_name="临时调试人物1", is_unknown=False)
    iu = Person(name="李知恩-IU", display_name="李知恩-IU", is_unknown=False)
    jenny = Person(name="金珍妮-Jenny", display_name="金珍妮-Jenny", is_unknown=False)
    unknown = Person(name="未知人物", display_name="未知人物", is_unknown=True)
    db_session.add_all([workspace, debug1, iu, jenny, unknown])
    db_session.flush()
    for person in (debug1, iu, jenny, unknown):
        person.workspace_id = workspace.id
    korea = Tag(name="韩娱", workspace_id=workspace.id)
    blackpink = Tag(name="BlackPink", workspace_id=workspace.id)
    db_session.add_all([korea, blackpink])
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=iu.id, tag_id=korea.id),
            PersonTag(person_id=jenny.id, tag_id=blackpink.id),
            PersonTag(person_id=jenny.id, tag_id=korea.id),
        ]
    )
    db_session.flush()
    return workspace, debug1, iu, jenny, unknown, korea, blackpink


def _photo(db_session, workspace_id: int, name: str) -> GalleryPhoto:
    photo = GalleryPhoto(
        filename=f"{name}.jpg",
        sha256=name.ljust(64, "0"),
        object_key=f"gallery/{name}.jpg",
        workspace_id=workspace_id,
    )
    db_session.add(photo)
    db_session.flush()
    return photo


def _face(workspace_id: int, photo_id: int, person_id: int | None, offset: int = 0, needs_review: bool = False) -> FaceRecord:
    return FaceRecord(
        workspace_id=workspace_id,
        gallery_photo_id=photo_id,
        bbox_left=1 + offset,
        bbox_top=2 + offset,
        bbox_right=30 + offset,
        bbox_bottom=40 + offset,
        matched_person_id=person_id,
        predicted_person_id=person_id,
        needs_review=needs_review,
    )


def _bind(db_session, photo, people_with_source, tags=()):
    db_session.add_all(
        [
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=person.id, source=source)
            for person, source in people_with_source
        ]
    )
    db_session.add_all(
        [
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=tag.id, source=tag_source)
            for tag, tag_source in tags
        ]
    )


def _context(debug1, unknown, old_tags, old_faces, old_photo_ids=None) -> RestoreContext:
    photo_ids = set(old_tags) if old_photo_ids is None else old_photo_ids
    return RestoreContext(
        debug1_id=debug1.id,
        unknown_ids={unknown.id},
        old_photo_ids=photo_ids,
        old_tags_by_photo=old_tags,
        old_faces_by_photo=old_faces,
    )


def _people(db_session, photo_id: int) -> set[int]:
    return set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo_id)
        ).all()
    )


def test_restore_replaces_tags_and_drops_unknown(db_session) -> None:
    workspace, debug1, iu, _jenny, unknown, korea, _blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "restore-unknown")
    _bind(
        db_session,
        photo,
        [(iu, "auto"), (unknown, "unknown"), (debug1, "debug")],
        [(korea, "person")],
    )
    old_face = {
        "id": 1,
        "bbox": [1, 2, 30, 40],
        "matched_person_id": iu.id,
        "needs_review": False,
    }
    known_box = _face(workspace.id, photo.id, unknown.id)
    extra_box = _face(workspace.id, photo.id, unknown.id, offset=80)
    db_session.add_all([known_box, extra_box])
    db_session.commit()

    result = restore_debug1_legacy_tags(
        db_session,
        _context(
            debug1,
            unknown,
            {photo.id: [{"person_id": iu.id, "source": "manual"}]},
            {photo.id: [old_face]},
        ),
        _picture_service(),
        apply=True,
    )

    assert result["restore_photos"] == 1
    assert result["keep_photos"] == 0
    assert _people(db_session, photo.id) == {iu.id}
    tag_row = db_session.scalar(select(GalleryPhotoPersonTag).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id))
    assert tag_row is not None and tag_row.source == "manual"
    faces = {
        face.id: face
        for face in db_session.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo.id))
    }
    assert faces[known_box.id].matched_person_id == iu.id
    assert faces[known_box.id].needs_review is False
    assert faces[extra_box.id].matched_person_id is None
    assert faces[extra_box.id].needs_review is True
    remaining_tags = {
        (tag.name, link.source)
        for link, tag in db_session.execute(
            select(GalleryPhotoTag, Tag).join(Tag, Tag.id == GalleryPhotoTag.tag_id).where(
                GalleryPhotoTag.gallery_photo_id == photo.id
            )
        )
    }
    assert remaining_tags == {("韩娱", "person")}


def test_keep_leaves_extra_known_and_debug1(db_session) -> None:
    workspace, debug1, iu, jenny, unknown, korea, blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "keep-jenny")
    _bind(
        db_session,
        photo,
        [(iu, "manual"), (jenny, "auto"), (debug1, "debug")],
        [(korea, "person"), (blackpink, "person")],
    )
    db_session.add(_face(workspace.id, photo.id, jenny.id, offset=40))
    db_session.commit()

    result = restore_debug1_legacy_tags(
        db_session,
        _context(
            debug1,
            unknown,
            {photo.id: [{"person_id": iu.id, "source": "manual"}]},
            {photo.id: []},
        ),
        _picture_service(),
        apply=True,
    )

    assert result["keep_photos"] == 1
    assert result["keep_photo_ids"] == [photo.id]
    assert _people(db_session, photo.id) == {iu.id, jenny.id, debug1.id}
    assert db_session.scalar(select(FaceRecord.matched_person_id).where(FaceRecord.gallery_photo_id == photo.id)) == jenny.id


def test_restore_keeps_whole_photo_when_promoted_person_would_lose_tag(db_session) -> None:
    workspace, debug1, iu, jenny, unknown, _korea, _blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "promoted")
    _bind(db_session, photo, [(iu, "manual"), (unknown, "unknown"), (debug1, "debug")])
    known_face = _face(workspace.id, photo.id, iu.id)
    extra = _face(workspace.id, photo.id, unknown.id, offset=40)
    db_session.add_all([known_face, extra])
    db_session.flush()
    db_session.add(
        SamplePhoto(
            workspace_id=workspace.id,
            person_id=unknown.id,
            filename="sample.jpg",
            sha256="a" * 64,
            object_key="samples/unknown.jpg",
            status="ready",
            source_type="gallery_face",
            source_gallery_photo_id=photo.id,
            source_gallery_face_id=extra.id,
        )
    )
    db_session.commit()

    result = restore_debug1_legacy_tags(
        db_session,
        _context(
            debug1,
            unknown,
            {photo.id: [{"person_id": iu.id, "source": "manual"}]},
            {
                photo.id: [
                    {"id": 1, "bbox": [1, 2, 30, 40], "matched_person_id": iu.id, "needs_review": False},
                ]
            },
        ),
        _picture_service(),
        apply=True,
    )

    assert result["restore_photos"] == 0
    assert result["keep_photos"] == 1
    assert result["plans"][0]["keep_reason"] == "promoted_sample_conflict"
    assert _people(db_session, photo.id) == {iu.id, unknown.id, debug1.id}
    faces = {
        face.id: face
        for face in db_session.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo.id))
    }
    assert faces[known_face.id].matched_person_id == iu.id
    assert faces[extra.id].matched_person_id == unknown.id
    assert extra.id in result["plans"][0]["promoted_face_ids"]


def test_restore_keeps_whole_photo_when_rebind_conflicts_with_promoted_sample(db_session) -> None:
    workspace, debug1, iu, jenny, unknown, _korea, _blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "promoted-rebind")
    _bind(db_session, photo, [(iu, "manual"), (jenny, "manual"), (debug1, "debug")])
    face = _face(workspace.id, photo.id, jenny.id)
    db_session.add(face)
    db_session.flush()
    db_session.add(SamplePhoto(
        workspace_id=workspace.id, person_id=jenny.id, filename="sample.jpg",
        sha256="b" * 64, object_key="samples/jenny.jpg", status="ready",
        source_type="gallery_face", source_gallery_photo_id=photo.id,
        source_gallery_face_id=face.id,
    ))
    db_session.commit()

    result = restore_debug1_legacy_tags(
        db_session,
        _context(debug1, unknown,
                 {photo.id: [{"person_id": iu.id, "source": "manual"},
                             {"person_id": jenny.id, "source": "manual"}]},
                 {photo.id: [{"id": 1, "bbox": [1, 2, 30, 40],
                              "matched_person_id": iu.id, "needs_review": False}]}),
        _picture_service(), apply=True,
    )

    assert result["keep_photo_ids"] == [photo.id]
    assert result["plans"][0]["promoted_sample_conflicts"][0]["face_record_id"] == face.id
    assert _people(db_session, photo.id) == {iu.id, jenny.id, debug1.id}
    assert db_session.get(FaceRecord, face.id).matched_person_id == jenny.id


def test_apply_rechecks_promoted_sample_added_after_plan(db_session) -> None:
    workspace, debug1, iu, jenny, unknown, _korea, _blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "promoted-after-plan")
    _bind(db_session, photo, [(iu, "manual"), (jenny, "manual"), (debug1, "debug")])
    face = _face(workspace.id, photo.id, jenny.id)
    db_session.add(face)
    db_session.commit()
    context = _context(debug1, unknown,
                       {photo.id: [{"person_id": iu.id, "source": "manual"},
                                   {"person_id": jenny.id, "source": "manual"}]},
                       {photo.id: [{"id": 1, "bbox": [1, 2, 30, 40],
                                    "matched_person_id": iu.id, "needs_review": False}]})
    plans = plan_restore(db_session, context)
    assert plans[0]["action"] == "restore"
    db_session.add(SamplePhoto(
        workspace_id=workspace.id, person_id=jenny.id, filename="later.jpg",
        sha256="c" * 64, object_key="samples/later.jpg", status="ready",
        source_type="gallery_face", source_gallery_photo_id=photo.id,
        source_gallery_face_id=face.id,
    ))
    db_session.commit()

    apply_restore(db_session, context, plans, _picture_service())

    assert plans[0]["action"] == "keep"
    assert _people(db_session, photo.id) == {iu.id, jenny.id, debug1.id}
    assert db_session.get(FaceRecord, face.id).matched_person_id == jenny.id


def test_missing_old_photo_raises(db_session) -> None:
    workspace, debug1, iu, _jenny, unknown, _korea, _blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "missing")
    _bind(db_session, photo, [(iu, "manual"), (debug1, "debug")])
    db_session.commit()

    with pytest.raises(RuntimeError, match="迁移前备份中找不到这些图片"):
        restore_debug1_legacy_tags(
            db_session,
            _context(debug1, unknown, {}, {}, old_photo_ids=set()),
            _picture_service(),
            apply=False,
        )


def test_dry_run_does_not_write(db_session) -> None:
    workspace, debug1, iu, _jenny, unknown, _korea, _blackpink = _setup(db_session)
    photo = _photo(db_session, workspace.id, "dry-run")
    _bind(db_session, photo, [(iu, "auto"), (unknown, "unknown"), (debug1, "debug")])
    db_session.commit()

    writes: list[str] = []

    def capture(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        result = restore_debug1_legacy_tags(
            db_session,
            _context(
                debug1,
                unknown,
                {photo.id: [{"person_id": iu.id, "source": "manual"}]},
                {photo.id: []},
            ),
            _picture_service(),
            apply=False,
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)

    assert result["applied"] is False
    assert result["restore_photos"] == 1
    assert writes == []
    assert _people(db_session, photo.id) == {iu.id, unknown.id, debug1.id}
