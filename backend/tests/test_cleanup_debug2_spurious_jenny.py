from __future__ import annotations

from types import SimpleNamespace

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
from app.tools.cleanup_debug2_spurious_jenny import CleanupContext, cleanup_debug2_spurious_jenny


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
    jenny = Person(name="金珍妮-Jenny", display_name="金珍妮-Jenny", is_unknown=False)
    debug2 = Person(name="临时调试人物2", display_name="临时调试人物2", is_unknown=False)
    debug1 = Person(name="临时调试人物1", display_name="临时调试人物1", is_unknown=False)
    iu = Person(name="李知恩-IU", display_name="李知恩-IU", is_unknown=False)
    unknown = Person(name="未知人物", display_name="未知人物", is_unknown=True)
    db_session.add_all([workspace, jenny, debug2, debug1, iu, unknown])
    db_session.flush()
    for person in (jenny, debug2, debug1, iu, unknown):
        person.workspace_id = workspace.id
    blackpink = Tag(name="BlackPink", workspace_id=workspace.id)
    korea = Tag(name="韩娱", workspace_id=workspace.id)
    db_session.add_all([blackpink, korea])
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=jenny.id, tag_id=blackpink.id),
            PersonTag(person_id=jenny.id, tag_id=korea.id),
            PersonTag(person_id=iu.id, tag_id=korea.id),
        ]
    )
    db_session.flush()
    return workspace, jenny, debug2, debug1, iu, unknown, blackpink, korea


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


def _face(workspace_id: int, photo_id: int, person_id: int, offset: int = 0) -> FaceRecord:
    return FaceRecord(
        workspace_id=workspace_id,
        gallery_photo_id=photo_id,
        bbox_left=1 + offset,
        bbox_top=2 + offset,
        bbox_right=30 + offset,
        bbox_bottom=40 + offset,
        matched_person_id=person_id,
        predicted_person_id=person_id,
        needs_review=False,
    )


def _context(jenny, debug1, debug2, old_tags, old_jenny_photos) -> CleanupContext:
    return CleanupContext(
        jenny_id=jenny.id,
        debug1_id=debug1.id,
        debug2_id=debug2.id,
        old_tags_by_photo=old_tags,
        old_jenny_photos=old_jenny_photos,
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


def test_cleanup_removes_jenny_and_debug2_when_jenny_was_only_conflict(db_session) -> None:
    workspace, jenny, debug2, debug1, iu, _unknown, blackpink, korea = _setup(db_session)
    photo = _photo(db_session, workspace.id, "only-jenny")
    _bind(
        db_session,
        photo,
        [(iu, "auto"), (jenny, "auto"), (debug2, "debug")],
        [(blackpink, "person"), (korea, "person")],
    )
    db_session.add(_face(workspace.id, photo.id, jenny.id))
    db_session.add(_face(workspace.id, photo.id, iu.id, offset=40))
    db_session.commit()

    result = cleanup_debug2_spurious_jenny(
        db_session,
        _context(jenny, debug1, debug2, {photo.id: {iu.id}}, set()),
        _picture_service(),
        apply=True,
    )

    assert result["cleaned_photos"] == 1
    assert result["debug2_tags_deleted"] == 1
    remaining_people = set(
        db_session.scalars(select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id))
    )
    remaining_tags = {
        (tag.name, link.source)
        for link, tag in db_session.execute(
            select(GalleryPhotoTag, Tag).join(Tag, Tag.id == GalleryPhotoTag.tag_id).where(
                GalleryPhotoTag.gallery_photo_id == photo.id
            )
        )
    }
    remaining_faces = list(
        db_session.scalars(select(FaceRecord).where(FaceRecord.gallery_photo_id == photo.id))
    )
    assert remaining_people == {iu.id}
    assert remaining_tags == {("韩娱", "person")}
    assert {face.matched_person_id for face in remaining_faces} == {iu.id}


