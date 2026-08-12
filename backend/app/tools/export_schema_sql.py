from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401  在导出前注册全部 ORM 表及其注释。
from app.db import Base


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "sql" / "tables.sql"


def _compile_schema_item(item: CreateTable | CreateIndex) -> str:
    return str(
        item.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).strip()


def render_schema_sql() -> str:
    """将当前 ORM 元数据渲染为可直接用于 SQLite 的全量建表脚本。"""
    sections = [
        "-- PictureShow 全量表设计",
        "-- 本文件由 backend/app/tools/export_schema_sql.py 根据 ORM 元数据生成，请勿手工修改。",
        "-- 生成命令：$env:PYTHONPATH='backend'; python -m app.tools.export_schema_sql",
        "-- 适用数据库：SQLite；包含全部业务表、运行时迁移登记表、索引、外键、默认值及中文说明。",
        "",
        "PRAGMA foreign_keys = ON;",
    ]

    for table in Base.metadata.sorted_tables:
        sections.extend(
            [
                "",
                f"-- 表名：{table.name}",
                f"-- 表说明：{table.comment}",
                "-- 字段说明：",
                *[f"--   {column.name}：{column.comment}" for column in table.columns],
                _compile_schema_item(CreateTable(table)) + ";",
            ]
        )
        for index in sorted(table.indexes, key=lambda value: value.name or ""):
            sections.append(_compile_schema_item(CreateIndex(index)) + ";")

    return "\n".join(sections) + "\n"


def verify_schema_sql(sql_text: str) -> None:
    """在内存 SQLite 中执行脚本，并核对关键结构是否与 ORM 元数据一致。"""
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(sql_text)
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        expected_tables = set(Base.metadata.tables)
        if actual_tables != expected_tables:
            raise ValueError(f"建表结果不一致：期望 {expected_tables}，实际 {actual_tables}")

        for table in Base.metadata.sorted_tables:
            actual_columns = [
                row[1]
                for row in connection.execute(
                    f'PRAGMA table_info("{table.name}")'
                )
            ]
            expected_columns = [column.name for column in table.columns]
            if actual_columns != expected_columns:
                raise ValueError(
                    f"字段不一致：{table.name} 期望 {expected_columns}，实际 {actual_columns}"
                )

            actual_indexes = {
                row[1]
                for row in connection.execute(f'PRAGMA index_list("{table.name}")')
                if row[3] == "c"
            }
            expected_indexes = {index.name for index in table.indexes}
            if actual_indexes != expected_indexes:
                raise ValueError(
                    f"索引不一致：{table.name} 期望 {expected_indexes}，实际 {actual_indexes}"
                )


def write_schema_sql(output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    """导出并验证全量表设计脚本。"""
    sql_text = render_schema_sql()
    verify_schema_sql(sql_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sql_text, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    print(write_schema_sql())
