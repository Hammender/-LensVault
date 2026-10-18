from __future__ import annotations

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, func, select, update

from app.api.face_cases import router
from app.core.config import Settings
from app.db import get_db
from app.dependencies.context import require_context
from app.models import FaceRecord, FaceRecognitionCase, FaceRecognitionCorrection, GalleryPhoto, Person, SamplePhoto, User, Workspace
from app.services.face_case_snapshots import face_revision
from app.services.importer import PictureService


class ObjectStream(BytesIO):
    def stream(self, size):
        while chunk := self.read(size):
            yield chunk

    def release_conn(self):
        pass


class CaseStorage:
    def __init__(self, key, payload):
        self.objects = {key: payload}
        self.fail_put = False
        self.fail_remove = False
        self.after_put = None

    def get_bytes(self, key):
        return self.objects[key]

    def put_bytes(self, key, payload, content_type=None):
        self.objects[key] = payload
        if self.fail_put:
            raise RuntimeError("模拟存储失败")
        if self.after_put:
            self.after_put()

    def remove_object(self, key):
        if self.fail_remove:
            raise RuntimeError("模拟清理失败")
        self.objects.pop(key, None)

    def get_stream(self, key, offset=0, length=None):
        data = self.objects[key]
        return ObjectStream(data[offset:None if length is None else offset + length])

    def stat_object(self, key):
        return SimpleNamespace(size=len(self.objects[key]))


@pytest.fixture
def cases(db_session, tmp_path):
    db = db_session
    user = User(username="case-tester", display_name="记录人", password_hash="unused")
    workspace = Workspace(name="案例测试")
    db.add_all([user, workspace]); db.flush()
    people = [Person(workspace_id=workspace.id, name=name, display_name=name, is_unknown=unknown)
              for name, unknown in [("未知人物", True), ("错误候选", False), ("正确人物", False)]]
    db.add_all(people); db.flush()
    image = Image.new("RGB", (80, 120), "white")
    exif = image.getexif(); exif[274] = 6
    stream = BytesIO(); image.save(stream, format="JPEG", exif=exif)
    payload = stream.getvalue()
    photo = GalleryPhoto(workspace_id=workspace.id, filename="案例.jpg", sha256=hashlib.sha256(payload).hexdigest(),
                         object_key="gallery/source.jpg", content_type="image/jpeg", width=80, height=120)
    db.add(photo); db.flush()
    face = FaceRecord(workspace_id=workspace.id, gallery_photo_id=photo.id, matched_person_id=people[0].id,
                      predicted_person_id=people[1].id, match_score=0.30, second_person_id=people[0].id,
                      second_match_score=0.28, match_margin=0.02, rejection_reason="below_threshold",
                      bbox_left=10, bbox_top=12, bbox_right=55, bbox_bottom=66, detection_score=0.98,
                      needs_review=True, embedding_version="case-model-v1", decision_threshold=0.4, decision_min_margin=0.06)
    db.add(face); db.flush()
    db.add(SamplePhoto(workspace_id=workspace.id, person_id=people[2].id, filename="sample.jpg", sha256="sample-hash",
                       object_key="sample/only-a-list.jpg", status="ready", source_type="gallery_face",
                       source_gallery_photo_id=photo.id, source_gallery_face_id=face.id))
    db.commit()
    storage = CaseStorage(photo.object_key, payload)
    settings = Settings(database_url=str(db.bind.url), data_dir=tmp_path)
    pictures = PictureService(storage, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), settings)
    context = SimpleNamespace(workspace_id=workspace.id, user=user, role="owner", membership=SimpleNamespace())
    app = FastAPI(); app.include_router(router)
    app.state.services = SimpleNamespace(storage=storage, pictures=pictures)
    app.state.settings = settings
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_context] = lambda: context
    with TestClient(app) as client:
        yield SimpleNamespace(db=db, client=client, storage=storage, photo=photo, face=face, people=people,
                              context=context, settings=settings, pictures=pictures, payload=payload)


