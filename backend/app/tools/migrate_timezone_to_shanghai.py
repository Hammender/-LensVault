from sqlalchemy import create_engine

from app.core.config import get_settings
from app.services.timezone_migration import migrate_system_timestamps


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    backup_path, updated_rows = migrate_system_timestamps(engine)
    if backup_path is None:
        print("数据库已经完成 Asia/Shanghai 时间迁移，无需重复执行。")
        return
    print(f"迁移完成，共更新 {updated_rows} 个时间值。")
    print(f"迁移前备份：{backup_path}")


if __name__ == "__main__":
    main()
