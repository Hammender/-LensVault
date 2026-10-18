# 审查报告：LensVault 提交 4f76551「新增图片与视频来源追溯及素材包导入导出」

- 审查时间：2026-10-17（上海时间，UTC+8）
- 审查方式：只读，按 code-review skill 流程。没有改代码、没有提交、没有切分支、没有启动服务。
- 路径约定：`B/` = `backend/app/`，`F/` = `frontend/src/`。行号以当前 HEAD `4f76551` 为准。

## 结论

**发现 0 个严重问题、1 个高危问题、7 个中危问题。建议先修高危的压缩炸弹问题，再合并或部署。**

来源追溯的主体做得扎实。创建人一路传到后台任务；来源表一对一，并且和素材在同一事务里写入；快照经过脱敏；前端用摘要加按需加载，跨工作区读取也被挡住了。Alembic 和 `sql/tables.sql` 一致，对已有数据是安全的。

和设计不一致的主要有三处：
- `plugin_data` 没有保存，换成了插件需要主动提供的新字段 `public_metadata`。
- 待审核期间删掉站点或分类，来源会丢失。
- 回填推定的创建人没有单独标记。

夹带的视频素材包导入有一个可利用的压缩炸弹或磁盘放大问题（高）。导出没有权限和并发限制（中）。

## 范围

- 提交：`git show 4f76551`，共 59 个文件，+3101/−47。
- 后端：`B/api/provenance.py`、`gallery.py`、`videos.py`、`acquisition.py`；`B/services/provenance.py`、`acquisition.py`、`importer.py`、`videos.py`、`telegram.py`、`tasks.py`、`video_transfer.py`、`media_archives.py`；`B/acquisition_adapters/contracts.py`；`B/models/*`（provenance、gallery、videos、tasks、acquisition）；`B/background_tasks.py`、`lifecycle.py`、`dependencies/context.py`、`mappers/*`、`schemas/*`；`B/tools/backfill_media_provenance.py`、`reclassify_legacy_videos.py`。
- 迁移：`backend/alembic/versions/20261017_6c4d9140f96b_新增素材来源快照与视频迁移任务.py`、`sql/tables.sql`。
- 前端：`F/components/MediaSource.tsx/.css`、`VideoTransfer.tsx`、`VideoLightbox.tsx`、`F/hooks/useGallery.tsx`、`F/pages/GalleryPage.tsx`、`VideoPlayPage.tsx`、`VideosPage.tsx`、`F/types/*`。
- 调用方和被调用方也读了：`process_import_batch`、`recover_imports`、`capture_frame`、`_create_video_from_object`、`spool_upload`、`require_context` 和 `ROUTE_PERMISSION_MATRIX`、`get_workspace_object`、站点和分类的删除接口、列表接口的筛选逻辑。
- 参考了调研报告 `/workspace/notes/provenance-survey-20261017.md`。
- 没有审：`docs/` 下的文档改动（只核对了插件规范第 57 行）、`backend/tests/contracts/openapi.json` 的逐行内容（契约测试已通过）。

## 测试与验证

