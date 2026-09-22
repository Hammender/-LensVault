from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.tools.analyze_face_migration_audit import _match_faces


DEBUG_1 = "临时调试人物1"
DEBUG_2 = "临时调试人物2"
MANUAL_SOURCES = frozenset({"manual", "face_manual"})
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIGRATION_DIR = REPO_ROOT / "data" / "face-migration"


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"SQLite 文件不存在：{path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _person_names(connection: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row["id"]): str(row["display_name"])
        for row in connection.execute("SELECT id, display_name FROM persons")
    }


def _debug_queue_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        "SELECT p.display_name AS name, COUNT(*) AS photo_count "
        "FROM gallery_photo_person_tags t JOIN persons p ON p.id=t.person_id "
        "WHERE p.display_name IN (?, ?) GROUP BY p.display_name",
        (DEBUG_1, DEBUG_2),
    )
    counts = {DEBUG_1: 0, DEBUG_2: 0}
    for row in rows:
        counts[str(row["name"])] = int(row["photo_count"])
    counts["live_photos"] = int(connection.execute("SELECT COUNT(*) FROM gallery_photos").fetchone()[0])
    return counts


def _named_counts(counter: Counter[int], names: dict[int, str], limit: int = 20) -> list[dict[str, object]]:
    return [
        {"person_id": person_id, "display_name": names.get(person_id, f"人物{person_id}"), "photos": count}
        for person_id, count in counter.most_common(limit)
    ]


def _is_new_auto_known(face: dict[str, Any], after_unknown_ids: set[int]) -> bool:
    person_id = face.get("matched_person_id")
    return (
        person_id is not None
        and not face.get("needs_review")
        and face.get("predicted_person_id") == person_id
        and int(person_id) not in after_unknown_ids
    )


def source_aware_photo_stats(plans: Iterable[dict[str, Any]]) -> dict[str, Any]:
    lost_by_person: Counter[int] = Counter()
    gained_by_person: Counter[int] = Counter()
    category_counts: Counter[str] = Counter()
    kept_tags: Counter[str] = Counter()
    lost_tags: Counter[str] = Counter()
    equal = lost_only = extra_only = both = 0
    photos_manual = photos_all_recovered = photos_any_recovered = photos_none_recovered = 0
    photos_manual_no_face = photos_manual_no_face_recovered = 0
    photos_lost_auto = photos_lost_manual = photos_lost_face_manual = photos_lost_import = 0
    manual_tags = manual_tags_recovered = 0
    recovered_by_source: Counter[str] = Counter()
    total_by_source: Counter[str] = Counter()

    for plan in plans:
        category_counts[str(plan["category"])] += 1
        old_tags = list(plan["old_tags"])
        old_known = {
            int(tag["person_id"]): str(tag["source"])
            for tag in old_tags
            if str(tag["source"]) != "unknown"
        }
        new_known = {int(person_id) for person_id in plan["current_known_person_ids"]}
        lost = set(old_known) - new_known
        gained = new_known - set(old_known)
        for person_id, source in old_known.items():
            if person_id in new_known:
                kept_tags[source] += 1
            else:
                lost_tags[source] += 1
        manual_people = {person_id for person_id, source in old_known.items() if source in MANUAL_SOURCES}
        auto_people = {person_id for person_id, source in old_known.items() if source == "auto"}
        import_people = {person_id for person_id, source in old_known.items() if source == "import"}
        if manual_people:
            photos_manual += 1
            recovered = manual_people & new_known
            for person_id in manual_people:
                source = old_known[person_id]
                total_by_source[source] += 1
                manual_tags += 1
                if person_id in new_known:
                    manual_tags_recovered += 1
                    recovered_by_source[source] += 1
            if recovered:
                photos_any_recovered += 1
            if recovered == manual_people:
                photos_all_recovered += 1
            if not recovered:
                photos_none_recovered += 1
            if int(plan.get("old_face_count") or 0) == 0:
                photos_manual_no_face += 1
                if recovered:
                    photos_manual_no_face_recovered += 1
        if lost & auto_people:
            photos_lost_auto += 1
        if lost & {person_id for person_id, source in old_known.items() if source == "manual"}:
            photos_lost_manual += 1
        if lost & {person_id for person_id, source in old_known.items() if source == "face_manual"}:
            photos_lost_face_manual += 1
        if lost & import_people:
            photos_lost_import += 1
        if not lost and not gained:
            equal += 1
            continue
        for person_id in lost:
            lost_by_person[person_id] += 1
        for person_id in gained:
            gained_by_person[person_id] += 1
        if lost and gained:
            both += 1
        elif lost:
            lost_only += 1
        else:
            extra_only += 1
        # jenny filled later if names known; keep raw ids in counters only

    return {
        "equal": equal,
        "lost_only": lost_only,
        "extra_only": extra_only,
        "both_lost_and_gained": both,
        "lost_photos": lost_only + both,
        "gained_photos": extra_only + both,
        "lost_by_person": lost_by_person,
        "gained_by_person": gained_by_person,
        "category_counts": category_counts,
        "kept_tags_by_source": dict(kept_tags),
        "lost_tags_by_source": dict(lost_tags),
        "photos_lost_auto": photos_lost_auto,
        "photos_lost_manual": photos_lost_manual,
        "photos_lost_face_manual": photos_lost_face_manual,
        "photos_lost_import": photos_lost_import,
        "manual_photos": photos_manual,
        "manual_photos_all_auto_matched": photos_all_recovered,
        "manual_photos_any_auto_matched": photos_any_recovered,
        "manual_photos_none_auto_matched": photos_none_recovered,
        "manual_photos_no_old_face": photos_manual_no_face,
        "manual_photos_no_old_face_auto_matched": photos_manual_no_face_recovered,
        "manual_person_tags": manual_tags,
        "manual_person_tags_auto_matched": manual_tags_recovered,
        "manual_person_tags_by_source": dict(total_by_source),
        "manual_person_tags_auto_matched_by_source": dict(recovered_by_source),
    }


