from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person, SamplePhoto
from app.services.importer import PictureService
from app.services.similarity import mark_similarity_scans_stale
from app.tools.analyze_face_migration_audit import _match_faces


DEBUG_1 = "临时调试人物1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OLD_DB = REPO_ROOT / "data" / "face-migration" / "pre-migration-20260908" / "app-before.db"


@dataclass(frozen=True)
class RestoreContext:
    debug1_id: int
    unknown_ids: set[int]
    old_photo_ids: set[int]
    old_tags_by_photo: dict[int, list[dict[str, Any]]]
    old_faces_by_photo: dict[int, list[dict[str, Any]]]


def _person_by_display_name(db: Session, name: str) -> Person | None:
    return db.scalar(select(Person).where(Person.display_name == name))


def _tag_pairs(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"person_id": int(tag["person_id"]), "source": str(tag["source"])} for tag in tags]


def _current_tags(db: Session, photo_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(GalleryPhotoPersonTag.person_id, GalleryPhotoPersonTag.source)
        .where(GalleryPhotoPersonTag.gallery_photo_id == photo_id)
        .order_by(GalleryPhotoPersonTag.person_id)
    ).all()
    return [{"person_id": int(person_id), "source": str(source)} for person_id, source in rows]


def _current_faces(db: Session, photo_id: int) -> list[dict[str, Any]]:
    faces = list(
        db.scalars(
            select(FaceRecord).where(FaceRecord.gallery_photo_id == photo_id).order_by(FaceRecord.id)
        ).all()
    )
    return [
        {
            "face_record_id": face.id,
            "bbox": [face.bbox_left, face.bbox_top, face.bbox_right, face.bbox_bottom],
            "matched_person_id": face.matched_person_id,
            "needs_review": bool(face.needs_review),
        }
        for face in faces
    ]


def _promoted_samples(db: Session, photo_id: int) -> list[SamplePhoto]:
    return list(db.scalars(select(SamplePhoto).where(
        SamplePhoto.source_gallery_photo_id == photo_id,
        SamplePhoto.source_gallery_face_id.is_not(None),
        SamplePhoto.status == "ready",
    )).all())


def _promotion_conflicts(samples: list[SamplePhoto], faces: list[dict[str, Any]],
                         legacy_tags: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, int]]:
    face_by_id = {int(face["face_record_id"]): face for face in faces}
    update_by_id = {int(update["face_record_id"]): update for update in updates}
    tag_ids = {int(tag["person_id"]) for tag in legacy_tags}
    conflicts = []
    for sample in samples:
        face_id = int(sample.source_gallery_face_id)
        face = face_by_id.get(face_id)
        update = update_by_id.get(face_id)
        if (face is None or face["matched_person_id"] != sample.person_id
                or sample.person_id not in tag_ids
                or (update is not None and update["matched_person_id"] != sample.person_id)):
            conflicts.append({"sample_photo_id": sample.id, "face_record_id": face_id,
                              "person_id": sample.person_id})
    return conflicts


