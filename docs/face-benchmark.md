# 人脸识别离线评测

该工具与主程序完全隔离。创建快照时只读 SQLite、只从 MinIO 下载对象；快照完成后，标注和候选模型评测只访问快照目录，不修改主数据库、图库标签、MinIO 或 Qdrant。

## 1. 创建冻结快照

在项目根目录执行：

```powershell
python -m tools.face_benchmark create --workspace-id 1 --face-count 1000 --detection-count 150
```

如果评测全局旧数据，不传 `--workspace-id`。输出默认位于 `data/face-benchmark/<时间>/`，包含：

- 约 1000 张人脸级识别题，按人物覆盖、未知/边界、困难样本和固定随机对照分层抽取。
- 约 150 张完整图片检测题，能够发现旧识别记录中不存在的漏检人脸。
- 所有可用人物样本的本地副本。
- 独立的 `benchmark.db`、不可变的 `selection.jsonl`、图片文件校验清单及其 SHA-256。

抽样只使用现有元信息，不运行候选模型。候选模型之间存在分歧时，可以另建挑战集，但不能修改正式快照或锁定测试集。

## 2. 人工标注

标注工具需要单独手动启动，不会跟随主程序启动：

```powershell
python -m tools.face_benchmark label data/face-benchmark/20260731-120000
```

浏览器访问 `http://127.0.0.1:8765`。人脸题选择真实人物或“未知人物”；检测题填写完整图片中的真实人脸数。所有修改仅写入快照自己的 `benchmark.db`。

## 3. 候选模型评测

先在 `calibration` 分区调试模型和阈值：

```powershell
python -m tools.face_benchmark evaluate data/face-benchmark/20260731-120000 --model buffalo_l --provider cpu
```

Windows NVIDIA 环境使用：

```powershell
python -m pip install -r requirements.txt
python -m pip uninstall -y onnxruntime
python -m pip install -r requirements-face-cuda.txt
python -m tools.face_benchmark evaluate data/face-benchmark/20260731-120000 --model buffalo_l --provider cuda
```

安装后必须确认 `CUDAExecutionProvider` 实际可用。显式使用 `--provider cuda` 时，工具发现 CUDA Provider 未加载会直接失败，不会静默退回 CPU。

兼容 InsightFace 推理接口的 AdaFace、LVFace 等 ONNX 可以通过 `--recognition-onnx` 注入，同时继续使用指定 InsightFace 模型包的检测器：

```powershell
python -m tools.face_benchmark evaluate data/face-benchmark/20260731-120000 --model buffalo_l --recognition-onnx E:\AI-MODELS\face\candidate.onnx --provider cuda --flip-tta
```

确认模型和阈值后才运行一次锁定测试集：

```powershell
python -m tools.face_benchmark evaluate data/face-benchmark/20260731-120000 --model buffalo_l --provider cuda --final-holdout
```

结果保存在快照的 `results/` 中，包含 JSON、中文 Markdown 和阈值/最小差值组合 CSV。正式比较以错误人物绑定不增加为硬约束，再比较已知人物拒识率、小脸/侧脸困难桶和检测计数召回代理值。

## 4. 生产配置

Mac 默认配置：

```dotenv
FACE_EXECUTION_PROVIDERS=CPUExecutionProvider
FACE_REQUIRE_PRIMARY_PROVIDER=false
```

Windows NVIDIA 默认配置：

```dotenv
FACE_EXECUTION_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
FACE_REQUIRE_PRIMARY_PROVIDER=true
```

`FACE_REQUIRE_PRIMARY_PROVIDER=true` 能阻止 CUDA 配置错误时静默回退 CPU。`FACE_RECOGNITION_MIN_MARGIN` 同时约束第一名和第二名的分数差；分数达标但差值不足的人脸保持未知，降低错误人物自动绑定风险。
