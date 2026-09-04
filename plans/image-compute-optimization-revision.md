# 图像计算优化方案审阅与修订说明

本文给后续实施的 AI 使用。前一稿《图像计算去重与有界并行优化方案》方向可用，**全局调度器要保留**，但若干前提、线程预算和协议是错的，不能按原文直接写代码。

实施时以本文为约束，覆盖前一稿冲突条款。前一稿未点名修改的部分仍可沿用。

---

## 1. 已确认决策

1. CPU 飙升是在 `cv2.setNumThreads(1)` **之前**测到的。之后没有对照压测。
2. **禁止**再把 OpenCV 全局线程打成 1。那是一刀切：所有 OpenCV 算子都单线程，吞吐会无谓变差，也不是为了“省 CPU”。目标是有界并行，不是把机器闲置。
3. **保留**进程级 `ImageComputeCoordinator`。采集、图库导入、人脸识别、相似整理共享同一调度器，避免各自建池后叠加。
4. 当前 FastAPI 按单进程理解；调度器做进程内单例。
5. 这是独立性能优化，不改 Telegram OpenSpec 记录，不碰工作区里已有的未提交改动。

当前工作区已有未提交文件（实施时不得撤销、覆盖或混入）：

- `backend/app/api/acquisition.py`
- `backend/app/db.py`
- `backend/app/services/acquisition.py`
- `backend/app/services/similarity.py`
- `frontend/src/AcquisitionCenter.tsx`

若与本任务冲突，停下来说明冲突，不要自行处理。

---

## 2. 前一稿哪些可保留

这些仍然要做：

- 进程级协调器，`max_parallel=4`，调度单位是一张图的一段 CPU 计算。
- 下载、MinIO、数据库不计入计算许可。
- 优先级：交互优先、不抢占已开始的单张图。
- 异常、超时、取消都必须释放许可。
- 嵌套分析共享同一许可，避免重复申请死锁。
- 启动阶段设置 OpenCV 线程，运行中禁止再改。OpenCV 官方说明 `setNumThreads` 影响后续并行区且非线程安全。
- `DecodedImageContext`：一张图只解码一次，短生命周期，不缓存原图像素。
- 兼容旧的 `bytes` 入口。
- 主脸质量字段不得当成完整多脸识别结果。
- 相似扫描优先读库；版本变化才重算。
- 采集转入图库时拷贝已验证的哈希、质量和主脸质量。
- ORB 仍用扫描内 LRU，不写库。
- CPU 分析期间不持有 SQLite 写锁；每张图用短事务落库。
- `/api/health` 增加只读 `image_compute`。
- 数据库模型、启动迁移、`sql/tables.sql` 同步；`sql/tables.sql` 用生成命令导出，禁止手改。

---

## 3. 必须修正的问题

### 3.1 「并行数 × 库线程数 = 16」公式不成立

前一稿把 `4 × 4 = 16` 当成全进程计算预算。这只在所有原生库共用一个线程池时成立。本项目里它们是分开的：

| 库 | 现状 | 证据 |
|---|---|---|
| OpenCV | 首次质量分析时设成 1，且只设一次 | `backend/app/services/similarity.py` 中 `_configure_opencv_threads()`，由 `ensure_perceptual_feature_dependencies()` 懒调用 |
| ONNX 识别 | 自建会话，**没有** `SessionOptions` | `face_runtime/adapters.py`：`ort.InferenceSession(str(model_path), providers=providers)` |
| ONNX 人脸检测 | InsightFace 自己建会话，同样没有线程配置 | `face_runtime/runtime.py` 的 `FaceAnalysis(...)` |
| NumPy / OpenBLAS / MKL | 完全未限制 | `assess_image_quality()`、`AcquisitionService._quality_image()` 大量 `mean` / `percentile` / `var` |
| Torch DINOv2 | 未设 `set_num_threads`；CUDA 不可用会回退 CPU | `backend/app/services/similarity.py` 的 `DinoV2FeatureExtractor` |
| RapidOCR | 另有一套 ONNX，不在前一稿范围内 | `backend/app/services/ocr.py` |