| 命令或方式 | 结果 |
| --- | --- |
| `source .venv/bin/activate && python -m pytest ...` | **跑不了**：`.venv` 里没装 pytest（`requirements-dev.txt` 声明了 `pytest==8.3.4`，但没安装）。按 skill 要求**没有安装依赖** |
| 替代方式：在 `/tmp` 写了一个极简的 pytest 替身和运行器（只实现 `fixture/raises/mark`、`tmp_path`、`monkeypatch`、`conftest.db_session` 和模块内 fixture），`unittest` 用例用标准库执行，设置了 `PYTHONDONTWRITEBYTECODE=1` | 见下面几行 |
| `test_media_provenance.py` | 14/14 通过 |
| `test_video_transfer.py` | 3/3 通过 |
| `test_database_migrations.py` | 7/7 通过 |
| 相关测试：`test_gallery_zip_transfer`(9)、`test_permissions`(7)、`test_gallery_parallel_import`(5)、`test_ignored_gallery_face_cleanup`(1)、`test_application`(1)、`test_acquisition`（unittest，38） | 全部通过。`test_permissions` 里有 1 个参数化用例替身跑不了 |
| 全量 backend（49 个测试文件） | **331 通过，0 失败，21 个替身跑不了**（`parametrize`、`caplog`、`request` 这几类 fixture） |
| 迁移实测：临时 SQLite，先升到 `0014b0f63f70`，插入图片、图片标签、视频、字幕、任务，再升到 head，再降回去 | 各表行数不变；`PRAGMA foreign_key_check` 为空；`gallery_photos`、`video_items`、`tasks` 原有的索引和唯一约束都还在 |
| `export_schema_sql.render_schema_sql()` 与 `sql/tables.sql` 比对，并执行 `verify_schema_sql` | **差异 0 行**，校验通过 |
| 压缩炸弹实测（见 H1） | 204 KB 的 ZIP 导致约 1000 MiB 解压写盘 |
| `frontend: tsc --noEmit -p tsconfig.json` | 通过 |
| `frontend: vitest run` | 144 通过，2 失败（`acquisitionRunForm.test.ts:176`、`utils.test.ts:55`）。这是已知的时区用例失败，和本次提交无关。新组件 `MediaSource` 和 `VideoTransfer` 没有测试 |

清理情况：删除了 `/tmp/rev_shim`、`/tmp/rev_*.txt` 和各个临时数据库目录，测试中生成的临时目录由运行器删除；删除了本次运行产生的 `__pycache__/*.pyc`（已被 gitignore 忽略，属于缓存）。`frontend/node_modules/.vite/vitest/results.json` 是 vitest 自带的缓存，留着没动。`git status` 和审查前一致（`.gitignore`、`docker-compose.yml` 已修改，`scripts/` 未跟踪），`tsconfig.tsbuildinfo` 的哈希没变。

## 一、设计对照

