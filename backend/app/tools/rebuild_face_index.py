from __future__ import annotations

import argparse
import json
from collections import defaultdict
import re

import numpy as np
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import FaceRecord, SamplePhoto
from app.services.face import FaceService
from app.services.qdrant import QdrantVectorStore
from app.services.storage import MinioStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild a sample-only, versioned Qdrant face index.")
    parser.add_argument("--collection", help="Target collection; defaults to known collection plus embedding version.")
    parser.add_argument("--embedding-version", help="Embedding version written to Qdrant payloads.")
    parser.add_argument("--replace", action="store_true", help="Replace an existing non-active target collection.")
    args = parser.parse_args()
    settings = get_settings()
    embedding_version = args.embedding_version or settings.face_embedding_version
    safe_version = re.sub(r"[^a-zA-Z0-9_]+", "_", embedding_version).strip("_")
    collection = args.collection or f"{settings.qdrant_known_collection}_{safe_version}"
    if collection == settings.qdrant_known_collection:
        raise SystemExit("Refusing to rebuild the configured active collection. Choose a distinct --collection.")
    store = QdrantVectorStore(settings)
    storage = MinioStorage(settings)
    face_service = FaceService(settings)
    if store.collection_exists(collection):
        if not args.replace:
            raise SystemExit(f"Target collection already exists: {collection}. Pass --replace to recreate it.")
        store.recreate_collection(collection)
    else:
        store.create_collection(collection)
    vectors: dict[tuple[int | None, int], list[np.ndarray]] = defaultdict(list)
    result: dict[str, object] = {
        "collection": collection,
        "embedding_version": embedding_version,
        "ready_samples": 0,
        "ready_people": 0,
        "indexed": 0,
        "skipped": 0,
        "centroids": 0,
        "skip_details": [],
    }
    with SessionLocal() as db:
        samples = db.scalars(select(SamplePhoto).where(SamplePhoto.status == "ready").order_by(SamplePhoto.id)).all()
        ready_people = {sample.person_id for sample in samples}
        result["ready_samples"] = len(samples)
        result["ready_people"] = len(ready_people)
        for sample in samples:
            try:
                faces = face_service.detect_faces(storage.get_bytes(sample.object_key))
            except Exception as exc:
                result["skipped"] = int(result["skipped"]) + 1
                result["skip_details"].append({"sample_photo_id": sample.id, "person_id": sample.person_id, "reason": f"read_or_detect_error:{type(exc).__name__}"})
                continue
            if not faces:
                result["skipped"] = int(result["skipped"]) + 1
                result["skip_details"].append({"sample_photo_id": sample.id, "person_id": sample.person_id, "reason": "no_face"})
                continue
            if len(faces) != 1:
                result["skipped"] = int(result["skipped"]) + 1
                result["skip_details"].append({"sample_photo_id": sample.id, "person_id": sample.person_id, "reason": f"multiple_faces:{len(faces)}"})
                continue
            if faces[0].face_size < settings.face_sample_min_size:
                result["skipped"] = int(result["skipped"]) + 1
                result["skip_details"].append({"sample_photo_id": sample.id, "person_id": sample.person_id, "reason": f"face_too_small:{faces[0].face_size:.1f}"})
                continue
            detected = faces[0]
            face = db.scalar(select(FaceRecord).where(FaceRecord.sample_photo_id == sample.id))
            if face is None:
                result["skipped"] = int(result["skipped"]) + 1
                result["skip_details"].append({"sample_photo_id": sample.id, "person_id": sample.person_id, "reason": "missing_face_record"})
                continue
            store.upsert_face(collection, face.id, sample.person_id, detected.embedding, workspace_id=sample.workspace_id, sample_photo_id=sample.id, embedding_version=embedding_version)
            vectors[(sample.workspace_id, sample.person_id)].append(detected.embedding)
            result["indexed"] = int(result["indexed"]) + 1
        for (workspace_id, person_id), items in vectors.items():
            centroid = np.mean(np.stack(items), axis=0)
            centroid /= max(float(np.linalg.norm(centroid)), 1e-12)
            store.upsert_centroid(collection, person_id, centroid, workspace_id=workspace_id, embedding_version=embedding_version)
            result["centroids"] = int(result["centroids"]) + 1
    inspection = store.inspect_collection(collection, embedding_version=embedding_version, include_vectors=True)
    indexed_people = {person_id for (_, person_id) in vectors}
    missing_person_ids = sorted(ready_people - indexed_people)
    ready_for_activation = (
        inspection.vector_size == settings.qdrant_vector_dimension
        and inspection.distance == "Cosine"
        and inspection.searchable_samples == result["indexed"]
        and inspection.searchable_centroids == result["centroids"]
        and inspection.invalid_payload_points == 0
        and inspection.invalid_vector_points == 0
        and not missing_person_ids
    )
    result["missing_person_ids"] = missing_person_ids
    result["inspection"] = inspection.as_dict()
    result["ready_for_activation"] = ready_for_activation
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if ready_for_activation:
        print("Validation passed. Activate manually with:")
        print(f"QDRANT_KNOWN_COLLECTION={collection}")
        print(f"FACE_EMBEDDING_VERSION={embedding_version}")
        print("Then restart the services manually and use the existing unknown-person re-recognition action.")
    else:
        raise SystemExit("Validation failed. Do not activate this collection; review skip_details and missing_person_ids.")


if __name__ == "__main__":
    main()
