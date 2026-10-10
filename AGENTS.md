# 仓库开发指南

## 项目结构与模块组织

`backend/` 包含 FastAPI 后端服务。主要 API 路由位于 `backend/app/main.py`，配置位于 `backend/app/core/config.py`，数据库初始化位于 `backend/app/db.py`，领域逻辑位于 `backend/app/services/`。数据库结构迁移由 Alembic 管理：根目录 `alembic.ini` 为配置入口，迁移脚本位于 `backend/alembic/versions/`（当前全量基线为 `364bf17881ef`，后续增量迁移以 `down_revision` 串联），迁移环境 `backend/alembic/env.py`，迁移脚本生成工具 `backend/app/tools/generate_migration.py`。`frontend/` 包含 Vite + React 前端，入口文件为 `frontend/src/main.tsx` 和 `frontend/src/App.tsx`。前端通用请求与类型定义位于 `frontend/src/api/` 和 `frontend/src/types/`。

常用手工命令：

```powershell
python -m uvicorn app.main:app --app-dir backend
cmd /c npm.cmd install
cmd /c npm.cmd run dev
cmd /c npm.cmd run build
```

提交前端改动前必须运行 `npm.cmd run build`，该命令也会执行 TypeScript 项目构建。运行依赖 MinIO 和 Qdrant，`.env` 的字段应与 `.env.example` 对应。

## 运行环境

当前项目默认运行环境是名为 "pictureshow"的Conda环境。

## 代码风格与命名规范

遵循现有代码风格：Python 使用 4 个空格缩进，TypeScript/TSX 使用 2 个空格缩进，前端文件使用双引号。Python 模块和服务文件使用 `snake_case`；React 组件、Pydantic 模型和 SQLAlchemy 模型使用 `PascalCase`。优先使用小型辅助函数，避免在路由处理函数中出现过深嵌套。除非周边界面已使用英文，前端面向用户的文案应使用中文。

## 测试规范

后端自动化测试位于 `backend/tests/`。后端改动应运行受影响的测试；涉及通用行为时运行完整后端测试。前端改动应运行 `cmd /c npm.cmd run build`，并在浏览器中手工验证修改流程。新增前端测试应放在 `frontend/src/` 下、靠近对应功能的位置；新增后端测试应放在 `backend/tests/`。

## 提交与合并请求规范

提交信息使用清晰的祈使句，例如 `新增集群重分配校验`。每个提交应聚焦一个功能或修复。合并请求应包含简短说明；若 `.env` 或 MinIO 行为有变化，应说明配置或迁移步骤。

## 配置与数据说明

不得将 `.env` 中的真实密钥提交到仓库。新增配置时应同步维护 `.env.example`。避免提交生成数据、模型下载文件或 `data/` 中的本地数据库改动。

配置变更必须优先维护本地 `.env` 的完整字段和值。程序运行时只读取 `.env`，不得读取 `.env.example`；`.env.example` 仅保留完整字段名与不泄露隐私的示例默认值。

## 数据库迁移工作流程（Alembic）

数据库结构变更一律通过 Alembic 迁移脚本完成，不再手写启动期检查/ALTER 函数。启动时 `app.lifecycle.initialize_database` 会自动执行 `alembic upgrade head`。空库从全量基线建表；无 `alembic_version` 的存量库仅登记到 head，不会自动补齐结构，必须先人工核对。任何 Agent 修改了 `backend/app/models/` 下的表结构后，必须走以下流程：

1. **生成迁移脚本**（基于临时空库 autogenerate，与真实库隔离；工具使用系统临时目录，结束或异常退出时自动清理）：

   ```powershell
   $env:PYTHONPATH='backend'
   python -m app.tools.generate_migration "新增视频封面对象键"
   ```

2. **AI 自审迁移脚本（必做，不得跳过）**：逐行阅读 `backend/alembic/versions/` 下新生成的脚本，确认：
   - 只包含本次模型改动，没有误删表/列/索引（尤其警惕 autogenerate 生成的 `drop_` 操作）；
   - SQLite 下修改约束/列走 `batch_alter_table`（表重建），未丢失既有索引、外键和默认值；
   - 存量数据需要回填时，用 `op.execute()` 补齐并核实回填条件；
   - `downgrade()` 与 `upgrade()` 对称且可回退；
   - 文件头说明为中文，描述变更内容与影响。发现问题时直接修正脚本后再进入下一步。

   常规表结构变更以逐行审查为主，不要求每次额外创建数据库或执行完整的升级、回退、再次升级演练。仅在审查无法确认数据保留、回填结果或数据库兼容性时，针对具体疑点做最小范围的隔离验证；使用少量构造数据，不复制真实全库。涉及大表操作时，根据实际操作评估锁持有时间和额外空间。

   生成或验证使用的临时数据库、日志及其他临时产物必须放在系统临时目录，通过 `TemporaryDirectory` 或 `try/finally` 管理；正常结束和异常退出均先关闭连接，再自动清理。不得遗留到仓库或 `data/` 下；用户明确要求保留的审查产物除外。

3. **应用迁移**：确认迁移链只有一个 head、本机当前 revision 已知且存在待执行迁移，再执行：

   ```powershell
   python -m alembic upgrade head
   ```

   若任务约束不允许直接改库（如仅出代码），则交付时明确说明由用户手工执行本命令。