| # | 设计条目 | 状态 | 证据与说明 |
| --- | --- | --- | --- |
| 1 | 图片表、视频表的创建人字段 | 满足 | `B/models/gallery.py:24-25`、`B/models/videos.py:19-20` 新增 `created_by`（外键指向 users，`SET NULL`）和 `actor_name` 快照 |
| 1 | 手动上传、导入记录操作人 | 满足 | 图片上传和图文上传：`B/api/gallery.py:354,384` → `Task.created_by`（`B/services/tasks.py:22-23`）→ `B/background_tasks.py:180-181`；ZIP 导入：`gallery.py:576` → `background_tasks.py:336` → `importer.py:2026`；视频分片上传：`B/api/videos.py:336` → `VideoUploadSession.created_by`（`services/videos.py:101`）→ `:311`；视频素材包：`api/provenance.py:116` → `video_transfer.py:282` |
| 1 | 采集素材记录在待审核区点入库的人 | 满足 | `B/api/acquisition.py:1356` 传入 `actor_id`，在 `services/acquisition.py:1665` 写到批次上；图片入库 `:1808`、视频入库 `:1738`、`_finish_imported` `:2004`、重启恢复 `:2686`，都用批次上的操作人。视频截图入库同样走批次 |
| 1 | 异步任务一路带上操作人 | 满足 | `Task`、`AcquisitionImportBatch`、`VideoUploadSession` 都加了 `created_by` 和 `actor_name`（迁移文件和 `models/*`） |
| 2 | 新建来源表，和图片、视频一对一 | 满足 | `B/models/provenance.py:12-39`：`photo_id` 和 `video_id` 各自唯一，加上 CHECK 约束保证二者只能有一个；`telegram_provenance` 是一对一子表 |
| 2 | 只在入库成功时写入；重复图不写；待审核区不写 | 满足 | `attach_provenance` 在素材 `flush` 之后、同一事务里调用（`importer.py:892`、`videos.py:152,311`、`video_transfer.py:217`），失败会一起回滚（`test_source_and_media_rollback_together`）。重复图：`importer.py:833-842` 提前返回，`_finish_gallery_duplicate` 和 `_finish_video_duplicate` 不写。待审核阶段只把快照写在 `acquisition_run_items.source_snapshot_json`（`acquisition.py:1166,1357`），不进来源表 |
| 2 | 一个素材关联多条采集记录时取最早的 | 满足 | `B/services/provenance.py:225-227` 按 `created_at, id` 升序取第一条 |
| 3 | 通用字段：类型、站点、分类、采集任务、原始地址、采集时间、入库时间 | 满足 | `TEXT_FIELDS`（`provenance.py:22-27`）加上 `acquisition_snapshot`（`:199-215`）。来源类型有 `manual_upload / import / acquisition / video_capture / unknown`（`:20`） |
| 3 | 存快照，删掉站点或分类后来源不丢（外键置空，不级联） | **部分满足** | 来源表里**完全没有**站点、分类、任务的外键，只存名称快照和 `run_id` 字符串，所以已入库素材不会被级联删除。但是：① 和设计写的「外键置空」不一样，没法再关联回现存的站点或分类；② **在待审核阶段删掉站点或分类，run_items 会被级联删除，之后入库时来源只剩 `{"source_type":"acquisition"}`**（见 M2） |
| 3 | Telegram 附属信息 | **部分满足** | `TG_FIELDS`（`provenance.py:28-34`）包含频道或群组、话题编号和话题名、是否评论区、标签、文案摘要（50 字）、`media_type`、`transport_type`、`original_filename`、`message_url`。但 `transport_type` 只有 photo 和 document 两种取值，**分不出「以视频发送」和「以文件发送」**（`telegram.py:1453`，见 M6） |
| 3 | 插件 plugin_data 要存、限大小、过滤凭据 | **不满足（改了方案）** | `plugin_data` 仍然不保存。代码新增了插件可选提供的 `public_metadata`（`contracts.py:127`），会做脱敏，限 16 KiB。插件规范 `docs/采集插件开发规范.md:57` 明确写了「`plugin_data` 继续只用于插件工作流，不会直接复制为公开来源」。现有插件都不会被记录任何附加信息（见 M3）。安全上可以理解，但需要 Hamender 拍板 |
| 4 | 采集代码：补媒体类型和原始文件名、修话题 id、写话题名 | 满足（有副作用） | `telegram.py:1430-1434`：`forum_topic` 时取 `reply_to_top_id`，没有再取 `reply_to_msg_id`，论坛的普通消息取 1；`:996` 用 `messages.GetForumTopicsByIDRequest` 取话题名（Telethon 1.44 有这个接口），并按话题缓存；`acquisition.py:1151-1152` 用分类上的话题名兜底；`:1453-1454` 写入 transport_type 和原始文件名。副作用：评论条目的 `channel_id` 和 `external_key` 变了（见 M5） |
| 5 | 灯箱和详情显示一行「站点 · 分类」；上传或导入显示「手动上传」或「导入」加操作人 | 满足 | `source_summary`（`provenance.py:165-180`）；图片灯箱 `F/hooks/useGallery.tsx:1121`、图库详情 `F/pages/GalleryPage.tsx:933`、视频灯箱 `F/components/VideoLightbox.tsx:495`、视频页 `F/pages/VideoPlayPage.tsx:78` |
| 5 | 点击后在信息栏里原地分层展开 | 满足 | `F/components/MediaSource.tsx:35-41,69-73`：先列通用字段，再分「Telegram 信息」「视频截图」「原始来源（来自导入包）」「更多来源信息」几层 |
| 5 | 接口直接返回摘要、详情按需加载 | 满足 | 列表和详情都带 `source_summary`（`mappers/gallery.py:37`、`mappers/videos.py:74`），关系用 `selectin` 加载，`snapshot_json` 设为 `deferred`（`models/provenance.py:29`）；详情走 `GET /api/gallery/photos/{id}/source`、`/api/videos/{id}/source`（`api/provenance.py:52-58`），只在展开时请求，前端有缓存（最多 200 条） |
| 5 | 所有工作区成员都能看 | 满足 | 两个 GET 都不在 `ROUTE_PERMISSION_MATRIX` 里，只经过 `get_workspace_object` 的工作区校验 |
| 6 | 回填可重复执行、能先试跑出报告 | 满足 | `backfill_media_provenance.py`：默认试跑并输出 JSON 报告（`:120-130`），`--apply-report` 才写入；写入前核对工作区、哈希和创建时间；重复执行不会重复写（`test_backfill_dry_run_and_idempotent_apply_cross_workspace`） |
| 6 | 推定的创建人标成推定值 | **部分满足** | 只有来源记录上 `record_method="backfilled"`（`:69`）。`created_by` 和 `actor_name` 没有任何「推定」标记，摘要显示的「手动上传 · Hamender」和实时记录的完全一样（见 M4） |
| 7 | 不做转发来源、浏览数、相册内顺序、单独的来源详情页 | 满足（但有超范围新增） | 这四项都没做。**超范围**的有：视频素材包导入导出（`video_transfer.py`、`media_archives.py`、`api/provenance.py:62-132`、`VideoExportJob` 表、`VideoTransfer.tsx`、`VideosPage.tsx` 的选择导出）；`reclassify_legacy_videos.py`；`video_items.content_sha256` 以及所有视频去重逻辑的修改（`videos.py:88,130,189`，`acquisition.py:1719,1902`）；`tasks.result_json` |