def analyze_audit_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    known_to_unknown_by_source: Counter[str] = Counter()
    photos_manual = set()
    photos_any_recovered = set()
    photos_no_old_face = set()
    photos_no_old_face_recovered = set()
    photos_old_auto_failed_recovered = set()
    photos_old_already_matched_recovered = set()
    person_tags_recovered = 0
    person_tags_no_old_face_recovered = 0
    person_tags_old_auto_failed_recovered = 0
    person_tags_already_matched_recovered = 0

    for row in rows:
        if row.get("status") != "success":
            continue
        before = row["before"]
        after = row["after"]
        tag_source = {int(tag["person_id"]): str(tag["source"]) for tag in before["person_tags"]}
        before_unknown = {person_id for person_id, source in tag_source.items() if source == "unknown"}
        after_unknown = {
            int(tag["person_id"]) for tag in after["person_tags"] if str(tag["source"]) == "unknown"
        }
        matches, _removed, _added = _match_faces(before["faces"], after["faces"])
        for old, new in matches:
            old_unknown = (
                bool(old.get("needs_review"))
                or old.get("matched_person_id") is None
                or old.get("matched_person_id") in before_unknown
            )
            new_unknown = (
                bool(new.get("needs_review"))
                or new.get("matched_person_id") is None
                or new.get("matched_person_id") in after_unknown
            )
            if old_unknown or not new_unknown:
                continue
            matched_id = old.get("matched_person_id")
            source = tag_source.get(int(matched_id)) if matched_id is not None else None
            known_to_unknown_by_source[source or "no_photo_tag"] += 1

        manual_people = {person_id for person_id, source in tag_source.items() if source in MANUAL_SOURCES}
        if not manual_people:
            continue
        photo_id = int(row["gallery_photo_id"])
        photos_manual.add(photo_id)
        old_faces = before["faces"]
        no_old_face = not old_faces
        if no_old_face:
            photos_no_old_face.add(photo_id)
        old_known_face_people = {
            int(face["matched_person_id"])
            for face in old_faces
            if face.get("matched_person_id") is not None and not face.get("needs_review")
        }
        new_auto_people = {
            int(face["matched_person_id"])
            for face in after["faces"]
            if _is_new_auto_known(face, after_unknown)
        }
        recovered = manual_people & new_auto_people
        if recovered:
            photos_any_recovered.add(photo_id)
            if no_old_face:
                photos_no_old_face_recovered.add(photo_id)
            elif recovered - old_known_face_people:
                photos_old_auto_failed_recovered.add(photo_id)
            if recovered & old_known_face_people:
                photos_old_already_matched_recovered.add(photo_id)
        for person_id in recovered:
            person_tags_recovered += 1
            if no_old_face:
                person_tags_no_old_face_recovered += 1
            elif person_id not in old_known_face_people:
                person_tags_old_auto_failed_recovered += 1
            else:
                person_tags_already_matched_recovered += 1

    return {
        "known_to_unknown_by_source": dict(known_to_unknown_by_source),
        "known_to_unknown_total": sum(known_to_unknown_by_source.values()),
        "manual_photos": len(photos_manual),
        "manual_photos_any_auto_matched": len(photos_any_recovered),
        "manual_photos_no_old_face": len(photos_no_old_face),
        "manual_photos_no_old_face_auto_matched": len(photos_no_old_face_recovered),
        "manual_photos_old_auto_failed_now_matched": len(photos_old_auto_failed_recovered),
        "manual_photos_old_already_matched": len(photos_old_already_matched_recovered),
        "manual_photos_true_lift": len(photos_no_old_face_recovered) + len(photos_old_auto_failed_recovered),
        "manual_person_tags_auto_matched": person_tags_recovered,
        "manual_person_tags_no_old_face_auto_matched": person_tags_no_old_face_recovered,
        "manual_person_tags_old_auto_failed_now_matched": person_tags_old_auto_failed_recovered,
        "manual_person_tags_old_already_matched": person_tags_already_matched_recovered,
    }


