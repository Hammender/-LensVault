# PictureShow（本地人脸图库）

PictureShow 是一个单用户、完全本地运行的人脸图库：

- 原图以对象形式写入本地 MinIO（不在仓库目录里落一堆可直接打开的 `jpg/png` 文件）
- 元数据、人物、标签、人脸检测与识别结果存入 SQLite
- 前端提供批量导入、人物样本库、按标签筛选分页浏览、未知人脸聚类归并、原图查看与纠错

## 开发期运行（源码直跑）

### 1) 启动 MinIO

确保有一个本地 MinIO 实例可用，默认配置如下（可通过 `.env` 覆盖）：

- Endpoint: `127.0.0.1:9000`
- Access Key: `pictureshow`
- Secret Key: `pictureshow-secret`
- Bucket: `photos`

`.env.example` 中已给出默认值。

### 2) 启动后端（FastAPI）

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
cd ..
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --app-dir backend
```

后端地址：`http://127.0.0.1:8000`

### 3) 启动前端（React + Vite）

你的 PowerShell 可能禁用 `npm.ps1`，因此这里使用 `npm.cmd`：

```powershell
cd frontend
cmd /c npm.cmd install
cmd /c npm.cmd run dev
```

前端地址：`http://127.0.0.1:5173`（`/api` 会代理到后端）

## 主要能力

- 批量导入图片：后台异步识别，任务有进度与状态。
- 人物库：先创建人物，再上传样本照写入人物特征库。
- 未知人脸聚类：未命中人物库的人脸会被聚类，可在前端命名归并到某人物。
- 标签检索：按人物标签分页查询图片列表。
- 原图查看：详情查看直接读取 MinIO 原图对象流，不做“压缩后落盘”。
- 纠错与重跑：支持移除标签、对单张图片重新识别。

## 目录结构

- `backend/`：FastAPI、SQLite、MinIO、识别/聚类服务。
- `frontend/`：React + Vite 前端页面。
- `.env.example`：配置模板。

## 备注

- InsightFace 首次运行可能需要下载模型或准备本地模型文件；目前按 CPU 基线实现。
- 开发阶段默认源码直跑；Docker 相关文件仅为后续打包预留。
