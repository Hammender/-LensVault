from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import Settings, get_settings

try:
    from pymilvus import MilvusClient
except Exception:
    MilvusClient = None  # type: ignore[assignment]


class MilvusVectorStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: MilvusClient | None = None  # type: ignore[type-arg]

    def _get_client(self) -> MilvusClient:
        if MilvusClient is None:
            raise RuntimeError(
                "pymilvus is not installed or failed to load. "
                "Install backend dependencies in the project venv: "
                ".\\.venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt"
            )
        if self._client is None:
            uri = f"http://{self.settings.milvus_host}:{self.settings.milvus_port}"
            self._client = MilvusClient(uri=uri)
        return self._client

    def ensure_collections(self) -> None:
        client = self._get_client()
        for collection_name in (self.settings.milvus_known_collection, self.settings.milvus_unknown_collection):
            if not client.has_collection(collection_name=collection_name):
                client.create_collection(
                    collection_name=collection_name,
                    dimension=self.settings.milvus_vector_dimension,
                    metric_type="COSINE",
                    auto_id=False,
                )

    def upsert_face(self, collection_name: str, face_id: int, person_id: int, vector: np.ndarray) -> None:
        client = self._get_client()
        client.upsert(
            collection_name=collection_name,
            data=[{"id": face_id, "person_id": person_id, "vector": vector.tolist()}],
        )

    def delete_faces(self, collection_name: str, face_ids: list[int]) -> None:
        if not face_ids:
            return
        client = self._get_client()
        client.delete(collection_name=collection_name, ids=face_ids)

    def get_face_vector(self, collection_name: str, face_id: int) -> np.ndarray | None:
        client = self._get_client()
        rows = client.get(collection_name=collection_name, ids=[face_id])
        if not rows:
            return None
        vector = rows[0].get("vector")
        if vector is None:
            return None
        return np.asarray(vector, dtype=np.float32)

    def search(self, collection_name: str, vector: np.ndarray, limit: int = 1) -> tuple[int | None, float | None]:
        client = self._get_client()
        results: list[list[dict[str, Any]]] = client.search(
            collection_name=collection_name,
            data=[vector.tolist()],
            limit=limit,
            output_fields=["person_id"],
        )
        if not results or not results[0]:
            return None, None
        item = results[0][0]
        entity = item.get("entity") or {}
        person_id = entity.get("person_id")
        score = item.get("distance")
        return (int(person_id) if person_id is not None else None, float(score) if score is not None else None)
