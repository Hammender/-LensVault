from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, GalleryPhoto, Person, SamplePhoto
from app.services.face import FaceService
from app.services.qdrant import QdrantVectorStore
from app.services.storage import MinioStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only direct face match diagnostics.")
    parser.add_argument("--gallery-photo-id", type=int, required=True)
    parser.add_argument("--person-id", type=int, required=True)
    parser.add_argument("--face-index", type=int, default=1, help="One-based detected face index; defaults to 1.")
    parser.add_argument("--collection", help="Qdrant collection to query; defaults to configured active collection.")
    parser.add_argument("--embedding-version", help="Qdrant embedding version filter.")
    args = parser.parse_args()
    if args.face_index < 1:
        raise SystemExit("--face-index must be at least 1")

    settings = get_settings()
    collection = args.collection or settings.qdrant_known_collection
    embedding_version = args.embedding_version or settings.face_embedding_version
    storage = MinioStorage(settings)
    face_service = FaceService(settings)
    vector_store = QdrantVectorStore(settings)

    with SessionLocal() as db:
        gallery = db.get(GalleryPhoto, args.gallery_photo_id)
        person = db.get(Person, args.person_id)
        if gallery is None:
            raise SystemExit(f"Gallery photo not found: {args.gallery_photo_id}")
        if person is None:
            raise SystemExit(f"Person not found: {args.person_id}")
        if gallery.workspace_id != person.workspace_id:
            raise SystemExit("Gallery photo and person belong to different workspaces")

        gallery_faces = face_service.detect_faces(storage.get_bytes(gallery.object_key))
        if len(gallery_faces) < args.face_index:
            raise SystemExit(
                f"Requested face {args.face_index}, but only {len(gallery_faces)} face(s) were detected"
            )
        query_face = gallery_faces[args.face_index - 1]
        samples = db.scalars(
            select(SamplePhoto)
            .where(SamplePhoto.person_id == person.id, SamplePhoto.status == "ready")
            .order_by(SamplePhoto.id)
        ).all()

        sample_scores: list[dict[str, object]] = []
        sample_skips: list[dict[str, object]] = []
        for sample in samples:
            try:
                detected = face_service.detect_faces(storage.get_bytes(sample.object_key))
            except Exception as exc:
                sample_skips.append(
                    {"sample_photo_id": sample.id, "reason": f"read_or_detect_error:{type(exc).__name__}"}
                )
                continue
            if len(detected) != 1:
                sample_skips.append(
                    {"sample_photo_id": sample.id, "reason": f"detected_faces:{len(detected)}"}
                )
                continue
            sample_face = detected[0]
            sample_record = db.scalar(
                select(FaceRecord).where(FaceRecord.sample_photo_id == sample.id)
            )
            sample_scores.append(
                {
                    "sample_photo_id": sample.id,
                    "face_record_id": sample_record.id if sample_record is not None else None,
                    "score": face_service.cosine_similarity(query_face.embedding, sample_face.embedding),
                    "face_size": sample_face.face_size,
                    "blur_score": sample_face.blur_score,
                    "pose_yaw": sample_face.pose_yaw,
                }
            )
        sample_scores.sort(key=lambda item: float(item["score"]), reverse=True)

        hits = vector_store.search_candidates(
            collection,
            query_face.embedding,
            workspace_id=gallery.workspace_id,
            embedding_version=embedding_version,
            limit=settings.face_search_limit,
        )
        qdrant_hits: list[dict[str, object]] = []
        for hit in hits:
            direct_score = None
            if hit.source_type == "sample":
                stored = vector_store.get_face_vector(collection, hit.point_id)
                if stored is not None:
                    direct_score = face_service.cosine_similarity(query_face.embedding, stored)
            qdrant_hits.append(
                {
                    "point_id": hit.point_id,
                    "person_id": hit.person_id,
                    "sample_photo_id": hit.sample_photo_id,
                    "source_type": hit.source_type,
                    "qdrant_score": hit.score,
                    "direct_stored_score": direct_score,
                    "score_delta": abs(hit.score - direct_score) if direct_score is not None else None,
                }
            )

        report = {
            "gallery_photo_id": gallery.id,
            "person_id": person.id,
            "person_name": person.display_name,
            "workspace_id": gallery.workspace_id,
            "collection": collection,
            "embedding_version": embedding_version,
            "detected_gallery_faces": len(gallery_faces),
            "selected_face_index": args.face_index,
            "selected_face": {
                "bbox": query_face.bbox,
                "detection_score": query_face.score,
                "face_size": query_face.face_size,
                "blur_score": query_face.blur_score,
                "pose_yaw": query_face.pose_yaw,
            },
            "ready_samples": len(samples),
            "sample_scores": sample_scores,
            "sample_skips": sample_skips,
            "best_direct_sample": sample_scores[0] if sample_scores else None,
            "qdrant_hits": qdrant_hits,
            "best_qdrant_hit": qdrant_hits[0] if qdrant_hits else None,
            "target_person_qdrant_hits": [hit for hit in qdrant_hits if hit["person_id"] == person.id],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
