from __future__ import annotations

import argparse
from dataclasses import dataclass
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


DEBUG_1 = "临时调试人物1"
DEBUG_2 = "临时调试人物2"
JENNY_NAME = "金珍妮-Jenny"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OLD_DB = REPO_ROOT / "data" / "face-migration" / "pre-migration-20260908" / "app-before.db"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "face-migration" / "jenny-debug2-cleanup"


@dataclass(frozen=True)
class CleanupContext:
    jenny_id: int
    debug1_id: int | None
    debug2_id: int
    old_tags_by_photo: dict[int, set[int]]
    old_jenny_photos: set[int]


def _person_by_display_name(db: Session, name: str) -> Person | None:
    return db.scalar(select(Person).where(Person.display_name == name))


def load_old_context(old_db: Path, jenny_id: int) -> tuple[dict[int, set[int]], set[int]]:
    connection = sqlite3.connect(old_db)
    try:
        tags_by_photo: dict[int, set[int]] = {}
        for gallery_photo_id, person_id in connection.execute(
            "SELECT gallery_photo_id, person_id FROM gallery_photo_person_tags"
        ):
            tags_by_photo.setdefault(int(gallery_photo_id), set()).add(int(person_id))
        old_jenny_photos = {
            int(row[0])
            for row in connection.execute(
                "SELECT DISTINCT gallery_photo_id FROM gallery_photo_person_tags WHERE person_id=?",
                (jenny_id,),
            )
        }
    finally:
        connection.close()
    return tags_by_photo, old_jenny_photos


def _debug_person_ids(debug1_id: int | None, debug2_id: int) -> set[int]:
    ids = {debug2_id}
    if debug1_id is not None:
        ids.add(debug1_id)
    return ids


def _current_person_ids(db: Session, photo_id: int) -> set[int]:
    return set(
        db.scalars(
            select(GalleryPhotoPersonTag.person_id).where(GalleryPhotoPersonTag.gallery_photo_id == photo_id)
        ).all()
    )


def _jenny_faces(db: Session, photo_id: int, jenny_id: int) -> list[FaceRecord]:
    return list(
        db.scalars(
            select(FaceRecord).where(
                FaceRecord.gallery_photo_id == photo_id,
                FaceRecord.matched_person_id == jenny_id,
            )
        ).all()
    )


def _promoted_face_ids(db: Session, face_ids: list[int]) -> set[int]:
    if not face_ids:
        return set()
    return set(
        db.scalars(
            select(SamplePhoto.source_gallery_face_id).where(
                SamplePhoto.source_gallery_face_id.in_(face_ids),
                SamplePhoto.status == "ready",
            )
        ).all()
    )


def _delete_person_tag(db: Session, photo_id: int, person_id: int) -> bool:
    link = db.scalar(
        select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo_id,
            GalleryPhotoPersonTag.person_id == person_id,
        )
    )
    if link is None:
        return False
    db.delete(link)
    return True


def plan_cleanup(db: Session, context: CleanupContext) -> list[dict[str, Any]]:
    debug_ids = _debug_person_ids(context.debug1_id, context.debug2_id)
    debug2_photos = set(
        db.scalars(
            select(GalleryPhotoPersonTag.gallery_photo_id).where(
                GalleryPhotoPersonTag.person_id == context.debug2_id
            )
        ).all()
    )
    jenny_photos = set(
        db.scalars(
            select(GalleryPhotoPersonTag.gallery_photo_id).where(
                GalleryPhotoPersonTag.person_id == context.jenny_id
            )
        ).all()
    )
    candidate_ids = sorted(debug2_photos & jenny_photos)
    plans: list[dict[str, Any]] = []
    for photo_id in sorted(candidate_ids):
        photo = db.get(GalleryPhoto, photo_id)
        faces = _jenny_faces(db, photo_id, context.jenny_id)
        face_ids = [face.id for face in faces]
        promoted = sorted(_promoted_face_ids(db, face_ids))
        had_jenny_before = photo_id in context.old_jenny_photos
        remaining_after_jenny = _current_person_ids(db, photo_id) - {context.jenny_id}
        remaining_without_debug = remaining_after_jenny - debug_ids
        old_tags = context.old_tags_by_photo.get(photo_id, set())
        drop_debug2 = remaining_without_debug == old_tags
        action = "clean"
        skip_reason = None
        if had_jenny_before:
            action = "skip"
            skip_reason = "migration_had_jenny_tag"
            drop_debug2 = False
        elif promoted:
            action = "skip"
            skip_reason = "jenny_face_promoted_to_sample"
            drop_debug2 = False
        plans.append(
            {
                "gallery_photo_id": photo_id,
                "workspace_id": photo.workspace_id if photo is not None else None,
                "action": action,
                "skip_reason": skip_reason,
                "jenny_face_ids": face_ids,
                "promoted_face_ids": promoted,
                "drop_debug2": drop_debug2,
                "remaining_person_ids_without_debug": sorted(remaining_without_debug),
                "old_person_ids": sorted(old_tags),
            }
        )
    return plans


