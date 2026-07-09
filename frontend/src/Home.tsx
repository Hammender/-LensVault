import { useEffect, useState } from "react";
import {
  BarChart3,
  Clapperboard,
  FileText,
  HardDrive,
  Images,
  ImagePlus,
  ScanFace,
  Tags,
  UploadCloud,
  UsersRound
} from "lucide-react";

import { listPersons, listTags, listGalleryPhotos, listVideos } from "./api";

const quickAccess = [
  {
    page: "gallery",
    title: "展示图库",
    description: "按人物和标签筛选浏览图片，适合快速挑选、整理与批量导出。",
    Icon: Images
  },
  {
    page: "people",
    title: "人物样本库",
    description: "管理人物样本，沉淀更稳定的识别基础。",
    Icon: UsersRound
  },
  {
    page: "upload",
    title: "展示图上传",
    description: "批量导入图片，自动识别人脸并补齐标签。",
    Icon: UploadCloud
  },
  {
    page: "videos",
    title: "视频库",
    description: "管理视频资源，维护分区、UP 主和在线播放。",
    Icon: Clapperboard
  },
  {
    page: "statistics",
    title: "数据统计",
    description: "查看素材规模、人物样本和标签分布。",
    Icon: BarChart3
  }
] as const;

const features = [
  {
    title: "人脸识别",
    description: "自动检测照片中的人脸，并与样本库匹配，未命中时统一标记为未知人物。",
    Icon: ScanFace
  },
  {
    title: "智能标签",
    description: "支持人物标签和普通标签，灵活组合筛选，精准定位图片。",
    Icon: Tags
  },
  {
    title: "批量导入",
    description: "支持批量上传和 ZIP 导入导出，方便数据迁移和备份。",
    Icon: ImagePlus
  },
  {
    title: "视频管理",
    description: "支持视频上传、分类管理和在线播放，与图片统一管理。",
    Icon: Clapperboard
  },
  {
    title: "图文识别",
    description: "支持图文图片 OCR 识别，自动提取文字内容。",
    Icon: FileText
  },
  {
    title: "本地部署",
    description: "数据完全本地化存储，保护隐私，无需担心云端泄露。",
    Icon: HardDrive
  }
] as const;

export default function Home() {
  const [stats, setStats] = useState({
    personCount: 0,
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

        const knownPersons = persons.filter(p => !p.is_unknown);
        const totalSamples = persons.reduce((sum, p) => sum + p.sample_count, 0);

        setStats({
          personCount: knownPersons.length,
          tagCount: tags.filter(t => !t.is_system).length,
          photoCount: photos.total,
          videoCount: videos.total,
          sampleCount: totalSamples
        });
      } catch (e) {
        console.error("Failed to load stats:", e);
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
      <section className="home-hero">
        <div className="hero-content">
          <p className="eyebrow">Local Face Archive</p>
          <h1>PictureShow</h1>
          <p className="hero-description">
            面向人物写真、活动图与视频片段的本地媒体库。把散落素材整理成可识别、可筛选、可回看的展示资产。
          </p>
          <div className="hero-actions">
            <button onClick={() => navigateTo("gallery")} className="hero-button primary">
              <Images size={18} />
              浏览图库
            </button>
            <button onClick={() => navigateTo("upload")} className="hero-button secondary">
              <UploadCloud size={18} />
              上传图片
            </button>
          </div>
        </div>
        <div className="hero-stats">
          <div className="stat-card">
            <span className="stat-number">{loading ? "-" : stats.personCount}</span>
            <span className="stat-label">已识别人物</span>
          </div>
          <div className="stat-card">
            <span className="stat-number">{loading ? "-" : stats.photoCount}</span>
            <span className="stat-label">展示图片</span>
          </div>
          <div className="stat-card">
            <span className="stat-number">{loading ? "-" : stats.videoCount}</span>
            <span className="stat-label">视频资源</span>
          </div>
          <div className="stat-card">
            <span className="stat-number">{loading ? "-" : stats.sampleCount}</span>
            <span className="stat-label">样本图片</span>
          </div>
        </div>
      </section>

      <section className="home-section">
        <h2>快速入口</h2>
        <div className="quick-access-grid">
          {quickAccess.map(({ page, title, description, Icon }) => (
            <button key={page} onClick={() => navigateTo(page)} className="quick-card">
              <span className="quick-icon">
                <Icon className="quick-icon-svg" aria-hidden="true" />
              </span>
              <h3>{title}</h3>
              <p>{description}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="home-section">
        <h2>功能特点</h2>
        <div className="features-grid">
          {features.map(({ title, description, Icon }) => (
            <div className="feature-item" key={title}>
              <span className="feature-icon">
                <Icon className="feature-icon-svg" aria-hidden="true" />
              </span>
              <div>
                <h4>{title}</h4>
                <p>{description}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="home-section tips-section">
        <h2>使用提示</h2>
        <div className="tips-list">
          <div className="tip-card">
            <strong>1. 先建样本库</strong>
            <p>在"人物样本库"页面为每个人物上传清晰的正脸样本照片，这是准确识别的基础。</p>
          </div>
          <div className="tip-card">
            <strong>2. 批量上传图片</strong>
            <p>在"展示图上传"页面批量选择图片，系统会自动识别并打上人物标签。</p>
          </div>
          <div className="tip-card">
            <strong>3. 处理未知人物</strong>
            <p>未命中的人脸会统一显示为"未知人物"，可在展示图库详情中重新识别或改为正式人物。</p>
          </div>
          <div className="tip-card">
            <strong>4. 灵活筛选</strong>
            <p>在"展示图库"中使用人物+标签的组合筛选，快速找到需要的图片。</p>
          </div>
        </div>
      </section>
    </main>
  );
}
