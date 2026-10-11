from __future__ import annotations

import sqlite3
import threading
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base
from app.native_runtime import (
    configure_opencv_threads,
    create_onnx_inference_session,
    create_onnx_session_options,
    insightface_session_options,
    read_library_thread_count,
)
from app.services.face import DetectedFace
from app.services.importer import PictureService
from app.services.similarity import ensure_perceptual_feature_dependencies
from face_runtime.adapters import create_adapter
from face_runtime.runtime import FaceRuntime


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, object_key: str, payload: bytes, _content_type: str | None = None) -> None:
        self.objects[object_key] = payload

    def get_bytes(self, object_key: str) -> bytes:
        return self.objects[object_key]

    def remove_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


class FakeVectorStore:
    def search_candidates(self, *_args: object, **_kwargs: object) -> list[object]:
        return []


class FakeOcrService:
    def extract_text(self, _payload: bytes) -> str:
        return ""


class RecordingFaceService:
    def __init__(self) -> None:
        self.bytes_calls = 0
        self.bgr_calls = 0

    def detect_faces(self, _payload: bytes) -> list[DetectedFace]:
        self.bytes_calls += 1
        return []

    def detect_faces_bgr(self, _array: np.ndarray) -> list[DetectedFace]:
        self.bgr_calls += 1
        return []


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (24, 16), "white")
    source = BytesIO()
    image.save(source, format="JPEG")
    return source.getvalue()


def test_library_thread_count_defaults_to_four() -> None:
    assert read_library_thread_count() >= 1


def test_onnx_session_options_use_configured_thread_limits() -> None:
    options = create_onnx_session_options(4)
    assert options.intra_op_num_threads == 4
    assert options.inter_op_num_threads == 1


def test_opencv_threads_are_set_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.native_runtime as native
    import cv2

    calls: list[int] = []
    monkeypatch.setattr(native, "_opencv_configured", False)
    monkeypatch.setattr(cv2, "setNumThreads", lambda value: calls.append(value))

    configure_opencv_threads(4)
    configure_opencv_threads(1)

    assert calls == [4]


def test_perceptual_dependency_check_does_not_change_opencv_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    def fail(_value: int) -> None:
        raise AssertionError("运行期不得再次调用 setNumThreads")

    monkeypatch.setattr(cv2, "setNumThreads", fail)
    ensure_perceptual_feature_dependencies()


def test_insightface_detector_session_receives_session_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from insightface.model_zoo import model_zoo

    captured: dict[str, object] = {}

    class DummySession:
        def __init__(self, model_path: str, **kwargs: object) -> None:
            captured.update(kwargs)
            self.model_path = model_path
            self._options = kwargs.get("sess_options")

        def get_session_options(self) -> object:
            return self._options

    monkeypatch.setattr(model_zoo, "PickableInferenceSession", DummySession)
    with insightface_session_options():
        session = model_zoo.PickableInferenceSession("det.onnx", providers=["CPUExecutionProvider"])

    options = session.get_session_options()
    assert options is not None
    assert options.intra_op_num_threads == read_library_thread_count()
    assert options.inter_op_num_threads == 1
    assert "sess_options" in captured


def test_recognition_adapter_uses_onnx_session_factory() -> None:
    captured: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as folder:
        model_path = Path(folder) / "w600k_r50.onnx"
        model_path.write_bytes(b"onnx")
        _assert_recognition_adapter_uses_factory(captured, model_path)


