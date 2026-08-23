# 普通相似扫描自动整理功能

## 背景 / Context

普通相似扫描的近重复组存在两个落地障碍：

1. **组内混杂**：complete-link 聚类以 `near_threshold=0.92` 传递合并（A~B=0.96、B~C=0.93 连成一组），
   一组大于两张时，往往其中只有两张是肉眼完全一样，其余只是"比较像"，逐组手动清理很费劲。
2. **100% 分数不可达**：近重复分数 = pHash/dHash 汉明相似度均值，≥0.82 时再叠加 ORB 加成
   （`max(perceptual, 0.85 + orb×0.15)`）。JPEG 重压缩等会扰动哈希低位与 ORB 匹配数，
   肉眼相同的两张图分数通常 < 1.0，因此镜像扫描那套 `min_score == 1.0` 的自动删除判据对普通扫描不适用。

目标：为普通扫描提供与镜像整理一致的自动整理能力——一键直接永久删除"肉眼相同"的冗余图片，
组内只相似但不同的图片（散图）不受影响。

## 已确认的需求决策

- 触发方式：一键直接删（A），交互与镜像自动整理完全一致（扫描创建时的开关 + 结果页按钮）。
- 判定标准：沿用现有综合近重复分数，组内两两分数 ≥ **0.985**（可配置，存 `.env`）构成"相同簇"；
  不引入 pHash 距离新标准（它只是现有分数的底层依据）。
- 删除粒度：每个相同簇独立执行"删到剩一张"；未进入任何簇的散图不动。
- 保留规则：与镜像一致——簇内质量分差 ≥ `gallery_similarity_quality_min_margin(3.0)` 时保留最高分者；
  分差不足（close_quality）时保留唯一体积最大者；体积并列则整簇跳过。
- 安全护栏：同一张图出现在多个簇（跨组重叠，源于一张图标注多个人物参与多桶聚类）时跳过相关簇。

## 现状关键代码 / Reuse

| 位置 | 复用点 |
| --- | --- |
| `backend/app/services/similarity.py` `_score_pairs` 内 `near_score` 闭包 | 近重复打分逻辑，需抽取为模块级函数供扫描与自动整理共用 |
| `backend/app/services/similarity.py` `select_exact_mirror_auto_delete_photo_ids` | 镜像自动整理骨架：pending 组过滤、重叠跳过、保留图选择、返回待删清单 |
| `backend/app/services/similarity.py` `choose_quality_recommendation` | 分差判定推荐 |
| `backend/app/models/gallery.py` `GallerySimilarityGroupMember.quality_score / overall_quality_score` | 发布时已落库的质量分，无需重算 |
| `GalleryPhoto.size_bytes` | close_quality 兜底的最大文件判据 |
| `backend/app/api/gallery.py` `/api/gallery/similarity-scans/{id}/auto-delete-exact-mirrors` | 权限（`can_delete_gallery`）、stale 校验、删除与计数流程 |
| `frontend/src/SimilarityReview.tsx`、`frontend/src/api.ts` | 镜像自动整理的前端交互 |

注意：`score_to_representative` 只存了各成员相对代表图的分数，**不包含组内完整两两分数**，
因此自动整理时需按簇内成员两两重新计算近重复分数（特征已缓存于 `GallerySimilarityFeature`，
仅 perceptual ≥ 0.82 的对需要从 MinIO 取原图算 ORB，成本可控）。

## 方案 / Approach

在近重复组内部做高阈值子聚类：组内两两分数 ≥ 0.985 的成员构成连通分量（"相同簇"，size ≥ 2），
每簇按镜像规则选保留图并删除其余；跨簇重叠的簇整体跳过。API 层复用现有自动整理端点，按 scan_type 分发。

## 文件改动 / Files to modify

1. `backend/app/core/config.py`
   - 新增 `gallery_similarity_auto_delete_threshold: float = 0.985`
   - 同步维护本地 `.env` 与 `.env.example` 字段（示例值，不含隐私）
2. `backend/app/services/similarity.py`
   - 把 `_score_pairs` 中的 `near_score` 抽成模块级函数（如 `near_duplicate_pair_score(left_feature, right_feature, load_payload)`），`_score_pairs` 改为调用它，保证打分口径唯一
   - 新增 `select_normal_near_duplicate_auto_delete_photo_ids(db, scan, settings) -> list[int]`：
     - 仅处理 `scan_type == "normal"`、completed、未 stale 扫描的 pending `near_duplicate` 组
     - 组内两两计算近重复分数（读缓存特征 + 按需取原图算 ORB，参考 `get_orb_features` 的 LRU 缓存做法）
     - 分数 ≥ 阈值的边做连通分量，取 size ≥ 2 的簇
     - 汇总所有簇，任一图片出现在多个簇中则这些簇全部跳过（与镜像护栏一致）
     - 每簇保留规则：`choose_quality_recommendation({photo_id: member.quality_score}, gallery_similarity_quality_min_margin)`
       → `recommended` 留最高分；`close_quality` 留唯一最大 `size_bytes`（并列则整簇跳过）；返回其余图片 id
3. `backend/app/api/gallery.py`
   - `auto_delete_exact_mirror_groups` 端点改为按 `scan.scan_type` 分发选择器（mirror→原逻辑，normal→新函数），
     移除"仅支持镜像"的 422 限制；权限与 stale 校验保持不变；URL 不变以减少前端/契约改动面
4. `frontend/src/SimilarityReview.tsx` + `frontend/src/api.ts`
   - 结果页按钮：普通相似已完成且未过期时也显示"自动整理近重复组"，确认弹窗说明规则（阈值、保留策略、护栏）
   - 扫描创建区：普通相似也显示"扫描后自动整理近重复组"开关（后端 `create_gallery_similarity_scan`
     中 `auto_delete_exact_mirror` 仅限 mirror 的校验需同步放开为两种类型均可）
5. `backend/tests/test_gallery_similarity.py`
   - 新增测试覆盖下方验证清单

## 实施步骤 / Steps

- [ ] config 新增阈值字段，同步 `.env` / `.env.example`
- [ ] 抽取 `near_duplicate_pair_score` 共享函数并回归 `_score_pairs`
- [ ] 实现 `select_normal_near_duplicate_auto_delete_photo_ids`（子聚类 + 重叠跳过 + 保留规则）
- [ ] API 端点按 scan_type 分发，放开创建扫描时的类型限制
- [ ] 前端按钮 / 开关 / 确认文案（中文文案）
- [ ] 后端测试补充
- [ ] 运行受影响测试与前端构建

## 边界行为约定

- 组内所有两两分数都 < 0.985（例如恰好只有两张的组）→ 不产生簇，不动
- 散图（不属于任何簇）永不进入删除清单
- 扫描过期（is_stale）或非 completed → 端点 409，同现状
- 自动删除成功后沿用现有流程：`delete_gallery_photos` + `scan.auto_deleted_count += deleted`
  （该计数字段两种类型共用，语义为"累计自动删除"）

## 验证 / Verification

- `python -m pytest backend/tests/test_gallery_similarity.py`（含新增用例）：
  - 混杂组（高相似对 + 一张松散图）：只删对中质量低的一张，散图保留
  - 两两分数均低于阈值：无删除
  - close_quality：保留唯一最大文件；体积并列则跳过
  - 同一图片跨两个簇：相关簇全部跳过
  - 非 normal / 已过期扫描调用被拒绝
- `cmd /c npm.cmd run build`
- 手工验证由用户执行：启动前后端，跑一次普通相似扫描，检查自动整理结果与确认弹窗文案
