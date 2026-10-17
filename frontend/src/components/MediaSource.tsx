import { useEffect, useState } from "react";
import { authFetch, getAuthToken, getSelectedWorkspaceId, parseResponse } from "../lib/apiClient";
import { formatDate } from "../lib/utils";
import type { SourceSummary } from "../types/provenance";
import "./MediaSource.css";

type Snapshot = Record<string, unknown>;
const cache = new Map<string, Snapshot | null>();
const labels: Record<string, string> = {
  source_type: "来源类型", actor_name: "入库人", imported_at: "入库时间", record_method: "记录方式",
  site_name: "站点", category_path: "分类", run_id: "采集任务", plugin_key: "采集插件",
  plugin_version: "插件版本", original_url: "原始地址", published_at: "发布时间", collected_at: "采集时间",
  channel_id: "会话编号", channel_title: "频道／群组", channel_username: "公开名称", peer_id: "会话标识",
  entity_type: "会话类型", message_id: "消息编号", topic_id: "话题编号", topic_title: "话题",
  is_comment: "来自评论区", root_channel_message_id: "根消息编号", root_channel_id: "根频道编号",
  root_channel_username: "根频道名称", reply_to_message_id: "回复消息", grouped_id: "相册编号",
  media_type: "媒体类型", transport_type: "发送形式", original_filename: "原始文件名", message_url: "消息链接",
  hashtags: "消息标签", caption_excerpt: "文案摘要", caption_truncated: "文案已截断",
  video_asset_id: "原视频素材", video_filename: "原视频文件名", video_sha256: "原视频哈希",
  frame_index: "帧序号", time_seconds: "截图时间（秒）", color_conversion: "色彩处理", original_sha256: "原始文件哈希"
};
const values: Record<string, string> = {
  manual_upload: "手动上传", import: "导入", acquisition: "采集", video_capture: "视频截图", unknown: "历史来源未知",
  recorded: "入库时记录", backfilled: "历史回填", imported_package: "来自导入包", image: "图片", video: "视频",
  photo: "照片", document: "文件", channel: "频道", group: "群组"
};

function Fields({ data }: { data: Snapshot }) {
  return <dl className="media-source-fields">{Object.entries(data).filter(([key, value]) => labels[key] && value !== null && value !== undefined && value !== "").map(([key, value]) => {
    const text = key.endsWith("_at") && typeof value === "string" ? formatDate(value) : typeof value === "boolean" ? (value ? "是" : "否") : Array.isArray(value) ? value.map(String).join("、") : typeof value === "object" ? JSON.stringify(value) : values[String(value)] ?? String(value);
    const isLink = (key === "original_url" || key === "message_url") && typeof value === "string" && /^(https?:\/\/|tg:\/\/)/.test(value);
    return <div key={key}><dt>{labels[key]}</dt><dd>{isLink ? <a href={String(value)} title={String(value)} target="_blank" rel="noreferrer">打开来源 ↗</a> : text}</dd></div>;
  })}</dl>;
}

function SourceDetails({ data }: { data: Snapshot }) {
  return <>
    <Fields data={data} />
    {([['telegram', 'Telegram 信息'], ['capture', '视频截图']] as const).map(([key, title]) => data[key] && typeof data[key] === "object" ? <details key={key} open><summary>{title}</summary><Fields data={data[key] as Snapshot} /></details> : null)}
    {data.upstream && typeof data.upstream === "object" ? <details open><summary>原始来源（来自导入包）</summary><SourceDetails data={data.upstream as Snapshot} /></details> : null}
    {data.public_metadata && typeof data.public_metadata === "object" && Object.keys(data.public_metadata).length > 0 ? <details><summary>更多来源信息</summary><pre>{JSON.stringify(data.public_metadata, null, 2)}</pre></details> : null}
  </>;
}

type Props = { mediaType: "photo" | "video"; mediaId: number; summary?: SourceSummary };

function SourceContent({ mediaType, mediaId, summary, cacheKey }: Props & { cacheKey: string }) {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<Snapshot | null | undefined>(cache.get(cacheKey));
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!expanded || data !== undefined) return;
    const controller = new AbortController();
    let active = true;
    const path = mediaType === "photo" ? `/api/gallery/photos/${mediaId}/source` : `/api/videos/${mediaId}/source`;
    setError("");
    void authFetch(path, { signal: controller.signal }).then(parseResponse<Snapshot | null>).then((result) => {
      if (!active) return;
      if (cache.size >= 200) cache.delete(cache.keys().next().value!);
      cache.set(cacheKey, result);
      setData(result);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "来源加载失败");
    });
    return () => { active = false; controller.abort(); };
  }, [expanded, data, cacheKey, mediaType, mediaId, attempt]);
  return <section className="media-source">
    <button type="button" className="media-source-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      <span>来源</span><strong>{summary?.text || "历史来源未知"}</strong><span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
    </button>
    {expanded && <div className="media-source-detail">
      {error ? <p role="alert">{error} <button type="button" onClick={() => setAttempt(attempt + 1)}>重试</button></p> : data === undefined ? <p role="status">正在加载来源…</p> : data === null ? <p>尚无详细来源记录。</p> : <SourceDetails data={data} />}
    </div>}
  </section>;
}

export default function MediaSource(props: Props) {
  const key = `${getAuthToken()}:${getSelectedWorkspaceId()}:${props.mediaType}:${props.mediaId}`;
  return <SourceContent key={key} {...props} cacheKey={key} />;
}
