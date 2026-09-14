import { useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  BarChart3,
  Camera,
  CheckCircle2,
  Clapperboard,
  Download,
  FolderSync,
  HardDrive,
  Images,
  ScanFace,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  UsersRound
} from "lucide-react";

import { listPersons, listTags, listGalleryPhotos, listVideos } from "../api";
import "./Home.css";

const workstations = [
  {
    page: "gallery",
    title: "展示图库",
    tag: "核心检索",
    description: "按人物与标签多维复合筛选，支持高保真画廊排版、灯箱沉浸预览与批量导出。",
    Icon: Images
  },
  {
    page: "people",
    title: "人物样本库",
    tag: "特征基准",
    description: "维护人物正脸及多角度样本，校准人脸特征向量，建立稳健的识别比对基础。",
    Icon: UsersRound
  },
  {
    page: "upload",
    title: "展示图上传",
    tag: "批量录入",
    description: "批量导入照片与视频，自动定位人脸特征、提取 OCR 图文并补齐多维标签。",
    Icon: UploadCloud
  },
  {
    page: "similarity",
    title: "相似查重",
    tag: "资产精简",
    description: "智能识别连拍近重复与镜像翻转图像，快速聚类对比并一键瘦身归档。",
    Icon: FolderSync
  },
  {
    page: "videos",
    title: "视频资源库",
    tag: "动态影像",
    description: "集中管理视频资源与 UP 主分区，支持在线播放与 ASR 语音字幕智能工作流。",
    Icon: Clapperboard
  },
  {
    page: "acquisition",
    title: "采集中心",
    tag: "自动化",
    description: "支持外部相册与批次媒体抓取，集中管理下载队列并一键转存入库。",
    Icon: Download
  },
  {
    page: "statistics",
    title: "数据统计",
    tag: "数据透视",
    description: "图表化呈现人物样本健康度、标签分类分布与媒体资产增长脉络。",
    Icon: BarChart3
  }
] as const;

