from __future__ import annotations

from app.db import Base
from app.tools.export_schema_sql import DEFAULT_OUTPUT_PATH, render_schema_sql, verify_schema_sql


def test_all_tables_and_columns_have_chinese_comments() -> None:
    for table in Base.metadata.tables.values():
        assert table.comment
        for column in table.columns:
            assert column.comment, f"缺少字段注释：{table.name}.{column.name}"


def test_checked_in_schema_sql_matches_orm_metadata() -> None:
    sql_text = render_schema_sql()

    assert DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8") == sql_text
    verify_schema_sql(sql_text)
