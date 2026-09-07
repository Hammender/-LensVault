from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db import SessionLocal
from app.models import FaceRecord, SamplePhoto
from app.services.face_profiles import ReferenceFace, aggregate_hits, build_centroid, unit_vector
from app.services.qdrant import FaceSearchHit, QdrantVectorStore


@dataclass(frozen=True)
class EvaluationSample:
    sample_id: int
    workspace_id: int | None
    person_id: int
    sha256: str
    source_photo_id: int | None
    face: ReferenceFace


def reference_split(query: EvaluationSample, samples: list[EvaluationSample]) -> list[EvaluationSample]:
    return [
        item for item in samples
        if item.workspace_id == query.workspace_id and item.sample_id != query.sample_id
        and item.sha256 != query.sha256
        and not (query.source_photo_id is not None and item.source_photo_id == query.source_photo_id)
    ]


def predict(query: EvaluationSample, references: list[EvaluationSample], settings: Settings,
            mode: str, bonus: float) -> tuple[int | None, float | None, float | None]:
    grouped: dict[int, list[EvaluationSample]] = defaultdict(list)
    hits = []
    vector = unit_vector(query.face.vector)
    for item in references:
        grouped[item.person_id].append(item)
        hits.append(FaceSearchHit(item.sample_id, item.person_id,
                                  float(vector @ unit_vector(item.face.vector)), "sample", item.sample_id))
    for person_id, items in grouped.items():
        center = build_centroid([item.face for item in items], mode=mode,
                                quality_strength=settings.face_centroid_quality_strength,
                                outlier_fraction=settings.face_centroid_outlier_fraction)
        hits.append(FaceSearchHit(f"center-{person_id}", person_id, float(vector @ center), "centroid", None))
    # 与在线流程相同：先截断向量候选，再按人物汇总；每个留出查询重建中心以防泄漏。
    hits.sort(key=lambda hit: (-hit.score, str(hit.point_id)))
    ranked = aggregate_hits(hits[:settings.face_search_limit], top_k=settings.face_match_top_k,
                            max_bonus=bonus, support_floor=settings.face_recognition_threshold - 0.05)
    if not ranked:
        return None, None, None
    score = ranked[0].score
    margin = score - ranked[1].score if len(ranked) > 1 else None
    accepted = score >= settings.face_recognition_threshold and (
        margin is None or margin >= settings.face_recognition_min_margin)
    return ranked[0].person_id if accepted else None, score, margin


def summarize(rows: list[dict]) -> dict:
    known = [row for row in rows if row["scenario"] == "known"]
    unknown = [row for row in rows if row["scenario"] == "unknown"]
    correct = sum(row["predicted"] == row["person_id"] for row in known)
    wrong = sum(row["predicted"] is not None and row["predicted"] != row["person_id"] for row in known)
    false_accepts = sum(row["predicted"] is not None for row in unknown)
    accepted = correct + wrong + false_accepts
    precision = correct / accepted if accepted else None
    recall = correct / len(known) if known else None
    return {
        "known_queries": len(known), "unknown_queries": len(unknown), "correct": correct,
        "wrong_identity": wrong, "rejected_known": len(known) - correct - wrong,
        "unknown_false_accepts": false_accepts,
        "unknown_false_accept_rate": false_accepts / len(unknown) if unknown else None,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0 else None,
        "margin_quantiles": np.quantile([row["margin"] for row in rows if row["margin"] is not None], [0.1, 0.5, 0.9]).tolist()
        if any(row["margin"] is not None for row in rows) else [],
    }