export default function Home() {
  const [stats, setStats] = useState({
    personCount: 0,
    unknownCount: 0,
    tagCount: 0,
    photoCount: 0,
    videoCount: 0,
    sampleCount: 0
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadStats() {
      try {
        const [persons, tags, photos, videos] = await Promise.all([
          listPersons(),
          listTags(),
          listGalleryPhotos([], [], [], [], 0, 1),
          listVideos([], [], "", 0, 1)
        ]);

        const knownPersons = persons.filter((p) => !p.is_unknown);
        const unknownPersons = persons.filter((p) => p.is_unknown);
        const totalSamples = persons.reduce((sum, p) => sum + (p.sample_count || 0), 0);

        setStats({
          personCount: knownPersons.length,
          unknownCount: unknownPersons.length,
          tagCount: tags.filter((t) => !t.is_system).length,
          photoCount: photos.total,
          videoCount: videos.total,
          sampleCount: totalSamples
        });
      } catch (e) {
        console.error("Failed to load archive stats:", e);
      } finally {
        setLoading(false);
      }
    }

    void loadStats();
  }, []);

  function navigateTo(page: string) {
    window.location.hash = `/${page}`;
  }

  return (
    <main className="home-page">
      {/* 1. Editorial Hero Section */}
      <section className="home-editorial-hero">
        <div className="hero-main-col">
          <div className="hero-header-block">
            <div className="hero-privacy-badge">
              <span className="pulse-dot" />
              <span>本地私有离线 · 毫秒级人脸特征引擎 · 0 云端回传</span>
            </div>
            <h1>PictureShow</h1>
            <p className="hero-tagline">Local Smart Portrait & Media Archive</p>
            <p className="hero-description">
              面向人物写真、活动记录与动态影像的私有智能媒体库。沉淀高精度面部特征基准，让每一幅珍贵肖像皆可精准检索与典藏。
            </p>
          </div>

          <div className="hero-cta-row">
            <button onClick={() => navigateTo("gallery")} className="hero-btn primary">
              <Images size={16} />
              浏览展示图库
            </button>
            <button onClick={() => navigateTo("upload")} className="hero-btn secondary">
              <UploadCloud size={16} />
              批量导入素材
            </button>
            <button onClick={() => navigateTo("people")} className="hero-btn ghost">
              <UsersRound size={16} />
              人物样本档案
            </button>
          </div>
        </div>

        {/* Abstract Artistic Framing Placeholder */}
        <div className="hero-art-frame">
          <div className="hero-art-header">
            <span>ARCHIVE ATELIER</span>
            <span>PRIVATE & SECURE</span>
          </div>

          <div className="hero-art-center">
            <div className="aperture-visual">
              <div className="aperture-ring" />
              <div className="aperture-inner">
                <Camera size={30} strokeWidth={1.75} />
              </div>
            </div>
            <h3 className="hero-art-title">人物肖像与影像工坊</h3>
            <p className="hero-art-sub">
              高保真媒体存储 · 离线人脸特征向量 · 多维智能标签检索
            </p>
          </div>

          <div className="hero-art-footer">
            <span>
              <HardDrive size={13} /> 本地 MinIO & SQLite
            </span>
            <span>
              <ShieldCheck size={13} /> 离线私有化环境
            </span>
          </div>
        </div>
      </section>

      {/* 2. Archive Pulse / Metrics Section */}
      <section className="home-section">
        <div className="section-title-wrap">
          <h2>
            资产脉络
            <span className="section-subtitle">/ 实时汇聚媒体库人物档案、素材与特征样本规模</span>
          </h2>
        </div>

        <div className="pulse-grid">
          <div className="pulse-card" onClick={() => navigateTo("people")}>
            <div className="pulse-card-top">
              <span className="pulse-label">已建档人物</span>
              <span className="pulse-icon-box">
                <UsersRound size={18} />
              </span>
            </div>
            <div className="pulse-value-wrap">
              <span className="pulse-number">{loading ? "-" : stats.personCount}</span>
              <span className="pulse-unit">位人物</span>
            </div>
            <div className="pulse-card-foot">
              <span>已建立基准特征</span>
              <span className="pulse-foot-action">
                管理 <ArrowRight size={12} />
              </span>
            </div>
          </div>

          <div className="pulse-card" onClick={() => navigateTo("gallery")}>
            <div className="pulse-card-top">
              <span className="pulse-label">展示图片</span>
              <span className="pulse-icon-box">
                <Images size={18} />
              </span>
            </div>
            <div className="pulse-value-wrap">
              <span className="pulse-number">{loading ? "-" : stats.photoCount}</span>
              <span className="pulse-unit">张照片</span>
            </div>
            <div className="pulse-card-foot">
              <span>人脸与标签多维索引</span>
              <span className="pulse-foot-action">
                浏览 <ArrowRight size={12} />
              </span>
            </div>
          </div>

          <div className="pulse-card" onClick={() => navigateTo("videos")}>
            <div className="pulse-card-top">
              <span className="pulse-label">动态影像</span>
              <span className="pulse-icon-box">
                <Clapperboard size={18} />
              </span>
            </div>
            <div className="pulse-value-wrap">
              <span className="pulse-number">{loading ? "-" : stats.videoCount}</span>
              <span className="pulse-unit">部视频</span>
            </div>
            <div className="pulse-card-foot">
              <span>分区分集与智能字幕</span>
              <span className="pulse-foot-action">
                查看 <ArrowRight size={12} />
              </span>
            </div>
          </div>

          <div className="pulse-card" onClick={() => navigateTo("people")}>
            <div className="pulse-card-top">
              <span className="pulse-label">训练样本</span>
              <span className="pulse-icon-box">
                <ScanFace size={18} />
              </span>
            </div>
            <div className="pulse-value-wrap">
              <span className="pulse-number">{loading ? "-" : stats.sampleCount}</span>
              <span className="pulse-unit">张样本</span>
            </div>
            <div className="pulse-card-foot">
              <span>{loading ? "..." : `${stats.tagCount} 个分类标签`}</span>
              <span className="pulse-foot-action">
                校准 <ArrowRight size={12} />
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Curator Workstations Matrix */}
      <section className="home-section">
        <div className="section-title-wrap">
          <h2>
            策展工坊
            <span className="section-subtitle">/ 从人脸样本校准到多维检索、相似排重与素材采集全流程</span>
          </h2>
        </div>

        <div className="workstations-grid">
          {workstations.map(({ page, title, tag, description, Icon }) => (
            <div key={page} onClick={() => navigateTo(page)} className="station-card">
              <div className="station-top-bar">
                <div className="station-icon-wrap">
                  <Icon size={20} />
                </div>
                <span className="station-tag">{tag}</span>
              </div>

              <div className="station-body">
                <h3 className="station-title">{title}</h3>
                <p className="station-desc">{description}</p>
              </div>

              <div className="station-footer">
                <span>进入工坊</span>
                <span className="station-arrow">
                  <ArrowRight size={14} />
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 4. Studio Health & Insights Section */}
      <section className="home-section">
        <div className="section-title-wrap">
          <h2>
            媒体库状态与智能助手
            <span className="section-subtitle">/ 实时监控待处理人脸与系统离线存储安全</span>
          </h2>
        </div>

        <div className="health-cards-grid">
          {/* Card 1: Unknown Face Review */}
          <div className={`health-card ${stats.unknownCount > 0 ? "alert-card" : ""}`}>
            <div className="health-header">
              <div className="station-icon-wrap">
                {stats.unknownCount > 0 ? <AlertCircle size={20} color="var(--accent-strong)" /> : <CheckCircle2 size={20} color="#276738" />}
              </div>
              <span className={`health-status-badge ${stats.unknownCount > 0 ? "attention" : "success"}`}>
                {stats.unknownCount > 0 ? `待整理队列 (${stats.unknownCount})` : "归档状态良好"}
              </span>
            </div>
            <div className="health-body">
              <h4 className="health-title">
                {stats.unknownCount > 0 ? `发现 ${stats.unknownCount} 位待归档未知人物` : "人脸匹配状态完备"}
              </h4>
              <p className="health-desc">
                {stats.unknownCount > 0
                  ? "图库中存在未命中已知样本的人脸，建议前往展示图库或人物库进行关联确认或新建人物档案。"
                  : "当前所有已识别的人脸均已归属到已知人物档案，无需额外整理。"}
              </p>
            </div>
            {stats.unknownCount > 0 && (
              <button onClick={() => navigateTo("people")} className="health-btn">
                前往人物库整理
                <ArrowRight size={13} />
              </button>
            )}
          </div>

          {/* Card 2: Sample Quality Guidelines */}
          <div className="health-card">
            <div className="health-header">
              <div className="station-icon-wrap">
                <Sparkles size={20} />
              </div>
              <span className="health-status-badge">
                识别精度建议
              </span>
            </div>
            <div className="health-body">
              <h4 className="health-title">建立高质量样本基准</h4>
              <p className="health-desc">
                建议为每位人物上传 3~5 张不同光线与角度的高清正脸照片，避免过度美颜或遮挡，能大幅提升复杂场景下的识别准确率。
              </p>
            </div>
          </div>

          {/* Card 3: Offline Privacy Guarantee */}
          <div className="health-card">
            <div className="health-header">
              <div className="station-icon-wrap">
                <ShieldCheck size={20} />
              </div>
              <span className="health-status-badge success">
                全本地化存储
              </span>
            </div>
            <div className="health-body">
              <h4 className="health-title">100% 离线与隐私安全</h4>
              <p className="health-desc">
                所有照片原图、特征向量与数据库均驻留在本地，人脸特征比对与搜索完全在本地计算，杜绝任何云端泄露风险。
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
