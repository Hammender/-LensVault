import { useEffect, useMemo, useState } from "react";
import "./Statistics.css";
import { compareByPinyin } from "../lib/sort";
import {
  getImageIntakeHistory,
  getPersonStatistics,
  getStatisticsOverview,
  getTagStatistics
} from "../api";
import type {
  ImageIntakeActivity,
  PersonStatistics,
  StatisticsOverview,
  TagStatistics
} from "../types";
import { formatCompactDate } from "../lib/utils";

type TagFilter = "all" | "system" | "custom";
type PersonFilter = "all" | "known" | "unknown";
type IntakeSourceFilter = "all" | ImageIntakeActivity["source"];

const historyPageSize = 30;

const intakeSourceLabels: Record<ImageIntakeActivity["source"], string> = {
  gallery: "普通上传",
  rich: "图文上传",
  gallery_zip: "ZIP 导入",
  acquisition: "采集入库"
};

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

function sourceCount(overview: StatisticsOverview | null, source: string): number {
  return overview?.source_counts[source] ?? 0;
}

function activitySummary(record: ImageIntakeActivity): string {
  if (record.source === "gallery_zip") {
    return `导入 ${record.total_count} 张 · 新增 ${record.imported_count} 张 · 已有图更新 ${record.updated_count} 张 · 无效跳过 ${record.skipped_count} 张`;
  }
  if (record.source === "acquisition") {
    const suffix = record.failed_count > 0 ? ` · 失败 ${record.failed_count} 张` : "";
    return `选择 ${record.total_count} 张 · 入图库 ${record.imported_count} 张${suffix}`;
  }
  return `提交 ${record.total_count} 张 · 入图库 ${record.imported_count} 张`;
}

function activityStatus(record: ImageIntakeActivity): string | null {
  if (record.status === "completed") {
    return null;
  }
  if (record.status === "completed_with_errors") {
    return "完成（有失败）";
  }
  if (record.status === "queued") {
    return "排队中";
  }
  if (record.status === "running") {
    return "处理中";
  }
  return record.status;
}