def body(cases, **changes):
    return {"photo_id": cases.photo.id, "face_id": cases.face.id, "face_revision": face_revision(cases.face),
            "correct_person_id": cases.people[2].id, "issue_type": "unknown", "notes": "正脸清晰", **changes}


def record(cases, **changes):
    response = cases.client.post("/api/face-recognition-cases", json=body(cases, **changes))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("answer_type", ["out_of_library", "not_person"])
def test_negative_answers_preserve_binding_and_independent_evidence(cases, answer_type):
    cases.face.matched_person_id = cases.people[1].id
    cases.face.needs_review = False
    cases.db.commit()
    excluded_id = cases.people[1].id if answer_type == "not_person" else None
    item = record(cases, answer_type=answer_type, correct_person_id=None,
                  excluded_person_id=excluded_id, issue_type="wrong_person")
    assert item["answer_type"] == answer_type
    assert item["correct_person_id"] is None and item["correct_person_name"] == ""
    assert item["excluded_person_id"] == excluded_id
    truth = item["snapshot"]["ground_truth"]
    assert truth["answer_type"] == answer_type and truth["correct_person"] is None
    assert item["snapshot"]["schema_version"] == 2
    assert (truth["excluded_person"] is not None) == (answer_type == "not_person")
    manifest = item["snapshot"]["reference_samples_at_capture"]
    assert manifest["role"] == ("excluded_person" if excluded_id else "recognized_person")
    assert manifest["person_id"] == cases.people[1].id
    assert cases.face.matched_person_id == cases.people[1].id and not cases.face.needs_review
    assert cases.db.scalar(select(func.count()).select_from(Person)) == 3
    assert cases.db.scalar(select(func.count()).select_from(SamplePhoto)) == 1
    assert cases.db.scalar(select(func.count()).select_from(FaceRecognitionCorrection)) == 0
    assert cases.client.get(item["original_url"]).content == cases.payload
    filtered = cases.client.get("/api/face-recognition-cases", params={"answer_type": answer_type}).json()
    assert filtered["total"] == 1
    assert cases.client.get("/api/face-recognition-cases", params={"answer_type": "known_person"}).json()["total"] == 0
    response = cases.client.post("/api/face-recognition-cases/export", json={"answer_type": answer_type})
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        exported = json.loads(archive.read("cases.jsonl"))
        assert exported["answer_type"] == answer_type
        assert exported["snapshot"]["ground_truth"] == truth
        assert "人工结论" in archive.read("summary.csv").decode("utf-8-sig")
    if excluded_id:
        assert cases.client.get("/api/face-recognition-cases", params={"correct_person_name": "错误候选"}).json()["total"] == 1
        cases.db.execute(delete(Person).where(Person.id == excluded_id))
        cases.db.commit(); cases.db.expire_all()
        stored = cases.client.get(f"/api/face-recognition-cases/{item['id']}").json()
        assert stored["excluded_person_id"] is None
        assert stored["excluded_person_name"] == "错误候选"
        assert stored["snapshot"]["ground_truth"] == truth


@pytest.mark.parametrize("changes", [
    {"answer_type": "out_of_library"},
    {"answer_type": "not_person", "correct_person_id": None},
    {"answer_type": "known_person", "correct_person_id": None},
    {"answer_type": "out_of_library", "correct_person_id": None, "issue_type": "unknown"},
    {"answer_type": "out_of_library", "correct_person_id": None, "issue_type": "wrong_person", "bind_person": True},
    {"answer_type": "out_of_library", "correct_person_id": None, "issue_type": "wrong_person", "excluded_person_id": 1},
    {"answer_type": "known_person", "excluded_person_id": 1},
])
def test_inconsistent_ground_truth_rejected_without_writes(cases, changes):
    assert cases.client.post("/api/face-recognition-cases", json=body(cases, **changes)).status_code == 422
    assert len(cases.storage.objects) == 1
    assert cases.db.scalar(select(func.count()).select_from(FaceRecognitionCase)) == 0


