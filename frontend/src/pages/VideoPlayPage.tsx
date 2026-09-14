import { Download, Edit3 } from "lucide-react";

import BiliVideoPlayer from "../components/BiliVideoPlayer";
import {
  formatBytes,
  formatCodecs,
  formatDate,
  formatDurationSeconds,
  formatResolution,
  subtitleTrackStatusLabel,
  videoStatusLabel
} from "../lib/utils";
import type { VideoDetail, VideoPlaybackDiagnostics } from "../types";

export type VideoPlayPageProps = {
  busy: boolean;
  canDeleteVideos: boolean;
  canEditVideos: boolean;
  selectedVideo: VideoDetail | null;
  videoPlayerUrl: string;
  videoPlaybackDiagnostics: VideoPlaybackDiagnostics | null;
  videoPlaybackDiagnosticsLoading: boolean;
  onEditVideo: () => void;
  onGenerateSubtitles: () => void;
  onReplaceCover: (files: FileList | null) => void;
  onLoadDiagnostics: () => void;
  onOptimizePlayback: () => void;
  onDeleteVideo: () => void;
};

export default function VideoPlayPage({
  busy,
  canDeleteVideos,
  canEditVideos,
  selectedVideo,
  videoPlayerUrl,
  videoPlaybackDiagnostics,
  videoPlaybackDiagnosticsLoading,
  onEditVideo,
  onGenerateSubtitles,
  onReplaceCover,
  onLoadDiagnostics,
  onOptimizePlayback,
  onDeleteVideo
}: VideoPlayPageProps) {
  const subtitleTracks = selectedVideo?.subtitle_tracks
    .filter((track) => track.status === "ready" && track.vtt_url)
    .map((track) => ({
      src: track.vtt_url as string,
      label: track.label,
      srclang: track.language
    })) ?? [];

  return (
    <main className="video-play-page">
      <section className="video-play-main">
        {selectedVideo ? (
          <div className="panel video-player-panel">
            <BiliVideoPlayer
              src={videoPlayerUrl}
              poster={selectedVideo.cover_url ?? undefined}
              subtitles={subtitleTracks}
            />
          </div>
        ) : (
          <div className="panel video-loading-panel">
            <p>加载中...</p>
          </div>
        )}
      </section>

      <aside className="video-play-sidebar panel">
        {selectedVideo && (
          <div className="detail-copy">
            <div className="video-play-info">
              <h1>{selectedVideo.title}</h1>
              <div className="micro-row wrap compact-actions video-detail-actions">
                {canEditVideos && (
                  <button className="compact-button" onClick={onEditVideo}>
                    <Edit3 size={14} aria-hidden="true" />
                    编辑信息
                  </button>
                )}
              </div>

              <div className="bili-up-list">
                {selectedVideo.people.map((person) => (
                  <div className="bili-up-item" key={person.id}>
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                    <span>{person.name}</span>
                  </div>
                ))}
              </div>

              <div className="micro-row wrap video-tag-row">
                {selectedVideo.category_tags.map((tag) => (
                  <span key={tag.id} className="pill muted">#{tag.name}</span>
                ))}
              </div>

              <div className="video-meta-grid">
                <span>{formatDate(selectedVideo.created_at)}</span>
                <span>{videoStatusLabel(selectedVideo.status)}</span>
                <span>{formatDurationSeconds(selectedVideo.duration_seconds)}</span>
                <span>{formatResolution(selectedVideo.width, selectedVideo.height)}</span>
              </div>

              <div className="description-box">
                {selectedVideo.description || "无简介"}
              </div>

              <div className="subtitle-panel">
                <div className="section-head compact-head">
                  <div>
                    <p className="eyebrow">字幕</p>
                    <h2>中文字幕</h2>
                  </div>
                </div>
                {selectedVideo.subtitle_tracks.length > 0 ? (
                  selectedVideo.subtitle_tracks.map((track) => (
                    <div className={`subtitle-status subtitle-status-${track.status}`} key={track.id}>
                      <strong>{track.label}</strong>
                      <span>{subtitleTrackStatusLabel(track.status)}</span>
                      {track.error_message && <small>{track.error_message}</small>}
                      {track.status === "ready" && track.srt_url && (
                        <a className="compact-button subtitle-download-link" href={track.srt_url}>
                          <Download size={14} aria-hidden="true" />
                          下载 SRT
                        </a>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="subtitle-empty">当前视频还没有字幕。</p>
                )}
                {canEditVideos && (
                  <button
                    className="ghost-button"
                    disabled={busy || selectedVideo.subtitle_tracks.some((track) => ["pending", "running"].includes(track.status))}
                    onClick={onGenerateSubtitles}
                  >
                    生成中文字幕
                  </button>
                )}
              </div>
            </div>

            <div className="section-head compact-head video-management-head">
              <div>
                <p className="eyebrow">视频管理</p>
                <h2>封面与文件</h2>
              </div>
            </div>

            <div className="video-cover-manager">
              {selectedVideo.cover_url ? (
                <img src={selectedVideo.cover_url} alt="视频封面" />
              ) : (
                <div className="video-cover-empty">暂无封面</div>
              )}
              {canEditVideos && (
                <label className="cover-upload-button">
                  <input
                    type="file"
                    accept="image/*"
                    disabled={busy}
                    onChange={(event) => {
                      onReplaceCover(event.target.files);
                      event.currentTarget.value = "";
                    }}
                  />
                  替换封面
                </label>
              )}
            </div>

            <p><strong>文件:</strong> {selectedVideo.filename}</p>
            <p><strong>原始格式:</strong> {formatCodecs(selectedVideo.original_video_codec, selectedVideo.original_audio_codec, selectedVideo.status)}</p>
            <p><strong>播放格式:</strong> {formatCodecs(selectedVideo.video_codec, selectedVideo.audio_codec, selectedVideo.status)}</p>
            <p><strong>体积:</strong> {formatBytes(selectedVideo.size_bytes)}</p>
            <p>
              {selectedVideo.faststart_applied ? "· 已完成 faststart 优化" : "· 未优化"}
            </p>
            <p>
              {selectedVideo.seek_optimized
                ? `· 已完成拖动优化${selectedVideo.seek_keyframe_interval_seconds ? `（关键帧约 ${selectedVideo.seek_keyframe_interval_seconds.toFixed(2)} 秒）` : ""}`
                : "· 未完成拖动优化"}
            </p>
            {selectedVideo.processing_error && <p className="inline-error">优化错误：{selectedVideo.processing_error}</p>}

            <div className="video-playback-tools">
              <button
                className="ghost-button"
                disabled={videoPlaybackDiagnosticsLoading || selectedVideo.status === "processing"}
                onClick={onLoadDiagnostics}
              >
                {videoPlaybackDiagnosticsLoading ? "诊断中..." : "读取播放诊断"}
              </button>
              {canEditVideos && (
                <button
                  className="compact-button"
                  disabled={busy || selectedVideo.status === "processing"}
                  onClick={onOptimizePlayback}
                >
                  优化拖动流畅度
                </button>
              )}
            </div>
            {videoPlaybackDiagnostics && (
              <div className="video-playback-diagnostics">
                <p><strong>播放链路:</strong> {videoPlaybackDiagnostics.expected_mode}</p>
                <p><strong>MinIO:</strong> {videoPlaybackDiagnostics.presigned_url_host || videoPlaybackDiagnostics.minio_public_endpoint}</p>
                <p><strong>对象:</strong> {formatBytes(videoPlaybackDiagnostics.object?.object_size_bytes ?? videoPlaybackDiagnostics.size_bytes)}</p>
                <p><strong>码率:</strong> {videoPlaybackDiagnostics.object?.bitrate ? `${Math.round(videoPlaybackDiagnostics.object.bitrate / 1000)} kbps` : "未知"}</p>
                <p><strong>Faststart:</strong> {videoPlaybackDiagnostics.object?.faststart === null || videoPlaybackDiagnostics.object?.faststart === undefined ? "未知" : videoPlaybackDiagnostics.object.faststart ? "是" : "否"}</p>
                <p>
                  <strong>估算关键帧间隔:</strong>{" "}
                  {videoPlaybackDiagnostics.object?.estimated_keyframe_interval_seconds
                    ? `${videoPlaybackDiagnostics.object.estimated_keyframe_interval_seconds.toFixed(2)} 秒`
                    : "未知"}
                </p>
                {videoPlaybackDiagnostics.object_probe_error && <p className="inline-error">{videoPlaybackDiagnostics.object_probe_error}</p>}
              </div>
            )}

            {canDeleteVideos && (
              <button
                className="danger-button full-width-action"
                disabled={busy}
                onClick={onDeleteVideo}
              >
                删除视频
              </button>
            )}
          </div>
        )}
      </aside>
    </main>
  );
}
