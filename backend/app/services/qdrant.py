from __future__ import annotations

import numpy as np

from app.core.config import Settings, get_settings

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except Exception:
    QdrantClient = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]


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

    def recreate_collection(self, collection_name: str) -> None:
        client = self._get_client()
        if client.collection_exists(collection_name=collection_name):
            client.delete_collection(collection_name=collection_name)
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=self.settings.qdrant_vector_dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def delete_collection(self, collection_name: str) -> None:
        client = self._get_client()
        if client.collection_exists(collection_name=collection_name):
            client.delete_collection(collection_name=collection_name)

    def upsert_face(self, collection_name: str, face_id: int, person_id: int, vector: np.ndarray) -> None:
        client = self._get_client()
        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=face_id,
                    vector=np.asarray(vector, dtype=np.float32).tolist(),
                    payload={"person_id": person_id},
                )
            ],
        )

    def delete_faces(self, collection_name: str, face_ids: list[int]) -> None:
        if not face_ids:
            return
        client = self._get_client()
        client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=face_ids),
        )

    def get_face_vector(self, collection_name: str, face_id: int) -> np.ndarray | None:
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

    def search(self, collection_name: str, vector: np.ndarray, limit: int = 1) -> tuple[int | None, float | None]:
        client = self._get_client()
        response = client.query_points(
            collection_name=collection_name,
            query=np.asarray(vector, dtype=np.float32).tolist(),
            limit=limit,
            with_payload=True,
        )
        if not response.points:
            return None, None
        point = response.points[0]
        person_id = (point.payload or {}).get("person_id")
        score = point.score
        return (int(person_id) if person_id is not None else None, float(score) if score is not None else None)
