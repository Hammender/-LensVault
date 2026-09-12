from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.gallery import router as gallery_router
from app.db import get_db
from app.dependencies.context import require_context
from app.models import (
    FaceRecognitionCorrection,
    FaceRecord,
    GalleryPhoto,
    GalleryPhotoPersonTag,
    GalleryPhotoTag,
    Person,
    PersonTag,
    Tag,
    Workspace,
)
from app.services.importer import PictureService


def _picture_service() -> PictureService:
    return PictureService(
        storage=SimpleNamespace(),
        face_service=SimpleNamespace(),
        vector_store=SimpleNamespace(),
        ocr_service=SimpleNamespace(),
        settings=SimpleNamespace(face_embedding_version="test-v1"),
    )


def _client(db_session, workspace_id: int) -> TestClient:
    app = FastAPI()
    app.state.services = SimpleNamespace(pictures=_picture_service())
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_context] = lambda: SimpleNamespace(workspace_id=workspace_id)
    app.include_router(gallery_router)
    return TestClient(app, raise_server_exceptions=True)


def _add_workspace_people_and_photo(db_session):
    workspace = Workspace(name="测试空间")
    unknown = Person(
        name="__system_unknown_person__:1",
        display_name="未知人物",
        is_unknown=True,
    )
    first = Person(name="first", display_name="第一人物", is_unknown=False)
    second = Person(name="second", display_name="第二人物", is_unknown=False)
    photo = GalleryPhoto(filename="photo.jpg", sha256="a" * 64, object_key="gallery/photo.jpg")
    db_session.add_all([workspace, unknown, first, second, photo])
    db_session.flush()
    unknown.workspace_id = workspace.id
    first.workspace_id = workspace.id
    second.workspace_id = workspace.id
    photo.workspace_id = workspace.id
    db_session.flush()
    return workspace, unknown, first, second, photo


def _face(workspace_id: int, photo_id: int, matched_person_id: int, offset: int = 0) -> FaceRecord:
    return FaceRecord(
        workspace_id=workspace_id,
        gallery_photo_id=photo_id,
        bbox_left=1 + offset,
        bbox_top=2 + offset,
        bbox_right=30 + offset,
        bbox_bottom=40 + offset,
        matched_person_id=matched_person_id,
        needs_review=True,
    )


def test_unlink_unknown_person_deletes_unknown_face_records(db_session) -> None:
    workspace, unknown, _, _, photo = _add_workspace_people_and_photo(db_session)
    link = GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=unknown.id, source="unknown")
    face = _face(workspace.id, photo.id, unknown.id)
    db_session.add_all([link, face])
    db_session.commit()
    face_id = face.id

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/persons/{unknown.id}")

    assert response.status_code == 200
    assert db_session.get(FaceRecord, face_id) is None
    assert db_session.get(GalleryPhotoPersonTag, link.id) is None
    assert response.json()["faces"] == []


def test_unlink_unknown_person_in_multi_face_photo_preserves_known_faces_and_tags(db_session) -> None:
    workspace, unknown, first, second, photo = _add_workspace_people_and_photo(db_session)
    links = [
        GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=unknown.id, source="unknown"),
        GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="manual"),
        GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=second.id, source="manual"),
    ]
    known_face = _face(workspace.id, photo.id, first.id)
    known_face.needs_review = False
    unknown_faces = [_face(workspace.id, photo.id, unknown.id, 50), _face(workspace.id, photo.id, unknown.id, 100)]
    db_session.add_all([*links, known_face, *unknown_faces])
    db_session.commit()
    known_face_id = known_face.id
    unknown_face_ids = [face.id for face in unknown_faces]

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/persons/{unknown.id}")

    assert response.status_code == 200
    assert db_session.get(FaceRecord, known_face_id) is not None
    assert all(db_session.get(FaceRecord, face_id) is None for face_id in unknown_face_ids)
    remaining_person_ids = set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id)
        ).all()
    )
    assert remaining_person_ids == {first.id, second.id}
    assert [face["id"] for face in response.json()["faces"]] == [known_face_id]