def _load_audit_rows(path: Path) -> list[dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            latest[int(row["gallery_photo_id"])] = row
    return list(latest.values())


def summarize(
    *,
    reconcile_report: dict[str, Any],
    audit_summary: dict[str, Any] | None,
    names: dict[int, str],
    live_queue: dict[str, int] | None,
    frozen_photo_count: int,
    audit_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    photo_stats = source_aware_photo_stats(reconcile_report["plans"])
    jenny_id = next((person_id for person_id, name in names.items() if name == "金珍妮-Jenny"), None)
    extra_only_jenny = jenny_gained = jenny_lost = 0
    if jenny_id is not None:
        for plan in reconcile_report["plans"]:
            old_known = {
                int(tag["person_id"]) for tag in plan["old_tags"] if str(tag["source"]) != "unknown"
            }
            new_known = {int(person_id) for person_id in plan["current_known_person_ids"]}
            lost = old_known - new_known
            gained = new_known - old_known
            if jenny_id in gained:
                jenny_gained += 1
            if jenny_id in lost:
                jenny_lost += 1
            if gained and not lost and gained == {jenny_id}:
                extra_only_jenny += 1

    face_counts = (audit_summary or {}).get("counts") or {}
    known_to_unknown_by_source = (audit_stats or {}).get("known_to_unknown_by_source") or {}
    return {
        "scope": {
            "note": "人脸框层和图片已知人物集合均来自 2026-09-08/09 迁移冻结数据，不是当前图库。",
            "frozen_gallery_photos": frozen_photo_count,
            "reconcile_photo_count": int(reconcile_report.get("photo_count") or len(reconcile_report["plans"])),
        },
        "face_level": {
            "aligned_faces": face_counts.get("faces_matched_by_iou"),
            "known_identity_unchanged": face_counts.get("known_identity_unchanged"),
            "known_to_unknown": face_counts.get("known_to_unknown"),
            "unknown_to_known": face_counts.get("unknown_to_known"),
            "known_identity_changed": face_counts.get("known_identity_changed"),
            "unknown_to_unknown": face_counts.get("unknown_to_unknown"),
            "detections_added": face_counts.get("detections_added"),
            "detections_removed": face_counts.get("detections_removed"),
            "faces_before": face_counts.get("faces_before"),
            "faces_after": face_counts.get("faces_after"),
            "known_to_unknown_by_old_tag_source": known_to_unknown_by_source,
            "known_to_unknown_from_auto_tag": int(known_to_unknown_by_source.get("auto") or 0),
            "known_to_unknown_from_manual_tag": int(known_to_unknown_by_source.get("manual") or 0)
            + int(known_to_unknown_by_source.get("face_manual") or 0),
            "known_to_unknown_without_photo_tag": int(known_to_unknown_by_source.get("no_photo_tag") or 0),
        },
        "photo_known_set": {
            "equal": photo_stats["equal"],
            "lost_only": photo_stats["lost_only"],
            "extra_only": photo_stats["extra_only"],
            "both_lost_and_gained": photo_stats["both_lost_and_gained"],
            "extra_only_jenny_only": extra_only_jenny,
            "photos_gained_jenny": jenny_gained,
            "photos_lost_jenny": jenny_lost,
            "lost_photos": photo_stats["lost_photos"],
            "gained_photos": photo_stats["gained_photos"],
            "kept_tags_by_source": photo_stats["kept_tags_by_source"],
            "lost_tags_by_source": photo_stats["lost_tags_by_source"],
            "photos_lost_auto": photo_stats["photos_lost_auto"],
            "photos_lost_manual": photo_stats["photos_lost_manual"],
            "photos_lost_face_manual": photo_stats["photos_lost_face_manual"],
            "photos_lost_import": photo_stats["photos_lost_import"],
        },
        "manual_now_auto": {
            "photos_with_manual_or_face_manual": photo_stats["manual_photos"],
            "photos_all_manual_people_auto_matched": photo_stats["manual_photos_all_auto_matched"],
            "photos_any_manual_people_auto_matched": photo_stats["manual_photos_any_auto_matched"],
            "photos_no_manual_people_auto_matched": photo_stats["manual_photos_none_auto_matched"],
            "person_tags": photo_stats["manual_person_tags"],
            "person_tags_auto_matched": photo_stats["manual_person_tags_auto_matched"],
            "person_tags_by_source": photo_stats["manual_person_tags_by_source"],
            "person_tags_auto_matched_by_source": photo_stats["manual_person_tags_auto_matched_by_source"],
            "photos_no_old_face": photo_stats["manual_photos_no_old_face"],
            "photos_no_old_face_auto_matched": photo_stats["manual_photos_no_old_face_auto_matched"],
            "true_lift_photos": (audit_stats or {}).get("manual_photos_true_lift"),
            "photos_old_no_face_now_matched": (audit_stats or {}).get("manual_photos_no_old_face_auto_matched"),
            "photos_old_auto_failed_now_matched": (audit_stats or {}).get("manual_photos_old_auto_failed_now_matched"),
            "photos_old_already_had_known_face": (audit_stats or {}).get("manual_photos_old_already_matched"),
        },
        "reconcile_categories": dict(photo_stats["category_counts"]),
        "top_lost_people": _named_counts(photo_stats["lost_by_person"], names),
        "top_gained_people": _named_counts(photo_stats["gained_by_person"], names),
        "live_review_queue": live_queue,
    }


def _source_count(mapping: dict[str, int], *keys: str) -> int:
    return sum(int(mapping.get(key) or 0) for key in keys)


def _markdown(report: dict[str, Any]) -> str:
    scope = report["scope"]
    faces = report["face_level"]
    photos = report["photo_known_set"]
    manual = report["manual_now_auto"]
    live = report.get("live_review_queue") or {}
    lost_tags = photos.get("lost_tags_by_source") or {}
    kept_tags = photos.get("kept_tags_by_source") or {}
    recovered_by_source = manual.get("person_tags_auto_matched_by_source") or {}
    total_by_source = manual.get("person_tags_by_source") or {}
    lines = [
        "# 人脸模型迁移重构效果概览",
        "",
        scope["note"],
        "",
        f"- 冻结图库照片：{scope['frozen_gallery_photos']} 张",
        f"- 标签重整覆盖：{scope['reconcile_photo_count']} 张",
        "",
        "## 以前靠手动，现在新模型能否自动认对",
        "",
        "这里只看迁移前标签来源是 `manual`（给图片打人物）或 `face_manual`（给人脸指定人物）的记录。",
        "“自动认对”指新模型重识别时用自动匹配接受了同一个人，不依赖你当时的手动标签。",
        "",
        "| 口径 | 数量 |",
        "|---|---:|",
        f"| 曾手动绑定人物的图片 | {manual.get('photos_with_manual_or_face_manual')} |",
        f"| 新模型自动认对其中全部手动人物 | {manual.get('photos_all_manual_people_auto_matched')} |",
        f"| 新模型至少自动认对其中一个手动人物 | {manual.get('photos_any_manual_people_auto_matched')} |",
        f"| 新模型一个都没自动认对 | {manual.get('photos_no_manual_people_auto_matched')} |",
        f"| 手动人物标签条数 | {manual.get('person_tags')} |",
        f"| 其中被新模型自动认对 | {manual.get('person_tags_auto_matched')} |",
        f"| 　图片人物标签 `manual` | {recovered_by_source.get('manual', 0)} / {total_by_source.get('manual', 0)} |",
        f"| 　人脸指定 `face_manual` | {recovered_by_source.get('face_manual', 0)} / {total_by_source.get('face_manual', 0)} |",
        "",
        f"上面 {manual.get('photos_any_manual_people_auto_matched')} 张里，有一部分旧模型其实已经把人脸绑上了，标签只是一直保留手动来源。真正属于“旧自动做不到、新自动做到了”的是：",
        "",
        "| 细分 | 图片 |",
        "|---|---:|",
        f"| 旧图没有人脸，新模型检出并认对 | {manual.get('photos_old_no_face_now_matched')} |",
        f"| 旧图有人脸但没把这个人自动认下，新模型认对 | {manual.get('photos_old_auto_failed_now_matched')} |",
        f"| 合计（旧自动失败 → 新自动成功） | {manual.get('true_lift_photos')} |",
        f"| 旧人脸已经绑着这个人，新模型继续认对 | {manual.get('photos_old_already_had_known_face')} |",
        f"| 旧图没有人脸的手动图总数 | {manual.get('photos_no_old_face')} |",
        "",
        "## 人脸框层（同一张脸对齐后）",
        "",
        "这是“原先这张脸是已知人物 / 现在这张脸变成未知”的口径。",
        "",
        "| 变化 | 数量 |",
        "|---|---:|",
        f"| 对齐人脸 | {faces.get('aligned_faces')} |",
        f"| 已知身份不变 | {faces.get('known_identity_unchanged')} |",
        f"| 旧已知 → 新未知 | {faces.get('known_to_unknown')} |",
        f"| 　其中旧人物标签是自动识别 `auto` | {faces.get('known_to_unknown_from_auto_tag')} |",
        f"| 　其中旧人物标签是手动 `manual` / `face_manual` | {faces.get('known_to_unknown_from_manual_tag')} |",
        f"| 　其中这张图上没有对应人物标签 | {faces.get('known_to_unknown_without_photo_tag')} |",
        f"| 旧未知 → 新已知 | {faces.get('unknown_to_known')} |",
        f"| 已知人物互变 | {faces.get('known_identity_changed')} |",
        f"| 仍为未知 | {faces.get('unknown_to_unknown')} |",
        f"| 新模型多检出的脸 | {faces.get('detections_added')} |",
        f"| 旧脸消失 | {faces.get('detections_removed')} |",
        f"| 迁移前人脸 | {faces.get('faces_before')} |",
        f"| 迁移后人脸 | {faces.get('faces_after')} |",
        "",
        f"{faces.get('known_to_unknown')} 条“旧已知 → 新未知”里，只有旧标签为 `auto` 的才是“原来自动认得出、现在认不出”。",
        "旧标签为手动的那些，多半本来就是你手动补的人物，新模型这张脸没自动接受，不等于把旧自动识别弄丢了。",
        "",
        "## 图片已知人物集合层",
        "",
        "比较迁移前图片上的已知人物，和新模型当时匹配成功的已知人物。一张图可以同时丢失旧人物、多出新人物。",
        "",
        "| 变化类型 | 张数 | 含义 |",
        "|---|---:|---|",
        f"| 完全一致 | {photos['equal']} | 新旧已知集合相同 |",
        f"| 只丢失旧人物 | {photos['lost_only']} | 旧模型标过的人，新模型这张图上没再匹配到 |",
        f"| 只多出新人物 | {photos['extra_only']} | 新模型多认了人 |",
        f"| 其中只多出金珍妮-Jenny | {photos['extra_only_jenny_only']} | 调试人物2队列膨胀的主因 |",
        f"| 既丢失又多出 | {photos['both_lost_and_gained']} | 集合两边都变 |",
        f"| 至少丢失一人 | {photos['lost_photos']} | 含“只丢失”和“既丢失又多出” |",
        f"| 至少多出一人 | {photos['gained_photos']} | 含“只多出”和“既丢失又多出” |",
        f"| 金珍妮被新模型加上的图 | {photos['photos_gained_jenny']} | |",
        f"| 金珍妮被新模型拿掉的图 | {photos['photos_lost_jenny']} | |",
        "",
        "按旧标签来源拆开“新模型自动结果里没有这个人”：",
        "",
        "| 旧标签来源 | 仍被自动认到的条数 | 新模型没自动认到的条数 | 涉及图片（没认到） |",
        "|---|---:|---:|---:|",
        f"| 自动识别 `auto` | {_source_count(kept_tags, 'auto')} | {_source_count(lost_tags, 'auto')} | {photos.get('photos_lost_auto')} |",
        f"| 图片手动 `manual` | {_source_count(kept_tags, 'manual')} | {_source_count(lost_tags, 'manual')} | {photos.get('photos_lost_manual')} |",
        f"| 人脸指定 `face_manual` | {_source_count(kept_tags, 'face_manual')} | {_source_count(lost_tags, 'face_manual')} | {photos.get('photos_lost_face_manual')} |",
        f"| 导入 `import` | {_source_count(kept_tags, 'import')} | {_source_count(lost_tags, 'import')} | {photos.get('photos_lost_import')} |",
        "",
        "### 丢失最多的人物",
        "",
        "| 人物 | 张数 |",
        "|---|---:|",
    ]
    for item in report["top_lost_people"]:
        lines.append(f"| {item['display_name']} | {item['photos']} |")
    lines.extend(["", "### 多出最多的人物", "", "| 人物 | 张数 |", "|---|---:|"])
    for item in report["top_gained_people"]:
        lines.append(f"| {item['display_name']} | {item['photos']} |")
    lines.extend(
        [
            "",
            "## 标签重整分类（当时打审核标记的依据）",
            "",
            "| 分类 | 张数 |",
            "|---|---:|",
            f"| 受保护来源冲突 → 临时调试人物1 | {report['reconcile_categories'].get('preserved_sources_conflict', 0)} |",
            f"| 普通 auto 冲突 → 临时调试人物2 | {report['reconcile_categories'].get('auto_conflict', 0)} |",
            f"| 受保护来源一致 | {report['reconcile_categories'].get('preserved_sources_equal', 0)} |",
            f"| 普通 auto 一致 | {report['reconcile_categories'].get('auto_equal', 0)} |",
            f"| 迁移前已有未知，恢复旧标签 | {report['reconcile_categories'].get('legacy_unknown_restore', 0)} |",
            f"| 其它 | {report['reconcile_categories'].get('ordinary_unknown_cleanup', 0) + report['reconcile_categories'].get('unchanged', 0)} |",
            "",
        ]
    )
    if live:
        lines.extend(
            [
                "## 当前审核队列（线上库，含迁移后改动）",
                "",
                "这部分不是迁移当时的结果，只说明现在还剩多少张没审完。",
                "",
                f"- 当前图库照片：{live.get('live_photos')} 张（冻结时为 {scope['frozen_gallery_photos']} 张）",
                f"- {DEBUG_1}：{live.get(DEBUG_1)} 张（重整当时 318 张）",
                f"- {DEBUG_2}：{live.get(DEBUG_2)} 张（重整当时 226 张）",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="根据迁移冻结快照汇总新人脸模型对全图库的重构效果，只读。")
    parser.add_argument("--old-db", type=Path, default=DEFAULT_MIGRATION_DIR / "pre-migration-20260908" / "app-before.db")
    parser.add_argument("--reconcile-report", type=Path, default=DEFAULT_MIGRATION_DIR / "gallery-tag-reconcile-apply.json")
    parser.add_argument("--audit-summary", type=Path, default=DEFAULT_MIGRATION_DIR / "full-apply-summary.json")
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_MIGRATION_DIR / "full-apply.jsonl")
    parser.add_argument("--database", type=Path, help="当前 SQLite，仅用于统计剩余临时调试人物；默认读取运行配置。")
    parser.add_argument("--output", type=Path, default=DEFAULT_MIGRATION_DIR / "rerecognition-overview")
    parser.add_argument("--skip-live", action="store_true", help="不读取当前图库。")
    args = parser.parse_args()

    old = _connect(args.old_db)
    names = _person_names(old)
    frozen_photo_count = int(old.execute("SELECT COUNT(*) FROM gallery_photos").fetchone()[0])
    old.close()

    reconcile_report = json.loads(args.reconcile_report.read_text(encoding="utf-8"))
    audit_summary = None
    if args.audit_summary.is_file():
        audit_summary = json.loads(args.audit_summary.read_text(encoding="utf-8"))
    audit_stats = None
    if args.audit_file.is_file():
        audit_stats = analyze_audit_rows(_load_audit_rows(args.audit_file))

    live_queue = None
    if not args.skip_live:
        if args.database is not None:
            live_path = args.database
        else:
            url = make_url(get_settings().database_url)
            live_path = Path(url.database) if url.database else None
        if live_path is not None and live_path.is_file():
            live = _connect(live_path)
            names.update(_person_names(live))
            live_queue = _debug_queue_counts(live)
            live.close()

    report = summarize(
        reconcile_report=reconcile_report,
        audit_summary=audit_summary,
        names=names,
        live_queue=live_queue,
        frozen_photo_count=frozen_photo_count,
        audit_stats=audit_stats,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "overview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = _markdown(report)
    (args.output / "overview.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "face_level": {
            "known_to_unknown": report["face_level"]["known_to_unknown"],
            "known_to_unknown_from_auto_tag": report["face_level"]["known_to_unknown_from_auto_tag"],
            "known_to_unknown_from_manual_tag": report["face_level"]["known_to_unknown_from_manual_tag"],
        },
        "manual_now_auto": report["manual_now_auto"],
        "live_review_queue": report["live_review_queue"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
