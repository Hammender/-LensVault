# 人脸识别准确率评测与升级设计

## 1. 文档用途和当前状态

本文是人脸识别准确率提升工作的总设计和执行手册。它面向两类读者：

- 使用者：按本文完成快照创建、人工标注、模型评测、生产切换和验收。
- 后续开发者或 AI：不依赖此前对话，也能知道现有实现、未完成工作、代码边界和验收标准。

当前状态：**正式快照、人工标注与复查、Mac CPU calibration、LVFace 候选比较和一次性 holdout 已完成；生产方案已经锁定并完成代码接入。** 快照为 `data/face-benchmark/20260804-203852`，包含 1000 条身份题和 150 条检测题；身份题中 987 条已标注、13 条跳过，检测题 150 条均已标注。胜出方案仍是 `buffalo_l`、关闭翻转 TTA，只把阈值调整为 `0.43`、最小差值调整为 `0.04`。当前 Windows ZIP 还原图库以清单标签为事实来源，不执行全图库重新识别。不得重建快照、清空真值或根据 holdout 再调参。

现有的 [人脸识别离线评测](face-benchmark.md) 说明基础命令；本文定义整个改进任务的设计意图、实施顺序和完成条件。两份文档冲突时，以本文为准。

## 2. 要解决的问题

当前系统用人脸样本向量和人物质心在 Qdrant 中检索，依次得到不同人物的 Top1、Top2 分数。只有同时满足以下条件时，系统才自动把该人脸绑定到 Top1 人物：

1. Top1 分数不低于 `FACE_RECOGNITION_THRESHOLD`。
2. Top1 与 Top2 的差值不低于 `FACE_RECOGNITION_MIN_MARGIN`。

第二条是为了避免两个相似人物之间的错误自动绑定。它会产生一种看似反常但符合设计的结果：例如 Top1 为 0.501，高于 0.45 阈值，但 Top2 为 0.447，差值约 0.054，小于 0.08 最小差值，因此该脸仍应被判定为未知。

问题不应只靠降低阈值解决。降低阈值通常会减少已知人物的拒识，却会提高错误人物绑定和未知人物误接纳。此次工作要用独立的真值数据，判断是模型、预处理、样本质量、阈值、最小差值还是检测失败造成问题，并在不牺牲错误绑定控制的前提下提高已知人物识别率。

## 3. 总体设计

评测、生产和人工真值必须分层，数据流如下：

```text
主程序 SQLite + MinIO（只读）
            |
            v
冻结快照：图片副本、人物样本副本、抽样清单、独立 benchmark.db
            |
            +--> 独立标注页面：只写 benchmark.db
            |
            +--> 候选模型评测：只读快照，输出结果目录
                                      |
                                      v
                             锁定模型和判定参数
                                      |
                                      v
新版本生产适配器 + 已验证 Qdrant 集合 + ZIP 清单纯还原
```

冻结快照是唯一的正式评测数据。任何候选模型都不得修改其中的图片、抽样清单、数据分区或人工真值。需要研究新的失败场景时，另建挑战集，不修改正式快照。

评测阶段不接触生产 Qdrant 集合，也不修改主数据库、MinIO 原图或正式图库标签。生产切换必须新建集合，验证后才通过 `.env` 切换，始终保留旧集合用于回滚。

## 4. 已有实现及其边界

当前已有的 `tools/face_benchmark` 可以：

- 从 SQLite 和 MinIO 只读创建快照，并保存 `selection.jsonl`、文件 SHA-256 和独立 `benchmark.db`。
- 分层抽取人物覆盖、未知/边界、困难和随机人脸题，以及完整图片检测题。
- 让同一张原图固定进入 calibration 或 holdout，避免同图泄漏到两个分区。
- 通过本地 HTTP 标注页面标记真实人物、未知人物和完整图片中的人脸数。
- 计算 Top1、Top2、阈值、最小差值、错误自动绑定、已知拒识和未知误接纳等指标。
- 使用 CPU 或 Windows CUDA Provider 运行 `buffalo_l`，并对 Qdrant 使用版本化集合重建脚本。

第 8 节已补齐的能力：

