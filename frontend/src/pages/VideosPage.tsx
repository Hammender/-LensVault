import { useEffect, useState } from "react";
import VideoTransfer from "../components/VideoTransfer";
import { getSelectedWorkspaceId } from "../lib/apiClient";
import { Edit3, Film, Sparkles, Trash2 } from "lucide-react";

import VideoLightbox from "../components/VideoLightbox";
import VideoUploadModal from "../components/VideoUploadModal";
import type { VideosModel } from "../hooks/useVideos";
import {
  formatBytes,
  formatDurationSeconds,
  getVideoFormatLabel,
  subtitleAsrStatusLabel,
  subtitleServiceStatusLabel,
  supportedVideoFormatLabel,
  subtitleTrackStatusLabel,
  videoStatusLabel
} from "../lib/utils";

export default function VideosPage({ model }: { model: VideosModel }) {
  const {
    busy,
    canAddVideos,
    canDeleteVideos,
    canEditVideos,
    videoItems,
    videoTotal,
    videoOffset,
    videoPageSize,
    videoCategoryTags,
    videoPeople,
    selectedVideoCategoryIds,
    selectedVideoPersonIds,
    videoTypeFilter,
    videoSearch,
    activeLightboxIndex,
    selectedVideo,
    videoPlaybackDiagnosticsLoading,
    videoFiles,
    videoTitle,
    videoDescription,
    videoUploadCategoryIds,
    videoUploadPersonIds,
    videoUploadTypeMode,
    videoUploadNewCategories,
    videoUploadGenerateSubtitles,
    videoUploadProgress,
    videoUploadSession,
    videoUploadCurrentIndex,
    videoUploadTotalCount,
    videoUploadBusy,
    videoUploadQueue,
    videoListRefreshing,
    isVideoEditModalOpen,
    editVideoTitle,
    editVideoDescription,
    editVideoType,
    editVideoCategoryIds,
    editVideoPersonIds,
    isCategoryManageModalOpen,
    isVideoPersonManageModalOpen,
    editingCategoryId,
    editingCategoryName,
    newManageCategoryName,
    editingPersonId,
    editingPersonName,
    editingPersonNote,
    newManagePersonName,
    newManagePersonNote,
    filteredVideoCategoryTags,
    filteredVideoPeople,
    videoTotalPages,
    videoCurrentPage,
    editingVideoId,
    subtitleServiceStatus,
    subtitleServiceLogs,
    subtitleJobsLoaded,
    subtitleServiceBusy,
    subtitleServiceNotice,
    subtitleLogsOpen,
    visibleSubtitleJobs,
    setVideoSearch,
    setVideoTypeFilter,
    setSelectedVideoCategoryIds,
    setSelectedVideoPersonIds,
    setActiveLightboxIndex,
    setVideoTitle,
    setVideoDescription,
    setVideoUploadTypeMode,
    setVideoUploadNewCategories,
    setVideoUploadGenerateSubtitles,
    setIsVideoEditModalOpen,
    setEditVideoTitle,
    setEditVideoDescription,
    setEditVideoType,
    setEditVideoCategoryIds,
    setEditVideoPersonIds,
    setIsCategoryManageModalOpen,
    setIsVideoPersonManageModalOpen,
    setEditingCategoryId,
    setEditingCategoryName,
    setNewManageCategoryName,
    setEditingPersonId,
    setEditingPersonName,
    setEditingPersonNote,
    setEditingPersonAvatar,
    setNewManagePersonName,
    setNewManagePersonNote,
    setNewManagePersonAvatar,
    refreshVideos,
    handleToggleVideoFilterCategory,
    handleToggleVideoFilterPerson,
    handleToggleVideoUploadCategory,
    handleToggleVideoUploadPerson,
    handleCreateVideoCategory,
    handleCreateVideoPerson,
    handleDeleteVideoItem,
    handlePickVideoFile,
    handleConfirmVideoUpload,
    handleCancelVideoUpload,
    handleGenerateSelectedVideoSubtitles,
    handleStartSubtitleService,
    handleStopSubtitleService,
    handleToggleSubtitleLogs,
    handleCancelSubtitleJob,
    openVideoEditModal,
    handleSaveVideoEdit,
    handleCreateManageCategory,
    handleUpdateManageCategory,
    handleDeleteManageCategory,
    handleCreateManagePerson,
    handleUpdateManagePerson,
    handleDeleteManagePerson,
    setVideoListRefreshing,
    refreshVideoList,
    setError,
    setEditingVideoId,
    error
  } = model;
  const [exportIds, setExportIds] = useState<number[]>([]);
  const workspaceId = getSelectedWorkspaceId();
  useEffect(() => setExportIds([]), [workspaceId]);
  const shortVideos = videoItems.filter((v) => v.video_type === "short");

  return (
    <>
        <main className="bili-videos-page">
          <div className="bili-top-bar">
            <div className="bili-search-box">
              <input
                className="search-input"
                value={videoSearch}
                onChange={(event) => setVideoSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter);
                  }
                }}
                placeholder="搜索视频名、简介或文件名"
              />
              <button disabled={busy} onClick={() => void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter)}>
                搜索
              </button>
            </div>
            <div className="micro-row wrap compact-actions">
              <button className="compact-button" disabled={videoListRefreshing} onClick={() => void refreshVideoList()}>
                {videoListRefreshing ? "刷新中…" : "刷新列表"}
              </button>
              {canEditVideos && (
                <>
              <button className="compact-button" onClick={() => setIsCategoryManageModalOpen(true)}>管理分区</button>
              <button className="compact-button" onClick={() => setIsVideoPersonManageModalOpen(true)}>管理UP主</button>
                </>
              )}
            </div>
          </div>

          <div className="bili-type-bar">
            <div className="bili-type-tabs">
              <button
                className={videoTypeFilter === "all" ? "bili-type-tab active" : "bili-type-tab"}
                onClick={() => {
                  setVideoTypeFilter("all");
                  void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, "all");
                }}
              >
                全部
              </button>
              <button
                className={videoTypeFilter === "short" ? "bili-type-tab active type-short" : "bili-type-tab type-short"}
                onClick={() => {
                  setVideoTypeFilter("short");
                  void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, "short");
                }}
              >
                <Sparkles size={13} />
                <span>短视频</span>
              </button>
              <button
                className={videoTypeFilter === "long" ? "bili-type-tab active type-long" : "bili-type-tab type-long"}
                onClick={() => {
                  setVideoTypeFilter("long");
                  void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, "long");
                }}
              >
                <Film size={13} />
                <span>长视频</span>
              </button>
            </div>
            {shortVideos.length > 0 && (
              <button
                className="bili-reel-btn"
                onClick={() => setActiveLightboxIndex(0)}
                title="进入 Shots 短视频沉浸放映流"
              >
                <Sparkles size={14} />
                <span>Shots</span>
              </button>
            )}
          </div>

          <section className="subtitle-service-panel">
            <div className="subtitle-service-head">
              <div>
                <p className="eyebrow">中文字幕</p>
                <h2>本地翻译服务</h2>
              </div>
              <div className="subtitle-service-actions">
                <span className={`subtitle-service-badge subtitle-service-badge-${subtitleServiceStatus?.status ?? "unknown"}`}>
                  {subtitleServiceStatus ? subtitleServiceStatusLabel(subtitleServiceStatus.status) : "检测中"}
                </span>
                <button disabled={subtitleServiceBusy} onClick={() => void handleStartSubtitleService()}>
                  启动服务
                </button>
                <button disabled={subtitleServiceBusy} onClick={() => void handleStopSubtitleService()}>
                  关闭服务
                </button>
                <button disabled={subtitleServiceBusy} onClick={() => void handleToggleSubtitleLogs()}>
                  {subtitleLogsOpen ? "收起日志" : "查看日志"}
                </button>
              </div>
            </div>

            <div className="subtitle-service-meta">
              <span>端点：{subtitleServiceStatus?.endpoint ?? "未检测"}</span>
              <span>PID：{subtitleServiceStatus?.pid ?? "无"}</span>
              <span>模型：{subtitleServiceStatus?.model ?? "Hy-MT2"}</span>
              <span>{subtitleServiceStatus?.managed ? "由 PictureShow 启动" : "外部或未启动"}</span>
            </div>

            <div className="subtitle-service-meta subtitle-service-asr-meta">
              <span>ASR：{subtitleServiceStatus?.asr ? subtitleAsrStatusLabel(subtitleServiceStatus.asr.status) : "检测中"}</span>
              <span>设备：{subtitleServiceStatus?.asr ? `${subtitleServiceStatus.asr.device}/${subtitleServiceStatus.asr.compute_type}` : "未检测"}</span>
              <span>模型：faster-whisper</span>
              {subtitleServiceStatus?.asr?.last_duration_seconds != null && (
                <span>上次耗时：{subtitleServiceStatus.asr.last_duration_seconds.toFixed(1)} 秒</span>
              )}
              {subtitleServiceStatus?.asr?.last_segment_count != null && (
                <span>上次片段：{subtitleServiceStatus.asr.last_segment_count}</span>
              )}
            </div>

            {(subtitleServiceNotice || subtitleServiceStatus?.message) && (
              <div
                className={
                  subtitleServiceNotice?.includes("失败") || subtitleServiceStatus?.status === "unhealthy"
                    ? "subtitle-service-message subtitle-service-message-error"
                    : "subtitle-service-message"
                }
              >
                {subtitleServiceNotice || subtitleServiceStatus?.message}
              </div>
            )}

            {subtitleServiceStatus?.asr?.message && (
              <div
                className={
                  subtitleServiceStatus.asr.status === "error"
                    ? "subtitle-service-message subtitle-service-message-error"
                    : "subtitle-service-message"
                }
              >
                语音识别：{subtitleServiceStatus.asr.message}
                {subtitleServiceStatus.asr.last_error ? `：${subtitleServiceStatus.asr.last_error}` : ""}
              </div>
            )}

            {visibleSubtitleJobs.length > 0 ? (
              <div className="subtitle-job-list">
                {visibleSubtitleJobs.map((job) => {
                  const progress = Math.round(Math.min(Math.max(job.task?.progress ?? 0, 0), 1) * 100);
                  const isActive = ["pending", "running"].includes(job.track.status);
                  return (
                    <div className={`subtitle-job-row subtitle-job-row-${job.track.status}`} key={`${job.video_id}-${job.track.id}`}>
                      <div className="subtitle-job-main">
                        <strong>{job.video_title}</strong>
                        <span>{subtitleTrackStatusLabel(job.track.status)} · {job.task?.message ?? job.video_filename}</span>
                        {job.track.error_message && <small>{job.track.error_message}</small>}
                      </div>
                      <div className="subtitle-job-progress">
                        <progress value={progress} max={100}></progress>
                        <span>{progress}%</span>
                      </div>
                      <button
                        className="ghost-button compact"
                        disabled={subtitleServiceBusy || !isActive}
                        onClick={() => void handleCancelSubtitleJob(job)}
                      >
                        取消
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : !subtitleJobsLoaded ? (
              <p className="subtitle-service-empty">正在读取字幕任务...</p>
            ) : (
              <p className="subtitle-service-empty">当前没有字幕生成任务。</p>
            )}

            {subtitleLogsOpen && (
              <div className="subtitle-log-panel">
                <div className="subtitle-log-path">{subtitleServiceLogs?.log_path ?? "未配置日志文件"}</div>
                <pre>{subtitleServiceLogs?.content || "暂无日志"}</pre>
              </div>
            )}
          </section>

          <div className="bili-filters-bar">
            <div className="bili-filter-row">
              <span className="bili-filter-label">分区</span>
              <div className="bili-chip-cloud">
                <button
                  className={selectedVideoCategoryIds.length === 0 ? "soft-chip active" : "soft-chip"}
                  onClick={() => {
                    setSelectedVideoCategoryIds([]);
                    void refreshVideos(0, [], selectedVideoPersonIds, videoSearch, videoTypeFilter);
                  }}
                >
                  全部
                </button>
                {filteredVideoCategoryTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={selectedVideoCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                    onClick={() => handleToggleVideoFilterCategory(tag.id)}
                  >
                    {tag.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="bili-filter-row">
              <span className="bili-filter-label">UP主</span>
              <div className="bili-chip-cloud">
                <button
                  className={selectedVideoPersonIds.length === 0 ? "video-person-chip active" : "video-person-chip"}
                  onClick={() => {
                    setSelectedVideoPersonIds([]);
                    void refreshVideos(0, selectedVideoCategoryIds, [], videoSearch, videoTypeFilter);
                  }}
                >
                  <b>全部</b>
                </button>
                {filteredVideoPeople.map((person) => (
                  <button
                    key={person.id}
                    className={selectedVideoPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                    onClick={() => handleToggleVideoFilterPerson(person.id)}
                  >
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                    <b>{person.name}</b>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <VideoTransfer key={workspaceId} canImport={canAddVideos} selectedIds={exportIds} categoryIds={selectedVideoCategoryIds} personIds={selectedVideoPersonIds} query={videoSearch} videoType={videoTypeFilter} onImported={() => { void refreshVideoList(); }} />
          <div className="bili-video-grid">
            {videoItems.map((video, idx) => (
              <article
                key={video.id}
                className={`bili-video-card video-card-type-${video.video_type}`}
                onClick={() => {
                  if (video.video_type === "short") {
                    const sIdx = shortVideos.findIndex((sv) => sv.id === video.id);
                    setActiveLightboxIndex(sIdx >= 0 ? sIdx : 0);
                  } else {
                    window.open("#video-play/" + video.id, "_blank");
                  }
                }}
              >
                <label className="video-export-selection" onClick={(event) => event.stopPropagation()}>
                  <input type="checkbox" checked={exportIds.includes(video.id)} onChange={(event) => setExportIds((ids) => event.target.checked ? [...ids, video.id] : ids.filter((id) => id !== video.id))} /> 选择导出
                </label>
                <div className="bili-video-cover">
                  {video.cover_url ? (
                    <img src={video.cover_url} alt={video.title} loading="lazy" />
                  ) : (
                    <span className="placeholder">{getVideoFormatLabel(video.filename)}</span>
                  )}
                  <span className={`bili-video-status status-${video.status}`}>{videoStatusLabel(video.status)}</span>
                  <span className="bili-video-duration">
                    {video.duration_seconds ? formatDurationSeconds(video.duration_seconds) : formatBytes(video.size_bytes)}
                  </span>
                  <div className="bili-card-hover-overlay" onClick={(e) => e.stopPropagation()}>
                    {video.video_type === "short" ? (
                      <>
                        <button
                          className="hover-action-btn"
                          title="Shots 放映"
                          onClick={() => {
                            const sIdx = shortVideos.findIndex((sv) => sv.id === video.id);
                            setActiveLightboxIndex(sIdx >= 0 ? sIdx : 0);
                          }}
                        >
                          <Sparkles size={14} />
                        </button>
                        <button
                          className="hover-action-btn"
                          title="影院模式播放"
                          onClick={() => window.open("#video-play/" + video.id, "_blank")}
                        >
                          <span style={{ fontSize: "0.75rem", fontWeight: 600 }}>影院</span>
                        </button>
                      </>
                    ) : (
                      <button
                        className="hover-action-btn"
                        title="影院播放"
                        onClick={() => window.open("#video-play/" + video.id, "_blank")}
                      >
                        <Film size={14} />
                        <span style={{ fontSize: "0.75rem", fontWeight: 600, marginLeft: 2 }}>播放</span>
                      </button>
                    )}
                    {canEditVideos && (
                    <button
                      className="hover-action-btn"
                      title="编辑视频信息"
                      onClick={() => openVideoEditModal(video)}
                    >
                      <Edit3 size={14} />
                    </button>
                    )}
                    {canDeleteVideos && (
                      <button
                        className="hover-action-btn delete-btn"
                        title="删除视频"
                        onClick={() => void handleDeleteVideoItem(video)}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="bili-video-info">
                  <h3 className="bili-video-title" title={video.title}>{video.title}</h3>
                  <div className="bili-up-list">
                    {video.people.map((person) => (
                      <div className="bili-up-item" key={person.id} title={person.name}>
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <span>{person.name}</span>
                      </div>
                    ))}
                    {video.people.length === 0 && <span className="muted small-muted">无UP主</span>}
                  </div>
                  <div className="bili-video-meta">
                    <span className={`bili-video-type-tag type-${video.video_type}`}>
                      {video.video_type === "short" ? (
                        <>
                          <Sparkles size={11} />
                          <span>短视频</span>
                        </>
                      ) : (
                        <>
                          <Film size={11} />
                          <span>长视频</span>
                        </>
                      )}
                    </span>
                    {video.category_tags.map((tag) => (
                      <span key={tag.id} className="bili-video-tag-pill">#{tag.name}</span>
                    ))}
                  </div>
                </div>
              </article>
            ))}
          </div>

          {activeLightboxIndex !== null && shortVideos.length > 0 && (
            <VideoLightbox
              videos={shortVideos}
              currentIndex={activeLightboxIndex}
              onClose={() => setActiveLightboxIndex(null)}
              onChangeIndex={(idx) => setActiveLightboxIndex(idx)}
              onEditVideo={canEditVideos ? (vid) => openVideoEditModal(vid) : undefined}
              onDeleteVideo={canDeleteVideos ? async (vid) => {
                const deleted = await handleDeleteVideoItem(vid);
                if (deleted) {
                  if (shortVideos.length <= 1) {
                    setActiveLightboxIndex(null);
                  } else if (activeLightboxIndex !== null && activeLightboxIndex >= shortVideos.length - 1) {
                    setActiveLightboxIndex(Math.max(0, shortVideos.length - 2));
                  }
                }
                return deleted;
              } : undefined}
            />
          )}

          {videoTotal > 0 && (
            <div className="pagination-row pagination-row-bottom">
              <button disabled={videoOffset === 0 || busy} onClick={() => void refreshVideos(Math.max(0, videoOffset - videoPageSize), selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter)}>
                上一页
              </button>
              <span>
                {videoOffset + 1} - {Math.min(videoOffset + videoPageSize, videoTotal)} / 共 {videoTotal}
              </span>
              <button disabled={videoOffset + videoPageSize >= videoTotal || busy} onClick={() => void refreshVideos(videoOffset + videoPageSize, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter)}>
                下一页
              </button>
            </div>
          )}

        </main>
      <VideoUploadModal model={model} />

      {isVideoEditModalOpen && editingVideoId != null && (
        <div className="modal-backdrop" onClick={() => setIsVideoEditModalOpen(false)}>
          <div className="video-edit-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">编辑视频</p>
                <h2>修改信息</h2>
              </div>
              <button className="close-modal" onClick={() => setIsVideoEditModalOpen(false)}>关闭</button>
            </div>
            <div className="stack-editor">
              <input value={editVideoTitle} onChange={(event) => setEditVideoTitle(event.target.value)} placeholder="视频标题" />
              <textarea
                className="rich-text-editor compact"
                value={editVideoDescription}
                onChange={(event) => setEditVideoDescription(event.target.value)}
                placeholder="视频简介"
              />
            </div>
            <div className="editor-block">
              <label>视频大类形态</label>
              <div className="video-type-radio-group">
                <label className="video-type-radio-item">
                  <input
                    type="radio"
                    name="editVideoType"
                    value="short"
                    checked={editVideoType === "short"}
                    onChange={() => setEditVideoType("short")}
                  />
                  <span className="radio-label-with-icon"><Sparkles size={14} /> <b>短视频</b></span>
                </label>
                <label className="video-type-radio-item">
                  <input
                    type="radio"
                    name="editVideoType"
                    value="long"
                    checked={editVideoType === "long"}
                    onChange={() => setEditVideoType("long")}
                  />
                  <span className="radio-label-with-icon"><Film size={14} /> <b>长视频</b></span>
                </label>
              </div>
            </div>
            <div className="editor-block">
              <label>分区</label>
              <div className="chip-cloud compact">
                {videoCategoryTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={editVideoCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                    onClick={() => {
                      setEditVideoCategoryIds((current) =>
                        current.includes(tag.id) ? current.filter((id) => id !== tag.id) : [...current, tag.id]
                      );
                    }}
                  >
                    #{tag.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="editor-block">
              <label>UP主</label>
              <div className="video-person-cloud compact">
                {videoPeople.map((person) => (
                  <button
                    key={person.id}
                    className={editVideoPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                    onClick={() => {
                      setEditVideoPersonIds((current) =>
                        current.includes(person.id) ? current.filter((id) => id !== person.id) : [...current, person.id]
                      );
                    }}
                  >
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                    <b>{person.name}</b>
                  </button>
                ))}
              </div>
            </div>
            <div className="modal-actions modal-actions-split">
              {canDeleteVideos && (
                <button
                  type="button"
                  className="danger-button"
                  disabled={busy}
                  onClick={() => {
                    const target = videoItems.find((item) => item.id === editingVideoId) ?? selectedVideo;
                    if (!target) {
                      return;
                    }
                    void handleDeleteVideoItem(target).then((deleted) => {
                      if (deleted) {
                        setIsVideoEditModalOpen(false);
                        setEditingVideoId(null);
                      }
                    });
                  }}
                >
                  <Trash2 size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
                  删除视频
                </button>
              )}
              <div className="modal-actions-right">
                <button className="ghost-button" onClick={() => setIsVideoEditModalOpen(false)}>取消</button>
                <button disabled={busy} onClick={() => void handleSaveVideoEdit()}>保存</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {isCategoryManageModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsCategoryManageModalOpen(false)}>
          <div className="manage-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">管理分区</p>
                <h2>视频分类</h2>
              </div>
              <button className="close-modal" onClick={() => setIsCategoryManageModalOpen(false)}>关闭</button>
            </div>
            <div className="inline-editor flush-editor">
              <input value={newManageCategoryName} onChange={(event) => setNewManageCategoryName(event.target.value)} placeholder="新分区名称" />
              <button disabled={busy || !newManageCategoryName.trim()} onClick={() => void handleCreateManageCategory()}>创建</button>
            </div>
            <div className="manage-list">
              {videoCategoryTags.map((tag) => (
                <div key={tag.id} className="manage-item">
                  {editingCategoryId === tag.id ? (
                    <div className="inline-editor flush-editor flex-editor">
                      <input value={editingCategoryName} onChange={(event) => setEditingCategoryName(event.target.value)} placeholder="分区名称" />
                      <button disabled={busy || !editingCategoryName.trim()} onClick={() => void handleUpdateManageCategory(tag.id)}>保存</button>
                      <button className="ghost-button" onClick={() => { setEditingCategoryId(null); setEditingCategoryName(""); }}>取消</button>
                    </div>
                  ) : (
                    <>
                      <span>#{tag.name}</span>
                      <div className="micro-row wrap mini-actions">
                        <button className="mini-button" onClick={() => { setEditingCategoryId(tag.id); setEditingCategoryName(tag.name); }}>编辑</button>
                        <button className="mini-button danger-text" onClick={() => void handleDeleteManageCategory(tag.id)}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {videoCategoryTags.length === 0 && <p className="tip">暂无分区</p>}
            </div>
          </div>
        </div>
      )}
      {isVideoPersonManageModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsVideoPersonManageModalOpen(false)}>
          <div className="manage-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">管理UP主</p>
                <h2>视频人物</h2>
              </div>
              <button className="close-modal" onClick={() => setIsVideoPersonManageModalOpen(false)}>关闭</button>
            </div>
            <div className="stack-editor modal-stack">
              <input value={newManagePersonName} onChange={(event) => setNewManagePersonName(event.target.value)} placeholder="UP主名称" />
              <input value={newManagePersonNote} onChange={(event) => setNewManagePersonNote(event.target.value)} placeholder="备注（可选）" />
              <div className="inline-editor flush-editor">
                <input type="file" accept="image/*" onChange={(event) => setNewManagePersonAvatar(event.target.files?.[0] ?? null)} />
                <button disabled={busy || !newManagePersonName.trim()} onClick={() => void handleCreateManagePerson()}>创建</button>
              </div>
            </div>
            <div className="manage-list">
              {videoPeople.map((person) => (
                <div key={person.id} className="manage-item">
                  {editingPersonId === person.id ? (
                    <div className="stack-editor flex-editor">
                      <input value={editingPersonName} onChange={(event) => setEditingPersonName(event.target.value)} placeholder="UP主名称" />
                      <input value={editingPersonNote} onChange={(event) => setEditingPersonNote(event.target.value)} placeholder="备注（可选）" />
                      <div className="inline-editor flush-editor">
                        <input type="file" accept="image/*" onChange={(event) => setEditingPersonAvatar(event.target.files?.[0] ?? null)} />
                        <button disabled={busy || !editingPersonName.trim()} onClick={() => void handleUpdateManagePerson(person.id)}>保存</button>
                        <button className="ghost-button" onClick={() => { setEditingPersonId(null); setEditingPersonName(""); setEditingPersonNote(""); setEditingPersonAvatar(null); }}>取消</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="manage-person-info">
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <div>
                          <strong>{person.name}</strong>
                          {person.note && <small>{person.note}</small>}
                        </div>
                      </div>
                      <div className="micro-row wrap mini-actions">
                        <button className="mini-button" onClick={() => { setEditingPersonId(person.id); setEditingPersonName(person.name); setEditingPersonNote(person.note || ""); setEditingPersonAvatar(null); }}>编辑</button>
                        <button className="mini-button danger-text" onClick={() => void handleDeleteManagePerson(person.id)}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {videoPeople.length === 0 && <p className="tip">暂无UP主</p>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
