# LensVault

LensVault 是一个本地优先的智能媒体库，用来管理图片、图文和视频素材。它把原始文件存入本地 MinIO，把元数据写入 SQLite，并通过人脸识别、向量检索、OCR、视频转码和本地字幕生成，把散落的媒体文件整理成可搜索、可筛选、可回看的内容资产。

> 项目历史名称为 PictureShow，代码、环境变量示例和对象存储前缀中仍可能保留 `pictureshow` 字样。

## 主要功能

- 图片图库：批量导入展示图，按人物、普通标签、排除条件分页筛选，支持 ZIP 导入导出。
- 相似图片整理：按同一人物标签扫描近重复图片和同场景图片，支持普通图库与图文图库分开或跨类型比较，并由用户勾选后复用图库批量删除流程。
- 人物样本库：维护人物与样本照，使用 InsightFace 提取人脸特征并写入 Qdrant。
- 未知人物归并：未命中样本库的人脸统一标记为“未知人物”，不写入向量库，可在图库详情中重新识别或改为正式人物。
- 图文 OCR：支持图文图片导入，自动提取文字，也可以手动编辑图文内容。
- 视频库：支持 MP4、MKV、MOV、WEBM 分片上传、分类、UP 主/人物绑定、封面生成和在线播放。
- 播放优化：使用 FFmpeg/FFprobe 生成封面、应用 faststart，并可按配置转码为更适合浏览器拖动播放的格式。
- 中文字幕：使用 faster-whisper 做语音识别，并通过本地 OpenAI-compatible 翻译服务生成 WebVTT/SRT 字幕。
- 多账号与工作区：支持初始化管理员、注册登录、私人空间、共享空间、成员邀请和细粒度权限。
- 统计面板：查看图库、人物、标签、上传历史和素材规模。

## 技术栈

- 后端：FastAPI、SQLAlchemy、SQLite、MinIO、Qdrant、InsightFace、Pillow、FFmpeg。
- 前端：React 18、Vite、TypeScript、lucide-react。
- AI 能力：InsightFace 人脸识别，DINOv2 Base 768 维图片特征，RapidOCR 或 pytesseract OCR，faster-whisper ASR，本地 llama-server/Hy-MT2 翻译。

## 目录结构

```text
backend/                 FastAPI 服务
  app/main.py            API 路由与应用初始化
  app/models.py          SQLAlchemy 数据模型
  app/schemas.py         Pydantic 请求与响应模型
  app/services/          图片、人脸、OCR、视频、字幕、存储等服务
  app/core/config.py     环境变量配置
frontend/                Vite + React 前端
  src/App.tsx            主应用与页面流程
  src/api.ts             前端 API 封装
  src/types.ts           前端类型定义
  src/Home.tsx           首页
openspec/                功能变更设计记录
requirements.txt         Python 依赖
docker-compose.yml       本地 MinIO 与 Qdrant 依赖服务
.env.example             环境变量模板
```

## 环境要求

- Windows 本地开发环境优先；其他系统需要自行调整路径和脚本。
- Python 3.11 或 3.12 建议优先使用。Python 3.13 下 RapidOCR 依赖可能不可用，会走 pytesseract 备用路径。
- Node.js 与 npm。
- Docker Desktop，用于启动 MinIO 和 Qdrant。
- FFmpeg 与 FFprobe，并确保命令在 `PATH` 中，或在 `.env` 中配置绝对路径。
- 可选：支持 CUDA 的 NVIDIA 显卡；相似图片扫描默认使用 DINOv2 Base，CUDA 不可用时会回退 CPU。
- 可选：Tesseract OCR、本地 faster-whisper 模型、本地 Hy-MT2 GGUF 模型和 llama-server。

## 快速开始

### 1. 准备配置

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

然后按本机环境修改 `.env`。尤其注意：

- `DATABASE_URL` 和 `DATA_DIR` 默认是开发者本机路径，开源部署时应改成自己的数据目录。
- `SUBTITLE_ASR_MODEL_PATH`、`SUBTITLE_TRANSLATION_MODEL_PATH`、`SUBTITLE_LLAMA_SERVER_PATH` 只有在使用字幕功能时才需要配置。
- `GALLERY_SIMILARITY_MODEL_PATH` 需要指向完整的本地 DINOv2 Base 模型目录；安装与下载命令见 `docs/gallery-similarity.md`。
- `AUTH_SECRET_KEY` 发布或长期使用前必须改成随机强密钥。
- `CORS_ORIGINS` 需要包含实际前端地址。

### 2. 启动依赖服务