export default function Statistics() {
  const [tagStats, setTagStats] = useState<TagStatistics[]>([]);
  const [personStats, setPersonStats] = useState<PersonStatistics[]>([]);
  const [overview, setOverview] = useState<StatisticsOverview | null>(null);
  const [activities, setActivities] = useState<ImageIntakeActivity[]>([]);
  const [activitiesTotal, setActivitiesTotal] = useState(0);
  const [tagFilter, setTagFilter] = useState<TagFilter>("all");
  const [personFilter, setPersonFilter] = useState<PersonFilter>("all");
  const [intakeSourceFilter, setIntakeSourceFilter] = useState<IntakeSourceFilter>("all");
  const [showAllPersons, setShowAllPersons] = useState(false);
  const [showAllTags, setShowAllTags] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  async function refreshData() {
    setLoading(true);
    setError(null);
    try {
      const [tags, persons, nextOverview, history] = await Promise.all([
        getTagStatistics(tagFilter === "all" ? undefined : tagFilter === "system"),
        getPersonStatistics(personFilter === "all" ? undefined : personFilter === "unknown"),
        getStatisticsOverview(),
        getImageIntakeHistory(intakeSourceFilter === "all" ? undefined : intakeSourceFilter, historyPageSize)
      ]);
      setTagStats(tags);
      setPersonStats(persons);
      setOverview(nextOverview);
      setActivities(history.items);
      setActivitiesTotal(history.total);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载数据失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadMoreActivities() {
    setLoadingMore(true);
    try {
      const history = await getImageIntakeHistory(
        intakeSourceFilter === "all" ? undefined : intakeSourceFilter,
        historyPageSize,
        activities.length
      );
      setActivities((current) => [...current, ...history.items]);
      setActivitiesTotal(history.total);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载更多记录失败");
    } finally {
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    void refreshData();
  }, [tagFilter, personFilter, intakeSourceFilter]);

  const rankedTagStats = useMemo(
    () => [...tagStats].sort((a, b) => b.photo_count - a.photo_count || compareByPinyin(a.tag_name, b.tag_name) || a.tag_id - b.tag_id),
    [tagStats]
  );
  const rankedPersonStats = useMemo(
    () => [...personStats].sort((a, b) => b.photo_count - a.photo_count || compareByPinyin(a.display_name, b.display_name) || a.person_id - b.person_id),
    [personStats]
  );
  const visibleTagStats = showAllTags ? rankedTagStats : rankedTagStats.slice(0, 10);
  const visiblePersonStats = showAllPersons ? rankedPersonStats : rankedPersonStats.slice(0, 10);
  const maxTagPhotos = rankedTagStats[0]?.photo_count ?? 0;
  const maxPersonPhotos = rankedPersonStats[0]?.photo_count ?? 0;
  const pendingReview = overview?.acquisition_status_counts.pending_review ?? 0;
  const importing = (overview?.acquisition_status_counts.import_queued ?? 0) + (overview?.acquisition_status_counts.importing ?? 0);
  const importFailed = overview?.acquisition_status_counts.import_failed ?? 0;
  const latestActivity = activities[0] ?? null;

  return (
    <main className="statistics-page">
      <section className="stats-hero">
        <div>
          <p className="eyebrow">数据统计</p>
          <h2>图库运行概览</h2>
          <p>先看当前图库与待处理采集，再按人物、标签和入库流水定位下一步工作。</p>
        </div>
        <button className="stats-refresh" disabled={loading} onClick={() => void refreshData()}>
          {loading ? "刷新中" : "刷新数据"}
        </button>
      </section>

      {error && <div className="stats-error">{error}</div>}

      <section className="stats-metrics">
        <article className="metric-card primary library-card">
          <span>当前图库</span>
          <strong>{overview?.gallery_total ?? 0}</strong>
          <small>普通图 {overview?.gallery_photo_count ?? 0} 张 · 图文图 {overview?.rich_photo_count ?? 0} 张</small>
          <div className="source-breakdown" aria-label="图库来源">
            <span>普通上传 {sourceCount(overview, "manual_upload")}</span>
            <span>ZIP {sourceCount(overview, "gallery_zip")}</span>
            <span>采集 {sourceCount(overview, "acquisition")}</span>
            <span>历史未标记 {sourceCount(overview, "legacy_unclassified")}</span>
          </div>
        </article>
        <article className="metric-card">
          <span>人物标注</span>
          <strong>{formatPercent(overview?.person_covered_count ?? 0, overview?.gallery_total ?? 0)}</strong>
          <small>{overview?.person_covered_count ?? 0} / {overview?.gallery_total ?? 0} 张图片已关联人物</small>
        </article>
        <article className="metric-card">
          <span>标签覆盖</span>
          <strong>{formatPercent(overview?.tag_covered_count ?? 0, overview?.gallery_total ?? 0)}</strong>
          <small>{overview?.tag_covered_count ?? 0} / {overview?.gallery_total ?? 0} 张图片已有标签</small>
        </article>
        <a className="metric-card collection-card" href="#/acquisition">
          <span>采集待办</span>
          <strong>{pendingReview}</strong>
          <small>待审核 {pendingReview} 项 · 入库中 {importing} 项 · 失败 {importFailed} 项</small>
          <em>前往采集中心</em>
        </a>
        <article className="metric-card">
          <span>最近入库</span>
          <strong>{latestActivity ? formatCompactDate(latestActivity.completed_at) : "暂无"}</strong>
          <small>{latestActivity ? intakeSourceLabels[latestActivity.source] : "还没有入库记录"}</small>
        </article>
      </section>

      <section className="stats-workbench">
        <article className="stats-board people-board">
          <div className="board-head">
            <div>
              <h3>人物使用排行</h3>
              <p>按关联图片数量排序，默认显示前 10 项。</p>
            </div>
            <select value={personFilter} onChange={(event) => { setPersonFilter(event.target.value as PersonFilter); setShowAllPersons(false); }}>
              <option value="all">全部人物</option>
              <option value="known">已知人物</option>
              <option value="unknown">未知人物</option>
            </select>
          </div>
          <div className="ranking-list">
            {visiblePersonStats.map((stat, index) => (
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
          {rankedPersonStats.length > 10 && (
            <button className="stats-expand" type="button" onClick={() => setShowAllPersons((value) => !value)}>
              {showAllPersons ? "收起排行" : `显示全部 ${rankedPersonStats.length} 人`}
            </button>
          )}
        </article>

        <article className="stats-board tag-board">
          <div className="board-head">
            <div>
              <h3>标签分布</h3>
              <p>按被图片使用的次数排序，默认显示前 10 项。</p>
            </div>
            <select value={tagFilter} onChange={(event) => { setTagFilter(event.target.value as TagFilter); setShowAllTags(false); }}>
              <option value="all">全部标签</option>
              <option value="system">系统标签</option>
              <option value="custom">自定义标签</option>
            </select>
          </div>
          <div className="ranking-list">
            {visibleTagStats.map((stat, index) => (
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
                  <small>张图片</small>
                </div>
              </div>
            ))}
            {rankedTagStats.length === 0 && <div className="stats-empty">当前条件下没有标签数据。</div>}
          </div>
          {rankedTagStats.length > 10 && (
            <button className="stats-expand" type="button" onClick={() => setShowAllTags((value) => !value)}>
              {showAllTags ? "收起排行" : `显示全部 ${rankedTagStats.length} 个标签`}
            </button>
          )}
        </article>
      </section>

      <section className="upload-ledger">
        <div className="board-head">
          <div>
            <h3>最近入库记录</h3>
            <p>普通上传、ZIP 导入和采集入库按完成时间统一排列。</p>
          </div>
          <select value={intakeSourceFilter} onChange={(event) => setIntakeSourceFilter(event.target.value as IntakeSourceFilter)}>
            <option value="all">全部来源</option>
            <option value="gallery">普通上传</option>
            <option value="rich">图文上传</option>
            <option value="gallery_zip">ZIP 导入</option>
            <option value="acquisition">采集入库</option>
          </select>
        </div>

        <div className="upload-timeline">
          {activities.map((record) => {
            const status = activityStatus(record);
            return (
              <article className="upload-record" key={record.id}>
                <div>
                  <span className={`stat-badge intake-${record.source}`}>{intakeSourceLabels[record.source]}</span>
                  <strong>{formatCompactDate(record.completed_at)}</strong>
                </div>
                <div className="upload-record-numbers">
                  <span>{activitySummary(record)}</span>
                  {status && <small>{status}</small>}
                </div>
              </article>
            );
          })}
          {activities.length === 0 && <div className="stats-empty">还没有入库记录。</div>}
        </div>
        {activities.length < activitiesTotal && (
          <button className="stats-expand stats-load-more" type="button" disabled={loadingMore} onClick={() => void loadMoreActivities()}>
            {loadingMore ? "加载中" : `加载更多（已显示 ${activities.length}/${activitiesTotal} 条）`}
          </button>
        )}
      </section>
    </main>
  );
}
