# 相似图片整理：本地模型配置

相似图片扫描使用 `facebook/dinov2-base`，输出 768 维整图向量。运行时只从 `.env` 的
`GALLERY_SIMILARITY_MODEL_PATH` 加载本地文件，并设置 `local_files_only=True`，不会自动联网下载。

## 安装 CUDA 推理依赖

在 `pictureshow` Conda 环境中依次执行：

```powershell
conda run -n pictureshow python -m pip install -r requirements-vision-cuda.txt
conda run -n pictureshow python -m pip install -r requirements.txt
```

## 下载模型

```powershell
conda run -n pictureshow hf download facebook/dinov2-base --local-dir E:/AI-MODELS/vision/dinov2-base
```

模型目录位于仓库之外，不应复制到项目或提交 Git。默认使用 CUDA 和批量 32；显存不足时扫描器会减小批次，CUDA 不可用时回退 CPU。

## 配置项

运行时只读取项目根目录 `.env`。以下字段需要保持完整：

- `GALLERY_SIMILARITY_MODEL_PATH`：本地 DINOv2 Base 模型目录。
- `GALLERY_SIMILARITY_MODEL_VERSION`：特征缓存版本；更换模型或预处理方式时应修改。
- `GALLERY_SIMILARITY_DEVICE`：默认 `cuda`，不可用时自动回退 CPU。
- `GALLERY_SIMILARITY_BATCH_SIZE`：DINOv2 推理批大小，默认 `32`；显存不足时会在当前批次内自动减半重试。
- `GALLERY_SIMILARITY_VECTOR_DIMENSION`：DINOv2 Base 固定为 `768`。
- `GALLERY_SIMILARITY_QDRANT_COLLECTION`：图库特征使用的独立 Qdrant collection。
- `GALLERY_SIMILARITY_NEAR_THRESHOLD`：近重复图片阈值。
- `GALLERY_SIMILARITY_SCENE_THRESHOLD`：同场景图片阈值。

## 使用流程

1. 确认 MinIO、Qdrant 和本地模型可用，然后由用户手动启动项目。
2. 进入“相似图片整理”，选择单个人物或全部人物。
3. 按需开启“跨普通/图文类型比较”；默认关闭时，同一图片即使同时存在于两类图库中也不会互相匹配。
4. 发起扫描并等待后台任务完成。
5. 在“近重复”与“同场景”页签中审核相似组，参考清晰度和尺寸生成的保留建议。
6. 勾选需要删除的图片并确认。系统不会根据建议自动删除任何图片。

图库内容或人物标签变化会把相关扫描标记为过期。过期结果仍可查看，但应重新扫描后再做清理决定。

## 资源与缓存

- 图片会在特征提取前按最长边 1024 像素缩放，避免一次扫描长期保留大量原图内存。
- DINOv2 按配置批量推理，16GB 显存运行 Base 版本通常足够；实际占用还会受同时运行的其他程序影响。
- 768 维向量写入独立 Qdrant collection，SQLite 只保存感知哈希、质量分和向量点位标识。
- 图片 SHA256、模型版本或向量缓存不一致时会自动重算特征。