def test_excluded_person_requires_formal_person_in_current_workspace(cases):
    for person_id in (cases.people[0].id, 987654):
        response = cases.client.post("/api/face-recognition-cases", json=body(cases,
            answer_type="not_person", correct_person_id=None, excluded_person_id=person_id, issue_type="wrong_person"))
        assert response.status_code == 400
    other = Workspace(name="其他工作区"); cases.db.add(other); cases.db.flush()
    person = Person(workspace_id=other.id, name="其他", display_name="其他")
    cases.db.add(person); cases.db.commit()
    assert cases.client.post("/api/face-recognition-cases", json=body(cases,
        answer_type="not_person", correct_person_id=None, excluded_person_id=person.id,
        issue_type="wrong_person")).status_code == 400


def test_out_of_library_without_reference_has_empty_manifest(cases):
    item = record(cases, answer_type="out_of_library", correct_person_id=None, issue_type="other")
    manifest = item["snapshot"]["reference_samples_at_capture"]
    assert manifest["person_id"] is None and manifest["role"] is None
    assert manifest["samples"] == []


@pytest.mark.parametrize("issue", ["unknown", "wrong_person", "other"])
def test_snapshot_retains_original_bytes_candidates_and_sample_list(cases, issue):
    if issue == "wrong_person":
        cases.face.matched_person_id = cases.people[1].id
        cases.face.needs_review = False
        cases.db.commit()
    before = cases.face.matched_person_id
    item = record(cases, issue_type=issue)
    snapshot = item["snapshot"]
    assert item["answer_type"] == "known_person"
    assert snapshot["ground_truth"]["correct_person"]["id"] == cases.people[2].id
    assert snapshot["recognition"]["predicted_person_id"] != cases.people[2].id
    assert snapshot["recognition"]["second_person_id"] != cases.people[2].id
    assert snapshot["recognition"]["decision_threshold"] == 0.4
    assert snapshot["reference_samples_at_capture"]["ready_count"] == 1
    assert snapshot["reference_samples_at_capture"]["images_included"] is False
    assert snapshot["same_photo_sample_ids_at_capture"]
    assert snapshot["photo"]["display_width"] == 120
    assert snapshot["photo"]["display_height"] == 80
    assert snapshot["coordinate_space"] == "exif_transposed_pixels"
    assert cases.face.matched_person_id == before
    assert cases.face.needs_review == (issue != "wrong_person")
    assert cases.db.scalar(select(func.count()).select_from(FaceRecognitionCorrection)) == 0
    assert len(cases.storage.objects) == 2
    response = cases.client.get(item["original_url"])
    assert response.status_code == 200 and response.content == cases.payload
    assert cases.client.get(item["thumbnail_url"]).status_code == 200


def test_duplicate_survives_manual_binding_but_new_recognition_is_new_case(cases):
    first = record(cases)
    cases.face.matched_person_id = cases.people[2].id; cases.face.needs_review = False
    cases.db.commit()
    assert record(cases)["id"] == first["id"]
    cases.face.match_score = 0.5; cases.face.embedding_version = "case-model-v2"
    cases.db.commit()
    assert record(cases)["id"] != first["id"]
    assert len(cases.storage.objects) == 3


def test_stale_revision_and_cross_workspace_and_unknown_target_rejected(cases):
    stale = body(cases)
    cases.face.needs_review = False; cases.db.commit()
    assert cases.client.post("/api/face-recognition-cases", json=stale).status_code == 409
    assert cases.client.post("/api/face-recognition-cases", json=body(cases, correct_person_id=cases.people[0].id)).status_code == 400
    other = Workspace(name="其他工作区"); cases.db.add(other); cases.db.flush()
    person = Person(name="其他人物", display_name="其他人物", workspace_id=other.id)
    cases.db.add(person); cases.db.commit()
    assert cases.client.post("/api/face-recognition-cases", json=body(cases, correct_person_id=person.id)).status_code == 400
    assert len(cases.storage.objects) == 1