4. **同步全量表设计文件**并验证：

   ```powershell
   python -m app.tools.export_schema_sql
   python -m pytest backend/tests
   ```

注意事项：

- 已应用过的迁移脚本不得修改，只能追加新 revision。
- 更新数据库到 head 后，执行 `python -m alembic check` 验证与 ORM 无漂移。生成新迁移脚本仍推荐用 `generate_migration` 工具（基于临时空库，不依赖真实数据）。
- 旧库的 `app_schema_migrations` 表保留历史审计记录，当前 ORM 不管理它；Alembic 结构比较明确忽略此表，不生成删表操作。
- 跨电脑拉取后，先执行 `python -m alembic heads` 和 `python -m alembic current` 核对迁移链，确认只有一个 head 且无重号或缺失 revision。当前版本已是 head 时无需升级；存在待执行迁移时，确认脚本已完成审查，再升级并执行结构检查。已完成审查并随代码交付的迁移不要求各设备重复做隔离演练。
- 数据库备份不作为拉取、只读检查或常规 Alembic 迁移的前置步骤，不得自动创建全库备份；仅在用户明确要求备份时执行。迁移的安全性、准确性和可靠性应在脚本生成和审查阶段落实，存在具体疑点时补充针对性验证。涉及删表、删列、不可逆数据转换等可能丢失数据的操作时，先说明具体影响并取得用户明确授权，不得通过自动备份替代授权。用户要求备份 SQLite 时，WAL 模式下使用 SQLite 备份接口生成一致性快照，不能只复制正在使用的主数据库文件。
- 当前全量基线已替代旧的 `0001`、`0002`、`0003`、`dde49fc544b6` 及同 revision 的旧分类策略脚本。遇到本机未跟踪的旧脚本时，保存在 `data/` 下再移出 `versions/`，不能把两套迁移历史混用。数据库引用未知 revision 时，先核对历史，不得直接 stamp head 跳过迁移。
- 新增迁移脚本必须纳入 Git，与模型和 `sql/tables.sql` 一起交付；提交前检查 `git status --short`，避免迁移脚本仍为未跟踪状态。
- `alembic.ini`、`backend/alembic/env.py`、`script.py.mako` 及 `versions/*.py` 属于共享源代码，必须由 Git 管理；公共配置不得保存本机数据库路径或凭据。实际连接串保留在各设备的 `.env`。`.env.example` 仅同步字段和非敏感示例，数据库、缓存和 `data/` 备份不纳入 Git。
- 多设备同时新增迁移出现多个 head 时，保留双方迁移，审核结构冲突后新增 Alembic merge revision 并提交；不能删除或改写已应用的 revision，也不能用 stamp 掩盖分叉。尽量先拉取最新迁移历史，再生成本次迁移。
- 迁移环境 `backend/alembic/env.py` 从 `.env` 读取数据库连接串，也可用 `alembic -x database_url=...` 指向其他库；`alembic.ini` 保持 ASCII 内容（它按系统 locale 编码读取）。
- 启动命令不加 `--reload`：涉及模型/迁移的改动若被自动热重载，可能在半成品代码上对真实库执行迁移。

## AI Agent 工作准则

1. 先阅读与任务直接相关的代码、配置、文档和当前 Git 状态，再实施改动；不根据文件名或历史印象臆测实现细节。
2. 改动应保持最小且聚焦。除非任务明确要求，不进行无关重构、格式化全仓库文件、升级依赖或修改生成文件。
3. 工作区中已有的未提交改动默认属于用户或其他协作者。不得撤销、覆盖、暂存或混入这些改动；若其与当前任务冲突，应说明冲突并请求处理方向。
4. 不执行可能造成数据丢失的操作，例如递归删除、清空数据库、强制重置 Git、覆盖配置或批量迁移。确有必要时，先核实目标范围、说明影响并取得用户明确授权。
5. 仅在任务确有需要且用户已授权的范围内安装、升级或卸载依赖。安装后应将依赖声明同步到对应的依赖清单，并说明实际变更。
6. 数据库表结构的一致性来源为「ORM 模型（`backend/app/models/`）+ Alembic 迁移脚本（`backend/alembic/versions/`）+ 生成的 `sql/tables.sql`」三者一致。新增或修改表、字段、索引、约束时，必须按「数据库迁移工作流程（Alembic）」生成并审核迁移脚本，同步补充中文注释，并重新生成全量表设计文件。
7. 修改 API、配置、数据结构或前端交互时，应追踪调用方和受影响流程，避免只修改单一入口而破坏兼容性；无法兼容时明确写出迁移要求。
8. 代码改动完成后，按改动风险运行必要的构建、测试或静态检查。因环境、权限或时间无法执行的检查，必须在交付说明中明确未执行项与原因。
9. 最终说明应简要列出改动内容、涉及的配置或迁移、验证结果及仍需用户手工操作的事项；不得声称未实际完成的验证或运行结果。

## 约束

1. 未经用户明确授权，运行过程中不能主动启动前端或后端程序；启动程序由用户手工执行。
2. 编写文档时使用中文，不使用英文。
3. 未经允许，不得执行 Git 提交、合并等会修改仓库历史或分支状态的操作。
