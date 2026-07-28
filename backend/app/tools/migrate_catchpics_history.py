from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.lifecycle import initialize_database
from app.services.acquisition import AcquisitionService, migrate_catchpics_history
from app.services.container import build_service_container


def main() -> None:
    parser = argparse.ArgumentParser(description="将 catchPics 旧资源复制到图片采集待审核区，不修改旧目录。")
    parser.add_argument("--root", required=True, help="catchPics 目录，例如 E:\\code\\catchPics")
    parser.add_argument("--workspace-id", type=int, default=None, help="目标工作区 ID；私有旧数据可省略")
    parser.add_argument("--dry-run", action="store_true", help="仅统计文件和分类，不写数据库或 MinIO")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"目录不存在：{root}")
    project_roots = [root] if (root / "resource").is_dir() else [
        path for path in root.iterdir() if path.is_dir() and (path / "resource").is_dir()
    ]
    if not project_roots:
        raise SystemExit(f"未在目录或其一级站点目录中找到 resource：{root}")

    settings = get_settings()
    services = build_service_container(settings)
    if not args.dry_run:
        initialize_database(engine)
    total: dict[str, int] = {"files": 0, "sources": 0, "categories": 0, "assets": 0, "records": 0}
    with SessionLocal() as db:
        for project_root in project_roots:
            result = migrate_catchpics_history(
                services.acquisition,
                db,
                args.workspace_id,
                project_root,
                args.dry_run,
            )
            for key, value in result.items():
                total[key] = total.get(key, 0) + value
    print(json.dumps({
        "dry_run": args.dry_run,
        "root": str(root),
        "projects": [str(path) for path in project_roots],
        **total,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
