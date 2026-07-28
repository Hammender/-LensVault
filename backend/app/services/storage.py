from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from minio import Minio
from minio.commonconfig import ComposeSource, CopySource
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
        self.public_client = self._build_public_client()

    def _build_public_client(self) -> Minio:
        if not self.settings.minio_public_endpoint:
            return self.client
        return Minio(
            self.settings.minio_public_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure if self.settings.minio_public_secure is None else self.settings.minio_public_secure,
        )

    def ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as exc:
            raise RuntimeError(f"MinIO bucket setup failed: {exc}") from exc

    def put_bytes(self, object_key: str, payload: bytes, content_type: str | None = None) -> None:
        stream = BytesIO(payload)
        self.put_stream(object_key, stream, len(payload), content_type)

    def put_stream(self, object_key: str, stream: BinaryIO, length: int, content_type: str | None = None) -> None:
        self.client.put_object(
            self.bucket,
            object_key,
            stream,
            length=length,
            content_type=content_type or "application/octet-stream",
        )

    def put_file(self, object_key: str, path: Path, content_type: str | None = None) -> None:
        self.client.fput_object(
            self.bucket,
            object_key,
            str(path),
            content_type=content_type or "application/octet-stream",
        )

    def stat_object(self, object_key: str):
        return self.client.stat_object(self.bucket, object_key)

    def presigned_get_url(self, object_key: str, expires_seconds: int) -> str:
        expires = timedelta(seconds=max(expires_seconds, 1))
        return self.public_client.presigned_get_object(self.bucket, object_key, expires=expires)

    def get_stream(self, object_key: str, offset: int = 0, length: int | None = None):
        if length is None:
            return self.client.get_object(self.bucket, object_key, offset=offset)
        return self.client.get_object(self.bucket, object_key, offset=offset, length=length)

    def compose_object(self, object_key: str, source_keys: list[str]) -> None:
        self.client.compose_object(
            self.bucket,
            object_key,
            [ComposeSource(self.bucket, source_key) for source_key in source_keys],
        )

    def copy_object(self, target_key: str, source_key: str) -> None:
        self.client.copy_object(
            self.bucket,
            target_key,
            CopySource(self.bucket, source_key),
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

    def remove_objects(self, object_keys: list[str]) -> None:
        for object_key in object_keys:
            self.remove_object(object_key)