`docker-compose.yml` 提供 MinIO 和 Qdrant。当前 compose 文件使用了 Windows 主机绝对路径，首次使用前请先把 `volumes` 改成你自己的持久化目录。

```powershell
docker compose up -d
```

默认服务：

- MinIO API: `http://127.0.0.1:19000`，容器内端口仍是 `9000`
- MinIO Console: `http://127.0.0.1:19001`，容器内端口仍是 `9001`
- Qdrant REST/UI: `http://127.0.0.1:16333`，容器内端口仍是 `6333`
- Qdrant gRPC: `127.0.0.1:16334`，容器内端口仍是 `6334`

### 3. 启动后端

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --app-dir backend
```

后端默认地址：`http://127.0.0.1:8000`

接口文档：`http://127.0.0.1:8000/docs`

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### 4. 启动前端

```powershell
cd frontend
cmd /c npm.cmd install
cmd /c npm.cmd run dev
```

前端端口由 `frontend/vite.config.ts` 控制，也可以用 `VITE_FRONTEND_PORT` 覆盖。Vite 启动后会输出实际访问地址，`/api` 会代理到后端。

### 5. 首次使用

打开前端后，系统会检测是否需要初始化管理员。首次进入需要创建管理员账号和默认内容空间。之后可以创建私人或共享工作区，并按成员配置图库、样本和视频权限。

## 字幕功能说明

字幕生成是可选能力。它依赖三部分：

1. FFmpeg 从视频中提取音频。
2. faster-whisper 对音频做语音识别。
3. 本地 OpenAI-compatible 翻译服务把识别文本翻译成简体中文字幕。

当前实现默认使用本地 `llama-server` 加载 Hy-MT2 GGUF 模型。配置项集中在 `.env.example` 的 `SUBTITLE_*` 段。未配置模型时，图片、视频管理等核心功能仍可使用，但字幕生成会失败。

## 相似图片整理

相似图片整理是可选能力，它要求本机上有DINOv2模型。

进入“相似图片整理”页面后，可以选择单个人物或全部人物发起扫描。系统只在同一人物标签范围内生成候选，先使用 pHash/dHash 和 ORB 判断近重复图片，再使用本地 DINOv2 Base 的 768 维向量识别同场景图片。默认不跨普通图库与图文图库比较，可在发起扫描时主动开启跨类型比较。

扫描完成后按“近重复”和“同场景”分页展示相似组，同时给出基于分辨率与清晰度的保留建议。建议仅供参考，系统不会自动删除图片；用户勾选图片并确认后，才会调用现有图库批量删除流程。图库导入、删除或人物标签变化后，已有结果会标记为过期，需要重新扫描。

模型安装、显存策略和配置项说明见 [相似图片整理：本地模型配置](docs/gallery-similarity.md)。


## 人脸识别准确度

针对某一张低分展示图，可以在切换前对新集合执行只读诊断：

```powershell
cd backend
python -m app.tools.diagnose_face_match --gallery-photo-id 123 --person-id 45 --collection pictureshow_known_faces_buffalo_l_v2_exif --embedding-version buffalo_l-v2-exif
```

报告会重新计算该人物每张可用样本的直接余弦分数，并对比 Qdrant 返回分数；命令不会修改 SQLite、MinIO、Qdrant 或图库标签。

人工修正会形成匿名化评估记录，可用以下命令生成阈值报告（Markdown、JSON、CSV）：

```powershell
cd backend
python -m app.tools.evaluate_face_recognition --output ../data/face-evaluation
```

样本质量门槛、搜索候选数、模型名、检测尺寸及可选翻转增强均在 `.env.example` 的 `FACE_*` 配置中。翻转增强默认关闭，评估样本不足时工具不会建议自动调整生产阈值。

## 数据与隐私

- 原图、视频、封面、上传分片等对象存储在 MinIO。
- 账号、工作区、标签、识别结果、字幕内容等元数据存储在 SQLite。
- 人脸向量存储在 Qdrant。
- 本项目按本地部署设计，不需要把媒体文件上传到第三方云服务。
- 不要提交 `.env`、本地数据库、MinIO 数据目录、Qdrant 数据目录、模型文件或生成缓存。

## 常用开发命令

```powershell
# 前端类型检查与生产构建
cd frontend
cmd /c npm.cmd run build

# 后端开发服务
python -m uvicorn app.main:app --reload --app-dir backend
```

后端测试位于 `backend/tests/`。提交后端改动时应运行完整测试并检查 `/api/health` 和受影响接口；提交前端改动时至少运行 `cmd /c npm.cmd run build`。
