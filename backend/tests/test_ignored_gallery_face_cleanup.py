from __future__ import annotations

from sqlalchemy import select, text

from app.lifecycle import IGNORED_GALLERY_FACE_CLEANUP_KEY, cleanup_ignored_gallery_face_records
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person, Workspace


def _face(workspace_id: int, photo_id: int, **overrides) -> FaceRecord:
    values = {
        "workspace_id": workspace_id,
        "gallery_photo_id": photo_id,
        "bbox_left": 1,
        "bbox_top": 2,
        "bbox_right": 30,
        "bbox_bottom": 40,
        "matched_person_id": None,
        "needs_review": False,
        "vector_collection": None,
    }
    values.update(overrides)
    return FaceRecord(**values)


def test_cleanup_ignored_gallery_face_records_is_precise_and_idempotent(db_session) -> None:
    workspace = Workspace(name="迁移测试空间")
    unknown = Person(name="__system_unknown_person__:1", display_name="未知人物", is_unknown=True)
    known = Person(name="known", display_name="已知人物", is_unknown=False)
    photos = [
        GalleryPhoto(filename=f"photo-{index}.jpg", sha256=str(index) * 64, object_key=f"gallery/{index}.jpg")
        for index in range(1, 5)
    ]
    db_session.add_all([workspace, unknown, known, *photos])
    db_session.flush()
    unknown.workspace_id = workspace.id
    known.workspace_id = workspace.id
    for photo in photos:
        photo.workspace_id = workspace.id
    db_session.flush()

    ignored = _face(workspace.id, photos[0].id)
    still_unknown = _face(workspace.id, photos[1].id)
    known_face = _face(workspace.id, photos[2].id, matched_person_id=known.id)
    pending_review = _face(workspace.id, photos[3].id, needs_review=True)
    db_session.add_all(
        [
            ignored,
            still_unknown,
            known_face,
            pending_review,
            GalleryPhotoPersonTag(
                gallery_photo_id=photos[1].id,
                person_id=unknown.id,
                source="unknown",
            ),
        ]
    )
    db_session.commit()
    ignored_id = ignored.id
    retained_ids = {still_unknown.id, known_face.id, pending_review.id}

    engine = db_session.get_bind()
    assert cleanup_ignored_gallery_face_records(engine) == 1
    assert cleanup_ignored_gallery_face_records(engine) == 0

    db_session.expire_all()
    remaining_ids = set(db_session.scalars(select(FaceRecord.id)).all())
    assert ignored_id not in remaining_ids
    assert retained_ids.issubset(remaining_ids)
    with engine.connect() as connection:
        marker_count = connection.scalar(
            text("SELECT COUNT(*) FROM app_schema_migrations WHERE migration_key=:key"),
            {"key": IGNORED_GALLERY_FACE_CLEANUP_KEY},
        )
    assert marker_count == 1
