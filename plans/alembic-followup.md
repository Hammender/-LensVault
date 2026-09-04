# Alembic 收尾：结构对齐迁移 + 删除引导桥接 + 数据迁移转入 Alembic

## 背景

上一轮已引入 Alembic（基线 `0001`，真实库已 stamp）。本任务完成三项收尾（用户确认：项目只部署在这一台机器，本机数据库即全部）：

1. **存量库装饰性漂移**：真实库由旧手工迁移建成，与 ORM 元数据存在结构差异（冗余库级默认值、外键缺失、唯一约束命名不同、`gallery_photos.display_batch_at` 可空性），导致对真实库 `alembic check`/autogenerate 误报。需生成**结构对齐迁移 `0002`**，把真实库改到与元数据完全一致。
2. **删除引导桥接**：真实库已带 `alembic_version`，`ensure_*` 桥接（约 900 行）永不再执行，整体删除，连带清理旧迁移测试。
3. **数据迁移转入 Alembic**：时区基线标记与遗留人脸清理（`app_schema_migrations` 登记表守卫）从启动期移入数据迁移 `0003`；时区转换逻辑对现存库已无意义（本机库已转换、新库无遗留数据），`timezone_migration.py` 与 `migrate_timezone_to_shanghai.py` 工具一并删除。

## 已核实的现状

- 漂移清单（对真实库副本 `alembic check`）分三类：
  - `modify_default`：旧 `ALTER TABLE ADD COLUMN NOT NULL DEFAULT` 强制携带的库级默认值（模型用 Python 端 `default=`，ORM 插入总显式给值）→ 0002 去掉，行为与全新库一致；
  - `add_fk` / `add_index`：旧 ALTER 加的列缺外键（`face_records.workspace_id` 等）与索引 → 0002 补齐（注意：外键补齐后新写入将强制引用完整性，与 create_all 建的库行为一致）；
  - 约束重命名对（`remove_index` + `add_constraint` 同列唯一约束）、`uq_video_items_workspace_filename_size` 旧索引删除、`gallery_photos.display_batch_at` 改 NOT NULL（模型 `nullable=False`，旧启动逻辑已回填过 NULL）。
- 基线 `0001` 无误：模型有 `server_default` 的仅 6 列，与漂移清单不冲突；`alembic check` 对全新库通过。
- `require_timezone_migration` 无外部调用方；`timezone_migration.py` 仅被 lifecycle、`migrate_timezone_to_shanghai.py` 工具、`test_timezones.py` 引用。
- 桥接删除后，`run_database_migrations` 的"存量无版本库"分支改为**仅 `stamp head` + 日志警告**（不再修复；本机唯一库已带版本，此分支实际不会再触发）。
- 涉及删除/改写的测试：`test_acquisition.py`（3 处）、`test_idolxxx_acquisition.py`（1 处）、`test_application.py`（3 个测试）、`test_face_recognition.py`（2 个测试）、`test_gallery_zip_transfer.py`（1 处）、`test_video_types.py`（1 个测试）、`test_ignored_gallery_face_cleanup.py`（改写为迁移测试）、`test_timezones.py`（删除迁移部分）、`test_database_migrations.py`（更新引导语义）。
- 当前后端正在运行（端口 8000）；应用 `0002` 前需停服。

## 实施步骤

- [ ] 1. **真实库体检**：复制最新真实库到临时目录；复核漂移清单；对将新增的每个唯一约束查重复数据、每个外键查孤儿行、`display_batch_at` 查 NULL。有违规数据则先报告并商定回填方案。
- [ ] 2. **生成并审核 `0002`（结构对齐）**：对真实库副本执行 `alembic revision --autogenerate`（唯一一次对存量库 autogenerate），逐行审核修正：合并同表 batch 操作、确认无 drop 误删、补中文说明；在副本上应用 → `alembic check` 无漂移 → 副本前后逐表行数比对 + `PRAGMA foreign_key_check` 干净。
- [ ] 3. **编写 `0003`（数据迁移）**：自包含脚本，带 `app_schema_migrations` 守卫：标记时区基线 key、执行遗留人脸清理 DELETE（本机库两 key 均已存在 → 实际 no-op；全新库 → 标记 + 空删除）。从 `lifecycle.py` 删除这两段启动调用；删除 `timezone_migration.py`、`migrate_timezone_to_shanghai.py`、`test_timezones.py` 中迁移相关部分。
- [ ] 4. **删除桥接**：删除 `apply_legacy_schema_fixups`、全部 `ensure_*`、`_sqlite_*`/`_rebuild_*` 辅助、`cleanup_ignored_gallery_face_records`；`run_database_migrations` 存量分支改为 stamp+警告；清理 imports；`initialize_database` 最终只剩 `run_database_migrations` + `seed_acquisition_scripts`。
- [ ] 5. **测试清理**：删除上列旧迁移测试；改写 `test_ignored_gallery_face_cleanup.py` 为「升级到 0002 → 插入遗留数据 → 升级 head → 断言清理与 key 标记」；更新 `test_database_migrations.py` 引导语义（stamp-only）；为 `0002` 补一个「全新库 upgrade head 全链路 + 无漂移」断言。全量 `pytest backend/tests`，结果与 HEAD 基线比对（当前基线：3 个存量失败）。
- [ ] 6. **应用到真实库**：请用户先停后端 → 用 SQLite backup API 备份真实库（`app.db.before-alembic-0002-<时间戳>.bak`，放在数据库同目录，沿用既有 .bak 惯例）→ `alembic upgrade head`（-x 指向真实库）→ `alembic check` 无漂移 → 行数/外键校验。用户手工重启后端验证功能正常。
- [ ] 7. **文档更新**：AGENTS.md 漂移注意事项改为「0002 已对齐，本地库可直接 `alembic check`；生成脚本仍推荐 `generate_migration` 工具」；（待确认）常用命令中的 `--reload` 同步删除。

## 验证方式

1. 副本库全流程：`alembic check` 无漂移；逐表行数一致；`PRAGMA foreign_key_check` 无孤儿；抽查默认值/约束名已对齐。
2. 全量后端测试通过数不低于 HEAD 基线（262 + 新增），仅剩 3 个已知存量失败。
3. 真实库应用后 `alembic current` = head、`alembic check` 干净、后端启动日志正常（由用户手工启动验证）。

## 待确认

1. 后端当前在运行（端口 8000）。**执行到第 6 步时请先停掉后端**，应用完成后再手工启动。
2. AGENTS.md「常用命令」里的 `--reload` 是否同步删掉（你已自行去掉，文档是否跟随）？
3. `0002` 会去掉旧列上的冗余库级默认值、补外键（新写入强制引用完整性）、删除旧的 `uq_video_items_workspace_filename_size` 唯一索引——均以 ORM 元数据为准，确认接受。