def test_unbind_one_of_two_faces_sharing_person_preserves_other_face(db_session) -> None:
    workspace, unknown, first, _, photo = _add_workspace_people_and_photo(db_session)
    person_link = GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="auto")
    first_face = _face(workspace.id, photo.id, first.id)
    second_face = _face(workspace.id, photo.id, first.id, 50)
    db_session.add_all([person_link, first_face, second_face])
    db_session.commit()
    first_face_id = first_face.id
    second_face_id = second_face.id

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/faces/{first_face_id}/person")

    assert response.status_code == 200
    updated_first = db_session.get(FaceRecord, first_face_id)
    updated_second = db_session.get(FaceRecord, second_face_id)
    assert updated_first is not None
    assert updated_first.matched_person_id == unknown.id
    assert updated_first.needs_review is True
    assert updated_second is not None
    assert updated_second.matched_person_id == first.id
    assert db_session.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo.id,
            GalleryPhotoPersonTag.person_id == first.id,
        )
    ) is not None


def test_add_person_to_single_face_photo_rebinds_face_and_removes_unknown_tag(db_session) -> None:
    workspace, unknown, first, _, photo = _add_workspace_people_and_photo(db_session)
    unknown_link = GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=unknown.id, source="unknown")
    face = _face(workspace.id, photo.id, unknown.id)
    face.predicted_person_id = first.id
    face.match_score = 0.61
    db_session.add_all([unknown_link, face])
    db_session.commit()
    face_id = face.id

    with _client(db_session, workspace.id) as client:
        response = client.post(f"/api/gallery/photos/{photo.id}/persons", json={"person_id": first.id})

    assert response.status_code == 200
    rebound_face = db_session.get(FaceRecord, face_id)
    assert rebound_face is not None
    assert rebound_face.matched_person_id == first.id
    assert rebound_face.needs_review is False
    person_ids = set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id)
        ).all()
    )
    assert person_ids == {first.id}
    correction = db_session.scalar(
        select(FaceRecognitionCorrection).where(FaceRecognitionCorrection.face_record_id == face_id)
    )
    assert correction is not None
    assert correction.corrected_person_id == first.id


def _tag_names(payload: dict) -> set[str]:
    return {item["name"] for item in payload["tags"]}


def _photo_tag_names(db_session, photo_id: int) -> set[str]:
    return set(
        db_session.scalars(
            select(Tag.name)
            .join(GalleryPhotoTag, GalleryPhotoTag.tag_id == Tag.id)
            .where(GalleryPhotoTag.gallery_photo_id == photo_id)
        ).all()
    )


def _photo_tag_sources(db_session, photo_id: int) -> dict[str, str]:
    return {
        tag.name: link.source
        for link in db_session.scalars(
            select(GalleryPhotoTag).where(GalleryPhotoTag.gallery_photo_id == photo_id)
        ).all()
        for tag in [db_session.get(Tag, link.tag_id)]
        if tag is not None
    }


def test_rebind_face_drops_old_person_inherited_tags(db_session) -> None:
    workspace, unknown, first, second, photo = _add_workspace_people_and_photo(db_session)
    aespa = Tag(name="aespa", workspace_id=workspace.id)
    ive = Tag(name="IVE", workspace_id=workspace.id)
    korea = Tag(name="韩娱", workspace_id=workspace.id)
    db_session.add_all([aespa, ive, korea])
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=first.id, tag_id=aespa.id),
            PersonTag(person_id=first.id, tag_id=korea.id),
            PersonTag(person_id=second.id, tag_id=ive.id),
            PersonTag(person_id=second.id, tag_id=korea.id),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="auto"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=aespa.id, source="person"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=korea.id, source="person"),
        ]
    )
    face = _face(workspace.id, photo.id, first.id)
    face.needs_review = False
    db_session.add(face)
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.patch(
            f"/api/gallery/photos/{photo.id}/faces/{face.id}/person",
            json={"person_id": second.id},
        )

    assert response.status_code == 200
    assert _tag_names(response.json()) == {"IVE", "韩娱"}
    assert _photo_tag_names(db_session, photo.id) == {"IVE", "韩娱"}
    assert _photo_tag_sources(db_session, photo.id) == {"IVE": "person", "韩娱": "person"}
    remaining_person_ids = set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id)
        ).all()
    )
    assert remaining_person_ids == {second.id}


