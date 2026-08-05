# 人脸识别离线评测操作手册

该工具与主程序隔离。创建快照时只读 SQLite 和 MinIO；快照完成后，标注和评测只访问快照目录，不修改主数据库、图库标签、MinIO 或 Qdrant。

当前正式快照为 `data/face-benchmark/20260804-203852`，已有 1000 条身份题和 150 条检测题。人工标注和复查、Mac CPU calibration、候选比较和一次性 holdout 均已完成。身份题 987 条已标注、13 条跳过，检测题 150 条均已标注。正式胜出方案为 `buffalo_l`、关闭翻转 TTA、阈值 `0.43`、最小差值 `0.04`；不得根据 holdout 再调参。

## 1. 创建正式快照

先确认项目根目录下的 `.env` 指向正确的 SQLite 和 MinIO。程序不读取 `.env.example`。在项目根目录执行：

```powershell
python -m tools.face_benchmark create --workspace-id 1 --face-count 1000 --detection-count 150
```

如果评测全局旧数据，不传 `--workspace-id`。输出默认位于 `data/face-benchmark/<时间>/`，包含：

- 约 1000 张人脸身份题，按人物覆盖、未知/边界、困难样本和固定随机对照分层抽取。
- 约 150 张完整图片检测题，用于发现旧人脸记录中没有的漏检。
- 所有可用人物样本的本地副本。
- 独立 `benchmark.db`、不可变的 `selection.jsonl`、图片校验清单及 SHA-256。

快照创建后，不要手动修改图片、`selection.jsonl` 或 `file-checksums.json`。标注真值只写入 `benchmark.db`。所有候选必须使用同一个快照目录。

## 2. 人工标注与复查

手动启动独立标注页面：

```powershell
python -m tools.face_benchmark label data/face-benchmark/20260804-203852
```

浏览器访问 `http://127.0.0.1:8765`。页面支持按题型、标注状态和数据分区筛选，也支持上一题、下一题、指定序号跳转以及重新保存。

标注页面不返回、不展示历史预测人物、分数、困难分层或候选模型结果。对于已知人物，先输入名称搜索，选中人物后才按需读取该人物在快照中的参考样本。

标注规则：

- 身份题的绿色框表示本题唯一目标脸，只判断框内人物；裁剪图中即使出现其他完整或残缺人脸，也不要按旁边人物作答。
- 身份题默认显示裁剪图，可切换到原图确认目标人物所处位置。两种视图中的绿色框指向同一张目标脸。
- 目标脸属于样本库人物时选择该人物；目标脸不属于样本库或无法确认身份时选择“未知人物”。目标脸不可可靠辨认时选择跳过，不要根据旁边人物推断。
- 检测题填写完整图片中实际可见的人脸数量。
- 无法可靠判断时选择跳过，不要猜测。
- 首轮完成后，切换到“已标注”复查同名人物、相似人物、侧脸、遮挡、低清晰度、多人图片和未知人物。
- 修改已标注项后直接重新保存，新真值会覆盖该快照中的旧真值。

身份题裁剪图是在创建 benchmark 快照时，根据主数据库已有的人脸框对 MinIO 原图做 35% 外扩后新生成的文件。它只保存在快照的 `faces/` 目录，不写回主数据库或 MinIO；`originals/` 则是同一次快照创建时保存的原图副本。

对于 `data/face-benchmark/20260804-203852`，升级前在没有目标框提示时完成的 7 条身份标注已随全部身份题完成复查，无需再次启动标注服务。

## 3. 模型与许可记录

工具只接受已注册适配器，不再允许把任意 ONNX 当作兼容模型注入。当前注册项为 `buffalo_l`、`lvface-t`、`lvface-s` 和 `lvface-b`。AdaFace 尚无已验证的本项目 ONNX 适配器，不应参与正式比较。

