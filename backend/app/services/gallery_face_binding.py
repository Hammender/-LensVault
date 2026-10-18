"""图库人脸改绑，调用方负责事务提交。"""
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import FaceRecord, GalleryPhotoPersonTag, SamplePhoto
from app.services.similarity import mark_similarity_scans_stale


def bind_face_person(db, pictures, photo, face, person) -> None:
    if person.is_unknown:
        raise HTTPException(status_code=400, detail="不能绑定系统未知人物")
    if db.scalar(select(SamplePhoto).where(SamplePhoto.source_gallery_face_id == face.id, SamplePhoto.status == "ready")) is not None:
        raise HTTPException(status_code=409, detail="该人脸已经加入样本库，请先撤销样本后再更换绑定")
    previous_person_id = face.matched_person_id
    pictures.move_gallery_face_to_known(db, face, person)
    if previous_person_id and previous_person_id != person.id:
        previous_link = db.scalar(select(GalleryPhotoPersonTag).where(
            GalleryPhotoPersonTag.gallery_photo_id == photo.id,
            GalleryPhotoPersonTag.person_id == previous_person_id,
        ))
        still_bound = db.scalar(select(func.count(FaceRecord.id)).where(
            FaceRecord.gallery_photo_id == photo.id,
            FaceRecord.matched_person_id == previous_person_id,
            FaceRecord.id != face.id,
        )) or 0
        if previous_link is not None and previous_link.source in {"auto", "unknown", "face_manual"} and not still_bound:
            db.delete(previous_link)
    pictures.ensure_gallery_person_tag(db, photo.id, person.id, "face_manual")
    pictures.sync_inherited_gallery_tags(db, photo.id)
    mark_similarity_scans_stale(db, photo.workspace_id, {person.id})
