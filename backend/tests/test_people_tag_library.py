from types import SimpleNamespace

from sqlalchemy import select

from app.api.people import delete_tag, list_persons, update_tag
from app.mappers.people import person_to_read
from app.models import GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, PersonTag, Tag, Workspace
from app.schemas import TagUpdate


def test_person_tag_ids_use_direct_bindings_and_workspace_scope(db_session):
    workspace = Workspace(name="主空间")
    other = Workspace(name="其他空间")
    db_session.add_all([workspace, other])
    db_session.flush()
    alice = Person(workspace_id=workspace.id, name="Alice", display_name="Alice")
    bob = Person(workspace_id=workspace.id, name="Bob", display_name="Bob")
    foreign = Person(workspace_id=other.id, name="其他人物", display_name="其他人物")
    tag = Tag(workspace_id=workspace.id, name="户外")
    photo = GalleryPhoto(workspace_id=workspace.id, filename="a.jpg", sha256="a" * 64, object_key="a.jpg")
    db_session.add_all([alice, bob, foreign, tag, photo])
    db_session.flush()
    db_session.add_all([
        PersonTag(person_id=alice.id, tag_id=tag.id),
        GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=bob.id),
        GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=tag.id),
    ])
    db_session.commit()

    result = list_persons(is_unknown=None, db=db_session, current=SimpleNamespace(workspace_id=workspace.id))

    assert {item.id: item.tag_ids for item in result} == {alice.id: [tag.id], bob.id: []}
    assert person_to_read(db_session, alice).tag_ids == [tag.id]


def test_tag_rename_and_delete_update_bindings_without_deleting_media(db_session):
    workspace = Workspace(name="主空间")
    db_session.add(workspace)
    db_session.flush()
    person = Person(workspace_id=workspace.id, name="Alice", display_name="Alice")
    tag = Tag(workspace_id=workspace.id, name="户外")
    photo = GalleryPhoto(workspace_id=workspace.id, filename="a.jpg", sha256="a" * 64, object_key="a.jpg")
    db_session.add_all([person, tag, photo])
    db_session.flush()
    db_session.add_all([PersonTag(person_id=person.id, tag_id=tag.id), GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=tag.id)])
    db_session.commit()
    current = SimpleNamespace(workspace_id=workspace.id)

    updated = update_tag(tag.id, TagUpdate(name="自然"), db=db_session, current=current)
    assert updated.name == "自然"
    assert person_to_read(db_session, person).tag_ids == [tag.id]

    delete_tag(tag.id, db=db_session, current=current)
    db_session.expire_all()
    assert person_to_read(db_session, person).tag_ids == []
    assert db_session.scalar(select(PersonTag.id)) is None
    assert db_session.scalar(select(GalleryPhotoTag.id)) is None
    assert db_session.get(Person, person.id) is not None
    assert db_session.get(GalleryPhoto, photo.id) is not None
