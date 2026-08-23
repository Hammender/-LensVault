# 相似簇常驻展示 + 自动整理预览确认

## 背景 / Context

上一轮实现的普通相似自动整理是一键直接永久删除，实际使用暴露三个问题：

1. **簇不可见**：哪些图片构成"肉眼相同簇"、哪张会被保留，界面上完全不展示。
2. **缺少确认**：用户面对大量图片不敢直接点击删除，要求先看预案再执行。
3. **无人值守删除开关风险高**：创建扫描时的"扫描后自动整理"勾选项会绕过一切确认直接删。

用户决策：
- 镜像整理暂不加预览，保持现状；普通相似整理改为"预览 → 确认 → 执行"。
- 肉眼相同簇要**常驻显示**：同簇图片相邻排布、散图放最后，不能只加角标；
  鼓励对相似整理页做一次更清晰直观美观的布局设计。
- 移除创建扫描时的自动整理开关，入口统一放到扫描完成后。

## 总体方案

发布扫描结果时把组内两两分数持久化到新表；读取组列表时由后端按自动整理阈值推导簇结构
（成员带 cluster 标记），前端据此重排组内布局并常驻展示簇；
新增预览端点返回"保留/删除/跳过"预案，前端弹窗确认后调用既有执行端点。

## 现状关键代码 / Reuse

| 位置 | 说明 |
| --- | --- |
| `backend/app/services/similarity.py` `run_scan` 发布段 | `near_scores`/`scene_scores` 已含组内全部两两分数（complete-link 保证组内每对都 ≥ 档位阈值），直接落库即可 |
| `backend/app/services/similarity.py` `select_normal_near_duplicate_auto_delete_photo_ids` | 簇判定 + 重叠跳过 + 保留规则；重构为返回结构化预案 |
| `backend/app/api/gallery.py` `_gallery_similarity_group_read` (~L230) | 组读取组装处，增加簇推导 |
| `backend/app/schemas/similarity.py` | 新响应模型集中处，复用 `GalleryPhotoListItem` |
| `backend/app/models/gallery.py` | 新表模型；`ondelete="CASCADE"` 模式参考 GallerySimilarityGroupMember |
| `backend/app/tools/export_schema_sql.py` | `sql/tables.sql` 由 ORM 元数据生成，勿手改 |
| `backend/tests/test_schema_sql.py` | 校验 tables.sql 与 ORM 一致、中文注释齐全 |
| 启动建表 | `backend/app/lifecycle.py` L779 `Base.metadata.create_all`——新表无需迁移代码 |
| `frontend/src/SimilarityReview.tsx`、`frontend/src/api/gallery.ts` | 页面与请求层 |

## 文件改动 / Files to modify

### 后端

1. **`backend/app/models/gallery.py`**：新增表 `gallery_similarity_group_pairs`
   - 字段：`id`(PK)、`group_id`(FK→groups, CASCADE)、`left_gallery_photo_id`、`right_gallery_photo_id`
     (FK→gallery_photos, CASCADE, left<right 归一化)、`score`(Float)
   - 约束：`uq` (group_id, left, right)；索引 group_id；关系挂到 `GallerySimilarityGroup.pairs`
   - 全部字段中文注释
   - 组被删/图片被删时级联清理（SQLite 外键 PRAGMA 已开启）
2. **`backend/app/services/similarity.py`**
   - `run_scan` 发布组时批量插入两两分数行（near_duplicate 与 same_scene 都存）
   - 重构选择器为 `build_normal_near_duplicate_auto_delete_plan(...) -> list[AutoDeleteClusterPlan]`
     （dataclass：member_ids、retained_id、delete_ids、skip_reason∈{overlap,no_retention,None}），
     原 id 列表函数变成薄包装，端点/后台任务行为不变
   - 新增纯函数 `derive_group_auto_clusters(pair_scores, threshold)`：连通分量 + min/avg 分数，供组读取复用