def apply_cleanup(
    db: Session,
    context: CleanupContext,
    plans: list[dict[str, Any]],
    picture_service: PictureService,
) -> None:
    stale_by_workspace: dict[int | None, set[int]] = {}
    for plan in plans:
        if plan["action"] != "clean":
            continue
        photo_id = int(plan["gallery_photo_id"])
        for face in _jenny_faces(db, photo_id, context.jenny_id):
            db.delete(face)
        _delete_person_tag(db, photo_id, context.jenny_id)
        dropped_ids = {context.jenny_id}
        if plan["drop_debug2"]:
            if _delete_person_tag(db, photo_id, context.debug2_id):
                dropped_ids.add(context.debug2_id)
        picture_service.sync_inherited_gallery_tags(db, photo_id)
        workspace_id = plan["workspace_id"]
        stale_by_workspace.setdefault(workspace_id, set()).update(dropped_ids)
    for workspace_id, person_ids in stale_by_workspace.items():
        if workspace_id is None:
            continue
        mark_similarity_scans_stale(db, workspace_id, person_ids)
    db.commit()


def summarize_plans(plans: list[dict[str, Any]], *, applied: bool) -> dict[str, Any]:
    clean = [plan for plan in plans if plan["action"] == "clean"]
    skipped = [plan for plan in plans if plan["action"] == "skip"]
    return {
        "applied": applied,
        "candidate_photos": len(plans),
        "cleaned_photos": len(clean),
        "skipped_photos": len(skipped),
        "jenny_faces_deleted": sum(len(plan["jenny_face_ids"]) for plan in clean),
        "debug2_tags_deleted": sum(1 for plan in clean if plan["drop_debug2"]),
        "debug2_tags_kept": sum(1 for plan in clean if not plan["drop_debug2"]),
        "skip_reasons": {
            reason: sum(1 for plan in skipped if plan["skip_reason"] == reason)
            for reason in sorted({str(plan["skip_reason"]) for plan in skipped})
        },
        "kept_debug2_photo_ids": [plan["gallery_photo_id"] for plan in clean if not plan["drop_debug2"]],
        "skipped_photo_ids": [plan["gallery_photo_id"] for plan in skipped],
        "plans": plans,
    }


def cleanup_debug2_spurious_jenny(
    db: Session,
    context: CleanupContext,
    picture_service: PictureService,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    plans = plan_cleanup(db, context)
    if apply:
        apply_cleanup(db, context, plans, picture_service)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="清理临时调试人物2队列中新模型误加的金珍妮-Jenny 标签和对应人脸。")
    parser.add_argument("--old-db", type=Path, default=DEFAULT_OLD_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式写入必须同时提供 --apply --confirm；预演时两个参数都不要提供。")
    if not args.old_db.is_file():
        raise SystemExit(f"迁移前备份不存在：{args.old_db}")

    picture_service = _picture_service()
    with SessionLocal() as db:
        jenny = _person_by_display_name(db, JENNY_NAME)
        debug2 = _person_by_display_name(db, DEBUG_2)
        debug1 = _person_by_display_name(db, DEBUG_1)
        if jenny is None or debug2 is None:
            raise SystemExit("当前库缺少金珍妮-Jenny 或临时调试人物2。")
        old_tags, old_jenny_photos = load_old_context(args.old_db, jenny.id)
        context = CleanupContext(
            jenny_id=jenny.id,
            debug1_id=debug1.id if debug1 is not None else None,
            debug2_id=debug2.id,
            old_tags_by_photo=old_tags,
            old_jenny_photos=old_jenny_photos,
        )
        if args.apply:
            url = make_url(get_settings().database_url)
            if url.get_backend_name() != "sqlite" or not url.database:
                raise SystemExit("当前工具只支持 SQLite 数据库备份。")
            _backup_sqlite(Path(url.database), args.output / "app-before.db")
        result = cleanup_debug2_spurious_jenny(db, context, picture_service, apply=args.apply)

    args.output.mkdir(parents=True, exist_ok=True)
    filename = "apply.json" if args.apply else "dry-run.json"
    (args.output / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "plans"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
