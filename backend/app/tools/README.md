# 工具脚本目录

本目录下的 Python 文件都可以通过 `PYTHONPATH=backend python -m app.tools.<脚本名>` 独立运行。它们不是启动时自动执行的后台任务。运行前先查看 `--help`，并确认数据库、Qdrant 和 MinIO 的目标环境。

## 人脸识别与迁移工具

| 脚本 | 作用 | 是否写入数据 |
| --- | --- | --- |
| `evaluate_face_recognition.py` | 根据明确的人工纠正记录评估识别阈值。 | 否 |
| `evaluate_face_profiles.py` | 对比普通中心、质量加权中心、稳健中心等样本向量策略。 | 否 |
| `evaluate_gallery_corrections.py` | 用真实图库人工纠正样本评估检测尺寸和识别配置。 | 否 |
| `evaluate_unknown_gallery.py` | 对现有未知图库做新配置候选评估。 | 否 |
| `evaluate_small_face_strategies.py` | 离线比较 AdaFace 小脸识别策略。 | 否 |
| `calibrate_adaface_migration.py` | 独立校准 AdaFace 阈值和 margin，并检查错认门槛。 | 否 |
| `summarize_face_experiments.py` | 汇总隔离实验报告。 | 否 |
| `rebuild_face_index.py` | 从样本图片重建版本化 Qdrant 人脸索引，可生成中心向量。 | 写 Qdrant；使用参数不当时可能替换目标集合 |
| `rerecognize_gallery.py` | 对图库图片重新检测、生成向量并更新人脸记录和人物标签；支持预演、审计、恢复。 | 预演只写审计文件，`--apply` 写 SQLite，查询阶段读取 Qdrant |
| `backup_face_migration.py` | 创建 SQLite 一致性备份、表计数和逐图快照。 | 写备份文件，不改源数据库 |
| `verify_face_migration.py` | 对照迁移前备份核验人脸迁移、标签、图片字段和样本资产。 | 否 |
| `analyze_face_migration_audit.py` | 汇总全图库迁移审计并检查迁移门禁。 | 否 |
| `build_face_review_pack.py` | 生成 AdaFace 人工抽查清单。 | 写抽查文件，不改数据库 |
| `build_migration_change_review.py` | 从迁移审计中生成已知人物变化对照表。 | 写对照文件，不改数据库 |
| `restore_legacy_auto_bindings.py` | 按迁移前快照恢复指定图片的旧自动人物绑定。 | 写 SQLite；使用前必须有备份 |
| `reconcile_gallery_person_tags.py` | 按迁移前标签和当前 AdaFace 人脸结果，对全图库人物标签分类重整。 | 预演只写报告，`--apply` 写 SQLite |
| `verify_gallery_tag_reconcile.py` | 核验标签重整计划与当前数据库逐图一致性，并检查临时调试人物是否绑定人脸。 | 否 |
| `summarize_gallery_rerecognition.py` | 按迁移冻结快照汇总新人脸模型对全图库的重构效果。 | 否 |
| `cleanup_debug2_spurious_jenny.py` | 清理临时调试人物2队列中新模型误加的金珍妮-Jenny 标签和对应人脸。 | 预演只写报告，`--apply` 写 SQLite |
| `restore_debug1_legacy_tags.py` | 把临时调试人物1 图片中已知集合未变的图整份复原为 AdaFace 迁移前人物标签；已知集合已变的图整张保留。 | 预演只写报告，`--apply` 写 SQLite |

## 通用、数据库和资源工具

| 脚本 | 作用 | 是否写入数据 |
| --- | --- | --- |
| `diagnose_face_match.py` | 输出单张人脸匹配诊断信息。 | 否 |
| `backfill_gallery_photo_sizes.py` | 回填展示图库文件大小字段，支持预演和恢复。 | `--apply` 写 SQLite |
| `cleanup_gallery_zip_import.py` | 清理旧 ZIP 导入造成的错误未知人物数据。 | 会写 SQLite，使用前必须确认范围 |
| `export_schema_sql.py` | 从 ORM 元数据导出全量表设计 SQL。 | 写 `sql/tables.sql` 等文件，不改数据库 |
| `generate_migration.py` | 基于临时空库生成 Alembic 迁移脚本。 | 写迁移文件，不改真实数据库 |
| `migrate_catchpics_history.py` | 将 catchPics 旧资源复制到采集待审核区。 | 写目标资源，不修改旧目录 |

## 本轮算法改进

最近两次提交分别完成了：质量加权/离群样本降权的中心向量实验基础，以及翻转增强、阈值校准、真实纠正集评估和历史图库重识别支持。随后工作区执行了 AdaFace IR-101 迁移：识别模型从 `buffalo_l` 更换为 AdaFace IR-101，输出仍为 512 维；样本库和查询侧同时启用水平翻转增强；使用独立校准后的阈值和 margin；新建版本化 Qdrant 集合并重建样本向量；全图库重新识别后又按迁移前快照重整图片人物标签。

## 文件保留建议

建议加入 Git：本目录脚本、配套测试、`docs/人脸识别优化实施与测评说明.md`、本 Wiki，以及不含真实密钥的 `.env.example`。这些是可复现的代码和操作说明。

不建议加入 Git：`data/` 下的 SQLite 备份、逐图 JSONL 审计、人工抽查包、校准中间结果和迁移报告中的本机绝对路径；它们包含本地数据、可能很大，且部分内容属于运行时状态。需要长期归档时放在备份介质或受控对象存储中。

可以删除的临时产物：确认不再需要复盘后，可删除 `data/face-migration/` 中的 dry-run JSONL、sandbox-denied 输出、重复校验输出和实验中间目录；删除前应至少保留最终迁移报告、最终核验 JSON、逐图快照以及一个可回滚的迁移前 SQLite 备份。

不建议删除的资产：`data/face-migration/pre-migration-20260908/app-before.db`、`pre-tag-reconcile-20260909/app-before.db` 及对应快照；当前 AdaFace Qdrant 旧集合和活动集合；AdaFace 模型文件。它们分别用于回滚、标签恢复、结果审计和重新部署。数据库备份和模型文件不应提交到 Git。

删除或重建 Qdrant 集合前，必须确认 `.env` 中的活动集合名称、备份可读且已经完成核验。任何带 `--apply`、`--replace` 或清理语义的工具，都应先执行 dry-run 并保留输出。
