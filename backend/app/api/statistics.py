from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.context import CurrentContext, require_context
from app.models import GalleryPhoto, GalleryPhotoPersonTag, GalleryPhotoTag, Person, SamplePhoto, Tag, UploadHistory
from app.schemas import PersonStatistics, TagStatistics, UploadHistoryRead


router = APIRouter()


@router.get("/api/statistics/tags", response_model=list[TagStatistics])
def get_tag_statistics(
    is_system: bool | None = Query(default=None, description="Filter by system tag status"),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[TagStatistics]:
    """Get photo count statistics for each tag."""
    query = (
        select(
            Tag.id,
            Tag.name,
            Tag.is_system,
            func.count(GalleryPhotoTag.gallery_photo_id).label("photo_count"),
        )
        .outerjoin(GalleryPhotoTag, Tag.id == GalleryPhotoTag.tag_id)
        .where(Tag.workspace_id == current.workspace_id)
        .group_by(Tag.id)
    )
    if is_system is not None:
        query = query.where(Tag.is_system == is_system)
    results = db.execute(query).all()
    return [
        TagStatistics(
            tag_id=row.id,
            tag_name=row.name,
            is_system=row.is_system,
            photo_count=row.photo_count,
        )
        for row in results
    ]


@router.get("/api/statistics/upload-history", response_model=list[UploadHistoryRead])
def get_upload_history(
    upload_type: str | None = Query(default=None, description="Filter by upload type: gallery or rich"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[UploadHistoryRead]:
    """Get upload history records."""
    query = (
        select(UploadHistory)
        .where(UploadHistory.workspace_id == current.workspace_id)
        .order_by(UploadHistory.created_at.desc())
    )
    if upload_type:
        query = query.where(UploadHistory.upload_type == upload_type)
    results = db.scalars(query.offset(offset).limit(limit)).all()
    return [UploadHistoryRead.model_validate(result) for result in results]


@router.get("/api/statistics/upload-summary")
def get_upload_summary(
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> dict:
    """Get summary statistics of uploads."""
    workspace_filter = UploadHistory.workspace_id == current.workspace_id
    total_uploads = db.scalar(select(func.count(UploadHistory.id)).where(workspace_filter))
    total_photos = db.scalar(select(func.sum(UploadHistory.total_count)).where(workspace_filter)) or 0
    total_success = db.scalar(select(func.sum(UploadHistory.success_count)).where(workspace_filter)) or 0
    total_duplicates = db.scalar(select(func.sum(UploadHistory.duplicate_count)).where(workspace_filter)) or 0

    by_type = {}
    for upload_type in ["gallery", "rich"]:
        type_filter = (workspace_filter, UploadHistory.upload_type == upload_type)
        by_type[upload_type] = {
            "count": db.scalar(select(func.count(UploadHistory.id)).where(*type_filter)),
            "photos": db.scalar(select(func.sum(UploadHistory.total_count)).where(*type_filter)) or 0,
        }

    return {
        "total_uploads": total_uploads,
        "total_photos": total_photos,
        "total_success": total_success,
        "total_duplicates": total_duplicates,
        "by_type": by_type,
    }


@router.get("/api/statistics/persons", response_model=list[PersonStatistics])
def get_person_statistics(
    is_unknown: bool | None = Query(default=None, description="Filter by unknown person status"),
    db: Session = Depends(get_db),
    current: CurrentContext = Depends(require_context),
) -> list[PersonStatistics]:
    """Get photo count statistics for each person."""
    photo_count_sq = (
        select(
            GalleryPhotoPersonTag.person_id,
            func.count(GalleryPhotoPersonTag.gallery_photo_id).label("count"),
        )
        .join(GalleryPhoto, GalleryPhoto.id == GalleryPhotoPersonTag.gallery_photo_id)
        .where(GalleryPhoto.workspace_id == current.workspace_id)
        .group_by(GalleryPhotoPersonTag.person_id)
        .subquery()
    )
    sample_count_sq = (
        select(SamplePhoto.person_id, func.count(SamplePhoto.id).label("count"))
        .where(SamplePhoto.workspace_id == current.workspace_id)
        .group_by(SamplePhoto.person_id)
        .subquery()
    )
    query = (
        select(
            Person.id,
            Person.name,
            Person.display_name,
            Person.is_unknown,
            func.coalesce(photo_count_sq.c.count, 0).label("photo_count"),
            func.coalesce(sample_count_sq.c.count, 0).label("sample_count"),
        )
        .outerjoin(photo_count_sq, Person.id == photo_count_sq.c.person_id)
        .outerjoin(sample_count_sq, Person.id == sample_count_sq.c.person_id)
        .where(Person.workspace_id == current.workspace_id)
    )
    if is_unknown is not None:
        query = query.where(Person.is_unknown == is_unknown)
    results = db.execute(
        query.order_by(Person.is_unknown.asc(), func.coalesce(photo_count_sq.c.count, 0).desc())
    ).all()
    return [
        PersonStatistics(
            person_id=row.id,
            person_name=row.name,
            display_name=row.display_name,
            is_unknown=row.is_unknown,
            photo_count=row.photo_count,
            sample_count=row.sample_count,
        )
        for row in results
    ]
