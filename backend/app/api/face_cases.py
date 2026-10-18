from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.timezones import shanghai_now
from app.db import get_db
from app.dependencies.context import CurrentContext, require_context, require_permission
from app.http.media import stream_storage_object
from app.models import FaceRecognitionCase
from app.schemas.face_cases import (
    CaseAnswerType, CaseIssueType, FaceCaseCreate, FaceCaseDetail, FaceCaseExport, FaceCaseNotesUpdate, PaginatedFaceCases,
)
from app.services.face_cases import build_export, case_query, case_read, create_case, delete_case
from app.services.thumbnails import render_gallery_thumbnail

router = APIRouter(tags=["识别异常案例"])
PREFIX = "/api/face-recognition-cases"


def get_case(db, current, case_id):
    case = db.scalar(select(FaceRecognitionCase).where(
        FaceRecognitionCase.id == case_id, FaceRecognitionCase.workspace_id == current.workspace_id,
    ))
    if case is None:
        raise HTTPException(404, "案例不存在")
    return case


@router.post(PREFIX, response_model=FaceCaseDetail)
def record_face_case(payload: FaceCaseCreate, request: Request, db: Session = Depends(get_db),
                     current: CurrentContext = Depends(require_context)):
    require_permission(current, "can_edit_gallery")
    services = request.app.state.services
    case = create_case(db, services.storage, services.pictures, request.app.state.settings, current, payload)
    return case_read(case, detail=True)


@router.get(PREFIX, response_model=PaginatedFaceCases)
def list_face_cases(correct_person_name: str | None = Query(None, max_length=256),
                    issue_type: CaseIssueType | None = None, embedding_version: str | None = Query(None, max_length=64),
                    answer_type: CaseAnswerType | None = None,
                    offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100),
                    db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    query = case_query(current.workspace_id, correct_person_name, issue_type, embedding_version, answer_type)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(FaceRecognitionCase.created_at.desc(), FaceRecognitionCase.id.desc()).offset(offset).limit(limit)).all()
    return PaginatedFaceCases(items=[case_read(case) for case in items], total=total, offset=offset, limit=limit)


@router.post(PREFIX + "/export")
def export_face_cases(payload: FaceCaseExport, request: Request, db: Session = Depends(get_db),
                      current: CurrentContext = Depends(require_context)):
    query = case_query(current.workspace_id, payload.correct_person_name, payload.issue_type, payload.embedding_version, payload.answer_type)
    if payload.case_ids is not None:
        if not payload.case_ids:
            raise HTTPException(400, "请先勾选案例")
        query = query.where(FaceRecognitionCase.id.in_(payload.case_ids))
    cases = db.scalars(query.order_by(FaceRecognitionCase.created_at, FaceRecognitionCase.id)).all()
    if payload.case_ids is not None and len(cases) != len(set(payload.case_ids)):
        raise HTTPException(404, "部分案例已不存在或不属于当前工作区，请刷新列表")
    if not cases:
        raise HTTPException(400, "没有可导出的案例")
    temp, archive_path = build_export(request.app.state.services.storage, cases)

    def iterate():
        try:
            with archive_path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    yield chunk
        finally:
            temp.cleanup()

    filename = f"face-recognition-cases-{shanghai_now():%Y%m%d_%H%M%S}.zip"
    return StreamingResponse(iterate(), media_type="application/zip", background=BackgroundTask(temp.cleanup),
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get(PREFIX + "/{case_id}", response_model=FaceCaseDetail)
def read_face_case(case_id: str, db: Session = Depends(get_db), current: CurrentContext = Depends(require_context)):
    return case_read(get_case(db, current, case_id), detail=True)


@router.patch(PREFIX + "/{case_id}", response_model=FaceCaseDetail)
def update_face_case(case_id: str, payload: FaceCaseNotesUpdate, db: Session = Depends(get_db),
                     current: CurrentContext = Depends(require_context)):
    require_permission(current, "can_edit_gallery")
    case = get_case(db, current, case_id)
    if case.status != "active":
        raise HTTPException(409, "该案例待清理，请重试删除")
    case.notes = payload.notes.strip()
    db.commit()
    return case_read(case, detail=True)


@router.delete(PREFIX + "/{case_id}")
def remove_face_case(case_id: str, request: Request, db: Session = Depends(get_db),
                     current: CurrentContext = Depends(require_context)):
    require_permission(current, "can_delete_gallery")
    delete_case(db, request.app.state.services.storage, get_case(db, current, case_id))
    return {"status": "deleted"}


@router.get(PREFIX + "/{case_id}/original")
def face_case_original(case_id: str, request: Request, db: Session = Depends(get_db),
                       current: CurrentContext = Depends(require_context)):
    case = get_case(db, current, case_id)
    if case.status != "active":
        raise HTTPException(409, "案例正在清理")
    import json
    photo = json.loads(case.snapshot_json)["photo"]
    try:
        return stream_storage_object(request.app.state.services.storage, request, case.object_key,
                                     photo["filename"], photo["content_type"])
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "案例原图暂时无法读取") from exc


@router.get(PREFIX + "/{case_id}/thumbnail")
def face_case_thumbnail(case_id: str, request: Request, db: Session = Depends(get_db),
                        current: CurrentContext = Depends(require_context)):
    case = get_case(db, current, case_id)
    if case.status != "active":
        raise HTTPException(409, "案例正在清理")
    try:
        thumb = render_gallery_thumbnail(request.app.state.services.storage.get_bytes(case.object_key))
    except Exception as exc:
        raise HTTPException(503, "案例缩略图暂时无法读取") from exc
    return Response(thumb.payload, media_type=thumb.media_type, headers={"Cache-Control": "private, max-age=3600"})