## 二、按严重度列出的漏洞

### 高

**H1 `B/services/media_archives.py:10-11`、`B/services/video_transfer.py:165,190-199`：视频素材包导入可以被压缩炸弹或磁盘放大攻击（CWE-409 / CWE-400）**
- 问题：单个文件上限 `MAX_FILE = 64 GiB`，总量上限 `MAX_TOTAL = 1 TiB`，实际上等于没限制。总量只统计 `infolist` 里的条目，**清单里的多个视频条目可以重复指向同一个路径**，每个条目都会被完整解压一遍。`size_bytes` 和 sha256 要等**整个文件解压写盘之后**才校验（`:199`）。临时目录用的是系统默认的 `/tmp`（`:163`），不在 `data_dir` 下。上传本身也没有大小限制（`import_spool.spool_upload`）。
- 实测证据：200 MiB 的全零文件压缩后 ZIP 只有 204,216 字节，清单里写 5 个条目指向它，一共解压写盘约 1000 MiB，耗时 3.2 秒，5 条最后全部报「视频文件大小或哈希校验失败」。照这个比例，64 GiB 的条目压缩后大约 64 MB；配上最多 10000 个重复引用，有 `can_add_videos` 权限的成员就能让服务器长时间满负荷读写磁盘，甚至写满磁盘。
- 建议：
  ```python
  info = safe_entry(archive, entry["path"], MAX_VIDEO)          # 改成合理上限，例如 8~16 GiB，或者做成配置项
  if info.file_size != entry.get("size_bytes"):                  # 解压前先比对清单大小
      raise ValueError("视频文件大小与清单不一致")
  if info.filename in used_paths: raise ValueError("清单重复引用同一文件"); used_paths.add(info.filename)
  if info.compress_size and info.file_size / info.compress_size > 200: raise ValueError("压缩比异常")
  ```
  另外：`MAX_TOTAL` 改成按清单实际引用的大小累计，并设一个合理值；临时目录放到 `settings.data_dir/tmp` 下，解压前检查剩余空间；`import-zip` 加上传大小上限。

### 中

**M1 `B/api/provenance.py:62-88`、`B/services/video_transfer.py:44-100`：视频导出没有权限要求、没有并发限制，会在系统临时目录写出完整的大文件**
- 问题：`POST /api/videos/exports` 不在权限矩阵里，任何成员都能调用，包括没有任何权限开关的成员。「导出全部」会把整个工作区的视频写进 `/tmp` 里的一个 ZIP，再上传到对象存储保留 24 小时。每次请求都会新建一个任务并立即开始后台执行，没有「同一工作区只能有一个进行中」之类的限制。重复点几次就能把本地磁盘和 MinIO 一起写满。
- 对比：图库导出原本也没在矩阵里，所以「成员能导出」和现有约定一致；但视频体积大得多。
- 建议：同一工作区只允许一个 `queued/running` 的导出任务，有就返回已有任务；临时文件写到 `data_dir` 下并检查剩余空间；考虑要求 `can_edit_videos` 权限或者新增一个导出权限，请 Hamender 决定。

