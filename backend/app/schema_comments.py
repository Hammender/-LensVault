from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import MetaData


SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "tables.sql"
_TABLE_PATTERN = re.compile(r"^-- 表名：(.*)$")
_TABLE_COMMENT_PATTERN = re.compile(r"^-- 表说明：(.*)$")
_COLUMN_PATTERN = re.compile(r"^--   ([^：]+)：(.*)$")


def _load_comments() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """读取受版本控制的全量表设计，将中文说明注册到 ORM 元数据。"""
    if not SCHEMA_SQL_PATH.is_file():
        raise RuntimeError(f"缺少全量表设计文件：{SCHEMA_SQL_PATH}")

    table_comments: dict[str, str] = {}
    column_comments: dict[tuple[str, str], str] = {}
    current_table: str | None = None
    for line in SCHEMA_SQL_PATH.read_text(encoding="utf-8").splitlines():
        table_match = _TABLE_PATTERN.match(line)
        if table_match:
            current_table = table_match.group(1)
            continue
        table_comment_match = _TABLE_COMMENT_PATTERN.match(line)
        if table_comment_match and current_table:
            table_comments[current_table] = table_comment_match.group(1)
            continue
        column_match = _COLUMN_PATTERN.match(line)
        if column_match and current_table:
            column_comments[(current_table, column_match.group(1))] = column_match.group(2)
    return table_comments, column_comments


def apply_schema_comments(metadata: MetaData) -> None:
    """为全部 ORM 表和字段注册中文说明，并阻止未说明的结构进入运行时。"""
    table_comments, column_comments = _load_comments()
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    for table in metadata.tables.values():
        comment = table_comments.get(table.name)
        if comment is None:
            missing_tables.append(table.name)
            continue
        table.comment = comment
        for column in table.columns:
            comment = column_comments.get((table.name, column.name))
            if comment is None:
                missing_columns.append(f"{table.name}.{column.name}")
            else:
                column.comment = comment
    if missing_tables or missing_columns:
        details = []
        if missing_tables:
            details.append(f"缺少表注释：{missing_tables}")
        if missing_columns:
            details.append(f"缺少字段注释：{missing_columns}")
        raise ValueError("；".join(details))
