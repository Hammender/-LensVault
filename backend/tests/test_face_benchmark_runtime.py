from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from face_runtime.adapters import ADAPTERS, OnnxFaceAdapter
from face_runtime.providers import resolve_provider_mode
from face_runtime.runtime import FaceDetection
from tools.face_benchmark.cache import CacheStore, stable_cache_key
from tools.face_benchmark.compare import compare_results
from tools.face_benchmark.evaluate import Prediction, acceptance_reason, evaluate_snapshot, metrics
from tools.face_benchmark.geometry import (
    TARGET_SELECTION_POLICY,
    face_crop_box,
    select_target_detection,
    target_bbox_in_crop,
)
from tools.face_benchmark.server import list_label_items, save_annotation, validate_annotation
from tools.face_benchmark.store import initialize_benchmark


class FakeSession:
    def __init__(
        self,
        input_shape: list[object] | None = None,
        output_shape: list[object] | None = None,
    ) -> None:
        self.input_shape = input_shape or [None, 3, 112, 112]
        self.output_shape = output_shape or [None, 512]
        self.batch: np.ndarray | None = None

    def get_inputs(self) -> list[object]:
        return [SimpleNamespace(name="input", shape=self.input_shape)]

    def get_outputs(self) -> list[object]:
        return [SimpleNamespace(name="output", shape=self.output_shape)]

    def get_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def run(self, _outputs: list[str], inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.batch = inputs["input"]
        return [np.ones((self.batch.shape[0], 512), dtype=np.float32)]


def test_adapter_preprocessing_obeys_rgb_nchw_normalization_and_flip(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")
    session = FakeSession()
    adapter = OnnxFaceAdapter(ADAPTERS["buffalo_l"], model, ["CPUExecutionProvider"], session=session)
    image = np.zeros((112, 112, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(112, dtype=np.uint8)[None, :]
    image[:, :, 1] = 128
    image[:, :, 2] = 255

    vector = adapter.embed_aligned(image, flip_tta=True)

    assert session.batch is not None
    assert session.batch.shape == (2, 3, 112, 112)
    assert session.batch[0, 0, 0, 0] == pytest.approx(1.0)
    assert session.batch[0, 1, 0, 0] == pytest.approx((128 - 127.5) / 127.5)
    assert session.batch[0, 2, 0, 0] == pytest.approx(-1.0)
    assert session.batch[1, 2, 0, 0] == pytest.approx(session.batch[0, 2, 0, -1])
    assert np.linalg.norm(vector) == pytest.approx(1.0)


def test_adapter_rejects_a_model_with_wrong_input_contract(tmp_path: Path) -> None:
    model = tmp_path / "wrong.onnx"
    model.write_bytes(b"wrong")

    with pytest.raises(RuntimeError, match="输入形状"):
        OnnxFaceAdapter(
            ADAPTERS["buffalo_l"], model, ["CPUExecutionProvider"], session=FakeSession([None, 3, 224, 224])
        )

    with pytest.raises(RuntimeError, match="输入形状"):
        OnnxFaceAdapter(
            ADAPTERS["buffalo_l"], model, ["CPUExecutionProvider"], session=FakeSession([None, 3, "height", 112])
        )

    with pytest.raises(RuntimeError, match="输出维度"):
        OnnxFaceAdapter(
            ADAPTERS["buffalo_l"], model, ["CPUExecutionProvider"], session=FakeSession(output_shape=[None, "features"])
        )


def test_provider_auto_priority_and_explicit_failure() -> None:
    available = ["CPUExecutionProvider", "CoreMLExecutionProvider", "CUDAExecutionProvider"]
    assert resolve_provider_mode("auto", available)[0] == "CUDAExecutionProvider"
    assert resolve_provider_mode("auto", available[:2])[0] == "CoreMLExecutionProvider"
    with pytest.raises(RuntimeError, match="CUDAExecutionProvider"):
        resolve_provider_mode("cuda", ["CPUExecutionProvider"])


def test_cache_key_changes_with_every_model_runtime_dimension(tmp_path: Path) -> None:
    base = {
        "snapshot": "snapshot-a",
        "detector": "detector-a",
        "detection_size": 640,
        "model_sha256": "model-a",
        "adapter_version": "1",
        "flip_tta": False,
        "provider": "cpu",
    }
    original = stable_cache_key(base)
    for field, value in {
        "snapshot": "snapshot-b",
        "detector": "detector-b",
        "detection_size": 1024,
        "model_sha256": "model-b",
        "adapter_version": "2",
        "flip_tta": True,
        "provider": "coreml",
    }.items():
        assert stable_cache_key({**base, field: value}) != original
    cache = CacheStore(tmp_path)
    cache.save("embeddings", original, {"value": 7})
    assert cache.load("embeddings", original) == {"cache_key": original, "value": 7}
    assert cache.load("embeddings", "missing") is None


def test_threshold_margin_and_metrics_keep_safety_failures_visible() -> None:
    accepted = Prediction(1, 0.7, 2, 0.6)
    narrow = Prediction(1, 0.7, 2, 0.65)
    low = Prediction(1, 0.44, 2, 0.1)
    assert acceptance_reason(accepted, 0.45, 0.08) == "accepted"
    assert acceptance_reason(narrow, 0.45, 0.08) == "below_margin"
    assert acceptance_reason(low, 0.45, 0.08) == "below_threshold"
    rows = [
        {"prediction": accepted, "truth_person_id": 2, "truth_is_unknown": False, "processing_error": None},
        {"prediction": accepted, "truth_person_id": None, "truth_is_unknown": True, "processing_error": "bad image"},
    ]
    values = metrics(rows, 0.45, 0.08)
    assert values["wrong_person"] == 2
    assert values["false_accept"] == 1
    assert values["processing_failures"] == 1


class FakeAdapter:
    def report_metadata(self) -> dict[str, object]:
        return {
            **ADAPTERS["buffalo_l"].as_dict(),
            "model_path": "/fake/model.onnx",
            "model_sha256": "a" * 64,
            "providers": ["CPUExecutionProvider"],
        }


class FakeRuntime:
    def __init__(self, **kwargs: object) -> None:
        self.flip_tta = bool(kwargs["flip_tta"])
        self.adapter = FakeAdapter()

    def warmup(self) -> None:
        return

    def detector_metadata(self) -> dict[str, object]:
        return {
            "detector_pack": "buffalo_l",
            "detection_size": 640,
            "model_path": "/fake/detector.onnx",
            "model_sha256": "d" * 64,
            "providers": ["CPUExecutionProvider"],
        }

    def detect_bgr(self, image: np.ndarray) -> tuple[list[FaceDetection], float]:
        if image[0, 0, 0] > image[0, 0, 1]:
            return [
                FaceDetection((0, 0, 16, 16), np.zeros((5, 2), dtype=np.float32), 0.95, 16, 90, 0),
                FaceDetection((4, 4, 14, 14), np.zeros((5, 2), dtype=np.float32), 0.9, 10, 90, 0),
            ], 2.0
        return [FaceDetection((0, 0, 10, 10), np.zeros((5, 2), dtype=np.float32), 0.9, 10, 90, 0)], 2.0

    def embed_detection(self, image: np.ndarray, detection: FaceDetection) -> tuple[np.ndarray, float]:
        vector = np.zeros(512, dtype=np.float32)
        if image[0, 0, 0] > image[0, 0, 1]:
            vector[0 if detection.bbox == (4, 4, 14, 14) else 1] = 1.0
        else:
            vector[0 if image[0, 0, 2] > image[0, 0, 1] else 1] = 1.0
        return vector, 3.0


def _build_snapshot(root: Path) -> Path:
    snapshot = root / "snapshot"
    for folder in ("samples", "faces", "originals"):
        (snapshot / folder).mkdir(parents=True, exist_ok=True)
    files = {
        "samples/1.jpg": "red",
        "samples/2.jpg": "green",
        "faces/10.jpg": "blue",
    }
    checksums: dict[str, str] = {}
    for relative, color in files.items():
        Image.new("RGB", (16, 16), color).save(snapshot / relative, format="JPEG")
        checksums[relative] = sha256((snapshot / relative).read_bytes()).hexdigest()
    selection = '{"kind":"face","face_id":10}\n'
    (snapshot / "selection.jsonl").write_text(selection, encoding="utf-8")
    checksum_payload = json.dumps(checksums, sort_keys=True, indent=2)
    (snapshot / "file-checksums.json").write_text(checksum_payload, encoding="utf-8")
    meta = {
        "snapshot_id": "test",
        "selection_sha256": sha256(selection.encode()).hexdigest(),
        "file_checksums_sha256": sha256(checksum_payload.encode()).hexdigest(),
    }
    (snapshot / "snapshot.json").write_text(json.dumps(meta), encoding="utf-8")
    db = initialize_benchmark(snapshot / "benchmark.db")
    db.executemany(
        "INSERT INTO persons(source_person_id, display_name, is_unknown) VALUES (?, ?, 0)",
        [(1, "人物一"), (2, "人物二")],
    )
    db.executemany(
        "INSERT INTO samples(source_sample_id, source_person_id, image_path, sha256) VALUES (?, ?, ?, ?)",
        [(1, 1, "samples/1.jpg", checksums["samples/1.jpg"]), (2, 2, "samples/2.jpg", checksums["samples/2.jpg"])],
    )
    db.execute(
        """INSERT INTO items(kind, source_photo_id, source_face_id, sample_bucket, split, image_path,
           original_path, source_sha256, bbox_json, metadata_json, status, truth_person_id, truth_is_unknown)
           VALUES ('face', 10, 10, 'hard', 'calibration', 'faces/10.jpg', 'faces/10.jpg', ?, ?, ?, 'labeled', 1, 0)""",
        (
            checksums["faces/10.jpg"],
            json.dumps([10, 10, 20, 20]),
            json.dumps({"match_score": 0.99, "suggested_person_name": "泄漏"}),
        ),
    )
    db.commit()
    db.close()
    return snapshot


def test_evaluation_writes_complete_per_face_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _build_snapshot(tmp_path)
    monkeypatch.setattr("tools.face_benchmark.evaluate.FaceRuntime", FakeRuntime)
    monkeypatch.setattr("tools.face_benchmark.evaluate.resolve_provider_mode", lambda _mode: ["CPUExecutionProvider"])

    output = evaluate_snapshot(
        snapshot,
        adapter_id="buffalo_l",
        model_path=None,
        detector_pack="buffalo_l",
        provider="cpu",
        detection_size=640,
        flip_tta=False,
        threshold=0.45,
        min_margin=0.08,
        final_holdout=False,
    )

    prediction = json.loads((output / "predictions.jsonl").read_text(encoding="utf-8"))
    assert prediction["truth_person_name"] == "人物一"
    assert prediction["top1_person_id"] == 1
    assert prediction["top2_person_id"] == 2
    assert prediction["accepted"] is True
    assert prediction["decision_reason"] == "accepted"
    assert prediction["sample_bucket"] == "hard"
    assert prediction["processing_ms"] == 8.0
    assert prediction["detected_face_count"] == 2
    assert prediction["target_bbox_crop"] == [4.0, 4.0, 14.0, 14.0]
    assert prediction["target_detection_bbox"] == [4, 4, 14, 14]
    assert prediction["target_detection_iou"] == 1.0
    assert prediction["target_selection_method"] == "contains_target_center"
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["snapshot"]["snapshot_id"] == "test"
    assert report["adapter"]["model_sha256"] == "a" * 64
    assert report["target_selection_policy"] == TARGET_SELECTION_POLICY


def test_target_geometry_clips_crop_and_rejects_unrelated_detection() -> None:
    bbox = (2.0, 3.0, 12.0, 13.0)
    assert face_crop_box(bbox, 100, 100) == (0, 0, 15, 16)
    assert target_bbox_in_crop(bbox) == (2.0, 3.0, 12.0, 13.0)
    unrelated = FaceDetection(
        (30, 30, 50, 50), np.zeros((5, 2), dtype=np.float32), 0.99, 20, 90, 0
    )
    selection = select_target_detection([unrelated], target_bbox_in_crop(bbox))
    assert selection.index is None
    assert selection.iou == 0.0
    assert selection.method == "target_not_detected"


def test_label_queries_are_blind_and_annotations_can_be_revised(tmp_path: Path) -> None:
    snapshot = _build_snapshot(tmp_path)
    db = sqlite3.connect(snapshot / "benchmark.db")
    db.row_factory = sqlite3.Row
    state = list_label_items(db, kind="face", status="labeled", split="all")
    item = state["items"][0]
    assert "metadata_json" not in item
    assert "suggested_person_id" not in item
    assert "sample_bucket" not in item
    assert "bbox_json" not in item
    assert item["target_bbox_original"] == [10.0, 10.0, 20.0, 20.0]
    assert item["target_bbox_crop"] == [4.0, 4.0, 14.0, 14.0]
    db_item = db.execute("SELECT id, kind FROM items WHERE id = ?", (item["id"],)).fetchone()
    assert validate_annotation(
        db, db_item, {"status": "labeled", "truth_person_id": 2, "truth_is_unknown": False, "notes": "复查"}
    ) == ("labeled", 2, 0, None, "复查")
    assert validate_annotation(
        db, db_item, {"status": "labeled", "truth_person_id": None, "truth_is_unknown": True}
    ) == ("labeled", None, 1, None, "")
    with pytest.raises(ValueError, match="不能同时"):
        validate_annotation(
            db, db_item, {"status": "labeled", "truth_person_id": 2, "truth_is_unknown": True}
        )
    save_annotation(
        db, item["id"], {"status": "labeled", "truth_person_id": 2, "truth_is_unknown": False, "notes": "首次"}
    )
    save_annotation(
        db, item["id"], {"status": "labeled", "truth_person_id": None, "truth_is_unknown": True, "notes": "修正"}
    )
    revised = db.execute(
        "SELECT status, truth_person_id, truth_is_unknown, notes, updated_at FROM items WHERE id = ?", (item["id"],)
    ).fetchone()
    assert tuple(revised[:4]) == ("labeled", None, 1, "修正")
    assert revised["updated_at"]
    db.close()


def _write_result(
    path: Path,
    *,
    adapter_id: str,
    known_score: float,
    unknown_score: float,
    truth_person_id: int = 1,
) -> None:
    path.mkdir()
    report = {
        "split": "calibration",
        "threshold": 0.45,
        "min_margin": 0.08,
        "target_selection_policy": TARGET_SELECTION_POLICY,
        "snapshot": {"snapshot_sha256": "s" * 64},
        "detector": {
            "detector_pack": "buffalo_l",
            "model_sha256": "d" * 64,
            "detection_size": 640,
            "providers": ["CPUExecutionProvider"],
        },
        "adapter": {
            "adapter_id": adapter_id,
            "model_sha256": sha256(adapter_id.encode()).hexdigest(),
            "providers": ["CPUExecutionProvider"],
        },
        "latency_ms_average": 5.0,
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    rows = [
        {
            "item_id": 1,
            "sample_bucket": "hard",
            "truth_person_id": truth_person_id,
            "truth_is_unknown": False,
            "top1_person_id": 1,
            "top1_score": known_score,
            "top2_person_id": 2,
            "top2_score": 0.1,
            "processing_ms": 5.0,
            "processing_error": None,
        },
        {
            "item_id": 2,
            "sample_bucket": "unknown",
            "truth_person_id": None,
            "truth_is_unknown": True,
            "top1_person_id": 1,
            "top1_score": unknown_score,
            "top2_person_id": 2,
            "top2_score": 0.1,
            "processing_ms": 5.0,
            "processing_error": None,
        },
    ]
    (path / "predictions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_compare_calibrates_candidate_under_baseline_safety_constraint(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_result(baseline, adapter_id="buffalo_l", known_score=0.4, unknown_score=0.3)
    _write_result(candidate, adapter_id="lvface-t", known_score=0.7, unknown_score=0.3)

    output = compare_results(
        baseline,
        [candidate],
        output_dir=tmp_path / "comparison",
        min_labels=1,
        min_people=1,
    )

    comparison = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["recommended"]["adapter_id"] == "lvface-t"
    assert comparison["recommended"]["wrong_person"] == 0
    assert comparison["recommended"]["false_accept"] == 0
    assert comparison["recommended"]["known_rejected"] == 0
    assert (output / "comparison.csv").is_file()
    assert "lvface-t" in (output / "comparison.md").read_text(encoding="utf-8")


def test_compare_rejects_truth_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_result(baseline, adapter_id="buffalo_l", known_score=0.4, unknown_score=0.3)
    _write_result(candidate, adapter_id="lvface-t", known_score=0.7, unknown_score=0.3, truth_person_id=2)

    with pytest.raises(RuntimeError, match="真值"):
        compare_results(baseline, [candidate], output_dir=tmp_path / "comparison", min_labels=1, min_people=1)


def test_compare_rejects_target_selection_policy_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_result(baseline, adapter_id="buffalo_l", known_score=0.4, unknown_score=0.3)
    _write_result(candidate, adapter_id="lvface-t", known_score=0.7, unknown_score=0.3)
    report_path = candidate / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["target_selection_policy"] = "largest-face-v0"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(RuntimeError, match="目标脸选择策略"):
        compare_results(baseline, [candidate], output_dir=tmp_path / "comparison", min_labels=1, min_people=1)
