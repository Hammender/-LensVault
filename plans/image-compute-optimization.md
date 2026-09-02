# 图像计算有界并行（待审核删除/导入 CPU 飙升）

## Context

CPU 飙升发生在采集**完成之后**的待审核区：删除图片、导入图库。这两步在用户看来几乎没有计算量，却能把 20 逻辑核打满。采集下载过程不是当时的问题。

Codex 的第一刀是 `cv2.setNumThreads(1)`，CPU 明显下降，但把所有 OpenCV 算子都单线程化，吞吐无谓变差，不能作为最终方案。

根因（对照当前代码）：

1. **导入图库**：`AcquisitionService.process_import_batch()` 逐张调用 `import_gallery_photo()`，未预计算识别计划，内部 `_recognition_plan()` → `FaceService.detect_faces()`。本机人脸是 CUDA，但 InsightFace 预处理仍走 OpenCV（`cv2.resize`、`blobFromImage`）。会话未设 `SessionOptions`，OpenCV 默认按逻辑核起线程。一张图的预处理就能占满 CPU。旋转备选还会把检测再跑多遍。
2. **删除后列表补位**：`reject_assets()` 本身只删对象和改状态。前端去掉已删项后会加载后续图片，并发打 `/assets/{id}/preview`。每张都从 MinIO 拉原图再 PIL 解码缩放。已有 `_preview_render_slots = BoundedSemaphore(2)`（当前工作区），需要保留并收到统一入口，不要再叠一套池。
3. **不是 GPU 调度问题**：DINOv2 已是 `batch_size=32` 的同步批推理；采集导入路径根本不跑 DINO。为人脸/DINO 做 CPU/GPU 四种组合调度，复杂度高、对这次故障几乎没有收益。

未提交改动必须保留在其上继续改，不得撤销覆盖：

- `backend/app/api/acquisition.py`
- `backend/app/db.py`
- `backend/app/services/acquisition.py`
- `backend/app/services/similarity.py`
- `frontend/src/AcquisitionCenter.tsx`

## Approach

只做三件事：封顶原生线程、限制预览并发、导入路径一次解码。不管人脸/DINO 的 GPU 推理，不建优先级/老化/GPU 队列。

1. 启动时把 OpenCV / OpenBLAS / ONNX（含 InsightFace **检测**会话）钉到每库 4 线程，之后禁止再改。用 4 替换 `setNumThreads(1)`，不要改回 1。
2. 预览继续最多 2 路；导入人脸保持现有串行。可选：`detect_faces` 外包信号量 2，`DinoV2FeatureExtractor.encode` 外包一把锁。二者都不进 CPU 分析槽。
3. 导入时元数据与人脸共用一次解码；识别适配器和检测器都通过统一工厂注入 `SessionOptions`。InsightFace 0.7.3 的 `get_model()` 会丢掉 `sess_options`，必须拦截真正的 `InferenceSession` 构造。

明确不做：全局 `ImageComputeCoordinator` 优先级队列、15 秒老化、DINO GPU in-flight/stream、CUDA 人脸占 CPU 槽、质量版本升到 v3、采集下载/分析拆队列（采集不是本次故障源）。

## Files to modify

- `backend/app/native_runtime.py`（新建）：环境变量保险、`cv2.setNumThreads`、`threadpoolctl`、ONNX `SessionOptions` 工厂、InsightFace 会话拦截
- `backend/app/main.py`：尽可能早设 `OMP_*` 环境变量（该模块不得 import 图像栈）
- `backend/app/lifecycle.py`：人脸 warmup **之前**完成 OpenCV / threadpoolctl / 拦截器安装
- `backend/app/core/config.py`、`.env`、`.env.example`：`IMAGE_COMPUTE_LIBRARY_THREADS=4`、`IMAGE_COMPUTE_THUMBNAIL_PARALLEL=2`
- `backend/app/services/similarity.py`：删除懒加载 `_configure_opencv_threads()` / `setNumThreads(1)`
- `face_runtime/adapters.py`、`face_runtime/runtime.py`：识别与检测会话走统一工厂
- `backend/app/services/face.py`：接收已解码 BGR 的入口；bytes 入口只做包装
- `backend/app/services/importer.py`、`backend/app/services/image_metadata.py`：导入一次解码
- `backend/app/api/acquisition.py`：预览信号量改为读配置，避免再写死另一套池
- `requirements.txt`：增加 `threadpoolctl`

## Reuse

- `backend/app/api/acquisition.py` 已有 `_preview_render_slots`，保留 2 路语义
- `backend/app/services/thumbnails.py` `render_acquisition_preview()`：继续 PIL，不进 OpenCV
- `backend/app/services/importer.py` `_recognition_plan()` / `import_gallery_photo()`：补解码上下文，不改识别决策
- `face_runtime/runtime.py` `decode_image_bytes()` / `analyze_bgr()`：新增数组入口，避免二次解码
- `backend/app/services/similarity.py` `DinoV2FeatureExtractor.encode()`：保持 batch 32，只加互斥锁
- InsightFace 安装路径：`insightface.model_zoo.model_zoo.get_model()` 只转发 `providers`/`provider_options`

## Steps

- [ ] 1. 新增 `native_runtime`：读 `IMAGE_COMPUTE_LIBRARY_THREADS`；设 `OMP_NUM_THREADS` 等；`cv2.setNumThreads(n)` 只调用一次；`threadpoolctl` 在 NumPy 已加载后生效并保持控制器存活；提供 ONNX `SessionOptions`（intra=n、inter=1、顺序执行）
- [ ] 2. 用进程级初始化锁，窄范围包装 `PickableInferenceSession`（或等价构造点），把 options 注入检测会话；构造结束后恢复；测试读检测器 `get_session_options()`，不能只测识别适配器
- [ ] 3. `initialize_runtime()` 在 `face.warmup()` 前调用上述配置；删掉 `ensure_perceptual_feature_dependencies()` 里的动态 `setNumThreads`
- [ ] 4. `OnnxFaceAdapter` 改走同一工厂；CUDA provider 保持原列表，线程限制仍作用于 CPU 预处理和 CPU 回退
- [ ] 5. `FaceService` 增加 `detect_faces_bgr`；`import_gallery_photo` 一次打开图，产出宽高/拍摄时间后把 BGR 交给检测；不要用主脸质量字段冒充完整识别
- [ ] 6. 预览继续最多 2 路，上限来自配置；不把预览和人脸推理排进同一组槽
- [ ] 7. `detect_faces` 外层信号量默认 2（与现图库识别并发一致）；`encode()` 加锁，禁止两路扫描同时 forward
- [ ] 8. 同步 `.env` / `.env.example` / `Settings`；`threadpoolctl` 写入 `requirements.txt`；不改 `sql/tables.sql`，本轮不加表字段
- [ ] 9. 在现有未提交 diff 上改 `acquisition.py` / `similarity.py`，不丢已有预览信号量和刷新修复

## Verification

- 单测：启动后 OpenCV 线程数为 4，运行期不再调用 `setNumThreads`
- 单测：检测会话和识别会话均为 intra=4、inter=1
- 单测：`import_gallery_photo` 路径对同一 payload 只解码一次（可打补丁计数 `Image.open` / `decode_image_bytes`）
- 单测：预览并发不超过 2
- 跑受影响后端测试（人脸、采集导入、图库导入）；不改前端则不必 `npm run build`
- 不启动长期服务、不 Git 提交
- 用户手工：待审核批量删除后翻页/补位，CPU 不应无界打满；批量导入图库时 CPU 可升高但应与 4 个 OpenCV 线程同量级，且列表预览仍可刷出
