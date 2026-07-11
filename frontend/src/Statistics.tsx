import { useEffect, useMemo, useState } from "react";
import "./Statistics.css";
import { compareByPinyin } from "./sort";
import {
  getPersonStatistics,
  getTagStatistics,
  getUploadHistory,
  getUploadSummary
} from "./api/index";
import type {
  PersonStatistics,
  TagStatistics,
  UploadHistory,
  UploadSummary
} from "./types";

type TagFilter = "all" | "system" | "custom";
type PersonFilter = "all" | "known" | "unknown";
type UploadTypeFilter = "all" | "gallery" | "rich";

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatPercent(value: number, total: number): string {
  if (total <= 0) {
    return "0%";
  }
  return `${((value / total) * 100).toFixed(1)}%`;
}

function barWidth(value: number, max: number): string {
  if (max <= 0) {
    return "0%";
  }
  return `${Math.max(4, (value / max) * 100)}%`;
}

export default function Statistics() {
  const [tagStats, setTagStats] = useState<TagStatistics[]>([]);
  const [personStats, setPersonStats] = useState<PersonStatistics[]>([]);
  const [uploadHistory, setUploadHistory] = useState<UploadHistory[]>([]);
  const [uploadSummary, setUploadSummary] = useState<UploadSummary | null>(null);
  const [tagFilter, setTagFilter] = useState<TagFilter>("all");
  const [personFilter, setPersonFilter] = useState<PersonFilter>("all");
  const [uploadTypeFilter, setUploadTypeFilter] = useState<UploadTypeFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function refreshData() {
    setLoading(true);
    setError(null);
    try {
      const [tags, persons, history, summary] = await Promise.all([
        getTagStatistics(tagFilter === "all" ? undefined : tagFilter === "system"),
        getPersonStatistics(personFilter === "all" ? undefined : personFilter === "unknown"),
        getUploadHistory(uploadTypeFilter === "all" ? undefined : uploadTypeFilter, 80),
        getUploadSummary()
      ]);
      setTagStats(tags);
      setPersonStats(persons);
      setUploadHistory(history);
      setUploadSummary(summary);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载数据失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshData();
  }, [tagFilter, personFilter, uploadTypeFilter]);

  const rankedTagStats = useMemo(
    () => [...tagStats].sort((a, b) => b.photo_count - a.photo_count || compareByPinyin(a.tag_name, b.tag_name) || a.tag_id - b.tag_id),
    [tagStats]
  );

  const rankedPersonStats = useMemo(
    () => [...personStats].sort((a, b) => b.photo_count - a.photo_count || compareByPinyin(a.display_name, b.display_name) || a.person_id - b.person_id),
    [personStats]
  );

  const totalTagPhotos = useMemo(() => rankedTagStats.reduce((sum, stat) => sum + stat.photo_count, 0), [rankedTagStats]);
  const totalPersonPhotos = useMemo(() => rankedPersonStats.reduce((sum, stat) => sum + stat.photo_count, 0), [rankedPersonStats]);
  const maxTagPhotos = rankedTagStats[0]?.photo_count ?? 0;
  const maxPersonPhotos = rankedPersonStats[0]?.photo_count ?? 0;
  const knownPersonCount = rankedPersonStats.filter((stat) => !stat.is_unknown).length;
  const unknownPersonCount = rankedPersonStats.filter((stat) => stat.is_unknown).length;
  const sampledPersonCount = rankedPersonStats.filter((stat) => stat.sample_count > 0).length;
  const successRate = uploadSummary ? formatPercent(uploadSummary.total_success, uploadSummary.total_photos) : "0%";
  const duplicateRate = uploadSummary ? formatPercent(uploadSummary.total_duplicates, uploadSummary.total_photos) : "0%";
  const latestUpload = uploadHistory[0] ?? null;

  return (
    <main className="statistics-page">
      <section className="stats-hero">
        <div>
          <p className="eyebrow">数据统计</p>
          <h2>图库运行概览</h2>
          <p>集中查看上传质量、人物覆盖和标签分布，快速判断哪些数据需要清理或补样本。</p>
        </div>
        <button className="stats-refresh" disabled={loading} onClick={() => void refreshData()}>
          {loading ? "刷新中" : "刷新数据"}
        </button>
      </section>

      {error && <div className="stats-error">{error}</div>}

      <section className="stats-metrics">
        <article className="metric-card primary">
          <span>累计图片</span>
          <strong>{uploadSummary?.total_photos ?? 0}</strong>
          <small>{uploadSummary?.total_uploads ?? 0} 次上传</small>
        </article>
        <article className="metric-card">
          <span>成功入库</span>
          <strong>{uploadSummary?.total_success ?? 0}</strong>
          <small>成功率 {successRate}</small>
        </article>
        <article className="metric-card warning">
          <span>重复跳过</span>
          <strong>{uploadSummary?.total_duplicates ?? 0}</strong>
          <small>重复率 {duplicateRate}</small>
        </article>
        <article className="metric-card">
          <span>人物覆盖</span>
          <strong>{sampledPersonCount}/{rankedPersonStats.length}</strong>
          <small>未知人物 {unknownPersonCount} 个</small>
        </article>
        <article className="metric-card">
          <span>最近上传</span>
          <strong>{latestUpload ? formatDate(latestUpload.created_at) : "暂无"}</strong>
          <small>{latestUpload ? `${latestUpload.success_count}/${latestUpload.total_count} 成功` : "还没有上传记录"}</small>
        </article>
      </section>

      <section className="stats-workbench">
        <article className="stats-board people-board">
          <div className="board-head">
            <div>
              <h3>人物使用排行</h3>
              <p>{rankedPersonStats.length} 人 · 图库关联 {totalPersonPhotos} 次 · 已知 {knownPersonCount} / 未知 {unknownPersonCount}</p>
            </div>
            <select value={personFilter} onChange={(event) => setPersonFilter(event.target.value as PersonFilter)}>
              <option value="all">全部人物</option>
              <option value="known">已知人物</option>
              <option value="unknown">未知人物</option>
            </select>
          </div>
          <div className="ranking-list">
            {rankedPersonStats.map((stat, index) => (
              <div className="ranking-row" key={stat.person_id}>
                <span className="rank-number">{index + 1}</span>
                <div className="ranking-main">
                  <div className="ranking-title">
                    <strong>{stat.display_name}</strong>
                    <span className={stat.is_unknown ? "stat-badge unknown" : "stat-badge known"}>{stat.is_unknown ? "未知" : "已知"}</span>
                  </div>
                  <div className="ranking-bar">
                    <i style={{ width: barWidth(stat.photo_count, maxPersonPhotos) }} />
                  </div>
                </div>
                <div className="ranking-count">
                  <strong>{stat.photo_count}</strong>
                  <small>样本 {stat.sample_count}</small>
                </div>
              </div>
            ))}
            {rankedPersonStats.length === 0 && <div className="stats-empty">当前条件下没有人物数据。</div>}
          </div>
        </article>

        <article className="stats-board tag-board">
          <div className="board-head">
            <div>
              <h3>标签分布</h3>
              <p>{rankedTagStats.length} 个标签 · 标注出现 {totalTagPhotos} 次</p>
            </div>
            <select value={tagFilter} onChange={(event) => setTagFilter(event.target.value as TagFilter)}>
              <option value="all">全部标签</option>
              <option value="system">系统标签</option>
              <option value="custom">自定义标签</option>
            </select>
          </div>
          <div className="ranking-list">
            {rankedTagStats.map((stat, index) => (
              <div className="ranking-row" key={stat.tag_id}>
                <span className="rank-number">{index + 1}</span>
                <div className="ranking-main">
                  <div className="ranking-title">
                    <strong>#{stat.tag_name}</strong>
                    <span className={stat.is_system ? "stat-badge system" : "stat-badge custom"}>{stat.is_system ? "系统" : "自定义"}</span>
                  </div>
                  <div className="ranking-bar">
                    <i style={{ width: barWidth(stat.photo_count, maxTagPhotos) }} />
                  </div>
                </div>
                <div className="ranking-count">
                  <strong>{stat.photo_count}</strong>
                  <small>{formatPercent(stat.photo_count, totalTagPhotos)}</small>
                </div>
              </div>
            ))}
            {rankedTagStats.length === 0 && <div className="stats-empty">当前条件下没有标签数据。</div>}
          </div>
        </article>
      </section>

      <section className="upload-ledger">
        <div className="board-head">
          <div>
            <h3>上传记录</h3>
            <p>
              普通图 {uploadSummary?.by_type.gallery.photos ?? 0} 张 · 图文 {uploadSummary?.by_type.rich.photos ?? 0} 张
            </p>
          </div>
          <select value={uploadTypeFilter} onChange={(event) => setUploadTypeFilter(event.target.value as UploadTypeFilter)}>
            <option value="all">全部上传</option>
            <option value="gallery">普通图片</option>
            <option value="rich">图文图片</option>
          </select>
        </div>

        <div className="upload-timeline">
          {uploadHistory.map((record) => (
            <article className="upload-record" key={record.id}>
              <div>
                <span className={record.upload_type === "rich" ? "stat-badge rich" : "stat-badge gallery"}>
                  {record.upload_type === "rich" ? "图文" : "普通"}
                </span>
                <strong>{formatDate(record.created_at)}</strong>
              </div>
              <div className="upload-record-numbers">
                <span>{record.success_count}/{record.total_count} 成功</span>
                <small>{record.duplicate_count > 0 ? `${record.duplicate_count} 张重复` : "无重复"}</small>
              </div>
            </article>
          ))}
          {uploadHistory.length === 0 && <div className="stats-empty">还没有上传记录。</div>}
        </div>
      </section>
    </main>
  );
}
