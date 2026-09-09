from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


PRESERVED_SOURCES = {"manual", "face_manual", "import", "import_unknown"}


def _iou(left: list[float], right: list[float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _match_faces(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], int, int]:
    candidates = sorted(
        (
            (_iou(old["bbox"], new["bbox"]), old_index, new_index)
            for old_index, old in enumerate(before)
            for new_index, new in enumerate(after)
        ),
        reverse=True,
    )
    used_old: set[int] = set()
    used_new: set[int] = set()
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for overlap, old_index, new_index in candidates:
        if overlap < 0.3:
            break
        if old_index in used_old or new_index in used_new:
            continue
        used_old.add(old_index)
        used_new.add(new_index)
        matches.append((before[old_index], after[new_index]))
    return matches, len(before) - len(used_old), len(after) - len(used_new)


def analyze(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    source_before: Counter[str] = Counter()
    source_after: Counter[str] = Counter()
    lost_preserved: list[dict[str, Any]] = []
    sample_remap_photos = 0
    sample_remaps = 0
    failures: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    latest_rows: dict[tuple[str, int], dict[str, Any]] = {}

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            counts["audit_lines"] += 1
            if not metadata:
                metadata = {
                    key: row.get(key)
                    for key in ("mode", "total", "collection", "embedding_version", "adapter_id", "threshold", "min_margin")
                }
            row["_audit_line"] = line_number
            latest_rows[(str(row.get("mode")), int(row["gallery_photo_id"]))] = row

    for row in latest_rows.values():
        counts["rows"] += 1
        if row.get("status") != "success":
            counts["failed"] += 1
            failures.append({
                "line": row["_audit_line"],
                "gallery_photo_id": row.get("gallery_photo_id"),
                "error": row.get("error"),
            })
            continue
        counts["succeeded"] += 1
        before = row["before"]
        after = row["after"]
        before_tags = {(int(tag["person_id"]), tag["source"]) for tag in before["person_tags"]}
        after_tags = {(int(tag["person_id"]), tag["source"]) for tag in after["person_tags"]}
        before_unknown_ids = {person_id for person_id, source in before_tags if source == "unknown"}
        after_unknown_ids = {person_id for person_id, source in after_tags if source == "unknown"}
        for _person_id, source in before_tags:
            source_before[source] += 1
        for _person_id, source in after_tags:
            source_after[source] += 1
        missing = sorted(tag for tag in before_tags if tag[1] in PRESERVED_SOURCES and tag not in after_tags)
        if missing:
            lost_preserved.append({"gallery_photo_id": row["gallery_photo_id"], "tags": missing})

        remaps = after.get("sample_face_remaps", [])
        if not remaps and before.get("promoted_samples") and after.get("promoted_samples"):
            old_samples = {
                sample["sample_photo_id"]: sample for sample in before["promoted_samples"]
            }
            remaps = [
                {
                    "sample_photo_id": sample["sample_photo_id"],
                    "old_face_record_id": old_samples[sample["sample_photo_id"]]["source_gallery_face_id"],
                    "new_face_record_id": sample["source_gallery_face_id"],
                }
                for sample in after["promoted_samples"]
                if sample["sample_photo_id"] in old_samples
                and sample["source_gallery_face_id"]
                != old_samples[sample["sample_photo_id"]]["source_gallery_face_id"]
            ]
        if remaps:
            sample_remap_photos += 1
            sample_remaps += len(remaps)
        old_faces = before["faces"]
        new_faces = after["faces"]
        counts["faces_before"] += len(old_faces)
        counts["faces_after"] += len(new_faces)
        matches, removed, added = _match_faces(old_faces, new_faces)
        counts["faces_matched_by_iou"] += len(matches)
        counts["detections_removed"] += removed
        counts["detections_added"] += added
        for old, new in matches:
            old_unknown = (
                bool(old.get("needs_review"))
                or old.get("matched_person_id") is None
                or old.get("matched_person_id") in before_unknown_ids
            )
            new_unknown = (
                bool(new.get("needs_review"))
                or new.get("matched_person_id") is None
                or new.get("matched_person_id") in after_unknown_ids
            )
            if old_unknown and new_unknown:
                counts["unknown_to_unknown"] += 1
            elif old_unknown:
                counts["unknown_to_known"] += 1
            elif new_unknown:
                counts["known_to_unknown"] += 1
            elif old.get("matched_person_id") == new.get("matched_person_id"):
                counts["known_identity_unchanged"] += 1
            else:
                counts["known_identity_changed"] += 1

    gate_reasons: list[str] = []
    if counts["failed"]:
        gate_reasons.append(f"存在 {counts['failed']} 张处理失败的照片")
    if lost_preserved:
        gate_reasons.append(f"存在 {len(lost_preserved)} 张照片丢失保留来源标签")
    expected_total = metadata.get("total")
    if expected_total is not None and counts["rows"] != expected_total:
        gate_reasons.append(f"审计行数 {counts['rows']} 与任务总数 {expected_total} 不一致")
    return {
        "audit_file": str(path),
        "metadata": metadata,
        "gate_passed": not gate_reasons,
        "gate_reasons": gate_reasons,
        "counts": dict(sorted(counts.items())),
        "tag_sources_before": dict(sorted(source_before.items())),
        "tag_sources_after": dict(sorted(source_after.items())),
        "sample_face_remap_photos": sample_remap_photos,
        "sample_face_remaps": sample_remaps,
        "lost_preserved_tags": lost_preserved[:100],
        "failures": failures[:100],
    }


def _markdown(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    counts = report["counts"]
    lines = [
        "# 人脸迁移审计汇总",
        "",
        f"- 审计文件：`{report['audit_file']}`",
        f"- 模式：`{metadata.get('mode')}`",
        f"- 模型适配器：`{metadata.get('adapter_id')}`",
        f"- 向量集合：`{metadata.get('collection')}`",
        f"- 阈值/最小间隔：`{metadata.get('threshold')}` / `{metadata.get('min_margin')}`",
        f"- 迁移门禁：{'通过' if report['gate_passed'] else '未通过'}",
        "",
        "## 处理结果",
        "",
    ]
    labels = {
        "rows": "审计照片数",
        "succeeded": "成功照片数",
        "failed": "失败照片数",
        "faces_before": "迁移前人脸数",
        "faces_after": "迁移后人脸数",
        "faces_matched_by_iou": "位置对齐人脸数",
        "detections_added": "新增检测数",
        "detections_removed": "消失检测数",
        "unknown_to_known": "未知转已知",
        "known_to_unknown": "已知转未知",
        "known_identity_unchanged": "已知身份不变",
        "known_identity_changed": "已知身份变化",
        "unknown_to_unknown": "仍为未知",
    }
    for key, label in labels.items():
        lines.append(f"- {label}：{counts.get(key, 0)}")
    lines.extend([
        "",
        "## 标签与样本保护",
        "",
        f"- 迁移前标签来源：`{json.dumps(report['tag_sources_before'], ensure_ascii=False)}`",
        f"- 迁移后标签来源：`{json.dumps(report['tag_sources_after'], ensure_ascii=False)}`",
        f"- 涉及提升样本重定位的照片：{report['sample_face_remap_photos']}",
        f"- 提升样本重定位数：{report['sample_face_remaps']}",
        f"- 丢失保留来源标签的照片：{len(report['lost_preserved_tags'])}",
    ])
    if report["gate_reasons"]:
        lines.extend(["", "## 阻断原因", ""])
        lines.extend(f"- {reason}" for reason in report["gate_reasons"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总全图库人脸迁移审计，并检查正式迁移门禁。")
    parser.add_argument("audit_file", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    report = analyze(args.audit_file)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
