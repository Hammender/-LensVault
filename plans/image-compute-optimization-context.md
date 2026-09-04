# 图像计算优化上下文记录

本文给下一会话的 AI 快速恢复上下文使用。它不是代码变更，也不是新的 OpenSpec；实施前先读本文和 `image-compute-optimization-execution.md`。

## 1. 当前任务状态

- 用户已经确认要继续实施图像计算优化。
- 当前阶段是先整理实施文档，下一会话可以直接按实施包执行。
- 本任务与 Telegram 频道采集 OpenSpec 分开，不修改 Telegram 设计记录。
- 不启动后端/前端服务，不提交 Git。

## 2. 当前工作区

以下文件已有未提交改动，默认属于用户或之前协作者，实施时必须先读取并在其基础上工作，不得撤销或覆盖：

- `backend/app/api/acquisition.py`
- `backend/app/db.py`
- `backend/app/services/acquisition.py`
- `backend/app/services/similarity.py`
- `frontend/src/AcquisitionCenter.tsx`

当前还有用户已有的未跟踪文件，例如 `plans/image-compute-optimization-revision.md`、`temp.txt` 和 `docs/待做功能.txt`。不要清理或重命名。

## 3. 已确认的代码事实

### 采集

- `AcquisitionService.process_run()` 当前使用 `ThreadPoolExecutor`，下载和分析仍在同一 worker 中；脚本可能继续有 adapter 级下载上限（idolxxx 为 3）。
- `_analyze_image_payload()` 已经尝试复用一次解码，但后续镜像哈希、主脸质量和部分导入路径仍可能重新解码。
- 采集资产质量的 `blur_score` 来自 `np.var(np.diff(...))`，阈值当前为 45；不要把它直接替换为图库 Laplacian 指标。

### 图库/相似

- `background_tasks.py` 中图库识别当前有自己的 `ThreadPoolExecutor`；实施时不能再保留一个绕过全局协调器的 CPU 池。
- `GallerySimilarityScanner._ensure_features()` 会在镜像哈希、质量或人脸字段缺失/过期时计算；应先按 SHA 和版本复用已有字段。
- DINOv2 当前通过 `DinoV2FeatureExtractor.encode(images)` 批量执行，图库默认 batch size 为 32；必须保留这条 GPU 批处理路径。
- ORB 当前适合扫描内 LRU，不要创建通用全分辨率图像缓存表。

### 人脸

- `FaceService.detect_faces(payload)` 当前会自行把 bytes 解码为 BGR，再调用共享 `FaceRuntime`。
- `face_runtime/adapters.py` 的 `OnnxFaceAdapter` 自己创建 ONNX Runtime session。
- `face_runtime/runtime.py` 使用 InsightFace `FaceAnalysis` 创建检测器。
- 安装版本 InsightFace 0.7.3 的 `model_zoo.get_model()` 只转发 `providers`/`provider_options`，丢弃 `sess_options`；不要写成只给 `FaceAnalysis` 传 kwargs 就能限制检测器线程。
- RetinaFace/SCRFD 可能有 `center_cache` 可变状态。先压测共享 warmed runtime；若失败，做小实例池或只保护缓存填充，不要整段锁住 `session.run`。

### 原生库

- 当前机器有 20 个逻辑处理器；之前观察到 OpenCV 和 OpenBLAS 会按较大线程数工作。
- 以前的修改中出现过 `cv2.setNumThreads(1)`，该做法必须移除或改为启动期的配置值，不能全局单线程化。
- NumPy/OpenBLAS 的环境变量经常在应用导入前已经错过时机，`threadpoolctl` 是已加载 BLAS 的主要控制手段；同时保留启动环境变量作为保险。
- ONNX Runtime 的 session options 必须在 session 创建时设置；GPU provider 不等于 CPU 线程预算，CPU 预处理/fallback 仍需单独控制。
- RapidOCR 使用自己的 ONNX session，本次不把它塞进图像分析协调器；如要限制，只做初始化层面的线程配置。

## 4. 必须保持的产品行为

- 采集、图库导入、人脸重识别和相似整理共享一个进程内协调器。
- 缩略图有独立 2 路轻量槽，不因人脸分析堵住待审核列表。
- 交互任务优先，后台任务等待老化最高只能到优先级 2。
- SQLite 写入必须短事务；分析或等待许可时不能持有写锁。
- 主脸质量字段只代表优势脸质量，不得冒充完整多脸识别结果。
- GPU DINO 不得被改写成每张图一个 CPU worker。
- quality version 继续 `technical-quality-v2`，除非 overall 公式真的改变。

## 5. 实施时的检查顺序

1. 读取本上下文、实施包和现有未提交文件。
2. 检查当前依赖清单、配置模型和 lifecycle 导入时序。
3. 先实现原生线程启动配置和 ONNX detector session 注入，再做协调器。
4. 协调器单测通过后接采集、图库、人脸和相似路径。
5. 最后做解码上下文、数据字段/迁移、健康接口和回归测试。

## 6. 不要误判的几个问题

- “工作线程在 CPU 上”不代表它占用的全部计算都在 CPU；它可能只是等待 GPU future。
- “GPU 任务不占 CPU 分析槽”不代表完全不消耗 CPU；解码、预处理和后处理仍要进入 CPU 预算。
- “OpenCV 设置为 4”不代表全进程只有 4 个线程；它只是 OpenCV 自己的上限。
- “已有哈希字段”只有在算法版本和数据完整性都匹配时才能复用。
- “一次解码”不等于长期缓存原图；上下文必须是单任务短生命周期。

