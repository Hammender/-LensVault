"""人脸识别异常案例的独立存档、事务及导出。"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import tempfile
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from PIL import Image, ImageOps
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.timezones import shanghai_isoformat, shanghai_now
from app.models import FaceRecord, FaceRecognitionCase, GalleryPhoto, GalleryPhotoPersonTag, Person, SamplePhoto
from app.schemas.face_cases import FaceCaseDetail, FaceCaseRead
from app.services.face_case_snapshots import digest, face_revision, json_value, recognition_key, recognition_snapshot
from app.services.gallery_face_binding import bind_face_person

logger = logging.getLogger(__name__)


def case_read(case: FaceRecognitionCase, *, detail: bool = False):
    data = {name: getattr(case, name) for name in FaceCaseRead.model_fields if not name.endswith("_url")}
    data.update(original_url=f"/api/face-recognition-cases/{case.id}/original",
                thumbnail_url=f"/api/face-recognition-cases/{case.id}/thumbnail")
    if detail:
        return FaceCaseDetail(**data, snapshot=json.loads(case.snapshot_json))
    return FaceCaseRead(**data)


def case_query(workspace_id, correct_person_name=None, issue_type=None, embedding_version=None, answer_type=None):
    query = select(FaceRecognitionCase).where(FaceRecognitionCase.workspace_id == workspace_id)
    if correct_person_name:
        query = query.where(or_(FaceRecognitionCase.correct_person_name.contains(correct_person_name, autoescape=True),
                                FaceRecognitionCase.excluded_person_name.contains(correct_person_name, autoescape=True)))
    if issue_type:
        query = query.where(FaceRecognitionCase.issue_type == issue_type)
    if embedding_version:
        query = query.where(FaceRecognitionCase.embedding_version == embedding_version)
    if answer_type:
        query = query.where(FaceRecognitionCase.answer_type == answer_type)
    return query


def _sample_manifest(db, person, captured_at, role):
    if person is None:
        return {"captured_at": captured_at, "role": None, "person_id": None, "person_name": None,
                "ready_count": 0, "images_included": False, "samples": []}
    samples = db.scalars(select(SamplePhoto).where(
        SamplePhoto.workspace_id == person.workspace_id, SamplePhoto.person_id == person.id,
    ).order_by(SamplePhoto.id)).all()
    return {
        "captured_at": captured_at,
        "role": role,
        "person_id": person.id,
        "person_name": person.display_name,
        "ready_count": sum(sample.status == "ready" for sample in samples),
        "images_included": False,
        "samples": [{
            key: json_value(getattr(sample, key)) for key in (
                "id", "filename", "sha256", "status", "quality_status", "quality_warnings", "error_message",
                "source_type", "source_gallery_photo_id", "source_gallery_face_id", "created_at",
            )
        } for sample in samples],
    }


def create_case(db, storage, pictures, settings, current, payload):
    workspace_id = current.workspace_id
    key_query = select(FaceRecognitionCase).where(FaceRecognitionCase.workspace_id == workspace_id)
    photo = db.scalar(select(GalleryPhoto).where(GalleryPhoto.id == payload.photo_id, GalleryPhoto.workspace_id == workspace_id))
    face = db.scalar(select(FaceRecord).where(FaceRecord.id == payload.face_id,
        FaceRecord.gallery_photo_id == payload.photo_id, FaceRecord.workspace_id == workspace_id))
    if photo is None or face is None:
        raise HTTPException(404, "图片或人脸已不存在，请刷新详情")
    key = recognition_key(face)
    existing = db.scalar(key_query.where(FaceRecognitionCase.recognition_key == key))
    if existing is not None:
        if existing.status != "active":
            raise HTTPException(409, "该案例正在清理，请到案例库重试删除")
        return existing
    if face_revision(face) != payload.face_revision:
        raise HTTPException(409, "人脸识别或绑定结果已经变化，请刷新详情后重新记录")
    person = None
    excluded = None
    target_id = payload.correct_person_id if payload.answer_type == "known_person" else payload.excluded_person_id
    if target_id is not None:
        target = db.scalar(select(Person).where(Person.id == target_id, Person.workspace_id == workspace_id))
        if target is None or target.is_unknown:
            raise HTTPException(400, "请选择当前工作区中的正式人物")
        if payload.answer_type == "known_person":
            person = target
        else:
            excluded = target
    reference_person = person or excluded
    reference_role = "correct_person" if person else "excluded_person"
    if payload.answer_type == "out_of_library":
        reference_person = db.scalar(select(Person).where(
            Person.id == face.matched_person_id, Person.workspace_id == workspace_id, Person.is_unknown.is_(False)))
        reference_role = "recognized_person"
    if payload.bind_person and db.scalar(select(SamplePhoto.id).where(
        SamplePhoto.source_gallery_face_id == face.id, SamplePhoto.status == "ready",
    )) is not None:
        raise HTTPException(409, "该人脸已经加入样本库，可仅记录异常，或先撤销样本再改绑")

    now = shanghai_now()
    captured_at = shanghai_isoformat(now)
    raw = recognition_snapshot(face)
    names = {p.id: p.display_name for p in db.scalars(select(Person).where(
        Person.workspace_id == workspace_id,
        Person.id.in_([v for v in (face.predicted_person_id, face.second_person_id, face.matched_person_id) if v is not None]),
    ))}
    source = db.scalar(select(GalleryPhotoPersonTag.source).where(
        GalleryPhotoPersonTag.gallery_photo_id == photo.id, GalleryPhotoPersonTag.person_id == face.matched_person_id,
    ))
    promoted = db.scalars(select(SamplePhoto.id).where(
        SamplePhoto.workspace_id == workspace_id, SamplePhoto.source_gallery_photo_id == photo.id,
    )).all()
    settings_snapshot = {name: json_value(value) for name, value in settings.model_dump().items()
                         if name.startswith("face_") or name in {"qdrant_known_collection", "qdrant_vector_dimension"}}
    # 保存实际原始字节，保留 EXIF；人脸框对应 EXIF 校正后的像素坐标。
    try:
        image_bytes = storage.get_bytes(photo.object_key)
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        if sha256 != photo.sha256:
            raise HTTPException(409, "原图内容与入库哈希不一致，未保存案例")
        with Image.open(BytesIO(image_bytes)) as image:
            orientation = int(image.getexif().get(274, 1))
            display_size = ImageOps.exif_transpose(image).size
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "读取案例原图失败，请稍后重试") from exc
    actor = current.user
    snapshot = {
        "schema_version": 2,
        "captured_at": captured_at,
        "workspace_id": workspace_id,
        "photo": {"id": photo.id, "filename": photo.filename, "sha256": sha256,
                  "content_type": photo.content_type, "size_bytes": len(image_bytes),
                  "width": photo.width, "height": photo.height, "exif_orientation": orientation,
                  "display_width": display_size[0], "display_height": display_size[1]},
        "coordinate_space": "exif_transposed_pixels",
        "recognition": {**raw, "predicted_person_name": names.get(face.predicted_person_id),
                        "second_person_name": names.get(face.second_person_id)},
        "binding_at_capture": {"person_id": face.matched_person_id, "person_name": names.get(face.matched_person_id),
                               "source": source, "needs_review": face.needs_review},
        "correct_person": {"id": person.id, "name": person.display_name} if person else None,
        "ground_truth": {"answer_type": payload.answer_type,
                         "correct_person": {"id": person.id, "name": person.display_name} if person else None,
                         "excluded_person": {"id": excluded.id, "name": excluded.display_name} if excluded else None},
        "reference_samples_at_capture": _sample_manifest(db, reference_person, captured_at, reference_role),
        "same_photo_sample_ids_at_capture": list(promoted),
        "configuration_at_capture": settings_snapshot,
        "bind_person_requested": payload.bind_person,
    }
    case_id = uuid4().hex
    object_key = f"workspaces/{workspace_id}/face-recognition-cases/{case_id}/original"
    case = FaceRecognitionCase(id=case_id, workspace_id=workspace_id, source_photo_id=photo.id,
        source_face_id=face.id, correct_person_id=person.id if person else None,
        correct_person_name=person.display_name if person else "", answer_type=payload.answer_type,
        excluded_person_id=excluded.id if excluded else None, excluded_person_name=excluded.display_name if excluded else None,
        issue_type=payload.issue_type, notes=payload.notes.strip(), recognition_key=key,
        embedding_version=face.embedding_version, object_key=object_key,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False), created_by=actor.id,
        actor_name=actor.display_name or actor.username, created_at=now, updated_at=now, status="active")
    expected = {column.name: getattr(face, column.name) for column in FaceRecord.__table__.columns}
    case_values = {column.name: getattr(case, column.name) for column in FaceRecognitionCase.__table__.columns}
    try:
        storage.put_bytes(object_key, image_bytes, photo.content_type)
        # 比较完整源行并取得写锁，防止存档期间另一请求重识别或改绑。
        result = db.execute(update(FaceRecord).where(*[
            getattr(FaceRecord, name) == value for name, value in expected.items()
        ]).values(id=face.id).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise HTTPException(409, "人脸结果已经变化，请刷新详情后重新记录")
        db.add(case)
        db.flush()
        if payload.bind_person:
            bind_face_person(db, pictures, photo, face, person)
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            storage.remove_object(object_key)
        except Exception:
            logger.exception("案例提交失败后的素材清理失败 case_id=%s", case_id)
            # 保存独立的清理凭据，避免失败副本只能依赖日志追溯。
            cleanup = FaceRecognitionCase(**{**case_values, "source_photo_id": None,
                "correct_person_id": None, "excluded_person_id": None, "created_by": None,
                "recognition_key": digest([key, case_id, "cleanup"]), "status": "deleting",
                "cleanup_error": "记录未完成，独立素材待清理，请重试删除"})
            try:
                db.add(cleanup)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("无法登记待清理素材 case_id=%s object_key=%s", case_id, object_key)
            else:
                raise HTTPException(503, "案例未保存，独立素材待清理，请在案例库重试删除") from exc
        if isinstance(exc, IntegrityError):
            existing = db.scalar(key_query.where(FaceRecognitionCase.recognition_key == key))
            if existing is not None and existing.status == "active":
                return existing
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "案例存档失败，请重试；人物绑定未提交") from exc
    return case


def delete_case(db, storage, case):
    # 先持久化待清理状态；失败后保留编号和对象键，允许用户重试。
    case.status = "deleting"
    case.cleanup_error = None
    db.commit()
    try:
        storage.remove_object(case.object_key)
        db.delete(case)
        db.commit()
    except Exception as exc:
        db.rollback()
        case = db.get(FaceRecognitionCase, case.id)
        if case is not None:
            case.status = "deleting"
            case.cleanup_error = "素材清理未完成，请重试删除"
            db.commit()
        raise HTTPException(503, "案例清理未完成，请在案例库中重试删除") from exc


EXPORT_HELP = """# 人脸识别异常案例包