3. **`backend/app/schemas/similarity.py`**：新增
   - `GallerySimilarityClusterRead`（index、member_photo_ids、min_pair_score、average_pair_score）
   - `GallerySimilarityMemberRead.auto_cluster_index: int | None`（None=散图）
   - `GallerySimilarityGroupRead.clusters: list[...]`
   - 预案模型 `GallerySimilarityAutoDeletePreview{Response,Cluster,Member}`（status: ready/skipped_overlap/skipped_no_retention）
4. **`backend/app/api/gallery.py`**
   - `_gallery_similarity_group_read` 注入簇信息（阈值取 `gallery_similarity_auto_delete_threshold`）
   - 新增 `GET /api/gallery/similarity-scans/{scan_id}/auto-delete-preview`（仅 normal；权限/stale 校验同执行端点）
5. **`sql/tables.sql`**：用生成命令重新导出
6. **契约夹具**：按 `backend/tests/test_contract.py` 的机制同步 `contracts/openapi.json`、`routes.json`（实施时确认其生成方式）

### 前端（引入 frontend-design 技能辅助布局设计）

7. **`frontend/src/api/gallery.ts` + `frontend/src/types.ts`**：预览端点与类型；创建扫描不再发送 `auto_delete_exact_mirror`
8. **`frontend/src/SimilarityReview.tsx`**
   - 删除扫描区的自动整理勾选开关及相关文案
   - 近重复组卡片重构：簇子容器（徽标"几乎完全相同 · n 张 · 簇内最低 xx%"）→ 同簇成员相邻、
     按质量分降序（建议保留者在前）；散图归入末尾"其他相似图片"区
   - 普通相似"自动整理近重复组"按钮 → 拉取预览 → 自定义弹窗（逐簇缩略图条 +
     建议保留/将删除/因重叠跳过徽标 + 合计删除数）→ 确认调既有 POST 执行 → 刷新
9. **对应样式文件**（实施时定位 similarity 样式所在 css）：簇容器、徽标、预览弹窗样式

## 实施步骤 / Steps

- [ ] 1. 模型新增 `gallery_similarity_group_pairs` 表 + 中文注释，重新生成 `sql/tables.sql`
- [ ] 2. `run_scan` 发布时落库两两分数；`cleanup_deleted_similarity_photos` 无需改动（FK 级联）
- [ ] 3. `derive_group_auto_clusters` 纯函数 + 单测（阈值边界、散图 None、多簇排序）
- [ ] 4. 组读取注入 clusters/auto_cluster_index；更新受影响测试
- [ ] 5. 选择器重构为预案构建器（行为回归：现有 3 个自动整理测试仍通过）
- [ ] 6. 预览端点 + schemas；契约夹具同步
- [ ] 7. 前端：移除开关、类型与 API、组卡片簇布局重排
- [ ] 8. 前端：预览弹窗（读 frontend-design 技能后实现样式）
- [ ] 9. 测试：发布落库断言、预览端点用例、权限回归
- [ ] 10. 运行完整后端测试与 `npm.cmd run build`

## 边界行为约定

- 旧扫描结果没有两两分数行 → 组读取时 clusters 为空、全部成员视为散图（不报错）；提示用户可重扫获得簇展示
- 预览与执行使用同一预案构建逻辑，执行前实时重算（防止预览后图库变化导致误删）
- 镜像整理按钮保持一键直删不变
- 创建扫描 API 字段 `auto_delete_exact_mirror` 保留但前端不再发送（后台任务分支保留兼容）

## 验证 / Verification

- `python -m pytest backend/tests`（重点：test_gallery_similarity.py、test_schema_sql.py、test_contract.py、test_permissions.py）
- `cmd /c npm.cmd run build`
- 用户手工验证：跑普通相似扫描 → 组卡片看到簇相邻排布与散图置底 → 点自动整理看预览弹窗 → 确认后删除数量一致