def evaluate(samples: list[EvaluationSample], settings: Settings, max_queries: int | None = None) -> dict:
    variants = [("baseline", "mean", 0.0), ("robust", "robust", 0.0), ("balanced", "robust", 0.02)]
    rows = []
    counts: dict[tuple[int | None, int], int] = defaultdict(int)
    for sample in samples:
        counts[(sample.workspace_id, sample.person_id)] += 1
    for query in samples[:max_queries]:
        references = reference_split(query, samples)
        known_available = any(item.person_id == query.person_id for item in references)
        other_people = [item for item in references if item.person_id != query.person_id]
        for name, mode, bonus in variants:
            for scenario, gallery in [("known", references), ("unknown", other_people)]:
                if (scenario == "known" and not known_available) or not gallery:
                    continue
                predicted, score, margin = predict(query, gallery, settings, mode, bonus)
                rows.append({"variant": name, "scenario": scenario, "sample_id": query.sample_id,
                             "workspace_id": query.workspace_id, "person_id": query.person_id,
                             "predicted": predicted, "score": score, "margin": margin,
                             "few_samples": counts[(query.workspace_id, query.person_id)] <= 3,
                             "small_face": query.face.face_size is not None and query.face.face_size < 80,
                             "side_face": query.face.pose_yaw is not None and abs(query.face.pose_yaw) > 35,
                             "blurred": query.face.blur_score is not None and query.face.blur_score < 45})
    metrics = {name: summarize([row for row in rows if row["variant"] == name]) for name, _, _ in variants}
    slices = {name: {flag: summarize([row for row in rows if row["variant"] == name and row[flag]])
                     for flag in ("few_samples", "small_face", "side_face", "blurred")}
              for name, _, _ in variants}
    known_rows = [row for row in rows if row["variant"] == "baseline" and row["scenario"] == "known"]
    enough = len(known_rows) >= settings.face_evaluation_min_labels and len({(row["workspace_id"], row["person_id"]) for row in known_rows}) >= settings.face_evaluation_min_people
    baseline = metrics["baseline"]
    candidates = [name for name in ("robust", "balanced") if enough
                  and metrics[name]["correct"] > baseline["correct"]
                  and metrics[name]["wrong_identity"] <= baseline["wrong_identity"]
                  and metrics[name]["unknown_false_accepts"] <= baseline["unknown_false_accepts"]]
    return {"metrics": metrics, "slices": slices, "rows": rows, "sufficient_samples": enough,
            "candidate_for_gallery_validation": max(candidates, key=lambda name: metrics[name]["correct"], default=None),
            "limitation": "样本留出结果只用于筛选方案；样本库与真实图库分布不同，不能视为图库准确率或自动启用依据。"}


def main() -> None:
    parser = argparse.ArgumentParser(description="只读样本向量，对比旧中心、稳健中心和有限融合评分。")
    parser.add_argument("--output", type=Path, default=Path("data/face-profile-evaluation"))
    parser.add_argument("--workspace-id", type=int)
    parser.add_argument("--max-queries", type=int, help="仅限制查询数量，参考样本仍全量加载。")
    args = parser.parse_args()
    if args.max_queries is not None and args.max_queries < 1:
        raise SystemExit("查询数量必须为正数")
    settings = get_settings()
    store = QdrantVectorStore(settings)
    samples = []
    with SessionLocal() as db:
        statement = select(SamplePhoto).where(SamplePhoto.status == "ready").order_by(SamplePhoto.id)
        if args.workspace_id is not None:
            statement = statement.where(SamplePhoto.workspace_id == args.workspace_id)
        for sample in db.scalars(statement):
            faces = db.scalars(select(FaceRecord).where(FaceRecord.sample_photo_id == sample.id)).all()
            if len(faces) != 1:
                raise SystemExit(f"样本 {sample.id} 人脸记录数量异常，先修复索引再评估")
            face = faces[0]
            vector = store.get_reference_vector(settings.qdrant_known_collection, face.id,
                                                 workspace_id=sample.workspace_id, person_id=sample.person_id,
                                                 embedding_version=settings.face_embedding_version)
            samples.append(EvaluationSample(sample.id, sample.workspace_id, sample.person_id, sample.sha256,
                                            sample.source_gallery_photo_id,
                                            ReferenceFace(vector, face.face_size, face.detection_score, face.blur_score, face.pose_yaw)))
    report = evaluate(samples, settings, args.max_queries)
    report.update(collection=settings.qdrant_known_collection, embedding_version=settings.face_embedding_version,
                  threshold=settings.face_recognition_threshold, min_margin=settings.face_recognition_min_margin,
                  sample_count=len(samples), max_queries=args.max_queries)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "queries.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        if report["rows"]:
            writer = csv.DictWriter(handle, fieldnames=list(report["rows"][0]))
            writer.writeheader()
            writer.writerows(report["rows"])
    lines = ["# 人脸中心向量离线对比", "", report["limitation"], "",
             "| 方案 | 已知查询 | 正确识别 | 错认人物 | 已知拒识 | 未知误接收 |", "|---|---:|---:|---:|---:|---:|"]
    for name, label in [("baseline", "原中心"), ("robust", "稳健中心"), ("balanced", "稳健中心与有限加分")]:
        metric = report["metrics"][name]
        lines.append(f"| {label} | {metric['known_queries']} | {metric['correct']} | {metric['wrong_identity']} | {metric['rejected_known']} | {metric['unknown_false_accepts']} |")
    lines.extend(["", f"达到数量门槛：{report['sufficient_samples']}；待图库验证方案：{report['candidate_for_gallery_validation'] or '暂无'}。"])
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
