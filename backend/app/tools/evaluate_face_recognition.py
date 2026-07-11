from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecognitionCorrection


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate recognition thresholds from explicit user corrections.")
    parser.add_argument("--output", default="data/face-evaluation")
    args = parser.parse_args()
    settings = get_settings()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        rows = db.scalars(select(FaceRecognitionCorrection).where(FaceRecognitionCorrection.embedding_version == settings.face_embedding_version)).all()
    thresholds = [round(value / 100, 2) for value in range(30, 71, 2)]
    metrics = []
    for threshold in thresholds:
        accepted = [row for row in rows if row.predicted_person_id is not None and (row.predicted_score or 0) >= threshold]
        wrong = [row for row in accepted if row.predicted_person_id != row.corrected_person_id]
        metrics.append({"threshold": threshold, "accepted": len(accepted), "wrong": len(wrong), "precision": round((len(accepted) - len(wrong)) / len(accepted), 4) if accepted else None})
    report = {"embedding_version": settings.face_embedding_version, "labels": len(rows), "minimum_labels": settings.face_evaluation_min_labels, "recommendation_ready": len(rows) >= settings.face_evaluation_min_labels, "metrics": metrics}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "thresholds.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["threshold", "accepted", "wrong", "precision"])
        writer.writeheader(); writer.writerows(metrics)
    recommendation = "数据量达到门槛，可结合误识率选择阈值。" if report["recommendation_ready"] else "纠错标签不足，仅输出观测结果，不建议自动修改生产阈值。"
    (output / "report.md").write_text(f"# 人脸识别离线评估\n\n- 向量版本：`{settings.face_embedding_version}`\n- 有效人工纠错：{len(rows)}\n- 结论：{recommendation}\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
