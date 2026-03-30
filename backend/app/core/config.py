from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PictureShow"
    database_url: str = "sqlite:///./data/app.db"
    data_dir: Path = Path("./data")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "pictureshow"
    minio_secret_key: str = "pictureshow-secret"
    minio_bucket: str = "photos"
    minio_secure: bool = False

    face_recognition_threshold: float = 0.45
    face_cluster_threshold: float = 0.55
    thumbnail_cache_size: int = 256

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