def test_optional_bind_uses_original_snapshot_and_correction_transaction(cases):
    cases.db.execute(delete(SamplePhoto)); cases.db.commit()
    original = cases.face.matched_person_id
    item = record(cases, bind_person=True)
    assert item["snapshot"]["binding_at_capture"]["person_id"] == original
    assert cases.face.matched_person_id == cases.people[2].id
    assert cases.face.needs_review is False
    assert cases.db.scalar(select(func.count()).select_from(FaceRecognitionCorrection)) == 1
    assert cases.db.scalar(select(func.count()).select_from(SamplePhoto)) == 0


def test_sample_lock_allows_record_but_blocks_optional_bind(cases):
    response = cases.client.post("/api/face-recognition-cases", json=body(cases, bind_person=True))
    assert response.status_code == 409
    assert len(cases.storage.objects) == 1
    assert record(cases)["id"]


def test_no_ready_samples_can_still_be_recorded(cases):
    cases.db.execute(delete(SamplePhoto)); cases.db.commit()
    assert record(cases)["snapshot"]["reference_samples_at_capture"]["ready_count"] == 0


def test_source_photo_face_person_deletion_does_not_destroy_case(cases):
    item = record(cases)
    photo_id = cases.photo.id; person_id = cases.people[2].id
    cases.db.execute(delete(GalleryPhoto).where(GalleryPhoto.id == photo_id))
    cases.db.execute(delete(Person).where(Person.id == person_id)); cases.db.commit(); cases.db.expire_all()
    cases.storage.objects.pop("gallery/source.jpg")
    detail = cases.client.get(f"/api/face-recognition-cases/{item['id']}").json()
    assert detail["source_photo_id"] is None and detail["correct_person_id"] is None
    assert detail["snapshot"]["photo"]["id"] == photo_id
    assert detail["snapshot"]["correct_person"]["id"] == person_id
    assert cases.client.get(item["original_url"]).content == cases.payload
    assert cases.client.post("/api/face-recognition-cases/export", json={"case_ids": [item["id"]]}).status_code == 200


def test_copy_failure_and_commit_failure_clean_only_new_asset(cases, monkeypatch):
    cases.storage.fail_put = True
    assert cases.client.post("/api/face-recognition-cases", json=body(cases)).status_code == 503
    assert len(cases.storage.objects) == 1
    cases.storage.fail_put = False
    cases.db.execute(delete(SamplePhoto)); cases.db.commit()
    def fail():
        raise RuntimeError("模拟提交失败")
    monkeypatch.setattr(cases.db, "commit", fail)
    assert cases.client.post("/api/face-recognition-cases", json=body(cases, bind_person=True)).status_code == 503
    assert len(cases.storage.objects) == 1
    assert cases.db.scalar(select(func.count()).select_from(FaceRecognitionCase)) == 0
    assert cases.db.scalar(select(func.count()).select_from(FaceRecognitionCorrection)) == 0
    assert cases.face.matched_person_id == cases.people[0].id


def test_concurrent_face_change_during_archive_is_rejected(cases):
    cases.storage.after_put = lambda: cases.db.execute(update(FaceRecord).where(FaceRecord.id == cases.face.id).values(match_score=0.9))
    assert cases.client.post("/api/face-recognition-cases", json=body(cases)).status_code == 409
    assert len(cases.storage.objects) == 1