- 生产与评测共用 `face_runtime`，包含显式模型适配器、严格输入/输出合同、统一对齐和嵌入归一化。
- Provider CLI 支持 `cpu`、`coreml`、`cuda` 和 `auto`，显式模式不可用时直接失败。
- 检测缓存和嵌入缓存使用快照、图片、模型、适配器、TTA 和 Provider 维度生成键。
- 每次评测输出逐脸 Top1/Top2、分数、差值、拒绝原因、困难桶和耗时，并可用统一安全约束比较 calibration 候选。
- 标注页面支持筛选、跳转、已标注复查和修改，并向标注者隐藏历史预测与分数。

仍存在的边界：

- 检测题仅记录真实人脸数量，得到的是计数召回代理值，不是检测框 IoU 指标。
- 旧版展示图 ZIP 导入曾在恢复清单标签后再次做人脸识别，可能给同一照片同时留下正确导入人物和错误未知人物。该问题使用按旧清单 SHA-256 圈定的专项命令清理，不通过全图库重新识别修复。
- 检测题尚未标注检测框，所以检测指标仍是计数代理值。

## 5. 平台与运行环境

### 5.1 M5 Mac 是本次工作的主平台

这台 24G 内存的 M5 Mac 可以完成数据快照、人工标注、CPU 基线、候选模型准确率评测、阈值校准、生产代码改造和 Qdrant 重建。候选模型必须以标准 ONNX 推理为主，并使用 512 维归一化嵌入，保证可在 Windows NVIDIA 上复用。全图库重新识别工具也能在 Mac CPU 上运行，但本次方案不需要执行它。

当前环境已经提供 `CoreMLExecutionProvider`。后续工具应增加显式 `--provider coreml`，使用 `CoreMLExecutionProvider,CPUExecutionProvider`。CoreML 是加速选项，不是准确率真值来源：正式候选选择以 CPU 结果为准，CoreML 用于缩短运行时间并做一致性检查。若 CoreML 出现不支持算子、明显数值偏差或性能不佳，直接使用 CPU，不影响方案完成。

