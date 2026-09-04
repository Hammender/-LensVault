# 图像计算优化实施包

本文是下一会话实施图像计算优化时的主入口。先阅读本文，再阅读同目录的 `image-compute-optimization-context.md`。现有 `image-compute-optimization-revision.md` 是评审与约束来源；如果三者措辞冲突，以本文的“硬约束”和“禁止事项”为准。

## 1. 目标

解决采集、图库导入、相似整理、人脸分析同时运行时的以下问题：

- CPU 原生线程池无界增长，图片越多线程越多；
- 同一张图片重复解码、重复计算质量和哈希；
- 采集下载线程被 CPU 分析阻塞；
- 缩略图被重型人脸/质量计算堵住，待审核区出现灰屏；
- SQLite 写事务跨越慢计算或等待，导致 `database is locked`；
- GPU 任务被错误地纳入 CPU worker 预算，破坏 DINOv2 批处理。

## 2. 三套独立资源模型

不要把“工作线程”“CPU 原生线程”“GPU 执行”混为一个数字。

| 资源 | 默认限制 | 说明 |
|---|---:|---|
| CPU 图片分析槽 | 4 张图 | 同时处于解码、质量、哈希、ORB、CPU 人脸或 CPU 后处理的图片数 |
| 每个 CPU 原生库/会话线程 | 4 线程 | OpenCV、ONNX Runtime CPU、OpenBLAS/NumPy、Torch CPU 各自的上限，不是共用线程池 |
| 缩略图槽 | 2 路 | 独立于 4 个分析槽，负责解码、缩放和 JPEG |
| GPU 批处理 | 初始 1 个 in-flight batch | 由 batch size、CUDA stream、显存和队列长度控制，不占 CPU 分析槽 |
| 下载并发 | 沿用脚本上限 | 网络 IO 不申请 CPU 分析许可，但结果进入有界队列 |

因此不得写“4 × 4 = 总共 16 线程”。正确表述是：最多 4 张图片同时进行 CPU 分析，每个原生库/会话不超过 4 个内部线程；GPU 路径另行计量。

## 3. 总体架构

新增进程级单例 `ImageComputeCoordinator`，由服务容器创建并注入采集、图库、人脸、相似和缩略图服务。

```text
Telegram/MinIO 下载池
        |
        v
有界下载结果队列（按张数限制，约 max_parallel 的 2~3 倍）
        |
        +--> CPU 分析调度器：4 个分析槽
        |       |
        |       +--> DecodedImageContext
        |       +--> 哈希 / 质量 / ORB / CPU 人脸 / 后处理
        |       +--> 提交 DINO 批请求后立即释放 CPU 槽
        |
        +--> 缩略图调度器：2 个轻量槽（不占分析槽）

DINO 批处理器：独立 GPU 队列，batch_size 保持 32，初始 max_in_flight=1
```

### 调度规则

1. 先进入 single-flight，再申请资源许可。相同 key 的等待者不占槽，只有胜者执行底层计算。
2. key 至少包含 `sha256 + 操作类型 + 算法版本 + normal/mirror`。
3. 成功结果只在等待者取走期间短暂保留；失败不缓存，允许重试。
4. 同线程嵌套计算使用线程局部深度计数，深度 0 才真正申请/释放许可。
5. 持有许可时禁止向另一个线程池 `submit` 后同步等待，避免线程池互等死锁。
6. 不抢占已经开始的单张图片。优先级只影响等待队列。
7. 交互任务优先；采集新图其次；后台相似扫描最低。等待 15 秒最多升到优先级 2，后台任务不能升到最高优先级 1。
8. 取消、异常、超时、停止采集都必须释放许可。尚未拿到许可的任务可退出，已开始的单图分析完成后再停。

## 4. CPU、GPU 与模型路径

### CPU 分析槽内的任务

- 图片解码和派生 RGB/BGR/灰度；
- pHash、dHash、镜像哈希；
- 当前质量评估、ORB 和 CPU 后处理；
- CPUExecutionProvider 下的人脸检测/识别；
- CUDA/TensorRT 路径的 CPU 预处理与结果后处理。

### GPU 调度器外置的任务

