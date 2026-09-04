# 引入 Alembic 数据库迁移，替换启动期手工检查函数

## 可行性评估结论

**可行**，且收益明确：

- 项目已使用 SQLAlchemy 2.0.37 ORM（`Base.metadata`），Alembic 与之原生集成，`revision --autogenerate` 可直接从模型生成迁移脚本。
- 当前 `backend/app/lifecycle.py` 中约 900 行、14 个 `ensure_*` / `cleanup_*` / `_rebuild_*` 函数全部是手写的幂等 schema 检查 + ALTER TABLE + SQLite 表重建逻辑，每次加字段都要追加一段，正是 Alembic 的标准使用场景。
- Alembic 的 `render_as_batch=True`（batch_alter_table）可替代手写的 `persons` / `gallery_photos` 等 SQLite 表重建代码。
- 版本 3.11.15（pictureshow conda 环境）与 Alembic 兼容；当前环境未安装 alembic，需 `pip install alembic`（约 1.15.x），并写入 `requirements.txt`。

## 现状梳理

启动链路：`backend/app/main.py` → `create_app`（`backend/app/application.py` lifespan）→ `initialize_database(engine)`（`backend/app/lifecycle.py` L827）→ 依次执行：

| 类别 | 函数 | 处置 |
| --- | --- | --- |
| 纯 schema 检查 | `ensure_video_seek_columns`、`ensure_video_type_columns`（含数据回填）、`ensure_face_recognition_columns`、`ensure_gallery_similarity_group_columns`、`ensure_similarity_scan_columns`（含数据回填）、`ensure_gallery_display_order_columns`（含回填）、`ensure_gallery_ingest_source_column`（含回填）、`ensure_gallery_photo_size_column` | → 由 Alembic 基线 + 后续迁移脚本取代 |
| SQLite 表重建 | `ensure_workspace_scoped_name_constraints`、`ensure_gallery_photo_type_unique_constraint`、`_rebuild_persons_table` 等 | → Alembic batch 模式取代 |
| schema + 种子数据混合 | `ensure_acquisition_schema`（后半段是 `SCRIPT_REGISTRY` upsert 种子与遗留数据修复） | schema 部分入 Alembic；种子部分拆成独立的启动期 seed 函数保留 |
| 一次性数据迁移 | `migrate_system_timestamps` / `mark_timezone_baseline`（`services/timezone_migration.py`）、`cleanup_ignored_gallery_face_records`（自建 `app_schema_migrations` 登记表） | 本次保留在启动期（带幂等 key，不重复执行）；后续可再转成 Alembic 数据迁移 |
| 运行时维护 | `initialize_runtime` 里的 `ensure_system_tags`、任务恢复、视频 SHA 回补等 | 不动，本来就不属于 schema 迁移 |

`Base.metadata.create_all` 当前承担"全新库建表"职责，改由 Alembic `upgrade head` 从空库建全量表。`sql/tables.sql` 由 `app/tools/export_schema_sql.py` 从 ORM 元数据生成，不受影响，继续作为全量表设计文档。

测试依赖：`backend/tests/` 多处直接调用 `ensure_acquisition_schema` / `ensure_gallery_photo_type_unique_constraint` / `initialize_database`，conftest 用 `create_all` 建测试库（不受影响）。

## 方案

### 1. 安装与目录结构

- `pip install alembic`（pictureshow 环境），`requirements.txt` 追加 `alembic==<实际安装版本>`。
- 仓库根新增 `alembic.ini`；迁移脚本放 `backend/alembic/`（`env.py` + `versions/`），与 `--app-dir backend` / `PYTHONPATH=backend` 的现有习惯一致。
- `env.py` 关键点：
  - `sys.path` 插入 `backend/`，导入 `app.models`（触发全部模型注册 + schema 中文注释）；
  - 数据库 URL **不写入 alembic.ini**，运行时从 `app.core.config.get_settings().database_url` 读取（`.env` 仍是唯一配置来源），CLI 与程序内调用共用；
  - `context.configure(..., render_as_batch=True)`，SQLite 下改约束/删列自动走表重建。

### 2. 基线迁移与存量库引导

- 生成一个 `0001_baseline` 迁移（autogenerate 对空库生成全部 46 张表），代表**当前模型完整 schema**。
- `initialize_database` 重写为：
  1. 若库中无任何表（全新库）→ 程序内执行 `alembic upgrade head` 建全量表；
  2. 若有表但没有 `alembic_version` 表（存量旧库）→ **最后一次**执行现有 `ensure_*` 系列把 schema 补齐到当前状态，然后 `alembic stamp head` 打基线标记；之后启动一律只走 `upgrade head`；
  3. 已有 `alembic_version` → 直接 `upgrade head`。
- 旧 `ensure_*` 函数保留为存量库引导路径（仅旧库首启会执行一次），待确认本地/部署库都已带 `alembic_version` 后，在后续提交中整体删除（届时同步删除对应旧迁移测试）。
- 用户本地 `data/app.db` 属本地状态：首次以新代码启动即自动完成引导 + stamp，无需手工操作；也可以选择手工 `alembic stamp head`。