def test_filters_notes_permissions_and_workspace_isolation(cases):
    item = record(cases)
    prefix = f"/api/face-recognition-cases/{item['id']}"
    response = cases.client.patch(prefix, json={"notes": "补充说明"})
    assert response.json()["notes"] == "补充说明"
    assert response.json()["snapshot"] == item["snapshot"]
    assert cases.client.get("/api/face-recognition-cases?correct_person_name=正确&issue_type=unknown&embedding_version=case-model-v1").json()["total"] == 1
    assert cases.client.get("/api/face-recognition-cases?correct_person_name=不存在").json()["total"] == 0
    cases.context.role = "member"; cases.context.membership.can_edit_gallery = False; cases.context.membership.can_delete_gallery = False
    assert cases.client.post("/api/face-recognition-cases", json=body(cases)).status_code == 403
    assert cases.client.patch(prefix, json={"notes": "不能编辑"}).status_code == 403
    assert cases.client.delete(prefix).status_code == 403
    assert cases.client.get(prefix).status_code == 200
    cases.context.workspace_id += 100
    for suffix in ["", "/original", "/thumbnail"]:
        assert cases.client.get(prefix + suffix).status_code == 404
    assert cases.client.get("/api/face-recognition-cases").json()["total"] == 0
    assert cases.client.post("/api/face-recognition-cases/export", json={"case_ids": [item["id"]]}).status_code == 404


def test_export_deduplicates_images_and_contains_no_reference_images(cases):
    first = record(cases, notes="=1+1")
    second_face = FaceRecord(workspace_id=cases.context.workspace_id, gallery_photo_id=cases.photo.id,
                            bbox_left=60, bbox_top=10, bbox_right=100, bbox_bottom=50, needs_review=True)
    cases.db.add(second_face); cases.db.commit()
    cases.face = second_face
    second = record(cases)
    response = cases.client.post("/api/face-recognition-cases/export", json={"case_ids": [first["id"], second["id"]]})
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        images = [name for name in archive.namelist() if name.startswith("images/")]
        assert len(images) == 1 and archive.read(images[0]) == cases.payload
        records = [json.loads(line) for line in archive.read("cases.jsonl").decode().splitlines()]
        assert len(records) == 2 and all(row["image_path"] == images[0] for row in records)
        assert "'=1+1" in archive.read("summary.csv").decode("utf-8-sig")
        assert not any(name.startswith("samples/") for name in archive.namelist())
        assert "说明.md" in archive.namelist()
    cases.storage.objects.pop(next(key for key in cases.storage.objects if first["id"] in key))
    assert cases.client.post("/api/face-recognition-cases/export", json={"case_ids": [first["id"]]}).status_code == 503


def test_failed_delete_is_visible_retryable_and_preserves_gallery(cases):
    item = record(cases)
    prefix = f"/api/face-recognition-cases/{item['id']}"
    cases.storage.fail_remove = True
    assert cases.client.delete(prefix).status_code == 503
    assert cases.client.get(prefix).json()["status"] == "deleting"
    assert cases.client.get("/api/face-recognition-cases").json()["total"] == 1
    assert cases.client.post("/api/face-recognition-cases/export", json={"case_ids": [item["id"]]}).status_code == 409
    cases.storage.fail_remove = False
    assert cases.client.delete(prefix).status_code == 200
    assert cases.client.get(prefix).status_code == 404
    assert list(cases.storage.objects) == [cases.photo.object_key]
    assert cases.db.get(GalleryPhoto, cases.photo.id) is not None


def test_failed_submission_and_cleanup_keep_retry_receipt(cases, monkeypatch):
    commit = cases.db.commit
    calls = 0
    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("提交失败")
        commit()
    monkeypatch.setattr(cases.db, "commit", fail_once)
    cases.storage.fail_remove = True
    assert cases.client.post("/api/face-recognition-cases", json=body(cases)).status_code == 503
    item = cases.client.get("/api/face-recognition-cases").json()["items"][0]
    assert item["status"] == "deleting"
    assert item["cleanup_error"]
    cases.storage.fail_remove = False
    assert cases.client.delete(f"/api/face-recognition-cases/{item['id']}").status_code == 200
    assert list(cases.storage.objects) == [cases.photo.object_key]
