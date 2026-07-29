from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def _dotenv_keys(path: Path) -> set[str]:
    if not path.is_file():
        raise RuntimeError(f"Runtime configuration file does not exist: {path}")
    keys: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


class Settings(BaseSettings):
    app_name: str = "PictureShow"
    database_url: str
    data_dir: Path
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    auth_secret_key: str = "pictureshow-local-dev-secret-change-me"
    access_token_expire_minutes: int = 7 * 24 * 60
    auth_cookie_secure: bool = False

    minio_endpoint: str = "127.0.0.1:19000"
    minio_access_key: str = "pictureshow"
    minio_secret_key: str = "pictureshow-secret"
    minio_bucket: str = "photos"
    minio_secure: bool = False
    minio_public_endpoint: str | None = None
    minio_public_secure: bool | None = None

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    video_faststart_enabled: bool = True
    video_transcode_non_browser_friendly: bool = True
    video_faststart_timeout_seconds: int = 3600
    video_transcode_timeout_seconds: int = 21600
    video_cover_capture_seconds: float = 1.0
    video_presigned_url_expires_seconds: int = 21600
    video_use_presigned_play_url: bool = True
    video_auto_seek_optimize_on_upload: bool = True
    video_seek_optimize_codec_policy: str = "preserve"
    video_seek_keyframe_interval_seconds: float = 1.0
    video_seek_optimize_threshold_seconds: float = 2.5
    video_transcode_accelerator: str = "nvenc"
    video_transcode_fallback_to_cpu: bool = True
    video_seek_transcode_crf: int = 21
    video_seek_transcode_preset: str = "veryfast"
    subtitle_asr_model_path: Path = Path("E:/AI-MODELS/ASR/faster-whisper-medium")
    subtitle_asr_device: str = "cpu"
    subtitle_asr_compute_type: str = "int8"
    subtitle_asr_unload_after_transcribe: bool = False
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

    qdrant_host: str = "127.0.0.1"
    qdrant_port: int = 16333
    qdrant_grpc_port: int = 16334
    qdrant_prefer_grpc: bool = True
    qdrant_known_collection: str = "pictureshow_known_faces"
    qdrant_vector_dimension: int = 512

    gallery_similarity_model_path: Path = Path("E:/AI-MODELS/vision/dinov2-base")
    gallery_similarity_model_version: str = "dinov2-base-v1"
    gallery_similarity_device: str = "cuda"
    gallery_similarity_batch_size: int = 32
    gallery_similarity_vector_dimension: int = 768
    gallery_similarity_qdrant_collection: str = "pictureshow_gallery_similarity_dinov2_base_v1"
    gallery_similarity_near_threshold: float = 0.92
    gallery_similarity_scene_threshold: float = 0.88

    acquisition_download_workers: int = 8
    acquisition_download_timeout_seconds: int = 30
    acquisition_download_retries: int = 3
    acquisition_failed_retry_hours: int = 24
    acquisition_max_file_bytes: int = 100 * 1024 * 1024
    acquisition_quality_min_pixels: int = 512 * 512
    acquisition_quality_max_aspect_ratio: float = 4.0
    acquisition_quality_blur_threshold: float = 45.0
    acquisition_export_ttl_hours: int = 24

    face_model_name: str = "buffalo_l"
    face_embedding_version: str = "buffalo_l-v2-exif"
    face_detection_size: int = 640
    face_search_limit: int = 50
    face_flip_augmentation: bool = False
    face_recognition_threshold: float = 0.45
    face_sample_min_size: int = 40
    face_sample_warning_size: int = 80
    face_sample_min_detection_score: float = 0.5
    face_sample_blur_warning: float = 45.0
    face_evaluation_min_labels: int = 100
    face_evaluation_min_people: int = 20
    thumbnail_cache_size: int = 256

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Runtime configuration is intentionally sourced from the project .env.
        # Explicit constructor values remain available for tests and tools.
        return init_settings, dotenv_settings


@lru_cache
def get_settings() -> Settings:
    expected_keys = {field_name.upper() for field_name in Settings.model_fields}
    missing_keys = sorted(expected_keys - _dotenv_keys(ENV_FILE))
    if missing_keys:
        raise RuntimeError(f"Missing required settings in {ENV_FILE}: {', '.join(missing_keys)}")
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
