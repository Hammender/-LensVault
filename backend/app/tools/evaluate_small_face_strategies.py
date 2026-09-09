from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FaceRecord
from app.tools.calibrate_adaface_migration import _flip_rows


def _accepted(row: dict[str, object], threshold: float, margin: float) -> bool:
    return bool(
        row.get("score") is not None
        and float(row["score"]) >= threshold
        and (row.get("margin") is None or float(row["margin"]) >= margin)
    )


def _summarize(decisions: list[tuple[dict[str, object], bool, bool]]) -> dict[str, int]:
    return {
        "rows": len(decisions),
        "accepted": sum(accepted for _row, accepted, _small in decisions),
        "correct": sum(
            accepted and row["predicted_person_id"] == row["corrected_person_id"]
            for row, accepted, _small in decisions
        ),
        "wrong_identity": sum(
            accepted and row["predicted_person_id"] != row["corrected_person_id"]
            for row, accepted, _small in decisions
        ),
        "rejected": sum(not accepted for _row, accepted, _small in decisions),
        "small_rows": sum(small for _row, _accepted_value, small in decisions),
        "small_correct": sum(
            small and accepted and row["predicted_person_id"] == row["corrected_person_id"]
            for row, accepted, small in decisions
        ),
        "small_wrong_identity": sum(
            small and accepted and row["predicted_person_id"] != row["corrected_person_id"]
            for row, accepted, small in decisions
        ),
        "small_rejected": sum(small and not accepted for _row, accepted, small in decisions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="离线比较 AdaFace 小脸识别策略。")
    parser.add_argument("--adaface-report", type=Path, required=True)
    parser.add_argument("--buffalo-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adaface = {int(row["face_record_id"]): row for row in _flip_rows(args.adaface_report)}
    buffalo = {int(row["face_record_id"]): row for row in _flip_rows(args.buffalo_report)}
    face_ids = sorted(set(adaface) & set(buffalo))
    with SessionLocal() as db:
        faces = {
            face.id: face for face in db.scalars(
                select(FaceRecord).where(FaceRecord.id.in_(face_ids))
            ).all()
        }

    strategies: dict[str, list[tuple[dict[str, object], bool, bool]]] = {
        "standard_adaface": [],
        "small_strict_margin": [],
        "small_dual_model_agreement": [],
    }
    for face_id in face_ids:
        candidate = adaface[face_id]
        baseline = buffalo[face_id]
        face = faces[face_id]
        small = face.face_size is not None and face.face_size < 80
        standard = _accepted(candidate, 0.42, 0.04)
        strict = _accepted(candidate, 0.42, 0.05) if small else standard
        agreement = bool(
            not small
            or (
                baseline["predicted_person_id"] == candidate["predicted_person_id"]
                and baseline.get("score") is not None
                and float(baseline["score"]) >= 0.35
                and (baseline.get("margin") is None or float(baseline["margin"]) >= 0.02)
            )
        )
        strategies["standard_adaface"].append((candidate, standard, small))
        strategies["small_strict_margin"].append((candidate, strict, small))
        strategies["small_dual_model_agreement"].append((candidate, standard and agreement, small))

    summaries = {name: _summarize(decisions) for name, decisions in strategies.items()}
    standard = summaries["standard_adaface"]
    eligible = [
        name for name, summary in summaries.items()
        if name != "standard_adaface"
        and summary["small_correct"] > standard["small_correct"]
        and summary["small_wrong_identity"] <= standard["small_wrong_identity"]
        and summary["wrong_identity"] <= standard["wrong_identity"]
    ]
    selected = max(eligible, key=lambda name: summaries[name]["small_correct"], default="standard_adaface")
    result = {
        "operating_point": {"threshold": 0.42, "margin": 0.04, "small_face_threshold": 80},
        "strategies": summaries,
        "selected": selected,
        "extra_strategy_enabled": selected != "standard_adaface",
        "limitation": "1024 全局检测已在同一纠正集上出现 20 个框对应失败，不进入生产候选。",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "small-face.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AdaFace 小脸专项实验",
        "",
        "| 策略 | 总正确 | 总错认 | 小脸正确 | 小脸错认 | 小脸拒绝 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, summary in summaries.items():
        lines.append(
            f"| {name} | {summary['correct']} | {summary['wrong_identity']} | "
            f"{summary['small_correct']} | {summary['small_wrong_identity']} | {summary['small_rejected']} |"
        )
    lines.extend(["", f"选择：`{selected}`。", "", result["limitation"]])
    (args.output / "small-face.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
