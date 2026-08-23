# 自动整理预览增强：大小警示排序 + 大图查看 + 手动调整

## 背景 / Context

自动整理预览弹窗上线后用户提出两点改进：

1. **文件大小警示**：若某簇内系统建议保留的图片不是该簇文件体积最大的
   （只比文件大小，不看评分），需要在簇栏右侧醒目标识提醒检查，
   并且这类簇要排在弹窗最前面。理由：质量分与体积判断可能不一致，删除前值得人工复核。
2. **弹窗功能欠缺**：目前只能看小图列表——不能点开大图确认是否真的相同，
   也不能手动调整保留/删除对象。全部加上又怕臃肿。

对第 2 点的设计取舍（已定）：两个能力都以轻量方式加入——
- **大图查看**：点击缩略图复用现有 `PhotoLightbox` 在弹窗之上叠加单张原图（无左右导航，Esc/点击关闭）；
- **手动调整**：点击每张缩略图下方的"保留/删除"徽标即翻转状态，不改版面结构；
  确认删除时把最终清单显式提交给执行端点。

关键约束：当前执行端点是**服务端重新计算预案**后删除，前端的任何手工调整都会被忽略。
因此必须给执行端点增加可选的显式删除清单参数，并在服务端做安全校验。

## 方案 / Approach

### 后端

1. 预案响应 `GallerySimilarityAutoDeletePreviewMember` 增加 `original_url`
   （`/api/gallery/photos/{id}/original?v={sha256}`，与 mapper 中的模式一致）。
2. 新增请求模型 `GallerySimilarityAutoDeleteExecuteRequest`：`delete_photo_ids: list[int] = []`。
3. 执行端点 `/auto-delete-exact-mirrors` 支持可选 JSON body：
   - 未传或为空 → 维持现状（normal 重算预案、mirror 走原逻辑）；
   - 传入且 scan 为 normal → 用同一预案构建器**实时重算**，然后校验：
     - 每个 id 必须属于某个 `ready` 簇的成员（跨组重叠/无法定保留图的簇一律不可删）；
     - 每个被触及的簇删除后至少剩余一张（禁止整簇清空）；
     - 校验失败返回 422；通过则精确删除所列图片，计数流程不变。
   - mirror 扫描不接受 body（维持原行为）。

### 前端（SimilarityReview.tsx 预览弹窗）

4. **大小警示**：以系统建议保留图（后端 `retained` 标记）与簇内最大 `size_bytes` 比较；
   不是最大时在簇头右侧显示琥珀色徽标"⚠ 建议保留图非最大文件（最大 xx）"。
   弹窗打开时按"有警示的 ready 簇优先"排定顺序（此后不随点击重排，避免跳动）；
   该簇内任一成员被手动改选后隐藏此警示（已由人工接管）。
5. **手动调整**：每张缩略图下方的徽标变为按钮——点击在 保留↔删除 间翻转；
   规则：仅 `ready` 簇可操作；翻转若会导致该簇没有任何保留图则禁用；
   跳过簇整体不可操作。底部合计删除数实时更新。
6. **大图查看**：点击缩略图打开 PhotoLightbox 单张原图
   （`canGoPrevious/Next=false`，新 backdrop 类 z-index 高于预览弹窗的 120）。
7. 确认按钮提交有效删除清单；为空时禁用（现状语义保留）。

## 文件改动 / Files to modify

| 文件 | 改动 |
| --- | --- |
| `backend/app/schemas/similarity.py` | 预案成员加 `original_url`；新增 `GallerySimilarityAutoDeleteExecuteRequest` |
| `backend/app/api/gallery.py` | 预览端点补 `original_url`；执行端点接受可选 body 并校验显式清单 |
| `frontend/src/api/gallery.ts` | 执行函数带可选 body |
| `frontend/src/SimilarityReview.tsx` | 警示徽标+排序、徽标翻转调整、PhotoLightbox 大图查看 |
| `frontend/src/styles.css` | 警示徽标、可点击徽标态、灯箱高层 backdrop |
| `backend/tests/test_gallery_similarity.py` | 显式清单校验用例；预览 `original_url` 断言 |

## 复用 / Reuse

- `build_normal_near_duplicate_auto_delete_plan`：执行时的实时校验基准（services/similarity.py）
- `PhotoLightbox`（frontend/src/PhotoLightbox.tsx）：支持关闭导航的单张大图展示
- URL 模式 `/api/gallery/photos/{id}/original?v={sha256}`（app/mappers/gallery.py L39）
- 现有琥珀提示样式 `.similarity-preview-skip` 的配色基调

## 实施步骤 / Steps

- [ ] 1. schemas：`original_url` 字段 + `GallerySimilarityAutoDeleteExecuteRequest`
- [ ] 2. 预览端点输出 `original_url`；执行端点解析可选 body、实时重算并校验（越界 422 / 清空簇 422）
- [ ] 3. 契约夹具重新捕获（openapi.json / routes.json）
- [ ] 4. 前端 API 层带 body
- [ ] 5. 弹窗交互：警示徽标与排序、徽标翻转（含"至少保留一张"约束）、大图查看、确认提交清单
- [ ] 6. 样式补充
- [ ] 7. 测试：显式清单合法/越界/清空三例；预览断言更新
- [ ] 8. 全量后端测试 + `npm.cmd run build`

## 边界行为约定

- 手动调整只影响本次确认提交的清单，不会写回扫描结果或影响下次预览
- 执行仍要求 completed 且未过期；预览后图库变化时服务端实时校验兜底
- mirror 整理路径完全不变
- 徽标翻转约束：簇内至少保留一张；跳过簇不可操作

## 验证 / Verification

- `python -m pytest backend/tests -q` 全量通过（含新增校验用例）
- `npm.cmd run build` 通过
- 用户手工验证：预览弹窗中非最大文件的保留图簇带琥珀警示且排最前；
  点击徽标可翻转且合计数联动；点缩略图可看原图；确认后实际删除与清单一致