DINOv2 必须保持现有批量路径：

- `batch_size=32`；
- GPU 推理不进入 4 个 CPU 分析槽；
- 通过 GPU 队列、in-flight batch、CUDA stream 和显存限制；
- GPU 完成后的必要 CPU 后处理才重新申请 CPU 分析槽；
- GPU 不可用回退 CPU 时，使用独立 Torch CPU 限制，仍不按“一图一 DINO worker”接入协调器。

视频探测、转码和 RapidOCR 不进入本次图像分析槽。RapidOCR 如需限制，只在初始化时复用原生线程配置，不改变其独立任务边界。

### 人脸模型

当前 InsightFace 0.7.3 的 `FaceAnalysis(..., sess_options=...)` 不可靠：`model_zoo.get_model()` 只转发 `providers` 和 `provider_options`，会丢弃 `sess_options`。

实施要求：

1. 建立统一 ONNX Session 工厂，构造 `SessionOptions`：
   - `intra_op_num_threads = IMAGE_COMPUTE_LIBRARY_THREADS`；
   - `inter_op_num_threads = 1`；
   - 默认顺序执行，除非实测有明确收益。
2. `OnnxFaceAdapter` 直接调用该工厂。
3. 创建 InsightFace `FaceAnalysis` 前，使用进程级初始化锁和窄范围包装/拦截 `PickableInferenceSession`（或等价的实际构造点），把上述 options 注入真正的 `onnxruntime.InferenceSession`，构造完成后恢复原对象。
4. 测试必须读取检测器真实 session 的 `get_session_options()`，不能只测识别适配器。
5. 先用共享、预热后的 FaceRuntime 并发压测；若发现 `center_cache` 等可变状态竞态，只锁缓存填充或改为小型实例池，不要先用一把大锁串行化整个 `session.run`，也不要无证据复制 4 套模型。

## 5. 启动期线程封顶

新增依赖无关的启动配置函数，例如 `backend/app/native_runtime.py`，在导入服务、路由和人脸 warmup 前执行：

