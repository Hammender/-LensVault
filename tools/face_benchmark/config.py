from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"配置文件不存在：{path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_sqlite_path(database_url: str, root: Path = REPO_ROOT) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("独立评测工具目前只支持 SQLite DATABASE_URL。")
    raw_path = database_url[len(prefix) :]
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


@dataclass(frozen=True)
class SourceConfig:
    database_path: Path
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    recognition_threshold: float
    min_margin: float

    @classmethod
    def from_env(cls, env_path: Path) -> "SourceConfig":
        values = read_dotenv(env_path)

        def required(name: str) -> str:
            value = values.get(name)
            if not value:
                raise RuntimeError(f".env 缺少配置：{name}")
            return value

        return cls(
            database_path=resolve_sqlite_path(required("DATABASE_URL"), env_path.resolve().parent),
            minio_endpoint=required("MINIO_ENDPOINT"),
            minio_access_key=required("MINIO_ACCESS_KEY"),
            minio_secret_key=required("MINIO_SECRET_KEY"),
            minio_bucket=required("MINIO_BUCKET"),
            minio_secure=values.get("MINIO_SECURE", "false").lower() == "true",
            recognition_threshold=float(values.get("FACE_RECOGNITION_THRESHOLD", "0.45")),
            min_margin=float(values.get("FACE_RECOGNITION_MIN_MARGIN", "0.08")),
        )