def test_unbind_face_drops_old_person_inherited_tags(db_session) -> None:
    workspace, unknown, first, second, photo = _add_workspace_people_and_photo(db_session)
    aespa = Tag(name="aespa", workspace_id=workspace.id)
    ive = Tag(name="IVE", workspace_id=workspace.id)
    korea = Tag(name="韩娱", workspace_id=workspace.id)
    db_session.add_all([aespa, ive, korea])
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=first.id, tag_id=aespa.id),
            PersonTag(person_id=first.id, tag_id=korea.id),
            PersonTag(person_id=second.id, tag_id=ive.id),
            PersonTag(person_id=second.id, tag_id=korea.id),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="auto"),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=second.id, source="manual"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=aespa.id, source="person"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=ive.id, source="person"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=korea.id, source="person"),
        ]
    )
    face = _face(workspace.id, photo.id, first.id)
    face.needs_review = False
    db_session.add(face)
    db_session.commit()
    face_id = face.id

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/faces/{face_id}/person")

    assert response.status_code == 200
    assert _tag_names(response.json()) == {"IVE", "韩娱"}
    assert _photo_tag_names(db_session, photo.id) == {"IVE", "韩娱"}
    remaining_person_ids = set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id)
        ).all()
    )
    assert remaining_person_ids == {second.id, unknown.id}


def test_unbind_one_of_two_faces_keeps_shared_person_inherited_tags(db_session) -> None:
    workspace, unknown, first, _, photo = _add_workspace_people_and_photo(db_session)
    aespa = Tag(name="aespa", workspace_id=workspace.id)
    db_session.add(aespa)
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=first.id, tag_id=aespa.id),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="auto"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=aespa.id, source="person"),
        ]
    )
    first_face = _face(workspace.id, photo.id, first.id)
    second_face = _face(workspace.id, photo.id, first.id, 50)
    db_session.add_all([first_face, second_face])
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/faces/{first_face.id}/person")

    assert response.status_code == 200
    assert _tag_names(response.json()) == {"aespa"}
    assert db_session.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo.id,
            GalleryPhotoPersonTag.person_id == first.id,
        )
    ) is not None


def test_rebind_keeps_manual_person_tag_and_its_inherited_tags(db_session) -> None:
    workspace, unknown, first, second, photo = _add_workspace_people_and_photo(db_session)
    aespa = Tag(name="aespa", workspace_id=workspace.id)
    ive = Tag(name="IVE", workspace_id=workspace.id)
    db_session.add_all([aespa, ive])
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=first.id, tag_id=aespa.id),
            PersonTag(person_id=second.id, tag_id=ive.id),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="manual"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=aespa.id, source="person"),
        ]
    )
    face = _face(workspace.id, photo.id, first.id)
    face.needs_review = False
    db_session.add(face)
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.patch(
            f"/api/gallery/photos/{photo.id}/faces/{face.id}/person",
            json={"person_id": second.id},
        )

    assert response.status_code == 200
    assert _tag_names(response.json()) == {"aespa", "IVE"}
    remaining_person_ids = set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id)
        ).all()
    )
    assert remaining_person_ids == {first.id, second.id}


def test_unbind_does_not_remove_manual_gallery_tag(db_session) -> None:
    workspace, unknown, first, _, photo = _add_workspace_people_and_photo(db_session)
    aespa = Tag(name="aespa", workspace_id=workspace.id)
    db_session.add(aespa)
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=first.id, tag_id=aespa.id),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="auto"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=aespa.id, source="manual"),
        ]
    )
    face = _face(workspace.id, photo.id, first.id)
    face.needs_review = False
    db_session.add(face)
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/faces/{face.id}/person")

    assert response.status_code == 200
    assert _tag_names(response.json()) == {"aespa"}
    assert _photo_tag_sources(db_session, photo.id) == {"aespa": "manual"}


def test_delete_person_tag_drops_unneeded_inherited_tags(db_session) -> None:
    workspace, unknown, first, second, photo = _add_workspace_people_and_photo(db_session)
    aespa = Tag(name="aespa", workspace_id=workspace.id)
    korea = Tag(name="韩娱", workspace_id=workspace.id)
    db_session.add_all([aespa, korea])
    db_session.flush()
    db_session.add_all(
        [
            PersonTag(person_id=first.id, tag_id=aespa.id),
            PersonTag(person_id=first.id, tag_id=korea.id),
            PersonTag(person_id=second.id, tag_id=korea.id),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=first.id, source="manual"),
            GalleryPhotoPersonTag(gallery_photo_id=photo.id, person_id=second.id, source="manual"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=aespa.id, source="person"),
            GalleryPhotoTag(gallery_photo_id=photo.id, tag_id=korea.id, source="person"),
        ]
    )
    db_session.commit()

    with _client(db_session, workspace.id) as client:
        response = client.delete(f"/api/gallery/photos/{photo.id}/persons/{first.id}")

    assert response.status_code == 200
    assert _tag_names(response.json()) == {"韩娱"}
    remaining_person_ids = set(
        db_session.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo.id)
        ).all()
    )
    assert remaining_person_ids == {second.id}