def load_old_context(old_db: Path) -> tuple[set[int], dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    connection = sqlite3.connect(old_db)
    connection.row_factory = sqlite3.Row
    try:
        photo_ids = {int(row[0]) for row in connection.execute("SELECT id FROM gallery_photos")}
        tags_by_photo: dict[int, list[dict[str, Any]]] = {}
        for row in connection.execute(
            "SELECT gallery_photo_id, person_id, source FROM gallery_photo_person_tags "
            "ORDER BY gallery_photo_id, person_id"
        ):
            tags_by_photo.setdefault(int(row["gallery_photo_id"]), []).append(
                {"person_id": int(row["person_id"]), "source": str(row["source"])}
            )
        faces_by_photo: dict[int, list[dict[str, Any]]] = {}
        for row in connection.execute(
            "SELECT id, gallery_photo_id, bbox_left, bbox_top, bbox_right, bbox_bottom, "
            "matched_person_id, needs_review FROM face_records WHERE gallery_photo_id IS NOT NULL "
            "ORDER BY gallery_photo_id, id"
        ):
            faces_by_photo.setdefault(int(row["gallery_photo_id"]), []).append(
                {
                    "id": int(row["id"]),
                    "bbox": [
                        float(row["bbox_left"]),
                        float(row["bbox_top"]),
                        float(row["bbox_right"]),
                        float(row["bbox_bottom"]),
                    ],
                    "matched_person_id": None if row["matched_person_id"] is None else int(row["matched_person_id"]),
                    "needs_review": bool(row["needs_review"]),
                }
            )
    finally:
        connection.close()
    return photo_ids, tags_by_photo, faces_by_photo


def _known_ids(tags: list[dict[str, Any]], *, exclude: set[int]) -> set[int]:
    return {int(tag["person_id"]) for tag in tags if int(tag["person_id"]) not in exclude}


def plan_restore(db: Session, context: RestoreContext) -> list[dict[str, Any]]:
    photo_ids = list(
        db.scalars(
            select(GalleryPhotoPersonTag.gallery_photo_id)
            .where(GalleryPhotoPersonTag.person_id == context.debug1_id)
            .order_by(GalleryPhotoPersonTag.gallery_photo_id)
        ).all()
    )
    missing = [photo_id for photo_id in photo_ids if photo_id not in context.old_photo_ids]
    if missing:
        raise RuntimeError(f"迁移前备份中找不到这些图片：{missing}")
    plans: list[dict[str, Any]] = []
    exclude_for_compare = {context.debug1_id, *context.unknown_ids}
    for photo_id in photo_ids:
        photo = db.get(GalleryPhoto, photo_id)
        if photo is None:
            raise RuntimeError(f"图库照片不存在：{photo_id}")
        current_tags = _current_tags(db, photo_id)
        old_tags = _tag_pairs(context.old_tags_by_photo.get(photo_id, []))
        if not old_tags:
            raise RuntimeError(f"迁移前备份中该图没有人物标签：{photo_id}")
        current_known = _known_ids(current_tags, exclude=exclude_for_compare)
        old_known = _known_ids(old_tags, exclude=context.unknown_ids)
        action = "keep" if current_known != old_known else "restore"
        current_faces = _current_faces(db, photo_id)
        old_faces = context.old_faces_by_photo.get(photo_id, [])
        matches, unmatched_old, unmatched_new = _match_faces(old_faces, current_faces)
        restored_ids = {int(tag["person_id"]) for tag in old_tags}
        promoted_samples = _promoted_samples(db, photo_id)
        promoted = {int(sample.source_gallery_face_id) for sample in promoted_samples}
        rebound_ids: set[int] = set()
        face_updates: list[dict[str, Any]] = []
        if action == "restore":
            for old_face, new_face in matches:
                face_id = int(new_face["face_record_id"])
                rebound_ids.add(face_id)
                face_updates.append(
                    {
                        "action": "rebind",
                        "face_record_id": face_id,
                        "old_face_record_id": old_face.get("id"),
                        "from_person_id": new_face.get("matched_person_id"),
                        "matched_person_id": old_face.get("matched_person_id"),
                        "needs_review": bool(old_face.get("needs_review")),
                    }
                )
            rebound_person_by_face = {
                int(update["face_record_id"]): update["matched_person_id"] for update in face_updates
            }
            for face in current_faces:
                face_id = int(face["face_record_id"])
                matched = rebound_person_by_face.get(face_id, face.get("matched_person_id"))
                if face_id in promoted:
                    continue
                if matched in restored_ids:
                    continue
                face_updates.append(
                    {
                        "action": "unbind",
                        "face_record_id": face_id,
                        "from_person_id": face.get("matched_person_id"),
                        "matched_person_id": None,
                        "needs_review": True,
                    }
                )
            conflicts = _promotion_conflicts(promoted_samples, current_faces, old_tags, face_updates)
            if conflicts:
                action = "keep"
                face_updates = []
            else:
                face_updates = [update for update in face_updates if update["face_record_id"] not in promoted]
        else:
            conflicts = []
        plans.append(
            {
                "gallery_photo_id": photo_id,
                "workspace_id": photo.workspace_id,
                "action": action,
                "current_tags": current_tags,
                "legacy_tags": old_tags,
                "current_known_person_ids": sorted(current_known),
                "legacy_known_person_ids": sorted(old_known),
                "face_updates": face_updates,
                "unmatched_old_faces": unmatched_old if action == "restore" else 0,
                "unmatched_current_faces": unmatched_new if action == "restore" else 0,
                "promoted_face_ids": sorted(promoted),
                "keep_reason": "promoted_sample_conflict" if conflicts else None,
                "promoted_sample_conflicts": conflicts,
            }
        )
    return plans


def apply_restore(
    db: Session,
    context: RestoreContext,
    plans: list[dict[str, Any]],
    picture_service: PictureService,
) -> None:
    stale_by_workspace: dict[int | None, set[int]] = {}
    for plan in plans:
        if plan["action"] != "restore":
            continue
        photo_id = int(plan["gallery_photo_id"])
        photo = db.get(GalleryPhoto, photo_id)
        if photo is None:
            raise RuntimeError(f"图库照片不存在：{photo_id}")
        samples = _promoted_samples(db, photo_id)
        promoted = {int(sample.source_gallery_face_id) for sample in samples}
        conflicts = _promotion_conflicts(samples, _current_faces(db, photo_id),
                                         plan["legacy_tags"], plan["face_updates"])
        if conflicts:
            plan["action"] = "keep"
            plan["keep_reason"] = "promoted_sample_conflict"
            plan["promoted_sample_conflicts"] = conflicts
            plan["promoted_face_ids"] = sorted(promoted)
            plan["face_updates"] = []
            continue
        plan["face_updates"] = [update for update in plan["face_updates"]
                                if int(update["face_record_id"]) not in promoted]
        plan["promoted_face_ids"] = sorted(promoted)
        old_person_ids = {int(tag.person_id) for tag in photo.person_tags}
        for tag in list(photo.person_tags):
            db.delete(tag)
        db.flush()
        for tag in plan["legacy_tags"]:
            person_id = int(tag["person_id"])
            if db.get(Person, person_id) is None:
                raise RuntimeError(f"迁移前人物不存在：photo_id={photo_id}, person_id={person_id}")
            db.add(
                GalleryPhotoPersonTag(
                    gallery_photo_id=photo_id,
                    person_id=person_id,
                    source=str(tag["source"]),
                )
            )
        db.flush()
        for update in plan["face_updates"]:
            face = db.get(FaceRecord, int(update["face_record_id"]))
            if face is None or face.gallery_photo_id != photo_id:
                raise RuntimeError(
                    f"当前人脸不存在或不属于照片：photo_id={photo_id}, face_id={update['face_record_id']}"
                )
            face.matched_person_id = update["matched_person_id"]
            face.needs_review = bool(update["needs_review"])
            if face.matched_person_id is not None:
                face.vector_collection = None
        picture_service.sync_inherited_gallery_tags(db, photo_id)
        new_person_ids = {int(tag["person_id"]) for tag in plan["legacy_tags"]}
        changed = old_person_ids.symmetric_difference(new_person_ids)
        if changed:
            stale_by_workspace.setdefault(plan["workspace_id"], set()).update(changed)
    for workspace_id, person_ids in stale_by_workspace.items():
        if workspace_id is None:
            continue
        mark_similarity_scans_stale(db, int(workspace_id), person_ids)
    db.commit()


def summarize_plans(plans: list[dict[str, Any]], *, applied: bool) -> dict[str, Any]:
    restore = [plan for plan in plans if plan["action"] == "restore"]
    keep = [plan for plan in plans if plan["action"] == "keep"]
    return {
        "applied": applied,
        "target_photos": len(plans),
        "restore_photos": len(restore),
        "keep_photos": len(keep),
        "keep_photo_ids": [plan["gallery_photo_id"] for plan in keep],
        "face_rebinds": sum(1 for plan in restore for update in plan["face_updates"] if update["action"] == "rebind"),
        "face_unbinds": sum(1 for plan in restore for update in plan["face_updates"] if update["action"] == "unbind"),
        "plans": plans,
    }


def restore_debug1_legacy_tags(
    db: Session,
    context: RestoreContext,
    picture_service: PictureService,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    plans = plan_restore(db, context)
    if apply:
        apply_restore(db, context, plans, picture_service)
    else:
        db.rollback()
    return summarize_plans(plans, applied=apply)


def _picture_service() -> PictureService:
    return PictureService(
        storage=SimpleNamespace(),
        face_service=SimpleNamespace(),
        vector_store=SimpleNamespace(),
        ocr_service=SimpleNamespace(),
        settings=get_settings(),
    )


def _backup_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    with sqlite3.connect(target) as backup:
        integrity = backup.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise SystemExit(f"SQLite 备份完整性检查失败：{integrity}")


def _write_notes(path: Path, result: dict[str, Any], *, old_db: Path, backup_db: Path | None) -> None:
    keep_ids = ", ".join(str(photo_id) for photo_id in result["keep_photo_ids"]) or "无"
    backup_line = str(backup_db) if backup_db is not None else "预演未生成数据库备份"
    lines = [
        "# 临时调试人物1 标签按迁移前备份复原",
        "",
        "## 目的",
        "",
        "当前库里仍带「临时调试人物1」的图片中，已知人物集合与迁移前备份相同且不冲突已提升样本的，整份人物标签集换回备份；已知人物集合不同或存在样本冲突的图片整张保留，包括临时调试人物1。",
        "",
        "## 对照与备份",
        "",
        f"- 对照库：`{old_db}`",
        f"- 清理前生产库备份：`{backup_line}`",
        f"- 正式写入：{'是' if result['applied'] else '否（预演）'}",
        "",
        "## 范围与结果",
        "",
        f"- 目标图片：{result['target_photos']}",
        f"- 整份复原：{result['restore_photos']}",
        f"- 整张保留：{result['keep_photos']}（{keep_ids}）",
        f"- 人脸按框重绑：{result['face_rebinds']}",
        f"- 人脸解绑（检测框保留）：{result['face_unbinds']}",
        "",
        "临时调试人物1 人物记录未删除，仍挂在保留的图片上。未改动临时调试人物2、Qdrant、MinIO。",
        "",
        "## 回滚",
        "",
        "先停止后端。用本目录 `app-before.db` 覆盖 `E:/dockerVolums/picture-show/sqllite/app.db`。若生产库带有 `-wal` / `-shm`，停进程后再替换，避免只换主文件。",
        "",
        "详细逐图计划见同目录 `apply.json` 或 `dry-run.json`。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="把临时调试人物1 图片中已知集合未变的图整份复原为 AdaFace 迁移前人物标签。")
    parser.add_argument("--old-db", type=Path, default=DEFAULT_OLD_DB)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式写入必须同时提供 --apply --confirm；预演时两个参数都不要提供。")
    if not args.old_db.is_file():
        raise SystemExit(f"迁移前备份不存在：{args.old_db}")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = (args.output or (REPO_ROOT / "data" / "face-migration" / f"restore-debug1-legacy-tags-{timestamp}")).resolve()
    output.mkdir(parents=True, exist_ok=True)

    picture_service = _picture_service()
    old_photo_ids, old_tags, old_faces = load_old_context(args.old_db)
    backup_path: Path | None = None
    with SessionLocal() as db:
        debug1 = _person_by_display_name(db, DEBUG_1)
        if debug1 is None:
            raise SystemExit("当前库没有临时调试人物1。")
        unknown_ids = set(db.scalars(select(Person.id).where(Person.is_unknown.is_(True))).all())
        context = RestoreContext(
            debug1_id=debug1.id,
            unknown_ids=unknown_ids,
            old_photo_ids=old_photo_ids,
            old_tags_by_photo=old_tags,
            old_faces_by_photo=old_faces,
        )
        if args.apply:
            url = make_url(get_settings().database_url)
            if url.get_backend_name() != "sqlite" or not url.database:
                raise SystemExit("当前工具只支持 SQLite 数据库备份。")
            backup_path = output / "app-before.db"
            _backup_sqlite(Path(url.database), backup_path)
        result = restore_debug1_legacy_tags(db, context, picture_service, apply=args.apply)

    filename = "apply.json" if args.apply else "dry-run.json"
    (output / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_notes(output / "说明.md", result, old_db=args.old_db.resolve(), backup_db=backup_path)
    print(json.dumps({key: value for key, value in result.items() if key != "plans"}, ensure_ascii=False, indent=2))
    print(str(output))


if __name__ == "__main__":
    main()
