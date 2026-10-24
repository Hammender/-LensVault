from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
from zipfile import ZipFile

import numpy as np
from PIL import Image
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db import Base
from app.models import Person, SamplePhoto, Task, Workspace
from app.services.face import DetectedFace
from app.services.importer import PictureService
from app.services.tasks import record_task_progress


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, object_key: str, payload: bytes, _content_type: str | None = None) -> None:
        self.objects[object_key] = payload


class SingleFaceService:
    def detect_faces(self, _payload: bytes) -> list[DetectedFace]:
        return [
            DetectedFace(
                (10, 10, 110, 110),
                0.99,
                np.ones(512, dtype=np.float32),
                100,
                90,
                0,
            )
        ]


class MemoryVectorStore:
    def __init__(self) -> None:
        self.faces: dict[int, np.ndarray] = {}
        self.centroids: dict[int, np.ndarray] = {}

    def upsert_face(
        self,
        _collection: str,
        face_id: int,
        _person_id: int,
        vector: np.ndarray,
        **_kwargs: object,
    ) -> None:
        self.faces[face_id] = np.asarray(vector, dtype=np.float32)

    def get_reference_vector(self, _collection: str, face_id: int, **_kwargs: object) -> np.ndarray:
        return self.faces[face_id]

    def upsert_centroid(
        self,
        _collection: str,
        person_id: int,
        vector: np.ndarray,
        **_kwargs: object,
    ) -> None:
        self.centroids[person_id] = np.asarray(vector, dtype=np.float32)

    def delete_centroid(self, _collection: str, _workspace_id: int | None, person_id: int, _version: str) -> None:
        self.centroids.pop(person_id, None)


class NoopOcrService:
    def extract_text(self, _payload: bytes) -> str:
        return ""


def _image_bytes(color: str) -> bytes:
    image = Image.new("RGB", (120, 120), color)
    source = BytesIO()
    image.save(source, format="JPEG")
    return source.getvalue()


def _person_zip(name: str, payloads: list[bytes]) -> bytes:
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        samples = []
        for index, payload in enumerate(payloads, start=1):
            filename = f"{index}.jpg"
            archive.writestr(f"samples/{name}/{filename}", payload)
            samples.append(
                {
                    "filename": filename,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "content_type": "image/jpeg",
                    "width": 120,
                    "height": 120,
                }
            )
        archive.writestr(
            "metadata.json",
            json.dumps({"persons": [{"name": name, "display_name": name, "tags": [], "samples": samples}]}),
        )
    return source.getvalue()


def _file_sqlite_factory(tmp_dir: Path):
    engine = create_engine(
        f"sqlite:///{(tmp_dir / 'import.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=2000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, factory


def _make_service() -> PictureService:
    return PictureService(  # type: ignore[arg-type]
        MemoryStorage(),
        SingleFaceService(),
        MemoryVectorStore(),
        NoopOcrService(),
        Settings(),
    )


def test_person_zip_import_commits_before_progress_callback() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white"), _image_bytes("gray")])
    db = factory()
    try:
        workspace = Workspace(name="主空间")
        db.add(workspace)
        db.flush()
        db.add(Task(id="person-import", workspace_id=workspace.id, kind="person_import", status="running", progress=0.0))
        db.commit()
        workspace_id = workspace.id
        seen_person: list[bool] = []
        progress_writes: list[str] = []

        def progress_callback(processed: int, total: int) -> None:
            other = factory()
            try:
                seen_person.append(other.scalar(select(Person).where(Person.name == "金米妮")) is not None)
                task = other.get(Task, "person-import")
                assert task is not None
                task.message = f"{processed}/{total}"
                other.commit()
                progress_writes.append(f"{processed}/{total}")
            finally:
                other.close()

        result = _make_service().import_persons_from_zip(db, archive, workspace_id, progress_callback)
        assert result["created_persons"] == 1
        assert result["added_samples"] == 2
        assert seen_person == [True, True]
        assert progress_writes == ["1/2", "2/2"]
        db.expire_all()
        person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
        assert person is not None
        samples = db.scalars(select(SamplePhoto).where(SamplePhoto.person_id == person.id)).all()
        assert len(samples) == 2
        assert {sample.status for sample in samples} == {"ready"}
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_person_zip_import_keeps_person_when_progress_callback_fails() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white")])
    db = factory()
    try:
        workspace = Workspace(name="主空间")
        db.add(workspace)
        db.commit()
        workspace_id = workspace.id

        def boom(_processed: int, _total: int) -> None:
            raise RuntimeError("database is locked")

        result = _make_service().import_persons_from_zip(db, archive, workspace_id, boom)
        assert result["created_persons"] == 1
        assert result["added_samples"] == 1
        db.expire_all()
        person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
        assert person is not None
        sample = db.scalar(select(SamplePhoto).where(SamplePhoto.person_id == person.id))
        assert sample is not None
        assert sample.status == "ready"
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_record_task_progress_does_not_raise_when_update_fails() -> None:
    def broken_factory() -> Session:
        raise RuntimeError("database is locked")

    record_task_progress(broken_factory, "missing-task", progress=0.1, message="正在处理 1/13 个样本", force=True)