**M2 `B/services/provenance.py:224-229`，联动 `B/api/acquisition.py:947-953,1051-1055`：待审核期间删掉站点或分类，入库后来源全部丢失**
- 问题：快照存在 `acquisition_run_items.source_snapshot_json` 上，而 run_items 会随着分类或站点的删除被级联删除。素材资产本身还留在待审核区。之后再点入库，`asset_source` 找不到 run_item，只返回 `{"source_type":"acquisition"}`，摘要只显示「采集」，站点、分类、Telegram 信息全没了。这和设计第 3 条「删掉站点或分类后来源不丢」相违背。
- 场景：采集一批图，还没审核完就删掉了这个分类，剩下的图入库后都没有来源。
- 建议：采集时把「最早来源快照」也冻结在 `AcquisitionAsset` 上（新增一个字段，第一次写入后不再覆盖）；或者删除分类前检查有没有待审核素材并提示。补一条「删除分类后再入库」的测试。

**M3 `B/services/acquisition_adapters/contracts.py:127`、`docs/采集插件开发规范.md:57`：plugin_data 没有保存，和设计不一致**
- 问题：设计要求保存 `plugin_data`，限制大小并过滤凭据。代码改成了插件可选提供的 `public_metadata`，现有插件一律什么都不存。另外，插件如果把 `public_metadata` 传成非对象类型，`public_metadata()` 会抛 `ValueError`，整条条目被判为无效，可能导致这一条采集失败（待确认插件侧怎么处理这个错误）。
- 建议：请 Hamender 二选一。A：接受 `public_metadata` 方案，把设计改掉；B：按原设计，把 `plugin_data` 经过 `_public()` 脱敏、限 16 KiB 后存进快照。另外，非对象类型的 `public_metadata` 应该丢弃并记一条警告，而不是让整条条目失败。

**M4 `B/tools/backfill_media_provenance.py:44-58,97-104`、`B/services/provenance.py:165-180`：回填推定的创建人没有单独标记**
- 问题：旧图片一律记成 `--photo-user-id` 指定的人，旧视频记成工作区唯一的管理员，但 `created_by` 和 `actor_name` 上都没有推定标记。摘要显示的「手动上传 · Hamender」和实时记录的完全一样，用户只有展开详情看到「记录方式：历史回填」才知道。采集来的旧图也会被记成指定的这个人。
- 建议：来源表加一个 `actor_inferred`（布尔值），或者把 `record_method` 细分成 `backfilled_inferred`；`source_summary` 和前端对推定值加上「（推定）」。

**M5 `B/services/telegram.py:1424-1427,1072`：评论条目的 channel_id 和 external_key 变了，增量采集会把历史评论当成新条目**
- 问题：`_record` 现在用消息实际所在的会话 id（讨论组）替换 `channel_id`，而 `_emit_comment_media` 用 `record['channel_id']` 拼 `external_key`。以前评论的键是「广播频道 id:评论 id:1」，现在变成「讨论组 id:评论 id:1」。升级后第一次增量采集，已采过的评论会被当成新条目重新下载，再在素材层判为内容重复，同时生成一批新的 source_item 和 telegram_message 行。另外评论的 `channel_title` 会变成空，原频道标题也没有存下来（只有 `root_channel_id` 和 `root_channel_username`）。
- 建议：评论的 `external_key` 继续用原广播频道 id，讨论组 id 另外存一个字段（比如 `discussion_peer_id`）；补上 `root_channel_title`。至少要在发布说明里写明会有一次性的重复下载。

