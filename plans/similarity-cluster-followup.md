# 相似簇展示与自动整理四项修复

## 背景 / Context

上一轮功能上线后用户反馈四个问题：

1. **簇块背景太浅**：`.similarity-cluster-block` 背景 `rgba(79,139,98,0.06)` 不够醒目。
2. **大图模式（PhotoLightbox）顺序不对**：底部组内缩略图条直接用 `previewGroup.members`
   （按质量分排序），没有走簇排序，同簇图片不相邻、也没有簇标记；网格预览是对的。
3. **成簇条件存疑**：出现"簇内相似度最低 94.5%"的三人簇——两张几乎一样，第三张明显不同却被归入同簇；
   而真正和第三张肉眼接近的图反而成了散图。
   根因：簇推导用的是**连通分量**（BFS），存在传递链——A~B=0.99、B~C=0.99 时即使 A~C=0.945 < 0.985，
   C 也会经由 B 进入同一簇；展示的"最低 94.5%"正是这条不达阈值的两两分数。
   自动整理预案构建器（`build_normal_near_duplicate_auto_delete_plan`）用的是同样的连通分量逻辑，
   存在同样的误成簇问题（会误删）。
4. **点击"预览自动整理"后端报错**：`backend/app/api/gallery.py` 预览端点使用了
   `GallerySimilarityGroupMember`（L643-644）但**未导入**，运行时 NameError → 500。

## 方案 / Approach

- **修复 3（核心算法）**：把簇推导从"连通分量"改为**严格完全连接**——簇内每一对两两分数都必须 ≥ 阈值
  才能同簇。直接复用现成的 `complete_link_clusters(member_ids, candidates, threshold)`
  （`backend/app/services/similarity.py`，complete-link 语义完全一致），在
  `derive_group_auto_clusters` 与 `build_normal_near_duplicate_auto_delete_plan` 两处替换 BFS 实现。
  修复后簇内最低/平均相似度必然 ≥ 98.5%，不再出现传递链混簇；被挤出的图片按各自实际分数
  另行成簇或成为散图。读取时推导，**已有扫描数据无需重扫**即生效。
- **修复 4**：补导入 `GallerySimilarityGroupPair` 已在、缺的是 `GallerySimilarityGroupMember`；
  并新增一个直接调用预览端点函数的回归测试，防止此类 NameError 再漏网。
- **修复 2**：灯箱内用与网格一致的顺序渲染缩略图条：由 `buildGroupSections(previewGroup)` 展平得到
  有序成员列表（无簇数据时回退 `previewGroup.members`）；导航（上一张/下一张/序号）全部改用该有序列表；
  缩略图上加簇标记（绿底小徽标显示簇号，散图灰显"散"）。
- **修复 1**：`.similarity-cluster-block` 背景加深至约 `rgba(79,139,98,0.14)`，边框同步加深。

## 文件改动 / Files to modify

| 文件 | 改动 |
| --- | --- |
| `backend/app/api/gallery.py` | 补导入 `GallerySimilarityGroupMember` |
| `backend/app/services/similarity.py` | `derive_group_auto_clusters` 与 `build_normal_near_duplicate_auto_delete_plan` 内的簇推导改为复用 `complete_link_clusters` |
| `frontend/src/SimilarityReview.tsx` | 灯箱缩略图条改用簇排序并加簇标记 |
| `frontend/src/styles.css` | 簇块背景加深；灯箱条簇标记样式 |
| `backend/tests/test_gallery_similarity.py` | 更新链式用例期望；新增传递链不误删用例；新增预览端点回归测试 |

## 复用 / Reuse

- `complete_link_clusters`（services/similarity.py）：严格 complete-link 聚类，签名契合
- `buildGroupSections`（SimilarityReview.tsx）：网格已用的簇排序逻辑，灯箱直接复用
- 测试模式：`tests/support/app_loader.load_test_main` + 直接调用端点函数 +
  `SimpleNamespace(app=SimpleNamespace(state=...))` 伪造 request；
  `module.PERMISSION_FIELDS` 构造带 `can_delete_gallery=True` 的 context（参照 test_permissions.py）

## 实施步骤 / Steps

- [ ] 1. api/gallery.py 补导入 `GallerySimilarityGroupMember`
- [ ] 2. similarity.py 两处簇推导改为 `complete_link_clusters`（候选对只保留 ≥ 阈值的边；结果按规模、最低分降序重排以保持展示一致）
- [ ] 3. 更新测试：
  - 链式用例 `(1,2,.99),(2,3,.99),(1,3,.80)` 期望变为仅 `[(1,2)]`（min .99）
  - 新增预案构建器传递链用例：A-B、B-C 达阈值而 A-C 不达 → 只删 {A,B} 中应删者，C 不动
  - 新增预览端点直接调用回归测试（覆盖权限 context、正常返回结构）
  - 确认现有自动整理 3 用例仍通过（语义不变）
- [ ] 4. 前端灯箱：有序成员列表 + 簇徽标；样式微调背景加深
- [ ] 5. 完整后端测试 + `npm.cmd run build`

## 验证 / Verification

- `python -m pytest backend/tests -q` 全量通过
- `npm.cmd run build` 通过
- 用户手工验证：
  - 点"预览自动整理"不再报错，预案与删除一致
  - 第五组这类混合组中，不同簇互不污染；簇内最低分 ≥ 98.5%
  - 大图模式缩略图条顺序与网格一致，同簇相邻且有簇号标记