### 3. 启动期保留逻辑

`initialize_database` 在 Alembic 之外继续调用（均为幂等、带登记 key）：

- 采集脚本种子（从 `ensure_acquisition_schema` 拆出为 `seed_acquisition_scripts`，含遗留源适配逻辑中"每次启动都要保证脚本注册表最新"的 upsert 部分）；
- `mark_timezone_baseline` / `migrate_system_timestamps`；
- `cleanup_ignored_gallery_face_records`。

### 4. AGENTS.md 工作流程更新

- 在「AI Agent 工作准则」新增一条并新增独立小节「数据库迁移工作流程（Alembic）」：
  1. 修改 `backend/app/models/` 后必须执行 `alembic revision --autogenerate -m "中文描述"` 生成迁移脚本；
  2. **Agent 必须逐行审核生成的脚本**：确认没有误删表/列、SQLite batch 重建未丢索引与约束、需要数据回填时用 `op.execute()` 补齐、`downgrade()` 合理、脚本含中文说明；
  3. 审核通过后执行 `alembic upgrade head` 应用迁移（或交付时说明由用户执行）；可用 `alembic check` 验证模型与库无漂移；
  4. 重新生成 `sql/tables.sql`（`$env:PYTHONPATH='backend'; python -m app.tools.export_schema_sql`）并运行受影响测试；
  5. 已应用过的迁移脚本不得修改，只能追加新 revision。
- 同步修订准则第 6 条：表结构一致性来源改为「ORM 模型 + Alembic 迁移脚本 + 生成的 tables.sql」三者一致。

### 5. 测试

- 保留桥接后，`test_application.py` / `test_face_recognition.py` / `test_acquisition.py` 中直接调用 `ensure_*` 与 `initialize_database` 的存量迁移测试保持可用（桥接路径覆盖）。
- 新增测试：全新空库经 `initialize_database` 后 `alembic_version` 存在且表齐全；带旧 schema 的库引导后 stamp 到 head；二次启动幂等不报错。

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `requirements.txt` | 新增 alembic 依赖 |
| `alembic.ini`（新增） | Alembic 配置（不含数据库 URL） |
| `backend/alembic/env.py`、`backend/alembic/versions/0001_baseline.py`（新增） | 迁移环境与基线 |
| `backend/app/lifecycle.py` | 重写 `initialize_database`；拆出 `seed_acquisition_scripts`；`ensure_*` 标注为存量库引导专用 |
| `AGENTS.md` | 新增 Alembic 工作流程章节，修订准则第 6 条 |
| `backend/tests/`（新增/调整） | 迁移引导测试 |
| `.gitignore` | 确认 `alembic_version` 相关无需处理（表在 db 里，不涉及） |

## 实施步骤

- [ ] 1. pictureshow 环境安装 alembic，更新 `requirements.txt`
- [ ] 2. 创建 `alembic.ini` + `backend/alembic/env.py`（settings 取 URL、batch 模式）
- [ ] 3. 对空 SQLite 库 autogenerate 生成并人工审核 `0001_baseline`
- [ ] 4. 重写 `initialize_database`：引导/升级/stamp 三分支；拆出种子函数；保留三段数据迁移调用
- [ ] 5. 新增迁移引导测试，运行完整后端测试（`pytest backend/tests`）
- [ ] 6. 用临时副本库验证：模拟旧库引导、全新库建表、重复启动幂等；`alembic check` 确认无漂移
- [ ] 7. 更新 `AGENTS.md` 工作流程与准则
- [ ] 8. 交付说明：列出改动、用户本地 `data/app.db` 首启自动引导的说明、以及后续删除 `ensure_*` 桥接的计划

## 验证方式

1. 复制现有 `data/app.db` 为临时库，指向它启动 `initialize_database` → 确认 stamp + 无报错；
2. 空临时库 → `upgrade head` 后比对 `sql/tables.sql` 表集合一致；
3. `pytest backend/tests` 全量通过；
4. `alembic check` 输出"No new upgrade operations detected"；
5. 后端启动由用户手工执行验证（遵守仓库约束，Agent 不主动启动服务）。

## 待确认事项（默认按推荐执行，可在评审时批注）

1. **存量库桥接策略**：推荐"旧库首启最后一次跑 `ensure_*` 再 stamp，函数保留待后续删除"；若你倾向直接删除 `ensure_*`、旧库只做 `stamp head`（不再自动修复漏迁移的旧库），请批注。
2. **数据迁移（时区、遗留人脸清理）本次不转入 Alembic**，保持现状以控制改动范围；如希望一并转为 Alembic 数据迁移，请批注。
3. 依赖安装授权：执行 `pip install alembic` 并写入 `requirements.txt`（准则第 5 条要求授权，本次任务隐含需要，请确认）。
