import { useEffect, useState } from "react";
import { listPersons, listTags, listGalleryPhotos, listVideos } from "./api";

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
      {/* Hero Section */}
      <section className="home-hero">
        <div className="hero-content">
          <p className="eyebrow">Local Face Archive</p>
          <h1>PictureShow</h1>
          <p className="hero-description">
            基于人脸识别的人物图库管理系统，支持自动识别、智能分类、视频管理与数据统计。
            将散乱的照片整理成可检索、可管理的数字资产。
          </p>
          <div className="hero-actions">
            <button onClick={() => navigateTo("gallery")} className="hero-button primary">
              浏览图库
            </button>
            <button onClick={() => navigateTo("upload")} className="hero-button secondary">
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

      {/* Quick Access */}
      <section className="home-section">
        <h2>快速入口</h2>
        <div className="quick-access-grid">
          <button onClick={() => navigateTo("gallery")} className="quick-card">
            <div className="quick-icon">🖼️</div>
            <h3>展示图库</h3>
            <p>按人物和标签筛选浏览所有图片，支持批量操作和导出。</p>
          </button>
          <button onClick={() => navigateTo("people")} className="quick-card">
            <div className="quick-icon">👥</div>
            <h3>人物样本库</h3>
            <p>管理人物样本，上传正脸照片训练识别模型。</p>
          </button>
          <button onClick={() => navigateTo("upload")} className="quick-card">
            <div className="quick-icon">📤</div>
            <h3>展示图上传</h3>
            <p>批量上传图片，自动人脸识别并打标签。</p>
          </button>
          <button onClick={() => navigateTo("videos")} className="quick-card">
            <div className="quick-icon">🎬</div>
            <h3>视频库</h3>
            <p>管理视频资源，支持分类标签和在线播放。</p>
          </button>
          <button onClick={() => navigateTo("statistics")} className="quick-card">
            <div className="quick-icon">📊</div>
            <h3>数据统计</h3>
            <p>查看系统使用统计和人物标签分布。</p>
          </button>
        </div>
      </section>

      {/* Features */}
      <section className="home-section">
        <h2>功能特点</h2>
        <div className="features-grid">
          <div className="feature-item">
            <span className="feature-icon">🔍</span>
            <h4>人脸识别</h4>
            <p>自动检测照片中的人脸，并与样本库匹配，支持未知人物自动创建。</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon">🏷️</span>
            <h4>智能标签</h4>
            <p>支持人物标签和普通标签，灵活组合筛选，精准定位图片。</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon">📤</span>
            <h4>批量导入</h4>
            <p>支持批量上传和 ZIP 导入导出，方便数据迁移和备份。</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon">🎬</span>
            <h4>视频管理</h4>
            <p>支持视频上传、分类管理和在线播放，与图片统一管理。</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon">📝</span>
            <h4>图文识别</h4>
            <p>支持图文图片 OCR 识别，自动提取文字内容。</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon">💾</span>
            <h4>本地部署</h4>
            <p>数据完全本地化存储，保护隐私，无需担心云端泄露。</p>
          </div>
        </div>
      </section>

      {/* Tips */}
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
            <p>识别出的未知人物可以在"人物样本库"中查看并改名转正。</p>
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