def test_cleanup_keeps_debug2_when_unknown_tag_remains(db_session) -> None:
    workspace, jenny, debug2, debug1, iu, unknown, blackpink, korea = _setup(db_session)
    photo = _photo(db_session, workspace.id, "keep-debug2")
    _bind(
        db_session,
        photo,
        [(iu, "auto"), (jenny, "auto"), (unknown, "unknown"), (debug2, "debug")],
        [(blackpink, "person"), (korea, "person")],
    )
    db_session.add(_face(workspace.id, photo.id, jenny.id))
    db_session.commit()

    result = cleanup_debug2_spurious_jenny(
        db_session,
        _context(jenny, debug1, debug2, {photo.id: {iu.id}}, set()),
        _picture_service(),
        apply=True,
    )

    assert result["cleaned_photos"] == 1
    assert result["debug2_tags_deleted"] == 0
    assert result["kept_debug2_photo_ids"] == [photo.id]
    remaining_people = set(
        db_session.scalars(select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id))
    )
    assert remaining_people == {iu.id, unknown.id, debug2.id}
    assert db_session.scalar(select(FaceRecord).where(FaceRecord.matched_person_id == jenny.id)) is None


def test_cleanup_skips_photos_that_had_jenny_before_migration(db_session) -> None:
    workspace, jenny, debug2, debug1, iu, _unknown, blackpink, korea = _setup(db_session)
    photo = _photo(db_session, workspace.id, "had-jenny")
    _bind(db_session, photo, [(iu, "auto"), (jenny, "auto"), (debug2, "debug")])
    db_session.add(_face(workspace.id, photo.id, jenny.id))
    db_session.commit()

    result = cleanup_debug2_spurious_jenny(
        db_session,
        _context(jenny, debug1, debug2, {photo.id: {iu.id, jenny.id}}, {photo.id}),
        _picture_service(),
        apply=True,
    )

    assert result["cleaned_photos"] == 0
    assert result["skipped_photos"] == 1
    remaining_people = set(
        db_session.scalars(select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id))
    )
    assert remaining_people == {iu.id, jenny.id, debug2.id}
    assert db_session.scalar(select(FaceRecord).where(FaceRecord.matched_person_id == jenny.id)) is not None


def test_cleanup_skips_promoted_jenny_faces(db_session) -> None:
    workspace, jenny, debug2, debug1, iu, _unknown, _blackpink, _korea = _setup(db_session)
    photo = _photo(db_session, workspace.id, "promoted")
    _bind(db_session, photo, [(iu, "auto"), (jenny, "auto"), (debug2, "debug")])
    face = _face(workspace.id, photo.id, jenny.id)
    db_session.add(face)
    db_session.flush()
    db_session.add(
        SamplePhoto(
            workspace_id=workspace.id,
            person_id=jenny.id,
            filename="sample.jpg",
            sha256="a" * 64,
            object_key="samples/jenny.jpg",
            status="ready",
            source_type="gallery_face",
            source_gallery_photo_id=photo.id,
            source_gallery_face_id=face.id,
        )
    )
    db_session.commit()

    result = cleanup_debug2_spurious_jenny(
        db_session,
        _context(jenny, debug1, debug2, {photo.id: {iu.id}}, set()),
        _picture_service(),
        apply=True,
    )

    assert result["skipped_photos"] == 1
    assert result["skip_reasons"] == {"jenny_face_promoted_to_sample": 1}
    assert db_session.scalar(select(GalleryPhotoPersonTag).where(GalleryPhotoPersonTag.person_id == jenny.id)) is not None


def test_cleanup_dry_run_does_not_write(db_session) -> None:
    workspace, jenny, debug2, debug1, iu, _unknown, blackpink, korea = _setup(db_session)
    photo = _photo(db_session, workspace.id, "dry-run")
    _bind(db_session, photo, [(iu, "auto"), (jenny, "auto"), (debug2, "debug")])
    db_session.add(_face(workspace.id, photo.id, jenny.id))
    db_session.commit()

    writes: list[str] = []

    def capture(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        result = cleanup_debug2_spurious_jenny(
            db_session,
            _context(jenny, debug1, debug2, {photo.id: {iu.id}}, set()),
            _picture_service(),
            apply=False,
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)

    assert result["applied"] is False
    assert result["cleaned_photos"] == 1
    assert writes == []
    assert db_session.scalar(select(FaceRecord).where(FaceRecord.matched_person_id == jenny.id)) is not None