| 适配器 | 权重来源 | 使用边界 |
| --- | --- | --- |
| `buffalo_l` | [InsightFace 模型库](https://github.com/deepinsight/insightface/tree/master/model_zoo) | 模型权重仅限非商业研究 |
| `lvface-t/s/b` | [LVFace 官方仓库](https://github.com/bytedance/LVFace) | 模型权重仅限非商业研究 |

评测报告的 `adapter` 字段会记录官方来源、许可名称、许可链接、本地模型路径和实际文件 SHA-256。正式对比前应确认权重来自该官方来源，并保留报告目录。

本机现有 `buffalo_l` 权重已校验：

| 文件 | SHA-256 |
| --- | --- |
| `w600k_r50.onnx` | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` |
| `det_10g.onnx` | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` |

本次使用的 LVFace 官方 ONNX 已保存在 `data/models/lvface/`，并按官方 Hugging Face 页面给出的 SHA-256 校验：

| 文件 | SHA-256 |
| --- | --- |
| `LVFace-T_Glint360K.onnx` | `bf8da0e1e93c432d9a1d874a9ba0990f5859f970e8864b3990f2f33d11f9cdb3` |
| `LVFace-S_Glint360K.onnx` | `cd09f27c82ce0a3633fb8b1966d779a7171b23aa4f14ca0de6edf9677573d119` |
| `LVFace-B_Glint360K.onnx` | `9d834ed8e927fd35b9123b2bf97c40aad05785b1f9ecfb1c4c1f6242d38d1382` |

权重不随代码提交。不要仅根据文件名判定权重身份，以文件哈希和生成报告为准。

## 4. calibration 评测

正式模型比较必须使用 `--provider cpu`，并固定检测器、检测尺寸和快照。先运行当前基线：

```powershell
python -m tools.face_benchmark evaluate data/face-benchmark/20260804-203852 --adapter buffalo_l --provider cpu
```

再运行翻转 TTA 和 LVFace 候选：

```powershell
python -m tools.face_benchmark evaluate data/face-benchmark/20260804-203852 --adapter buffalo_l --provider cpu --flip-tta
python -m tools.face_benchmark evaluate data/face-benchmark/20260804-203852 --adapter lvface-t --model-path D:\AI-MODELS\face\lvface-t.onnx --provider cpu
```

`auto` 按 CUDA、CoreML、CPU 的顺序选择。`coreml` 和 `cuda` 可用于性能实验，但不用于正式候选排名。显式选择的 Provider 不可用时，命令会直接失败，不会静默回退。

检测和嵌入结果默认缓存在快照的 `cache/` 下。缓存键包含快照校验值、图片校验值、检测模型和尺寸、识别模型 SHA-256、适配器版本、对齐规则、TTA 和实际 Provider。需要强制重算时使用 `--no-cache`。

每个 `results/` 结果目录包含：

- `report.json` 和中文 `report.md`：快照、命令、系统、模型、Provider、阈值、指标和缓存命中情况。
- `predictions.jsonl`：每张人脸的真值、Top1/Top2 人物与分数、差值、接纳结果、拒绝原因、困难桶、耗时，以及目标框、实际选中检测框、IoU 和选择方式。
- `detections.jsonl`：每张检测题的真实数量、检出数量和处理失败。
- `thresholds.csv`：阈值与最小差值组合的全量网格指标。

## 5. 候选比较与 holdout

选定一个 CPU 基线结果目录，将其他 CPU calibration 结果作为候选：

```powershell
python -m tools.face_benchmark compare --baseline <基线结果目录> <候选结果目录-1> <候选结果目录-2>
```

评测使用 `target-bbox-v1` 目标脸选择策略：优先选择包含旧目标框中心且 IoU 最高的检测框；没有检测框包含中心时，只接受 IoU 不低于 0.20 的最高重叠框，否则按目标脸未检出处理。比较命令会硬性校验同一快照、同一检测模型及尺寸、同一目标脸选择策略、同一逐脸真值和分层、且检测与识别都是 CPU。只有错误绑定数不高于基线、未知人物误接纳数不高于基线的参数才会进入排名。然后依次比较已知拒识、困难桶拒识、处理失败和耗时。

默认至少要有 100 条身份标注和 20 个已知人物，否则仍输出 `comparison.json`、`comparison.csv` 和中文 `comparison.md`，但不给出正式推荐。

模型、预处理、TTA、阈值和最小差值全部锁定后，只运行一次 holdout：

```powershell
python -m tools.face_benchmark evaluate data/face-benchmark/20260804-203852 --adapter <锁定适配器> --model-path <权重路径> --provider cpu --threshold <锁定阈值> --min-margin <锁定差值> --final-holdout
```

不得根据 holdout 结果再调参并将同一分区当作新的最终测试。

### 5.1 本次正式结果

calibration 比较报告位于：

`data/face-benchmark/20260804-203852/results/comparisons/20260805-172332-069020`

满足“错误绑定不增加、未知误接纳不增加”安全约束后的排序如下：

| 方案 | 阈值/差值 | 错误绑定 | 未知误接纳 | 已知拒识 | 平均单脸耗时 |
| --- | --- | ---: | ---: | ---: | ---: |
| `buffalo_l`，无 TTA | `0.43/0.04` | 5 | 2 | 129 | 164.529 ms |
| `buffalo_l`，翻转 TTA | `0.45/0.04` | 5 | 2 | 138 | 229.904 ms |
| 旧参数 `buffalo_l` | `0.45/0.08` | 5 | 2 | 153 | 164.529 ms |
| LVFace-B | `0.38/0.04` | 5 | 1 | 208 | 见对应报告 |
| LVFace-T | `0.43/0.05` | 5 | 1 | 211 | 见对应报告 |
| LVFace-S | `0.36/0.06` | 5 | 1 | 224 | 见对应报告 |

胜出方案的一次性 holdout 报告位于：

`data/face-benchmark/20260804-203852/results/buffalo_l-4c06341c33c2-holdout-20260805-172505-713835`

holdout 有 274 条有效身份题，其中已知 234 条、未知 40 条。锁定参数 `0.43/0.04` 的错误绑定为 2、未知误接纳为 0、已知拒识为 51；旧参数 `0.45/0.08` 的错误绑定同为 2、未知误接纳同为 0、已知拒识为 60。新参数在安全指标不恶化的情况下多接纳 9 条已知人物题，因此正式锁定。检测题 50 张，真实 60 张脸、检出 61 张，47 张图片计数完全一致，计数召回代理值为 `0.983333`。

## 6. 生产配置边界

共享运行时已被生产 `FaceService` 和离线评测共用。当前 `.env` 保持基线：

```dotenv
FACE_MODEL_NAME=buffalo_l
FACE_ADAPTER_ID=buffalo_l
FACE_RECOGNITION_MODEL_PATH=
FACE_EXECUTION_PROVIDERS=CPUExecutionProvider
FACE_REQUIRE_PRIMARY_PROVIDER=false
```

生产仍使用 `buffalo_l`、原嵌入版本和关闭 TTA；`.env` 的判定参数已更新为：

```dotenv
FACE_RECOGNITION_THRESHOLD=0.43
FACE_RECOGNITION_MIN_MARGIN=0.04
```

生产侧已增加 Top1/Top2、候选人物姓名、拒绝原因和判定参数留痕，并保留默认预演的全图库重识别工具。数据库字段已通过独立幂等迁移命令完成，不需要为迁移而启动前后端；本次开发过程没有主动启动前后端。新 Qdrant 集合已重建并写入 508 个样本点、173 个质心点，共 681 点，`.env` 已切换到该集合。当前 Windows ZIP 还原图库以 `metadata.json` 的人物绑定为事实来源，不执行全图库重识别；该工具仅在以后真正更换模型、预处理或嵌入版本，或明确要求旧图库重新应用识别结果时使用。完整状态和操作见 `face-recognition-upgrade-design.md` 第 10 节。

Windows NVIDIA 后续验证时可配置：

```dotenv
FACE_EXECUTION_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
FACE_REQUIRE_PRIMARY_PROVIDER=true
```

`FACE_REQUIRE_PRIMARY_PROVIDER=true` 用于阻止 CUDA 配置错误时静默回退 CPU。

### 6.1 展示图 ZIP 与全图库重识别的边界

展示图 ZIP 导入已经改为纯清单还原：人物标签和普通标签完全来自 `metadata.json`，不调用人脸模型或 Qdrant。新版导出协议为版本 2，`photos` 数组与网页图库使用同一排序，并写入连续 `display_index`；导入后整个批次置顶，批次内部按该序号稳定恢复。版本 1 仍按数组顺序兼容导入，但旧导出器本身按拍摄时间生成数组，所以无法承诺恢复旧电脑网页上的原顺序。

旧 Windows 包导入产生的未知人物污染使用 `app.tools.cleanup_gallery_zip_import` 按 SHA-256 专项清理，默认模式只查询和计数，不发出数据库写操作；正式执行必须同时提供 `--apply --confirm`。全图库重新识别不属于当前清理步骤，只在以后真正更换模型、预处理或嵌入版本，或明确要求旧图库重新应用识别结果时使用。完整命令、备份要求和本次预演计数见 `face-recognition-upgrade-design.md` 第 10.4 节。
