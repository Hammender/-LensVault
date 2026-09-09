from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FaceRecord


def _load_flip_rows(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    config = next(item for item in report["configs"] if item["name"] == "flip_640")
    details = next(item for item in report["details"] if item["summary"]["name"] == "flip_640")
    return config, list(details["rows"])


def _group_metrics(rows: list[dict[str, object]], faces: dict[int, FaceRecord]) -> dict[str, dict[str, object]]:
    groups = {
        "all": lambda face: True,
        "small_face_lt_80": lambda face: face.face_size is not None and face.face_size < 80,
        "blur_lt_45": lambda face: face.blur_score is not None and face.blur_score < 45,
        "profile_yaw_ge_45": lambda face: face.pose_yaw is not None and abs(face.pose_yaw) >= 45,
    }
    result: dict[str, dict[str, object]] = {}
    for name, predicate in groups.items():
        selected = [row for row in rows if int(row["face_record_id"]) in faces and predicate(faces[int(row["face_record_id"])])]
        accepted = [row for row in selected if row["accepted"]]
        result[name] = {
            "rows": len(selected),
            "correct": sum(bool(row["correct"]) for row in selected),
            "wrong_identity": sum(bool(row["wrong_identity"]) for row in selected),
            "rejected": sum(not bool(row["accepted"]) for row in selected),
            "recovered_unknown": sum(bool(row["recovered_unknown"]) for row in selected),
            "accepted": len(accepted),
        }
    return result


def _threshold_scan(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for threshold in (0.35, 0.37, 0.39, 0.41, 0.43, 0.45, 0.47, 0.49):
        accepted = [
            row for row in rows
            if row["score"] is not None and float(row["score"]) >= threshold
            and (row["margin"] is None or float(row["margin"]) >= 0.039)
        ]
        output.append({
            "threshold": threshold,
            "accepted": len(accepted),
            "correct": sum(int(bool(row["predicted_person_id"] == row["corrected_person_id"])) for row in accepted),
            "wrong_identity": sum(int(row["predicted_person_id"] != row["corrected_person_id"]) for row in accepted),
            "recovered_unknown": sum(int(bool(row["old_prediction_was_unknown"]) and row["predicted_person_id"] == row["corrected_person_id"]) for row in accepted),
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总隔离人脸实验报告，不写入数据库。")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--antelope", type=Path, required=True)
    parser.add_argument("--adaface", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {"buffalo_l_flip": args.baseline, "antelopev2": args.antelope, "adaface_r101": args.adaface}
    loaded = {name: _load_flip_rows(path) for name, path in paths.items()}
    ids = {int(row["face_record_id"]) for _, rows in loaded.values() for row in rows}
    with SessionLocal() as db:
        faces = {face.id: face for face in db.scalars(select(FaceRecord).where(FaceRecord.id.in_(ids))).all()}
    result: dict[str, object] = {"models": {}, "notes": [
        "仅使用各模型与自身翻转样本集合匹配的 flip_640 配置。",
        "小脸、模糊、侧脸分组来自原始 FaceRecord 质量字段；未知图库没有人工真值。",
        "阈值扫描复用已计算的分数和 margin，不重新访问或修改生产数据。",
    ]}
    for name, (summary, rows) in loaded.items():
        result["models"][name] = {
            "summary": summary,
            "groups": _group_metrics(rows, faces),
            "threshold_scan": _threshold_scan(rows),
        }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 人脸识别隔离实验汇总", "", "仅比较每个模型与自身翻转样本集合匹配的 `flip_640` 配置。", "", "| 模型 | 纠正样本 | 找回未知 | 正确 | 错认 | 拒绝 |", "|---|---:|---:|---:|---:|---:|"]
    for name, item in result["models"].items():
        summary = item["summary"]
        lines.append(f"| {name} | {summary['corrections']} | {summary['recovered_unknown']} | {summary['correct_after_redetect']} | {summary['wrong_identity_after_redetect']} | {summary['rejected_after_redetect']} |")
    lines.extend(["", "## 困难样本分组", "", "| 模型/分组 | 样本 | 找回未知 | 正确 | 错认 | 拒绝 |", "|---|---:|---:|---:|---:|---:|"])
    for name, item in result["models"].items():
        for group, metrics in item["groups"].items():
            lines.append(f"| {name}/{group} | {metrics['rows']} | {metrics['recovered_unknown']} | {metrics['correct']} | {metrics['wrong_identity']} | {metrics['rejected']} |")
    lines.extend(["", "## 阈值扫描", "", "阈值扫描固定 `margin=0.039`，仅用于离线观察 operating point。", ""])
    for name, item in result["models"].items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| 阈值 | 接受 | 正确 | 错认 | 找回未知 |")
        lines.append("|---:|---:|---:|---:|---:|")
        for row in item["threshold_scan"]:
            lines.append(f"| {row['threshold']:.2f} | {row['accepted']} | {row['correct']} | {row['wrong_identity']} | {row['recovered_unknown']} |")
        lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({name: item["summary"] for name, item in result["models"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