- 设置 `OMP_NUM_THREADS`、`MKL_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`NUMEXPR_NUM_THREADS` 作为尚未 import 时的保险；
- 调用 `cv2.setNumThreads(n)` 一次；
- 通过 `threadpoolctl` 限制已加载的 NumPy/OpenBLAS（将 `threadpoolctl` 写入依赖清单）；
- ONNX SessionOptions 在每个会话创建时注入；
- Torch 线程在 DINO CPU fallback 初始化时配置，CUDA 路径不以 Torch CPU 线程数衡量。

`cv2.setNumThreads` 不得写在懒加载的依赖检查函数中，也不得在运行期重复调用。不要把 OpenCV 全局设置为 1。

## 6. 单次解码上下文

新增短生命周期 `DecodedImageContext`，兼容现有 bytes 入口。

- 原始 bytes 的 SHA-256 不触发解码；
- RGB、BGR、灰度、镜像数据惰性生成；
- 同一流水线中元数据、质量、普通/镜像哈希、人脸预处理复用同一上下文；
- 不长期缓存全分辨率像素，任务完成立即释放；
- `FaceService` 增加接收已解码 BGR/上下文的内部入口，bytes 入口仅做兼容包装；
- `assess_primary_face` 接收已有检测结果和上下文，不再自行重新打开图片。

第一阶段不要改变现有质量公式：图库保持 `technical-quality-v2`，采集当前 `np.var(np.diff(...))` 模糊指标和阈值 45 保持不变。统一解码不等于统一指标；若未来改采集模糊算法，必须另行标定阈值和评估缓存影响。

## 7. 业务接入顺序

### 7.1 启动封顶

涉及：`backend/app/lifecycle.py`、新增 native runtime 模块、依赖清单、配置。

在人脸 warmup 之前完成原生库设置，并增加运行期禁止重复 `cv2.setNumThreads` 的测试。

### 7.2 协调器本体

建议新增 `backend/app/services/image_compute.py`：

- 分析槽和缩略图槽；
- 优先级队列和老化；
- single-flight；
- 可取消 Future；
- 同线程可重入；
- 运行指标和健康快照。

协调器 worker 自己执行任务，不让调用方线程拿许可后阻塞在另一个池里。

### 7.3 采集流水线

涉及：`backend/app/services/acquisition.py` 及其 adapter。

- 下载池只下载；
- 分析结果进入有界队列；
- 分析 worker 使用 `DecodedImageContext` 和协调器；
- idolxxx 的下载并发上限继续由 adapter 约束；
- 多分类采集共享全局 CPU 分析许可；
- 采集停止时清理等待队列，已开始的单图分析正常收尾。

### 7.4 图库导入、人脸和相似整理

涉及：`backend/app/background_tasks.py`、`backend/app/services/importer.py`、`backend/app/services/similarity.py`、`backend/app/services/face.py`。

- 移除不受协调器约束的 CPU 分析池；`GALLERY_RECOGNITION_WORKERS=4` 只表示最多提交的不同图片数；
- `_ensure_features` 先读库字段和版本，完整时跳过下载和重算；
- 相似扫描不重复下载已有特征的待审核图；
- DINO 仍在批量 GPU 阶段；
- ORB 继续使用扫描内 LRU，不写入通用缓存表；
- 分析线程不持有调用方 Session。

### 7.5 数据库和接口

- `AcquisitionAsset` 增加镜像 pHash、镜像 dHash、主脸分析版本；
- `GallerySimilarityFeature` 增加主脸分析版本；
- 模型、启动迁移和 `sql/tables.sql` 同步，后者使用 `backend/app/tools/export_schema_sql.py` 生成；
- 不升级 `technical-quality-v2`；
- `/api/health` 增加只读 `image_compute`：配置并行数、当前分析数、缩略图数、各优先级等待数、single-flight 等待数、GPU 队列/批次数；
- Task 等待资源超过 1 秒显示“等待图像计算资源”，不新增运行状态枚举；
- 每张图或极小批次使用短事务写入，计算和等待期间不持有 SQLite 写锁。

## 8. 配置

`.env` 与 `.env.example` 同步，程序只读取 `.env`：

```env
IMAGE_COMPUTE_MAX_PARALLEL=4
IMAGE_COMPUTE_LIBRARY_THREADS=4
IMAGE_COMPUTE_PRIORITY_AGING_SECONDS=15
IMAGE_COMPUTE_THUMBNAIL_PARALLEL=2
IMAGE_GPU_MAX_IN_FLIGHT=1
GALLERY_RECOGNITION_WORKERS=4
GALLERY_SIMILARITY_BATCH_SIZE=32
```

`MAX_PARALLEL` 和 `LIBRARY_THREADS` 可独立调节。CPU 人脸过热时先降低 `MAX_PARALLEL`，不要为了降温把 OpenCV 改成单线程；GPU 显存不足时降低 batch 或 GPU in-flight，不降低 CPU 槽作为替代。

## 9. 必须完成的测试

- 协调器全局 CPU 分析数不超过 4；缩略图数不超过 2，二者互不抢槽；
- single-flight 先登记后申请许可，等待者不占槽，失败可重试；
- 同线程嵌套不重复申请；取消、异常、超时不泄漏；
- 优先级 FIFO、15 秒老化最高到 2；
- 下载队列有界，停止采集不会卡死下载池；
- 同图质量、普通/镜像哈希、元数据和人脸预处理只解码一次；
- 库中版本匹配时不重算，版本变化时才失效；
- DINO 仍按批执行，GPU 队列不占 CPU 分析槽；
- InsightFace 检测 session 与识别 adapter 都是 `intra_op=4/inter_op=1`；
- 共享 FaceRuntime 并发压测，覆盖 `center_cache`；
- 计算期间列表读取不被 SQLite 写锁长时间阻塞；
- 受影响后端测试；如修改前端，执行 `cmd /c npm.cmd run build`；
- 不启动长期前后端服务，不执行 Git 提交。

## 10. 手工验收

由用户手工启动服务后验证：两个分类同时采集、图库导入、相似扫描并行进行时，待审核区刷新和大图翻页可用，缩略图不会长期灰屏；交互识别能进入对应槽位；停止任务后可立即再次运行；SQLite 不再出现持续锁死。

