from __future__ import annotations

from datetime import datetime
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .evaluate import Prediction, metrics


def _load_result(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = path.resolve()
    report_path = path / "report.json"
    predictions_path = path / "predictions.jsonl"
    if not report_path.is_file() or not predictions_path.is_file():
        raise RuntimeError(f"结果目录缺少 report.json 或 predictions.jsonl：{path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        value["prediction"] = Prediction(
            value.get("top1_person_id"),
            value.get("top1_score"),
            value.get("top2_person_id"),
            value.get("top2_score"),
        )
        rows.append(value)
    return report, rows


def _validate_compatible(
    baseline_report: dict[str, Any],
    baseline_rows: list[dict[str, Any]],
    report: dict[str, Any],
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    if report.get("split") != "calibration":
        raise RuntimeError(f"候选比较只允许 calibration 结果：{path}")
    baseline_identity = (
        baseline_report.get("snapshot", {}).get("snapshot_sha256"),
        baseline_report.get("detector", {}).get("detector_pack"),
        baseline_report.get("detector", {}).get("model_sha256"),
        baseline_report.get("detector", {}).get("detection_size"),
        baseline_report.get("target_selection_policy"),
    )
    candidate_identity = (
        report.get("snapshot", {}).get("snapshot_sha256"),
        report.get("detector", {}).get("detector_pack"),
        report.get("detector", {}).get("model_sha256"),
        report.get("detector", {}).get("detection_size"),
        report.get("target_selection_policy"),
    )
    if not baseline_identity[0] or not baseline_identity[2] or not baseline_identity[4]:
        raise RuntimeError("基线结果缺少快照、检测模型哈希或目标脸选择策略，无法可靠比较。")
    if candidate_identity != baseline_identity:
        raise RuntimeError(f"快照、检测配置或目标脸选择策略与基线不一致：{path}")
    providers = report.get("adapter", {}).get("providers")
    detector_providers = report.get("detector", {}).get("providers")
    if providers != ["CPUExecutionProvider"] or detector_providers != ["CPUExecutionProvider"]:
        raise RuntimeError(f"统一候选比较要求识别器和检测器均使用 CPUExecutionProvider：{path}")

    def truth_signature(values: list[dict[str, Any]]) -> list[tuple[object, ...]]:
        return [
            (
                row["item_id"],
                row.get("truth_person_id"),
                row.get("truth_is_unknown"),
                row.get("sample_bucket"),
            )
            for row in values
        ]

    if truth_signature(rows) != truth_signature(baseline_rows):
        raise RuntimeError(f"逐脸题目、真值或分层与基线不一致：{path}")


def _hard_rejected(rows: list[dict[str, Any]], threshold: float, min_margin: float) -> int:
    hard = [row for row in rows if row.get("sample_bucket") == "hard"]
    values = metrics(hard, threshold, min_margin)
    return int(values["known_rejected"])


def _candidate_parameters(
    rows: list[dict[str, Any]],
    baseline_metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for threshold_value in [round(value / 100, 2) for value in range(20, 81)]:
        for margin_value in [round(value / 100, 2) for value in range(0, 21)]:
            values = metrics(rows, threshold_value, margin_value)
            safe = (
                values["wrong_person"] <= baseline_metrics["wrong_person"]
                and values["false_accept"] <= baseline_metrics["false_accept"]
            )
            if not safe:
                continue
            latencies = [row["processing_ms"] for row in rows if row.get("processing_ms") is not None]
            candidates.append({
                "threshold": threshold_value,
                "min_margin": margin_value,
                **values,
                "hard_known_rejected": _hard_rejected(rows, threshold_value, margin_value),
                "latency_ms_average": round(float(np.mean(latencies)), 3) if latencies else None,
            })
    return candidates


def _rank_key(row: dict[str, Any]) -> tuple[object, ...]:
    return (
        row["known_rejected"],
        row["hard_known_rejected"],
        row["processing_failures"],
        row["latency_ms_average"] if row["latency_ms_average"] is not None else float("inf"),
        row["wrong_person"],
        row["false_accept"],
        -row["min_margin"],
        -row["threshold"],
        row["result_dir"],
    )


def compare_results(
    baseline_dir: Path,
    candidate_dirs: list[Path],
    *,
    output_dir: Path | None = None,
    min_labels: int = 100,
    min_people: int = 20,
) -> Path:
    if not candidate_dirs:
        raise RuntimeError("至少需要一个候选结果目录。")
    baseline_report, baseline_rows = _load_result(baseline_dir)
    _validate_compatible(baseline_report, baseline_rows, baseline_report, baseline_rows, baseline_dir)
    baseline_threshold = float(baseline_report["threshold"])
    baseline_margin = float(baseline_report["min_margin"])
    baseline_values = metrics(baseline_rows, baseline_threshold, baseline_margin)
    labeled_people = len({row["truth_person_id"] for row in baseline_rows if row["truth_person_id"] is not None})
    sufficient = baseline_values["labeled"] >= min_labels and labeled_people >= min_people

    baseline_option = {
        "result_dir": str(baseline_dir.resolve()),
        "adapter_id": baseline_report["adapter"]["adapter_id"],
        "model_sha256": baseline_report["adapter"]["model_sha256"],
        "is_baseline": True,
        "threshold": baseline_threshold,
        "min_margin": baseline_margin,
        **baseline_values,
        "hard_known_rejected": _hard_rejected(baseline_rows, baseline_threshold, baseline_margin),
        "latency_ms_average": baseline_report.get("latency_ms_average"),
    }
    options = [baseline_option]
    rejected: list[dict[str, Any]] = []
    for candidate_dir in candidate_dirs:
        report, rows = _load_result(candidate_dir)
        _validate_compatible(baseline_report, baseline_rows, report, rows, candidate_dir)
        safe_parameters = _candidate_parameters(rows, baseline_values)
        if not safe_parameters:
            rejected.append({"result_dir": str(candidate_dir.resolve()), "reason": "没有满足基线安全约束的参数"})
            continue
        best = min(safe_parameters, key=lambda row: (
            row["known_rejected"],
            row["hard_known_rejected"],
            row["processing_failures"],
            row["latency_ms_average"] if row["latency_ms_average"] is not None else float("inf"),
            row["wrong_person"],
            row["false_accept"],
            -row["min_margin"],
            -row["threshold"],
        ))
        options.append({
            "result_dir": str(candidate_dir.resolve()),
            "adapter_id": report["adapter"]["adapter_id"],
            "model_sha256": report["adapter"]["model_sha256"],
            "is_baseline": False,
            **best,
        })

    ranked = sorted(options, key=_rank_key)
    recommended = ranked[0] if sufficient else None
    output_dir = output_dir or (
        baseline_dir.resolve().parent / "comparisons" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    comparison = {
        "created_at": datetime.now().astimezone().isoformat(),
        "baseline_dir": str(baseline_dir.resolve()),
        "snapshot_sha256": baseline_report["snapshot"]["snapshot_sha256"],
        "target_selection_policy": baseline_report["target_selection_policy"],
        "minimum_labels": min_labels,
        "minimum_people": min_people,
        "actual_labels": baseline_values["labeled"],
        "actual_people": labeled_people,
        "sufficient_for_recommendation": sufficient,
        "safety_constraint": {
            "wrong_person_max": baseline_values["wrong_person"],
            "false_accept_max": baseline_values["false_accept"],
        },
        "recommended": recommended,
        "ranked": ranked,
        "rejected": rejected,
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fields = list(ranked[0])
    with (output_dir / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ranked)
    if sufficient and recommended is not None:
        conclusion = (
            f"推荐 `{recommended['adapter_id']}`，阈值 `{recommended['threshold']}`，"
            f"最小差值 `{recommended['min_margin']}`。"
        )
    else:
        conclusion = (
            f"当前只有 {baseline_values['labeled']} 条身份标注、{labeled_people} 个已知人物，"
            "未达到最低样本量，不给出候选推荐。"
        )
    lines = [
        "# 人脸候选比较报告",
        "",
        conclusion,
        "",
        f"安全上限：错误绑定不超过 {baseline_values['wrong_person']}，未知误接纳不超过 {baseline_values['false_accept']}。",
        "",
        "| 排名 | 适配器 | 阈值 | 最小差值 | 错误绑定 | 未知误接纳 | 已知拒识 | 困难桶拒识 | 失败 | 平均耗时 ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | {row['adapter_id']} | {row['threshold']} | {row['min_margin']} | "
            f"{row['wrong_person']} | {row['false_accept']} | {row['known_rejected']} | "
            f"{row['hard_known_rejected']} | {row['processing_failures']} | {row['latency_ms_average']} |"
        )
    lines.extend(["", "该报告只比较 calibration；锁定参数后再单次运行 holdout。", ""])
    (output_dir / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    return output_dir