**M6 `B/services/telegram.py:1453`：transport_type 分不出视频和文件**
- 问题：取值是 `"photo" if message.photo else "document"`。在 Telegram 里，以视频发送的消息底层也是 document，所以「以视频发送」和「以文件发送的视频」都会记成 document，达不到设计要的「照片、视频还是 document」。
- 建议：按 `message.photo` → photo、`message.gif` → animation、`message.video`（document 带 `DocumentAttributeVideo`）→ video、其余 → document 来分；前端的 `values` 映射也同步加上。

**M7 测试缺口**
- 没有测试的：压缩炸弹、清单 `size_bytes` 不一致、重复路径；导出接口的权限和并发；待审核期间删分类再入库（M2）；`GetForumTopicsByIDRequest` 取话题名和失败兜底；评论 external_key 是否兼容旧数据（M5）；前端 `MediaSource` 和 `VideoTransfer` 一个测试都没有。
- 建议：至少给 H1、M1、M2 补后端用例。

### 低

- **L1 `B/services/video_transfer.py:213-227`**：素材包导入会新建 `VideoPerson` 和分类标签，只需要 `can_add_videos`，而直接新建人物（`POST /api/video-people`）需要 `can_edit_videos`。这是轻微的权限绕过。建议导入时只关联已有人物，或者校验 `can_edit_videos`。
- **L2 `B/services/provenance.py:88`**：快照超过 64 KiB 时直接抛 `ValueError`。采集时会导致这一条失败，入库时会导致这一条入库失败。现实中很少触发（Telegram 文案有长度上限），但走插件版 Telegram 时字段长度不受控制。建议对超大字段截断，而不是让整条失败。
- **L3 `B/api/gallery.py:491`**：图库 ZIP 导出时，每张图调用一次 `export_source`，会触发 `snapshot_json` 的延迟加载和 telegram 的懒加载，每张图多 2 次查询，大图库导出会变慢。建议导出查询时 `undefer` 并预加载 `telegram`。
- **L4 `B/services/provenance.py:221`**：本次提交之前生成的旧截图（`capture_metadata_json` 里没有 `provenance`），回退时只取 `source_message_url`，不会沿着 `video_asset_id` 找原视频的 run_item，所以拿不到站点和分类。
- **L5 `B/services/video_transfer.py:51,251`**：导出只排除了 `processing` 状态，`processing_failed` 和 `uploaded` 的视频也会导出；导入时直接标成 `ready`，不做 faststart 优化。导出的源文件如果不是优化过的版本，导入后播放可能不正常。
- **L6 `B/services/video_transfer.py:104-111`、`api/provenance.py:84,94,101`**：过期导出只在调用相关接口或重启时清理，没人访问时，过期 ZIP 会一直占着存储；GET 请求里还会顺带改其他工作区的数据。
- **L7 `B/services/provenance.py:21`**：凭据过滤只按字段名做正则，`auth`、`key`、`sig`、`jwt` 这类名字匹配不到；值的检查也只认 `Bearer` 和 `password=` 这几种格式。插件文档要求 `public_metadata` 本身就是公开数据，所以风险低。
- **L8 `F/pages/VideosPage.tsx:395`**：新加的 `.video-export-selection` 没有对应的 CSS，每张视频卡片上都会多出一行「选择导出」复选框。实际界面效果**待确认**（这次不能启动服务）。
- **L9 迁移的 `downgrade()`**：降级会删掉 `media_provenance` 和 `telegram_provenance`，来源数据就没了，这本身是预期行为。另外升级时 SQLite 会用 batch 方式重建 `gallery_photos`、`video_items`、`tasks`、`acquisition_import_batches`、`video_upload_sessions`，大库启动时会多花一些时间。建议升级前先备份 `app.db`。