def _assert_recognition_adapter_uses_factory(captured: dict[str, object], model_path: Path) -> None:

    class FakeSession:
        def __init__(self) -> None:
            self._options = create_onnx_session_options(4)

        def get_inputs(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(name="input", shape=[None, 3, 112, 112])]

        def get_outputs(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(name="output", shape=[None, 512])]

        def get_providers(self) -> list[str]:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        def get_session_options(self) -> object:
            return self._options

    def factory(path: object, *, providers: list[str], provider_options: object = None) -> FakeSession:
        captured["path"] = str(path)
        captured["providers"] = providers
        captured["provider_options"] = provider_options
        return FakeSession()

    adapter = create_adapter(
        "buffalo_l",
        model_path=model_path,
        detector_pack="buffalo_l",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        create_session=factory,
    )
    options = adapter.session.get_session_options()
    assert captured["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert options.intra_op_num_threads == 4
    assert options.inter_op_num_threads == 1
    assert adapter.providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_face_runtime_wraps_detector_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = {"count": 0}

    class FakeGuard:
        def __enter__(self) -> None:
            entered["count"] += 1
            return None

        def __exit__(self, *_args: object) -> None:
            return None

    class FakeFaceAnalysis:
        def __init__(self, **_kwargs: object) -> None:
            assert entered["count"] == 1
            self.models = {"detection": SimpleNamespace(session=SimpleNamespace(get_providers=lambda: ["CPUExecutionProvider"]))}

        def prepare(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr("insightface.app.FaceAnalysis", FakeFaceAnalysis)
    runtime = FaceRuntime(
        detector_pack="buffalo_l",
        adapter_id="buffalo_l",
        model_path=None,
        providers=["CPUExecutionProvider"],
        detection_size=640,
        flip_tta=False,
        detector_session_guard=FakeGuard,
    )
    detector = runtime.detector
    assert detector is not None
    assert entered["count"] == 1


def test_import_gallery_photo_decodes_image_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image as PilImage

    opens: list[object] = []
    original_open = PilImage.open

    def counting_open(*args: object, **kwargs: object):
        opens.append(args[0] if args else kwargs)
        return original_open(*args, **kwargs)

    monkeypatch.setattr("app.services.image_metadata.Image.open", counting_open)
    monkeypatch.setattr("face_runtime.runtime.Image.open", counting_open)

    face = RecordingFaceService()
    service = PictureService(  # type: ignore[arg-type]
        FakeStorage(),
        face,
        FakeVectorStore(),
        FakeOcrService(),
        Settings(),
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    payload = _jpeg_bytes()
    with Session(engine) as db:
        service.import_gallery_photo(db, "once.jpg", payload, "image/jpeg", [], False, None, None)

    assert face.bgr_calls == 1
    assert face.bytes_calls == 0
    assert len(opens) == 1


def test_prepared_gallery_image_is_reused_for_recognition_and_import(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image as PilImage

    opens = 0
    original_open = PilImage.open

    def counting_open(*args, **kwargs):
        nonlocal opens
        opens += 1
        return original_open(*args, **kwargs)

    monkeypatch.setattr("app.services.image_metadata.Image.open", counting_open)
    service = PictureService(  # type: ignore[arg-type]
        FakeStorage(), RecordingFaceService(), FakeVectorStore(), FakeOcrService(), Settings(),
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    payload = _jpeg_bytes()
    prepared = service.prepare_gallery_image(payload)
    with Session(engine) as db:
        recognition = service.prepare_gallery_recognition(db, payload, None, image_bgr=prepared[3])
        service.import_gallery_photo(db, "reuse.jpg", payload, "image/jpeg",
                                     recognition_plan=recognition, prepared_image=prepared)
    assert opens == 1


def test_gallery_recognition_does_not_hold_sqlite_write_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "recognition.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    service = PictureService(  # type: ignore[arg-type]
        FakeStorage(), RecordingFaceService(), FakeVectorStore(), FakeOcrService(), Settings(),
    )
    started = threading.Event()
    release = threading.Event()
    errors: list[Exception] = []

    def pause_recognition(*_args, **_kwargs):
        started.set()
        if not release.wait(timeout=3):
            raise TimeoutError("识别测试等待超时")
        return []

    monkeypatch.setattr(service, "_recognition_plan", pause_recognition)

    def import_photo():
        try:
            with Session(engine) as db:
                service.import_gallery_photo(db, "photo.jpg", _jpeg_bytes(), "image/jpeg")
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=import_photo)
    worker.start()
    try:
        assert started.wait(timeout=3)
        with sqlite3.connect(database, timeout=0.2) as concurrent:
            concurrent.execute("BEGIN IMMEDIATE")
            concurrent.execute("ROLLBACK")
    finally:
        release.set()
        worker.join(timeout=3)
        engine.dispose()
    assert not worker.is_alive()
    assert not errors


def test_create_onnx_inference_session_passes_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as folder:
        model_path = Path(folder) / "model.onnx"
        model_path.write_bytes(b"onnx")

        class FakeOrtSession:
            def __init__(self, path: str, **kwargs: object) -> None:
                captured["path"] = path
                captured["kwargs"] = kwargs

        monkeypatch.setattr("onnxruntime.InferenceSession", FakeOrtSession)
        create_onnx_inference_session(model_path, providers=["CPUExecutionProvider"])
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    options = kwargs["sess_options"]
    assert options.intra_op_num_threads == read_library_thread_count()
    assert options.inter_op_num_threads == 1
    assert kwargs["providers"] == ["CPUExecutionProvider"]