同一张图里 OpenCV 预处理和 ONNX 推理通常是串行的，所以单图峰值接近 `max(各库线程)`。  
**4 张图并行时**，4 个 ONNX 池和 4 个 OpenCV 池会同时存在。最热路径（CPU 人脸）峰值接近 `4 × intra_op`，再叠 OpenBLAS，不是 16。

修订：

- `IMAGE_COMPUTE_LIBRARY_THREADS=4` 表示**每个**原生库自己的上限，不是全家共用 4 个线程。
- 启动时把下面全部钉到同一个值，禁止只改 OpenCV：
  - `cv2.setNumThreads(n)`
  - ONNX `intra_op_num_threads=n`，`inter_op_num_threads=1`
  - `torch.set_num_threads(n)`
  - 进程环境 `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `OPENBLAS_NUM_THREADS` / `NUMEXPR_NUM_THREADS`（尽量在相应库首次 import 前）
- 不要宣称“理论预算 16 个逻辑线程”。对外表述改为：最多 4 张图的 CPU 分析同时进行；每个原生库内部不超过 4 线程。
- 默认值仍可用 `MAX_PARALLEL=4`、`LIBRARY_THREADS=4`。这台 20 逻辑处理器机器吃得下，也明显好于全核无界。若压测时人脸 CPU 路径过热，先降 `MAX_PARALLEL`，不要把 OpenCV 打回 1。

### 3.2 人脸检测会话才是 CPU 大头，前一稿没改到

默认配置是 CPU 人脸，不是 CUDA：

- `.env.example`：`FACE_EXECUTION_PROVIDERS=CPUExecutionProvider`
- `backend/app/core/config.py` 同默认值
- 识别模型在 `OnnxFaceAdapter`，检测模型在 InsightFace `FaceAnalysis`

前一稿写“ONNX Runtime 的人脸检测和特征模型设置 intra_op=4”。按现有代码，只改 `OnnxFaceAdapter` 等于只限制特征提取；**检测器仍按逻辑核数起线程**。CPU 飙升很大概率就在这里：`buffalo_l` 检测 + 默认 `intra_op`。

修订：

- 必须把线程限制打进 InsightFace **检测**会话，不能只改识别适配器。
- 若 `FaceAnalysis` 不接受 `SessionOptions`，就包装 detector session、替换 session，或在创建前用 ONNX 默认会话选项注入。写代码前先读 `insightface` 实际创建路径，不要臆测。
- CUDA / TensorRT 仍走原 provider；CPU 预处理用的 OpenCV 同样受启动时全局线程限制。线程设置不要写在“仅 CPU provider”分支里才执行。
- `FaceService` 是进程单例，图库导入已经用线程池并发打它（`backend/app/background_tasks.py`，`gallery-recognition`）。`FaceAnalysis.get()` 未必线程安全。有许可 ≠ 人脸对象可并发。
  - 不允许用一把大锁把 4 个许可堵住（许可空转）。
  - 先确认 `detector.get` 与 `session.run` 能否并发。
  - 不安全则用大小等于 `max_parallel` 的运行时实例池，获取计算许可时一并取实例。

### 3.3 OpenCV 必须在人脸预热前设置，现在不是

前一稿写对了“启动时设一次”，但没对准现有时序。

现状：

- `initialize_runtime()` 先 `services.face.warmup()`（`backend/app/lifecycle.py`）
- OpenCV 线程要等第一次 `assess_image_quality()` / `ensure_perceptual_feature_dependencies()` 才设置
- 人脸预热会先加载 InsightFace / OpenCV。之后再 `setNumThreads` 对已建并行区无效，而且该调用非线程安全

修订：

- 在 `initialize_runtime()` **最前面**、人脸 warmup **之前**设置所有原生库线程。
- 删掉依赖检查函数里的动态设置；保留依赖是否可 import 的检查。
- 运行期断言：除启动路径外，禁止再调用 `cv2.setNumThreads`。测试里可打补丁检查。

### 3.4 下载“不占许可”和现有流水线矛盾

现状采集是同一个 worker 里下载完立刻分析：

- `AcquisitionService._download_and_analyze()`
- `process_run()` 里 `ThreadPoolExecutor(max_workers=workers)`，`workers` 来自 `ACQUISITION_DOWNLOAD_WORKERS`（默认 8），再被脚本 `max_download_workers` 收窄
- idolxxx 最多 3 路下载（`backend/app/services/acquisition_adapters/registry.py`）

若仍在该线程里 `coordinator.run()`，许可确实不含下载，但 **8 个下载线程会在许可上堵住，后续下载停摆**。前一稿把这写成“下载完全不占计算名额”，与实现不符。

修订，按这个做，不要偷懒：

1. 下载池和分析解耦。下载线程只负责网络；分析由协调器许可后执行。
2. 落库仍在持有短会话的线程里做，分析线程不碰未提交写事务。
3. 下载结果用有界队列交给分析，队列长度不要明显大于 `max_parallel`，避免下载过快把内存堆满。
4. 停止采集时：队列里还没拿到许可的任务直接退出；已经开始的单张分析不中断，结束后再停。

idolxxx 继续最多 3 路下载；多分类同时采时共享全局许可。这点前一稿正确。

### 3.5 许可与 single-flight 顺序必须写死

前一稿没定义二者顺序。两种都有坑：

- 先拿许可再进 single-flight：等待者白白占槽
- 先占 single-flight 再拿许可：正确

必须实现为：

1. 按 `key` 加入 single-flight。已有飞行中任务则等待结果，**不申请许可**。
2. 只有胜者申请许可、计算、发布结果、移除飞行记录。
3. 失败不缓存，允许重试。
4. 计算完成且等待者取走后删除内存结果，不长期持有像素或 ORB。

`key = SHA256 + 操作类型 + 算法版本 + normal/mirror` 可保留。采集热路径几乎都是新图，single-flight 不是主收益，但协议仍要做对，避免和许可互相卡死。

嵌套许可用线程局部深度计数：深度 0 才真正申请，退出时深度回到 0 才释放。硬规则：

- **持有许可期间，禁止向另一个线程池 `submit` 再同步等待。** 这比“内部函数别重复申请”更硬。现有采集、图库识别都有 `ThreadPoolExecutor`，写错就会自锁。
- 内部质量 / 哈希 / 人脸函数默认假定调用方已持许可，或走“可重入、同线程不重复申请”的入口，不要每个内部函数自己 `acquire`。

### 3.6 缩略图不要和重计算抢同一组 4 个槽

前一稿把缩略图、图库导入、人脸重识别、采集入库都放进优先级 1，且“不抢占”。大人脸 CPU 推理可跑数秒，缩略图只能等，列表会灰屏。而验收又写了“列表刷新不进入长时间灰屏”，自相矛盾。

缩略图主要是解码和 JPEG，和人脸 / 质量 / ORB 不是一类活。

修订：

- 仍由**同一个**协调器对象管理，避免再造线程池。
- 缩略图走独立轻量限额，例如最多 2 路，**不占用** 4 个 CPU 分析槽。
- 不要让缩略图排在正在进行的人脸/质量分析后面。
- 15 秒老化可以留，但后台任务**不得升到最高档**，不能和缩略图、交互识别抢保留槽。
- 建议槽位：4 个分析槽给 CPU 分析；另 2 个轻量槽给缩略图。交互分析可插队到分析槽，但不抢已开始的任务，也不挤占轻量槽。

优先级修订：

1. 交互：缩略图（轻量槽）、图库导入识别、采集资产入库、人脸重新识别
2. 正在采集的新图分析
3. 待审核相似扫描、图库全量相似整理

同级 FIFO。等待超过 15 秒可升一级，**最高升到 2**，不能升到 1。

### 3.7 重复计算比线程数更浪费，前一稿方向对，但要对准现状

采集下载阶段已经一次解码出质量和普通哈希：

- `AcquisitionService._analyze_image_payload()` 调用 `_quality_image()` + `compute_perceptual_features_from_image()`

仍存在的重复：

1. `_quality_image()` 用 NumPy 再算一遍模糊；`assess_image_quality()` 又用 OpenCV Laplacian / Sobel。一次解码里不要做两套灰度质量。
2. `compute_mirrored_perceptual_hashes()` 会重新 `open_normalized_image()`。
3. `assess_primary_face()` 再解一次图；`FaceService.detect_faces()` 内部 `decode_image_bytes()` 再解成 BGR。
4. 图库导入：`parse_image_metadata(payload)` 一次，`detect_faces(payload)` 再解一次（`backend/app/services/importer.py`）。
5. `scan_similarity()` 对待审核图几乎总是重下载、重算质量和哈希，再跑人脸，即使库里已有 `quality_version` 和 pHash（`backend/app/services/acquisition.py`）。
6. 图库 `_ensure_features()` 在缺镜像哈希或质量版本变化时，会 `compute_perceptual_features` 再 `compute_mirrored_perceptual_hashes`，两次解码。

修订时 `DecodedImageContext` 必须成为上述路径的唯一解码入口。扫描路径先看库字段和版本，齐全则跳过下载和计算。

主脸质量仍只表示“优势脸质量”，不能恢复成完整识别计划。多脸识别继续走一次完整检测。这点前一稿正确，必须守住。

### 3.8 SQLite 边界要对准真实调用点

相似扫描和图库特征补齐现在会在同一会话里边算边 `db.add`：

- `AcquisitionService.scan_similarity()`
- `GallerySimilarityScanner._ensure_features()`

CPU 一慢或一等许可，写锁就拖住列表接口。这和灰屏、`database is locked` 对得上。

修订：

- 申请许可前必须提交或结束当前写事务。
- 分析线程不得使用调用方未提交的会话写数据。
- 每张图（或很小的一批特征）用短事务写入。
- `Task.message` 等待超过 1 秒显示“等待图像计算资源”，拿到许可后恢复真实进度。采集运行状态机不要新增 API 状态。

### 3.9 成功标准写错了

前一稿把“重任务时 CPU 70%–90%”当目标。用户要的是：有活时能用满合理核数，无界线程和重复计算消失；**不是**追求某个 CPU 百分比。

轻负载 1 张图时，CPU 打满才是线程泄漏。重负载 70%–90% 反而可能正常。

改用：

- 同时处于 CPU 分析中的图片数 ≤ `IMAGE_COMPUTE_MAX_PARALLEL`
- 运行期不再调用 `cv2.setNumThreads`
- CPU 人脸会话 `intra_op=4`、`inter_op=1`（含检测器）
- 同一张图、同一次流水线只解码一次
- 版本匹配的特征不重算
- 相同 single-flight key 底层函数只跑一次
- 停止采集时，未拿到许可的任务能退出，许可不泄漏
- 列表刷新不再因计算持有 SQLite 写锁而长时间灰屏
- 原生线程数不随图片数线性涨到接近 `图片数 × 逻辑核数`

---

## 4. 修订后的硬约束

### 配置

同步 `.env`、`.env.example`、`Settings`。运行时只读 `.env`。

```
IMAGE_COMPUTE_MAX_PARALLEL=4
IMAGE_COMPUTE_LIBRARY_THREADS=4
IMAGE_COMPUTE_PRIORITY_AGING_SECONDS=15
IMAGE_COMPUTE_THUMBNAIL_PARALLEL=2
GALLERY_RECOGNITION_WORKERS=4
```

`GALLERY_RECOGNITION_WORKERS=4` 只表示图库批量导入最多提交多少张不同图；最终仍受全局 4 个分析许可约束。不要再额外建不受协调器约束的 CPU 池。

### 协调器

- 由服务容器创建单例并注入采集、图库、人脸、相似、缩略图。
- 分析槽：`max_parallel=4`。轻量槽：缩略图 `2`。
- 先 single-flight，后分析许可。
- 同线程可重入；跨线程同步等待禁止。
- 取消、异常、超时都释放。
- 健康接口只读返回：配置并行数、当前分析数、当前缩略图数、各优先级等待数、single-flight 等待数。

### 解码上下文

短生命周期，用完立即释放 PIL / NumPy。按需惰性生成 RGB、BGR、灰度、镜像，不要一张图四份全分辨率常驻。4 路并行全分辨率图会吃掉大量内存。

SHA-256 仍只对原始字节计算，不触发解码。

### 库表

- `AcquisitionAsset` 增加镜像 pHash、镜像 dHash、主脸分析版本。
- `GallerySimilarityFeature` 增加主脸分析版本。
- 字段中文注释；启动迁移与 `sql/tables.sql` 同步。`sql/tables.sql` 用 `backend/app/tools/export_schema_sql.py` 生成。
- 不新建通用缓存大表。

### 不要做的事

- 不要 `cv2.setNumThreads(1)`。
- 不要只改 OpenCV 线程，却不改 ONNX 检测会话 / OpenBLAS / Torch。
- 不要让缩略图占用 4 个分析槽。
- 不要在持有写事务时等待计算许可。
- 不要用主脸质量恢复完整人脸识别结果。
- 不要启动前端或后端（由用户手工启动）。
- 不要 Git 提交。
- 不要把视频探测、转码、OCR 塞进图像分析许可。OCR 若后续要管，另开任务；本次至少不要让 RapidOCR 再起无界 ONNX 线程——若改动很小，可在 OCR 初始化时套同一套 `LIBRARY_THREADS`，但不进 4 个分析槽。

---

## 5. 建议实施顺序

不要把调度器、解码上下文、库表、线程封顶搅成一个不可测的大提交。可以仍是同一功能分支，但按层验证：

1. **启动封顶原生线程**  
   人脸 warmup 前设置 OpenCV / ONNX（含检测器）/ OpenBLAS / Torch。单测：启动后线程配置正确，运行期不再 `setNumThreads`。
2. **协调器本体**  
   许可、优先级、老化（最高到 2）、取消、异常释放、single-flight 顺序、同线程可重入、缩略图轻量槽。先单测，不接业务。
3. **接入业务**  
   采集分析、图库识别、相似特征、人脸重识别走分析槽；缩略图走轻量槽。拆分采集下载/分析。计算前后短事务。
4. **单次解码与去重**  
   `DecodedImageContext` 打通采集、导入、扫描。扫描复用库字段。采集转图库拷贝已验证特征。
5. **库表与健康接口**
6. **回归**  
   受影响后端测试、采集/相似/人脸专项、`cmd /c npm.cmd run build`。不要启动长期服务。

---

## 6. 验证

除前一稿已有单测外，必须补：

- 全局同时分析数不超过 4；缩略图不超过 2，且不计入那 4 个。
- 先 single-flight 后许可：等待者不占分析槽。
- 同线程嵌套不申请第二次许可；跨线程同步等待要有测试或明确代码禁令。
- 人脸检测会话（不只是识别适配器）`intra_op=4`、`inter_op=1`。
- 同一图片质量 + 普通/镜像哈希 + 元数据 + 人脸预处理只解码一次。
- 采集已有特征、图库已有特征、采集转图库不重算；版本变化才失效。
- 图库批量导入保持原文件顺序，单张失败不阻塞其他图。
- 取消等待中的任务不泄漏许可。

手工验收（用户执行，实施 AI 不要自行启动服务）：两个分类同时采集 + 图库导入 + 相似扫描时，列表刷新不长时间灰屏，交互任务能拿到分析槽或缩略图槽，SQLite 不再锁死。

---

## 7. 仓库约束（实施时遵守）

- 默认 Conda 环境名：`pictureshow`。
- Python 4 空格，TS/TSX 2 空格，前端双引号。
- 面向用户文案用中文。
- 新增配置必须写进本地 `.env` 和 `.env.example`；程序只读 `.env`。
- 表、字段、索引、约束变更必须有中文注释，并更新全量表设计文件。
- 前端改动提交前本应 `npm.cmd run build`；本次若改了前端，构建一次。未改前端则不必。
- 最终说明写清：改了什么、配置/迁移、实际跑过的验证、需要用户手工做的事。不要声称没有跑过的测试。
