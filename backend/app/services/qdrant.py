from __future__ import annotations

from dataclasses import dataclass
import math
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from app.core.config import Settings, get_settings

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except Exception:
    QdrantClient = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]


@dataclass(frozen=True)
class FaceSearchHit:
    point_id: int | str
    person_id: int
    score: float
    source_type: str
    sample_photo_id: int | None


@dataclass(frozen=True)
class FaceIndexInspection:
    collection: str
    exists: bool
    vector_size: int | None
    distance: str | None
    total_points: int
    searchable_samples: int
    searchable_centroids: int
    covered_people: int
    invalid_payload_points: int
    invalid_vector_points: int
    vector_norm_min: float | None
    vector_norm_max: float | None

    @property
    def schema_valid(self) -> bool:
        return self.vector_size is not None and self.distance == "Cosine"

    def as_dict(self) -> dict[str, object]:
        return {
            "collection": self.collection,
            "exists": self.exists,
            "vector_size": self.vector_size,
            "distance": self.distance,
            "total_points": self.total_points,
            "searchable_samples": self.searchable_samples,
            "searchable_centroids": self.searchable_centroids,
            "covered_people": self.covered_people,
            "invalid_payload_points": self.invalid_payload_points,
            "invalid_vector_points": self.invalid_vector_points,
            "vector_norm_min": self.vector_norm_min,
            "vector_norm_max": self.vector_norm_max,
        }


class QdrantVectorStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: QdrantClient | None = None  # type: ignore[type-arg]

    def _get_client(self) -> QdrantClient:
        if QdrantClient is None or models is None:
            raise RuntimeError(
                "qdrant-client is not installed or failed to load. "
                "Install backend dependencies: "
                "conda run -n pictureshow python -m pip install -r requirements.txt"
            )
        if self._client is None:
            self._client = QdrantClient(
                host=self.settings.qdrant_host,
                port=self.settings.qdrant_port,
                grpc_port=self.settings.qdrant_grpc_port,
                prefer_grpc=self.settings.qdrant_prefer_grpc,
            )
        return self._client

    def ensure_collections(self) -> None:
        client = self._get_client()
        if not client.collection_exists(collection_name=self.settings.qdrant_known_collection):
            client.create_collection(
                collection_name=self.settings.qdrant_known_collection,
                vectors_config=models.VectorParams(
                    size=self.settings.qdrant_vector_dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            return
        inspection = self.inspect_collection(
            self.settings.qdrant_known_collection,
            embedding_version=self.settings.face_embedding_version,
            include_vectors=False,
        )
        if inspection.vector_size != self.settings.qdrant_vector_dimension or inspection.distance != "Cosine":
            raise RuntimeError(
                "Qdrant face collection schema mismatch: "
                f"collection={inspection.collection} size={inspection.vector_size} distance={inspection.distance}; "
                f"expected size={self.settings.qdrant_vector_dimension} distance=Cosine"
            )

    def ensure_gallery_similarity_collection(self) -> None:
        collection_name = self.settings.gallery_similarity_qdrant_collection
        dimension = self.settings.gallery_similarity_vector_dimension
        client = self._get_client()
        if not client.collection_exists(collection_name=collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            )
            return
        info = client.get_collection(collection_name=collection_name)
        vector_size, distance = self._vector_schema(info)
        if vector_size != dimension or distance != "Cosine":
            raise RuntimeError(
                "Qdrant gallery similarity collection schema mismatch: "
                f"collection={collection_name} size={vector_size} distance={distance}; "
                f"expected size={dimension} distance=Cosine"
            )

    @staticmethod
    def gallery_similarity_point_id(workspace_id: int | None, photo_id: int, feature_version: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"pictureshow:{workspace_id}:{photo_id}:{feature_version}:gallery-similarity"))

    def upsert_gallery_similarity_vector(
        self,
        *,
        workspace_id: int | None,
        photo_id: int,
        sha256: str,
        is_rich_text: bool,
        feature_version: str,
        vector: np.ndarray,
    ) -> str:
        self.ensure_gallery_similarity_collection()
        point_id = self.gallery_similarity_point_id(workspace_id, photo_id, feature_version)
        self._get_client().upsert(
            collection_name=self.settings.gallery_similarity_qdrant_collection,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=np.asarray(vector, dtype=np.float32).tolist(),
                    payload={
                        "workspace_id": workspace_id,
                        "gallery_photo_id": photo_id,
                        "sha256": sha256,
                        "is_rich_text": is_rich_text,
                        "feature_version": feature_version,
                    },
                )
            ],
        )
        return point_id

    def get_gallery_similarity_vectors(self, point_ids: list[str]) -> dict[str, np.ndarray]:
        if not point_ids:
            return {}
        points = self._get_client().retrieve(
            collection_name=self.settings.gallery_similarity_qdrant_collection,
            ids=point_ids,
            with_vectors=True,
            with_payload=False,
        )
        return {
            str(point.id): np.asarray(point.vector, dtype=np.float32)
            for point in points
            if point.vector is not None
        }

    def search_gallery_similarity(
        self,
        *,
        workspace_id: int | None,
        feature_version: str,
        vector: np.ndarray,
        score_threshold: float,
        limit: int = 200,
    ) -> list[tuple[int, float]]:
        response = self._get_client().query_points(
            collection_name=self.settings.gallery_similarity_qdrant_collection,
            query=np.asarray(vector, dtype=np.float32).tolist(),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="workspace_id",
                        match=models.MatchValue(value=workspace_id),
                    ),
                    models.FieldCondition(
                        key="feature_version",
                        match=models.MatchValue(value=feature_version),
                    ),
                ]
            ),
        )
        return [
            (int(point.payload["gallery_photo_id"]), float(point.score))
            for point in response.points
            if point.payload
            and point.payload.get("gallery_photo_id") is not None
            and point.score is not None
        ]

    def delete_gallery_similarity_vectors(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        if not self.collection_exists(self.settings.gallery_similarity_qdrant_collection):
            return
        self.delete_faces(self.settings.gallery_similarity_qdrant_collection, point_ids)

    def recreate_collection(self, collection_name: str) -> None:
        client = self._get_client()
        if client.collection_exists(collection_name=collection_name):
            client.delete_collection(collection_name=collection_name)
        self.create_collection(collection_name)

    def create_collection(self, collection_name: str) -> None:
        client = self._get_client()
        if client.collection_exists(collection_name=collection_name):
            raise ValueError(f"Qdrant collection already exists: {collection_name}")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=self.settings.qdrant_vector_dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def collection_exists(self, collection_name: str) -> bool:
        return bool(self._get_client().collection_exists(collection_name=collection_name))

    def delete_collection(self, collection_name: str) -> None:
        client = self._get_client()
        if client.collection_exists(collection_name=collection_name):
            client.delete_collection(collection_name=collection_name)

    def upsert_face(
        self,
        collection_name: str,
        face_id: int,
        person_id: int,
        vector: np.ndarray,
        *,
        workspace_id: int | None,
        sample_photo_id: int | None,
        embedding_version: str,
    ) -> None:
        client = self._get_client()
        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=face_id,
                    vector=np.asarray(vector, dtype=np.float32).tolist(),
                    payload={
                        "workspace_id": workspace_id,
                        "person_id": person_id,
                        "source_type": "sample",
                        "sample_photo_id": sample_photo_id,
                        "embedding_version": embedding_version,
                    },
                )
            ],
        )

    @staticmethod
    def centroid_point_id(workspace_id: int | None, person_id: int, embedding_version: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"pictureshow:{workspace_id}:{person_id}:{embedding_version}:centroid"))

    def upsert_centroid(
        self,
        collection_name: str,
        person_id: int,
        vector: np.ndarray,
        *,
        workspace_id: int | None,
        embedding_version: str,
    ) -> None:
        self._get_client().upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=self.centroid_point_id(workspace_id, person_id, embedding_version),
                    vector=np.asarray(vector, dtype=np.float32).tolist(),
                    payload={
                        "workspace_id": workspace_id,
                        "person_id": person_id,
                        "source_type": "centroid",
                        "sample_photo_id": None,
                        "embedding_version": embedding_version,
                    },
                )
            ],
        )

    def delete_centroid(self, collection_name: str, workspace_id: int | None, person_id: int, embedding_version: str) -> None:
        self.delete_faces(collection_name, [self.centroid_point_id(workspace_id, person_id, embedding_version)])

    def delete_faces(self, collection_name: str, face_ids: list[int | str]) -> None:
        if not face_ids:
            return
        client = self._get_client()
        client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=face_ids),
        )

    def get_face_vector(self, collection_name: str, face_id: int | str) -> np.ndarray | None:
        client = self._get_client()
        points = client.retrieve(
            collection_name=collection_name,
            ids=[face_id],
            with_vectors=True,
            with_payload=False,
        )
        if not points:
            return None
        vector = points[0].vector
        if vector is None:
            return None
        return np.asarray(vector, dtype=np.float32)

    def get_reference_vector(
        self, collection_name: str, face_id: int, *, workspace_id: int | None,
        person_id: int, embedding_version: str,
    ) -> np.ndarray:
        points = self._get_client().retrieve(
            collection_name=collection_name, ids=[face_id], with_vectors=True, with_payload=True,
        )
        expected = {"workspace_id": workspace_id, "person_id": person_id,
                    "embedding_version": embedding_version, "source_type": "sample"}
        if not points or any((points[0].payload or {}).get(key) != value for key, value in expected.items()):
            raise ValueError(f"样本向量缺失或版本、工作区、人物不一致：{face_id}")
        vector = np.asarray(points[0].vector, dtype=np.float32)
        if vector.shape != (self.settings.qdrant_vector_dimension,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-8:
            raise ValueError(f"样本向量无效：{face_id}")
        return vector / np.linalg.norm(vector)

    @staticmethod
    def _vector_schema(info: object) -> tuple[int | None, str | None]:
        params = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
        if isinstance(params, dict):
            if len(params) != 1:
                return None, None
            params = next(iter(params.values()))
        size = getattr(params, "size", None)
        distance = getattr(params, "distance", None)
        distance_value = getattr(distance, "value", distance)
        return (int(size) if size is not None else None, str(distance_value) if distance_value is not None else None)

    def inspect_collection(
        self,
        collection_name: str,
        *,
        embedding_version: str,
        workspace_id: int | None = None,
        include_vectors: bool = False,
    ) -> FaceIndexInspection:
        client = self._get_client()
        if not client.collection_exists(collection_name=collection_name):
            return FaceIndexInspection(
                collection=collection_name,
                exists=False,
                vector_size=None,
                distance=None,
                total_points=0,
                searchable_samples=0,
                searchable_centroids=0,
                covered_people=0,
                invalid_payload_points=0,
                invalid_vector_points=0,
                vector_norm_min=None,
                vector_norm_max=None,
            )
        info = client.get_collection(collection_name=collection_name)
        vector_size, distance = self._vector_schema(info)
        searchable_samples = 0
        searchable_centroids = 0
        people: set[int] = set()
        invalid_payload_points = 0
        invalid_vector_points = 0
        vector_norms: list[float] = []
        offset = None
        scanned = 0
        required_payload = {"workspace_id", "person_id", "source_type", "sample_photo_id", "embedding_version"}
        while True:
            points, offset = client.scroll(
                collection_name=collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=include_vectors,
            )
            scanned += len(points)
            for point in points:
                payload = point.payload or {}
                if not required_payload.issubset(payload):
                    invalid_payload_points += 1
                source_type = payload.get("source_type")
                same_version = payload.get("embedding_version") == embedding_version
                same_workspace = workspace_id is None or payload.get("workspace_id") == workspace_id
                person_id = payload.get("person_id")
                if same_version and same_workspace and person_id is not None:
                    if source_type == "sample":
                        searchable_samples += 1
                        people.add(int(person_id))
                    elif source_type == "centroid":
                        searchable_centroids += 1
                        people.add(int(person_id))
                if include_vectors:
                    vector = point.vector
                    if not isinstance(vector, list) or (vector_size is not None and len(vector) != vector_size):
                        invalid_vector_points += 1
                        continue
                    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
                    vector_norms.append(norm)
                    if not math.isfinite(norm) or abs(norm - 1.0) > 1e-3:
                        invalid_vector_points += 1
            if offset is None:
                break
        total_points = int(getattr(info, "points_count", scanned) or scanned)
        return FaceIndexInspection(
            collection=collection_name,
            exists=True,
            vector_size=vector_size,
            distance=distance,
            total_points=total_points,
            searchable_samples=searchable_samples,
            searchable_centroids=searchable_centroids,
            covered_people=len(people),
            invalid_payload_points=invalid_payload_points,
            invalid_vector_points=invalid_vector_points,
            vector_norm_min=min(vector_norms) if vector_norms else None,
            vector_norm_max=max(vector_norms) if vector_norms else None,
        )

    def search_candidates(
        self,
        collection_name: str,
        vector: np.ndarray,
        *,
        workspace_id: int | None,
        embedding_version: str,
        limit: int,
        source_types: tuple[str, ...] = ("sample", "centroid"),
    ) -> list[FaceSearchHit]:
        client = self._get_client()
        conditions = [
            models.FieldCondition(key="embedding_version", match=models.MatchValue(value=embedding_version)),
            models.FieldCondition(key="source_type", match=models.MatchAny(any=list(source_types))),
        ]
        if workspace_id is not None:
            conditions.append(models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)))
        response = client.query_points(
            collection_name=collection_name,
            query=np.asarray(vector, dtype=np.float32).tolist(),
            limit=limit,
            with_payload=True,
            query_filter=models.Filter(must=conditions),
        )
        hits: list[FaceSearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            person_id = payload.get("person_id")
            if person_id is None or point.score is None:
                continue
            hits.append(
                FaceSearchHit(
                    point_id=point.id,
                    person_id=int(person_id),
                    score=float(point.score),
                    source_type=str(payload.get("source_type") or "sample"),
                    sample_photo_id=int(payload["sample_photo_id"]) if payload.get("sample_photo_id") is not None else None,
                )
            )
        return hits
