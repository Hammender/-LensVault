from __future__ import annotations

from io import BytesIO

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings, get_settings


class MinioStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure,
        )
        self.bucket = self.settings.minio_bucket

    def ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as exc:
            raise RuntimeError(f"MinIO bucket setup failed: {exc}") from exc

    def put_bytes(self, object_key: str, payload: bytes, content_type: str | None = None) -> None:
        stream = BytesIO(payload)
        self.client.put_object(
            self.bucket,
            object_key,
            stream,
            length=len(payload),
            content_type=content_type or "application/octet-stream",
        )

    def get_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def remove_object(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.bucket, object_key)
        except S3Error as exc:
            if getattr(exc, "code", "") in {"NoSuchKey", "NoSuchObject"}:
                return
            raise RuntimeError(f"MinIO remove object failed: {exc}") from exc
