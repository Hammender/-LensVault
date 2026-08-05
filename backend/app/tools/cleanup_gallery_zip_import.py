from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, GalleryPhotoPersonTag, Person


class ManifestPeopleMap(dict[str, set[str]]):
    def __init__(self, *, manifest_photo_count: int) -> None:
        super().__init__()
        self.manifest_photo_count = manifest_photo_count


def load_manifest_people(metadata_path: Path) -> ManifestPeopleMap:
    manifest = json.loads(metadata_path.read_text(encoding="utf-8"))
    photos = manifest.get("photos")
    if not isinstance(photos, list):
        raise ValueError("metadata.json 缺少有效的 photos 数组")

    people_by_sha = ManifestPeopleMap(manifest_photo_count=len(photos))
    for item in photos:
        if not isinstance(item, dict):
            raise ValueError("metadata.json 中存在格式错误的照片项")
        sha256 = str(item.get("sha256") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError("metadata.json 中存在无效的 SHA-256")
        manifest_people = item.get("persons", [])
        if not isinstance(manifest_people, list):
            raise ValueError("metadata.json 中存在格式错误的 persons 字段")
        if any(isinstance(person, dict) and bool(person.get("is_unknown")) for person in manifest_people):
            raise ValueError("清单本身包含未知人物绑定，不能使用此专项清理命令")
        known_names = {
            str(person.get("name") or "").strip()
            for person in manifest_people
            if isinstance(person, dict)
            and not bool(person.get("is_unknown"))
            and str(person.get("name") or "").strip()
        }
        people_by_sha.setdefault(sha256, set()).update(known_names)
    if not people_by_sha:
        raise ValueError("metadata.json 中没有可用于匹配图库的 SHA-256")
    return people_by_sha


def cleanup_gallery_zip_import(
    db: Session,
    people_by_sha: dict[str, set[str]],
    *,
    workspace_id: int | None = None,
    apply: bool = False,
) -> dict[str, int | bool]:
    # 只选旧数据库中已经存在的列，使结构迁移前也可以安全预演清理范围。
    query = select(GalleryPhoto.id, GalleryPhoto.sha256).where(GalleryPhoto.sha256.in_(people_by_sha))
    if workspace_id is not None:
        query = query.where(GalleryPhoto.workspace_id == workspace_id)
    photos = list(db.execute(query).all())
    photo_ids = [photo_id for photo_id, _sha256 in photos]

    unknown_links: list[GalleryPhotoPersonTag] = []
    unknown_faces: list[FaceRecord] = []
    known_source_links: list[GalleryPhotoPersonTag] = []
    if photo_ids:
        unknown_links = list(
            db.scalars(
                select(GalleryPhotoPersonTag)
                .join(Person, Person.id == GalleryPhotoPersonTag.person_id)
                .where(
                    GalleryPhotoPersonTag.gallery_photo_id.in_(photo_ids),
                    Person.is_unknown.is_(True),
                )
            ).all()
        )
        unknown_faces = list(
            db.scalars(
                select(FaceRecord)
                .join(Person, Person.id == FaceRecord.matched_person_id)
                .where(
                    FaceRecord.gallery_photo_id.in_(photo_ids),
                    Person.is_unknown.is_(True),
                )
            ).all()
        )
        known_links = db.execute(
            select(GalleryPhotoPersonTag, Person, GalleryPhoto.sha256)
            .join(Person, Person.id == GalleryPhotoPersonTag.person_id)
            .join(GalleryPhoto, GalleryPhoto.id == GalleryPhotoPersonTag.gallery_photo_id)
            .where(
                GalleryPhotoPersonTag.gallery_photo_id.in_(photo_ids),
                Person.is_unknown.is_(False),
            )
        ).all()
        known_source_links = [
            link
            for link, person, sha256 in known_links
            if person.name in people_by_sha.get(sha256, set()) and link.source != "import"
        ]

    affected_photo_ids = {
        *(link.gallery_photo_id for link in unknown_links),
        *(face.gallery_photo_id for face in unknown_faces if face.gallery_photo_id is not None),
        *(link.gallery_photo_id for link in known_source_links),
    }
    result: dict[str, int | bool] = {
        "manifest_photos": getattr(people_by_sha, "manifest_photo_count", len(people_by_sha)),
        "manifest_unique_sha256": len(people_by_sha),
        "matched_photos": len(photos),
        "matched_unique_sha256": len({sha256 for _photo_id, sha256 in photos}),
        "affected_photos": len(affected_photo_ids),
        "unknown_tags_deleted": len(unknown_links),
        "unknown_faces_deleted": len(unknown_faces),
        "known_sources_changed": len(known_source_links),
        "applied": apply,
    }

    if apply:
        for link in unknown_links:
            db.delete(link)
        for face in unknown_faces:
            db.delete(face)
        for link in known_source_links:
            link.source = "import"
        db.commit()
    else:
        db.rollback()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="清理旧展示图 ZIP 导入产生的错误未知人物数据。")
    parser.add_argument("metadata", type=Path, help="原展示图导出目录中的 metadata.json。")
    parser.add_argument("--workspace-id", type=int, help="只处理指定工作区。")
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演并回滚。")
    parser.add_argument("--confirm", action="store_true", help="确认正式写入，必须与 --apply 同时使用。")
    args = parser.parse_args()
    if args.apply != args.confirm:
        raise SystemExit("正式写入必须同时提供 --apply --confirm；预演时两个参数都不要提供。")

    people_by_sha = load_manifest_people(args.metadata)
    with SessionLocal() as db:
        result = cleanup_gallery_zip_import(
            db,
            people_by_sha,
            workspace_id=args.workspace_id,
            apply=args.apply,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