### 核对过、没有发现问题的地方
- 跨工作区读取来源：`get_workspace_object` 会校验工作区（`api/provenance.py:52-58`，`test_source_read_denies_other_workspace`）；`asset_source` 用 `AcquisitionRun.workspace_id == asset.workspace_id` 过滤（`provenance.py:226`）；导出时按工作区重新校验（`video_transfer.py:49`）；下载会校验工作区并检查过期时间。
- 注入：都用 ORM 参数化，LIKE 只是通配符语义，不构成注入。XSS：链接只允许 `http/https/tg` 三种协议（后端 `public_url` 加前端 `isLink` 正则），其他内容都按文本渲染。
- 路径穿越（zip slip）：导入不会按压缩包里的路径解压到磁盘；`safe_entry` 拒绝 `..`、绝对路径、反斜杠、冒号和加密条目；临时文件名用的是「序号加后缀」。
- 凭据泄露：Telegram 的 `sender_*` 和 `access_hash` 不在白名单里；URL 会去掉 userinfo 和敏感的查询参数。
- 迁移：Alembic 和 ORM 没有差异（`test_fresh_database_upgrade_head_has_no_alembic_drift`），`tables.sql` 和 ORM 的差异是 0。Alembic 的 env 用的是自己的引擎，没有打开 `foreign_keys`，所以 batch 重建表时不会触发级联删除，实测子表数据都保留了。
- 并发：`media_provenance` 上的唯一约束能挡住重复写入；同一个素材包被并发导入时，第二次会撞上 `uq_video_items_workspace_sha256`，被捕获后记为一条错误，不会产生重复数据。

## 三、夹带功能专节：素材包导入导出（超出设计范围）

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| zip slip | 没有问题 | 不按条目路径落盘；`safe_entry`（`media_archives.py:14-22`）拒绝 `..` 和绝对路径；图库导入也改成走 `safe_entry`（`importer.py:1955`） |
| 压缩炸弹 | **高（H1）** | 上限是 64 GiB / 1 TiB；清单可以重复引用同一个文件；解压完才校验大小；实测 204 KB 的包解压出约 1 GB |
| 跨工作区导出 | 没有问题 | 导出选择按 `current.workspace_id` 过滤（`api/provenance.py:64`）；任务和下载都校验工作区；对象键在 `workspaces/{id}/video-exports/` 下 |
| 权限 | **中（M1）和低（L1）** | 导入要求 `can_add_videos`（`context.py:93`）；导出、导出列表、导入列表、下载只要求是成员；导入能顺带新建人物和分类 |
| 大文件内存 | 基本没有问题 | 导出按 1 MiB 分块流式写（`video_transfer.py:23-35`），导入也是分块流式解压；封面限 20 MiB、字幕限 10 MiB 读进内存；图库 ZIP 每张图最多 128 MiB 读进内存（沿用原有行为）。主要风险在**磁盘**（H1、M1），不在内存 |
| 其他 | 低（L5、L6） | 导入后直接标为 ready；过期清理依赖接口调用 |
| 测试 | 有缺口（M7） | 现有 3 个用例覆盖了往返导出导入、旧视频按内容哈希去重、损坏条目回滚 |

## 未核实项

1. 全量 pytest 没能用官方方式运行：环境里没有 pytest，我也没有安装。用替身运行器跑了 331 个用例，全部通过；另有 21 个参数化、`caplog` 一类的用例没覆盖到。要确认，需要先 `pip install -r requirements-dev.txt`，再跑 `python -m pytest backend/tests -q -p no:cacheprovider`。
2. 话题名接口 `messages.GetForumTopicsByIDRequest` 在真实论坛群里能不能拿到话题名，评论 external_key 变化对已有数据的实际影响（M5）：需要用 Hamender 的真实 Telegram 账号和数据验证。
3. 插件把 `public_metadata` 传成非对象类型时，是只跳过这一条，还是整页或整次采集失败：需要看插件运行器的错误处理，或者用插件实测。
4. 前端界面效果，包括信息栏里来源那一行的排版、视频卡片上「选择导出」的样式：这次不能启动服务，没有看界面。
5. 在真实大库上执行迁移要多久、回填报告的结果如何：真实数据在 Hamender 的 Windows 机器上，云电脑上的库只是测试数据。