ONNX Runtime 的 CoreML Provider 支持 macOS，并可使用 CPU、GPU 和 Neural Engine；其执行提供器与 CUDA、CPU 使用同一个 ONNX Runtime 接口。参考 [ONNX Runtime CoreML Provider](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html) 和 [ONNX Runtime Execution Providers](https://onnxruntime.ai/docs/execution-providers/)。

### 5.2 Windows NVIDIA 是后续性能平台

Windows 台式机恢复可用后，安装 CUDA Provider，使用同一个适配器、同一个模型文件、同一个模型哈希、同一个预处理版本和同一套阈值。需要执行的仅是：

1. 确认 `CUDAExecutionProvider` 可加载，不能静默回退 CPU。
2. 使用固定的 100 张校验样本与 Mac CPU 结果比较。
3. 验证 Top1 人物和最终接纳结果完全一致；平均嵌入余弦相似度不低于 0.999，单项不低于 0.995。
4. 记录吞吐量、单图耗时和显存占用。

这属于平台验收，不能替代也不需要重新做人工标注或模型选择。若 CUDA 未通过一致性门槛，Windows 可先使用 CPU；不得为了速度改变模型或阈值。

### 5.3 环境隔离

评测建议使用独立 Conda 环境，避免安装候选模型依赖影响主程序环境。标注工具只需要快照和 Python 标准库；候选模型、缓存、评测报告全部存放在 `data/face-benchmark/` 或本地模型目录，不提交 Git。

主程序仍只读取 `.env`。生产配置变更必须同时维护 `.env` 的完整值；`.env.example` 只放不含隐私信息的字段示例。

## 6. 候选模型和适配器合同

### 6.1 候选顺序

候选模型按以下顺序评测，不直接相信公开榜单：

1. `buffalo_l`：当前基线。
2. `buffalo_l + flip TTA`：验证翻转增强是否改善本图库困难照片。
3. LVFace-T、LVFace-S、LVFace-B 的官方 ONNX：优先选体积和速度更可控的 T/S/B，不优先测试 L。
4. AdaFace IR50、IR100：在完成正确预处理和 ONNX 数值校验后纳入。
5. 其他模型：仅在有官方权重来源、可用许可证和完整适配器合同后加入。

LVFace 官方仓库提供 ONNX 和 PyTorch 推理权重，但模型权重声明为非商业研究用途；InsightFace 模型库也声明模型仅用于非商业研究。若本项目将用于商业用途，必须在选型前取得替代权重的明确商业许可。参考 [LVFace 官方仓库](https://github.com/bytedance/LVFace) 和 [InsightFace 模型库许可说明](https://github.com/deepinsight/insightface/blob/master/model_zoo/README.md)。

AdaFace 的官方推理要求五点对齐后的 112x112 BGR 图像，并使用特定的 `mean=0.5`、`std=0.5` 预处理；不能假定其与 InsightFace 默认 RGB 预处理相同。参考 [AdaFace 官方说明](https://github.com/mk-minchul/adaface)。

### 6.2 模型适配器必须声明的内容

每个模型不得只提供一个 ONNX 文件路径，而必须有明确的适配器清单。清单和运行报告必须包含：

| 字段 | 目的 |
| --- | --- |
| 适配器 ID、版本 | 防止同名模型使用不同处理逻辑 |
| 模型文件路径和 SHA-256 | 确认实际评测和生产使用同一权重 |
| 输入宽高、布局 | 防止 NCHW/NHWC 或尺寸错误 |
| RGB/BGR、像素范围、均值和方差 | 防止颜色和归一化错误导致低分 |
| 对齐模板与关键点顺序 | 保证人脸裁剪方式可复现 |
| 输出名称、输出维度、归一化规则 | 确认可用于余弦检索 |
| 是否支持翻转 TTA | 防止对不兼容模型错误增强 |
| Provider 兼容性和许可证 | 约束 Mac/Windows 部署和使用范围 |

识别模型比较期间固定检测器、检测尺寸和人脸排序策略，只替换识别适配器。检测器本身的升级作为单独实验，否则无法判断识别率变化是识别网络还是检测变化造成的。

## 7. 真值数据和评测规则

### 7.1 创建快照

工具从主程序数据只读抽取约 1000 张人脸身份题和约 150 张完整图片检测题，并复制所有可用人物样本。抽样依赖已有元信息，不会为了抽样重新运行候选模型。

快照创建完成后，使用者应保存整个快照目录。`selection.jsonl` 和校验文件不可手动编辑；任意候选模型都使用完全相同的快照。

### 7.2 人工标注

身份题只判断绿色目标框内的人物，只能标记为一个真实人物或“未知人物”；裁剪图中其他完整或残缺人脸不是题目对象。标注人可在裁剪图与原图之间切换确认目标位置。完整图片题记录其中真实人脸数量。标注人只判断事实，不看候选模型分数或预测结果，避免人为偏向。

标注完成后必须有复查阶段：优先复查同名人物、相似人物、低清晰度、侧脸、遮挡、多人照片和被标为未知的项目。人工真值与模型无关，因此只要快照不变，后续换模型、换 Provider、迁移 Windows 都不需要重新标注。

检测题在本阶段仅作为“漏检趋势”指标。若检测计数代理值显示明显问题，再新增检测框标注和 IoU 评测；不要一开始就让人工标注检测框，避免把主要的人脸身份识别任务拖慢。

### 7.3 calibration 和 holdout

`calibration` 用于模型对比、阈值和最小差值选择。`holdout` 在模型、预处理、TTA、阈值和最小差值全部锁定后只运行一次。holdout 的失败表示候选没有通过，不允许根据 holdout 继续调参后再把同一结果当作最终成绩。

每次报告必须记录：快照 ID、快照校验值、命令、模型和模型哈希、适配器版本、Provider、检测尺寸、TTA、运行系统、结果时间。

## 8. 评测前必须补齐的代码

以下修改共同构成评测前置完成条件。前 8 项在正式快照创建前完成；第 9 项是在开始标注后发现并修正的目标语义缺口，现有快照无需重建：

1. 新增共享人脸模型运行时模块，例如 `face_runtime/`，由 `tools/face_benchmark` 与 `backend/app/services/face.py` 同时调用。禁止评测和生产各自复制一份预处理代码。
2. 将 `tools/face_benchmark/evaluate.py` 中的 `InsightFaceAdapter` 改为适配器注册表，移除“任意 ONNX 都兼容”的假设。
3. CLI Provider 改为 `cpu`、`coreml`、`cuda`、`auto`。`auto` 的优先级为 CUDA、CoreML、CPU；显式选择的 Provider 不可用时直接失败。
4. 新增检测缓存和嵌入缓存。缓存键至少包含快照校验值、检测模型和尺寸、模型 SHA-256、适配器版本、TTA 和 Provider。
5. 新增逐脸 `predictions.csv` 或 `predictions.jsonl`，保存真实人物、Top1/Top2 ID 和名称、分数、差值、接纳结果、拒绝原因、困难桶和耗时。
6. 新增候选比较命令，按统一安全约束从 calibration 结果中选择参数，并输出可阅读的差异报告。
7. 标注页面增加筛选、已标注复查、跳转和重新保存功能，所有修改仍只写快照的 `benchmark.db`。
8. 为适配器预处理、缓存失效、阈值/差值逻辑、逐脸报告和标注修改添加测试。
9. 身份题页面必须根据快照已有 `bbox_json` 在裁剪图和原图中显示同一目标脸；评测必须使用 `target-bbox-v1` 选择目标检测框，禁止默认取最大脸或检测列表第一张脸。逐脸结果记录目标框、选中框、IoU 和选择方式，候选比较拒绝目标脸策略不一致的结果。

建议新增或调整的文件如下：

| 文件 | 工作 |
| --- | --- |
| `face_runtime/adapters.py` | 模型适配器合同、预处理、推理与嵌入归一化 |
| `face_runtime/providers.py` | CPU/CoreML/CUDA Provider 选择与校验 |
| `tools/face_benchmark/evaluate.py` | 使用共享适配器、缓存和逐脸结果 |
| `tools/face_benchmark/cli.py` | Provider、适配器、缓存和比较命令参数 |
| `tools/face_benchmark/server.py` | 标注复查和修改能力 |
| `tools/face_benchmark/compare.py` | calibration 结果比较与候选选择 |
| `backend/app/services/face.py` | 使用共享适配器，而非固定 InsightFace 模型 |
| `backend/tests/` | 快照、适配器、评测和迁移测试 |

## 9. 候选选择和验收标准

候选选择采用安全优先的固定顺序：

1. 错误自动绑定数不得高于基线；若基线为零，候选也必须为零。
2. 未知人物误接纳率不得高于基线。
3. 在满足前两条的候选中，优先降低已知人物拒识率。
4. 再比较困难桶的拒识率、样本解析失败数和耗时。
5. 使用锁定 holdout 验证上述结论没有失效。

不能仅凭平均匹配分数、单张“看起来明显”的图片或公开 LFW/IJB 分数选择模型。目标是降低真实图库中的漏识，同时不把陌生人或相似人物自动绑定到错误人物。

当模型选定后，阈值和最小差值也随模型一起版本化。不同模型的余弦分数分布不同，不能把旧 `0.45`/`0.08` 当作永久正确参数。

### 9.1 已完成的正式选择

正式 calibration 比较目录为 `data/face-benchmark/20260804-203852/results/comparisons/20260805-172332-069020`。`buffalo_l` 无 TTA 在 `0.43/0.04` 下得到 5 个错误绑定、2 个未知误接纳、129 个已知拒识；旧 `0.45/0.08` 参数的安全指标相同，但有 153 个已知拒识。翻转 TTA 的已知拒识为 138 且更慢。LVFace-T/S/B 虽各少 1 个未知误接纳，但已知拒识分别为 211、224、208，均明显差于胜出方案。

锁定后的唯一一次 holdout 位于 `data/face-benchmark/20260804-203852/results/buffalo_l-4c06341c33c2-holdout-20260805-172505-713835`。新参数与旧参数同为 2 个错误绑定、0 个未知误接纳，新参数把已知拒识从 60 降到 51。因此模型不更换，生产只调整阈值与差值，并保留现有 `buffalo_l-v2-exif` 嵌入版本。holdout 已经消耗，不得再次用它选择参数。

## 10. 生产代码和数据迁移

### 10.1 保存候选信息

生产 `FaceRecord` 增加独立的 `predicted_person_id`（或等价 `top1_person_id`）字段。保留现有 `matched_person_id` 作为最终实际绑定人物。每条脸记录还必须保存 Top1 分数、Top2 人物、Top2 分数、差值、拒绝原因、模型适配器版本和嵌入版本。

这样，当人脸显示未知时，界面和诊断工具仍能说明：第一候选是谁、第二候选是谁、是低于阈值还是差值不足。它直接解决“分数高于阈值却被标为未知，且无法知道第二名是谁”的排查困难。

该部分已经实现。`FaceRecord` 现在分别保存 `matched_person_id` 与 `predicted_person_id`，并保存 Top1 分数、Top2、差值、`rejection_reason`、`recognition_adapter_id`、`embedding_version`、`decision_threshold` 和 `decision_min_margin`。图库详情页会显示第一候选、第二候选、分数、差值及中文拒绝原因。旧行新增字段为空；新导入和重新识别的行会完整写入。

拒绝原因固定为：`no_candidate`、`candidate_not_found`、`below_threshold`、`insufficient_margin`。人工修正只改变最终绑定，不再把原始预测分数覆盖为 `1.0`，因此纠错后仍可追溯模型当时的真实判断。

### 10.2 重建新索引

模型、预处理或嵌入版本变化后，旧向量不能与新查询向量混用。必须：

1. 使用选定适配器重新解析所有有效人物样本。
2. 新建独立 Qdrant 集合，不覆盖当前活动集合。
3. 写入每个样本向量和每个人物质心向量。
4. 校验向量维度、L2 归一化、样本数量、质心数量、人物覆盖、模型哈希和 payload 完整性。
5. 只有校验通过后，才在 `.env` 更新 `QDRANT_KNOWN_COLLECTION`、`FACE_EMBEDDING_VERSION`、模型适配器和判定参数。

Qdrant 点数可以大于人物样本照片数：每张可用样本通常对应一个点，另有每个人物一个质心点。点数是否正确应以“有效样本点数 + 人物质心点数”的预期值验证，而不是只看原始图片总数。

本次胜出模型、预处理和嵌入版本没有变化，理论上无需为了参数调整重建向量。仍建议执行一次版本化重建以验证当前 400 多张样本是否都能重新解析，并核对“样本点 + 人物质心点”与当前约 670 个点的关系。命令只创建非活动集合，不覆盖当前集合：

```bash
PYTHONPATH=.. conda run -n pictureshow python -m app.tools.rebuild_face_index \
  --collection pictureshow_known_faces_buffalo_l_verified_20260805 \
  --embedding-version buffalo_l-v2-exif
```

该命令在 `backend/` 目录运行。只有输出 `ready_for_activation: true` 且 `missing_person_ids` 为空，才允许把 `.env` 的 `QDRANT_KNOWN_COLLECTION` 改为新集合。旧集合不得删除。

本次已在 2026-08-05 实际执行并激活新集合 `pictureshow_known_faces_buffalo_l_verified_20260805`。结果为：数据库中有 508 张 `ready` 样本、173 个有样本人物；成功写入 508 个样本点和 173 个质心点，共 681 点；跳过 0、缺失人物 0、无效 payload 0、无效向量 0，`ready_for_activation` 为 `true`。因此旧集合约 670 点并非对应 670 张样本，它同样包含人物质心，而且比当前完整索引少 11 个点。旧集合继续保留，用于必要时回滚。

### 10.3 展示图 ZIP 的事实来源和稳定顺序

展示图 ZIP 是图库状态快照，`metadata.json` 是人物标签、普通标签和展示顺序的事实来源。新版导入直接写入对象存储和 `GalleryPhoto`，不会调用人脸检测、不会生成嵌入、不会查询 Qdrant，也不会因为本机分数低而额外创建未知人物绑定。普通前端上传仍按原流程做人脸识别；人物样本 ZIP 仍会检测人脸、生成样本向量并写入 Qdrant。

遇到相同 SHA-256 的已有展示图时，导入会用清单完全覆盖文件名、媒体类型、尺寸、拍摄时间、富文本、OCR 状态、普通标签和人物绑定，并删除该照片原有的识别人脸记录。已知人物来源写为 `import`，清单明确包含的未知人物来源写为 `import_unknown`。缺文件、SHA-256 不一致或单项字段非法时只记为跳过，不做人脸识别兜底。

图库统一按以下字段排序：

```text
display_batch_at DESC,
display_index ASC,
created_at DESC,
id DESC
```

每次 ZIP 导入共用一个 `display_batch_at`，并按清单得到连续的 `display_index`。因此后导入批次整体置顶，同一批内部不穿插；重复照片再次导入时移动到新批次对应位置。应用启动时的幂等迁移只给旧照片回填 `display_batch_at = created_at`、`display_index = 0`，保持当前 Mac 图库已有相对顺序，不利用旧 ZIP 修复历史顺序。

导出清单版本 2 复用图库列表的同一排序，并给每项写入连续 `display_index`。版本 2 导入严格按该字段恢复，缺失、重复或不连续会拒绝整个清单。版本 1 继续兼容并按 `photos` 数组顺序导入，但旧导出器曾按拍摄时间而不是网页顺序生成数组，因此版本 1 无法承诺还原源图库顺序。全量导出和筛选导出遵循同一协议，筛选包导入后也作为一个新批次置顶。

### 10.4 清理旧 ZIP 导入产生的错误未知数据

专项命令为 `backend/app/tools/cleanup_gallery_zip_import.py`。它按原始 `metadata.json` 中的 SHA-256 精确圈定照片，只删除这些照片与系统未知人物之间的绑定、这些照片下最终匹配人物为系统未知人物的 `FaceRecord`，并把清单中确实存在的已知人物绑定来源改为 `import`。它不会删除未知人物本身，不修改图片文件、普通标签、样本照片、Qdrant、正确人物绑定或图库顺序。

该命令只适用于“原清单没有任何未知人物绑定”的旧导出包；如果清单本身包含未知人物，它会直接拒绝执行。操作前先停止后端并备份 `.env` 中 `DATABASE_URL` 指向的数据库。以下命令均在 `backend/` 目录运行。

1. 预演，不写数据库：

```bash
PYTHONPATH=.. conda run -n pictureshow python -m app.tools.cleanup_gallery_zip_import \
  /Users/hamender/PycharmProjects/gallery_export_20260729_191917/metadata.json \
  --workspace-id 1
```

2. 核对输出：当前旧包的 `manifest_photos` 应为 11082，`manifest_unique_sha256` 应为 11064，二者相差 18 是因为清单包含重复内容。2026-08-05 对工作区 1 的只读预演得到：`matched_photos = 11081`、`matched_unique_sha256 = 11063`、`affected_photos = 11070`、`unknown_tags_deleted = 1056`、`unknown_faces_deleted = 1630`、`known_sources_changed = 11602`、`applied = false`。记录数多于唯一 SHA 是因为普通图片与图文图片允许共用图片内容。当前两条示例命令都应增加 `--workspace-id 1`，避免以后新增工作区后扩大范围。

3. 确认备份和预演范围无误后正式执行，两个确认参数缺一不可：

```bash
PYTHONPATH=.. conda run -n pictureshow python -m app.tools.cleanup_gallery_zip_import \
  /Users/hamender/PycharmProjects/gallery_export_20260729_191917/metadata.json \
  --workspace-id 1 \
  --apply --confirm
```

4. 再次运行不带 `--apply --confirm` 的预演命令。正常结果是删除和来源修正计数均为 0。随后由使用者手动启动程序，抽查原来同时带正确人物和未知人物的照片；不要求也不应重新识别整库。

### 10.5 可选的全图库重新识别工具

`backend/app/tools/rerecognize_gallery.py` 继续保留，支持预演、逐图事务、审计和 `--resume`。它不是本次 ZIP 污染清理步骤，也不是当前准确率方案的完成条件。本次仍使用 `buffalo_l`、同一预处理和 `buffalo_l-v2-exif` 嵌入，只改变判定阈值和最小差值，因此无需重新生成所有展示图的人脸记录。

只有以后真正更换嵌入模型、预处理或嵌入版本，或者业务上明确要求旧图库重新应用最新识别结果时，才执行全图库重新识别。届时必须先备份数据库、建立并验证新的 Qdrant 集合，再预演抽查审计；正式执行必须显式使用 `--apply --confirm`。迁移只能替换自动来源，必须保留 `manual`、`import` 和 `import_unknown`。旧集合和数据库备份在验收完成前不得删除。

## 11. 建议删除或替换的旧代码

完成共享适配器后：

- 删除 `tools/face_benchmark/evaluate.py` 内重复的 `InsightFaceAdapter`。
- 删除或废弃宽泛的 `--recognition-onnx` 直接注入方式，改为显式 `--adapter`，防止错误预处理。
- 将 `backend/app/tools/evaluate_face_recognition.py` 改名并定位为“上线后人工纠错趋势监控”；它不能替代冻结快照评测。若新的监控实现已覆盖其职责，再删除旧脚本和 README 中的旧入口。
- 保留并升级 `backend/app/tools/rebuild_face_index.py` 和 `backend/app/tools/diagnose_face_match.py`，使其调用同一生产适配器并输出模型版本、Top1/Top2 明细。

不得删除冻结快照、最终报告、模型文件校验记录、旧 Qdrant 集合或迁移审计，直到新方案稳定运行并确认不需要回滚。

## 12. 使用者实际操作清单

当前按以下顺序操作；括号内为本次实际状态：

1. 已完成：创建独立评测环境和本地模型目录。结果：不会影响主程序环境。
2. 已完成：创建一次正式冻结快照。原因：所有候选必须在同一批数据上比较。结果：得到可重复、可校验的评测目录。
3. 已完成：完成人工标注并进行复查。原因：模型比较必须有独立真值。结果：模型以后怎么更换都无需再标注。
4. 已完成：在 Mac CPU 上运行 `buffalo_l` 基线。原因：先量化当前问题。结果：得到后续候选的安全下限。
5. 已完成：在 calibration 中评测候选适配器、TTA 和阈值/差值组合。结果：得到可比较的逐脸错误报告。
6. 已完成：锁定候选后运行一次 holdout。结果：确认方案没有只对调参数据有效。
7. 已完成：接入生产适配器并重建新的 Qdrant 集合。结果：新模型不会污染旧索引。
8. 已完成：`.env` 已切换到校验通过的新集合，生产锁定为 `buffalo_l`、`0.43/0.04`。结果：后续普通上传使用评测胜出参数。
9. 由使用者执行：先备份数据库，再预演并正式运行第 10.4 节专项清理命令。结果：只移除旧 ZIP 导入污染，不重新识别或改动图库顺序。
10. 由使用者验收：手动启动新版程序，抽查污染照片，并验证以后版本 2 ZIP 的批次顺序。结果：清单人物不会再与本机识别产生的未知人物并存，导入顺序可稳定迁移。
11. 可选维护：仅在模型、预处理或嵌入版本变化时按第 10.5 节执行全图库重新识别。
12. 后续平台验收：Windows 可用后运行 CUDA 一致性和性能验收。结果：获得更高吞吐量，不改变已确认的准确率结论。

## 13. 完成定义

本任务只有同时满足以下条件才算完成：

- 正式冻结快照已创建、完整性校验通过，人工真值已完成复查。
- 至少完成基线、候选模型 calibration 和一次 holdout 评测。
- 胜出方案在 holdout 上满足错误自动绑定和未知误接纳硬约束，并改善或不恶化已知人物拒识。
- 模型适配器、模型哈希、预处理、阈值、最小差值和嵌入版本均有记录。
- 新 Qdrant 集合校验通过，未覆盖旧集合。
- 展示图 ZIP 导入不调用人脸服务或 Qdrant，清单标签可精确覆盖重复照片。
- 版本 2 导出顺序与图库列表一致，导入后批次整体置顶且内部顺序稳定。
- 旧 ZIP 污染已用专项命令预演、备份后清理并完成人工抽查；全图库重新识别不是本次完成条件。
- 每条被判未知的人脸都可查到 Top1、Top2、分数、差值和拒绝原因。
- Mac 生产流程完成验收；Windows CUDA 一致性和性能验收作为后续平台验收项记录。
