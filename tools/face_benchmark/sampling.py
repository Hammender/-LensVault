from __future__ import annotations

from collections import defaultdict
import random
from typing import Any


def is_hard_face(row: dict[str, Any], min_margin: float) -> bool:
    margin = row.get("match_margin")
    return bool(
        (row.get("face_size") is not None and float(row["face_size"]) < 80)
        or (row.get("pose_yaw") is not None and abs(float(row["pose_yaw"])) > 35)
        or (row.get("blur_score") is not None and float(row["blur_score"]) < 45)
        or (margin is not None and float(margin) < min_margin)
    )


def stratified_face_sample(
    rows: list[dict[str, Any]],
    *,
    target: int,
    seed: int,
    recognition_threshold: float,
    min_margin: float,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    target = min(target, len(shuffled))
    quotas = {
        "known": round(target * 0.50),
        "unknown_boundary": round(target * 0.25),
        "hard": round(target * 0.15),
    }
    quotas["random"] = target - sum(quotas.values())
    selected: list[dict[str, Any]] = []
    used: set[int] = set()

    def add(bucket: str, candidates: list[dict[str, Any]], limit: int) -> None:
        for row in candidates:
            face_id = int(row["face_id"])
            if face_id in used:
                continue
            selected.append({**row, "sample_bucket": bucket})
            used.add(face_id)
            if sum(item["sample_bucket"] == bucket for item in selected) >= limit:
                return

    known = [row for row in shuffled if row.get("suggested_person_id") is not None]
    by_person: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in known:
        by_person[int(row["suggested_person_id"])].append(row)
    person_ids = list(by_person)
    rng.shuffle(person_ids)
    coverage: list[dict[str, Any]] = []
    for pass_index in range(4):
        for person_id in person_ids:
            candidates = by_person[person_id]
            if pass_index < len(candidates):
                coverage.append(candidates[pass_index])
    coverage.extend(sorted(known, key=lambda row: not is_hard_face(row, min_margin)))
    add("known", coverage, quotas["known"])

    boundary = [
        row
        for row in shuffled
        if row.get("suggested_person_id") is None
        or (
            row.get("match_score") is not None
            and 0.30 <= float(row["match_score"]) < recognition_threshold
        )
    ]
    add("unknown_boundary", boundary, quotas["unknown_boundary"])
    hard = [row for row in shuffled if is_hard_face(row, min_margin)]
    add("hard", hard, quotas["hard"])
    add("random", shuffled, quotas["random"])

    if len(selected) < target:
        add("fill", shuffled, target - len(selected))
    return selected[:target]


def sample_detection_photos(rows: list[dict[str, Any]], *, target: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed + 1)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    hard = [
        row
        for row in shuffled
        if int(row.get("face_count") or 0) > 1
        or float(row.get("min_face_size") or 99999) < 80
        or float(row.get("max_abs_pose") or 0) > 35
    ]
    result = hard[: target // 2]
    used = {int(row["photo_id"]) for row in result}
    result.extend(row for row in shuffled if int(row["photo_id"]) not in used)
    return result[: min(target, len(rows))]
