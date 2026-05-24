from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PictureShow"
    database_url: str = "sqlite:///E:/dockerVolums/picture-show/sqllite/app.db"
    data_dir: Path = Path("E:/dockerVolums/picture-show/sqllite")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "pictureshow"
    minio_secret_key: str = "pictureshow-secret"
    minio_bucket: str = "photos"
    minio_secure: bool = False

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    video_faststart_enabled: bool = True
    video_transcode_non_browser_friendly: bool = True
    video_faststart_timeout_seconds: int = 3600
    video_transcode_timeout_seconds: int = 21600
    video_cover_capture_seconds: float = 1.0
    video_presigned_url_expires_seconds: int = 21600
    video_use_presigned_play_url: bool = True
    subtitle_asr_model_path: Path = Path("E:/AI-MODELS/ASR/faster-whisper-medium")
    subtitle_asr_device: str = "cpu"
    subtitle_asr_compute_type: str = "int8"
    subtitle_translation_provider: str = "local_hymt2"
    subtitle_translation_base_url: str = "http://127.0.0.1:8081/v1"
    subtitle_translation_model: str = "Hy-MT2-1.8B-Q4_K_M"
    subtitle_translation_model_path: Path = Path("E:/AI-MODELS/translate/HY-MT2-1-1.88GGUF/Hy-MT2-1.8B-Q4_K_M.gguf")
    subtitle_translation_timeout_seconds: int = 600
    subtitle_batch_size: int = 3
    subtitle_llama_server_path: Path | None = None
    subtitle_llama_server_threads: int = 16
    subtitle_llama_server_context_size: int = 4096
    subtitle_llama_server_startup_timeout_seconds: int = 300
    subtitle_llama_server_log_path: Path | None = None
    subtitle_llama_server_device: str = "none"
    subtitle_llama_server_gpu_layers: int = 0
    subtitle_llama_server_warmup: bool = False

    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_known_collection: str = "pictureshow_known_faces"
    milvus_unknown_collection: str = "pictureshow_unknown_faces"
    milvus_vector_dimension: int = 512

    face_recognition_threshold: float = 0.45
    face_unknown_match_threshold: float = 0.6
    thumbnail_cache_size: int = 256

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
