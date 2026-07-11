from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import SamplePhoto
from app.services.qdrant import QdrantVectorStore


def build_face_index_health(
    db: Session,
    vector_store: QdrantVectorStore,
    settings: Settings,
) -> dict[str, object]:
    ready_samples = int(
        db.scalar(select(func.count(SamplePhoto.id)).where(SamplePhoto.status == "ready")) or 0
    )
    ready_people = int(
        db.scalar(
            select(func.count(distinct(SamplePhoto.person_id))).where(SamplePhoto.status == "ready")
        )
        or 0
    )
    try:
        inspection = vector_store.inspect_collection(
            settings.qdrant_known_collection,
            embedding_version=settings.face_embedding_version,
            include_vectors=False,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "collection": settings.qdrant_known_collection,
            "embedding_version": settings.face_embedding_version,
            "ready_samples": ready_samples,
            "ready_people": ready_people,
            "error": f"{type(exc).__name__}: {exc}",
        }
    healthy = (
        inspection.exists
        and inspection.vector_size == settings.qdrant_vector_dimension
        and inspection.distance == "Cosine"
        and inspection.searchable_samples == ready_samples
        and inspection.covered_people == ready_people
        and inspection.invalid_payload_points == 0
    )
    result = inspection.as_dict()
    result.update(
        {
            "status": "ok" if healthy else "degraded",
            "embedding_version": settings.face_embedding_version,
            "ready_samples": ready_samples,
            "ready_people": ready_people,
            "sample_coverage": (
                inspection.searchable_samples / ready_samples if ready_samples else 1.0
            ),
            "person_coverage": inspection.covered_people / ready_people if ready_people else 1.0,
        }
    )
    return result