cases.jsonl 每行保存一个版本化案例，summary.csv 保存概要，images/ 保存独立原图。
recognition 是源人脸记录中的算法结果；binding_at_capture 是记录时的绑定，可能已经人工修改。
reference_samples_at_capture 和 configuration_at_capture 是点击记录时的状态，不代表原识别发生时的状态。
参考样本图片、模型文件、人脸向量均不包含在包内，样本清单仅用于追溯。
人脸框 bbox_left/top/right/bottom 使用 EXIF 校正后的像素坐标；读取原图后先应用 EXIF 方向，再裁剪。
answer_type 为 known_person（库中人物）、out_of_library（确定是库外人物）、not_person（只确定不是指定人物）。
ground_truth 保存完整人工结论；not_person 仅排除 excluded_person，不能据此推断属于库外。
正确人物或排除人物可能为空，库外人物没有正确人物编号；禁止把这两类负例当成某个库中人物的正样本。
快照版本 1 的历史案例均为 known_person，可从 correct_person 读取正确答案；版本 2 使用 ground_truth。
reference_samples_at_capture.role 区分正确人物、被排除人物及原绑定人物的样本；旧版未填写时为正确人物样本。
issue_type 为 unknown（未知）、wrong_person（错认）、other（其他）。
同源样本可能造成测评泄漏：使用图片哈希、样本来源与 same_photo_sample_ids_at_capture 排除同源图片。
这是人工挑选的困难案例集合，不代表全图库准确率；使用者需自行划分互不重叠的训练集和测试集。
人物或源图库图片可能已删除，snapshot 中的原始编号与名称仍保留。
"""


def build_export(storage, cases):
    temp = tempfile.TemporaryDirectory(prefix="face-case-export-")
    path = Path(temp.name) / "cases.zip"
    try:
        with ZipFile(path, "w", ZIP_DEFLATED, allowZip64=True) as archive:
            records = []
            csv_text = StringIO(newline="")
            writer = csv.writer(csv_text)
            writer.writerow(["案例编号", "正确人物", "异常类型", "向量版本", "记录时间", "备注", "图片路径", "人工结论", "排除人物"])
            images = {}
            for case in cases:
                if case.status != "active":
                    raise HTTPException(409, "导出包含待清理案例，请先完成删除或取消勾选")
                data = case_read(case, detail=True).model_dump(mode="json")
                photo = data["snapshot"]["photo"]
                sha = photo["sha256"]
                if sha not in images:
                    suffix = Path(photo["filename"]).suffix.lower()
                    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}:
                        suffix = ".bin"
                    image_path = f"images/{sha}{suffix}"
                    payload = storage.get_bytes(case.object_key)
                    if hashlib.sha256(payload).hexdigest() != sha:
                        raise HTTPException(409, "案例原图哈希不一致，无法生成完整导出包")
                    archive.writestr(image_path, payload)
                    images[sha] = image_path
                data.pop("original_url")
                data.pop("thumbnail_url")
                data["image_path"] = images[sha]
                records.append(json.dumps(data, ensure_ascii=False))
                # 防止人工备注或人物名称被表格软件作为公式执行。
                def cell(value):
                    text = "" if value is None else str(value)
                    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
                writer.writerow([cell(v) for v in (case.id, case.correct_person_name, case.issue_type,
                    case.embedding_version, shanghai_isoformat(case.created_at), case.notes, images[sha],
                    {"known_person": "库中人物", "out_of_library": "确定是库外人物", "not_person": "只确定不是指定人物"}[case.answer_type],
                    case.excluded_person_name)])
            archive.writestr("cases.jsonl", "\n".join(records) + ("\n" if records else ""))
            archive.writestr("summary.csv", "\ufeff" + csv_text.getvalue())
            archive.writestr("说明.md", EXPORT_HELP)
    except Exception as exc:
        temp.cleanup()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "案例原图缺失或读取失败，未生成导出包") from exc
    return temp, path
