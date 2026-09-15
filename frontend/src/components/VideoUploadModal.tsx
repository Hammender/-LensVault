import { Film, Sparkles } from "lucide-react";

import type { VideosModel } from "../hooks/useVideos";
import { formatBytes, supportedVideoAccept, supportedVideoFormatLabel } from "../lib/utils";
import { videoFileFingerprint, videoQueueStatusLabel } from "../lib/videoUploadQueue";

export default function VideoUploadModal({ model }: { model: VideosModel }) {
  const {
    error,
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
    videoCategoryTags,
    videoPeople,
    isVideoUploadModalOpen,
    setVideoTitle,
    setVideoDescription,
    setVideoUploadTypeMode,
    setVideoUploadNewCategories,
    setVideoUploadGenerateSubtitles,
    setIsVideoUploadModalOpen,
    handlePickVideoFile,
    handleToggleVideoUploadCategory,
    handleToggleVideoUploadPerson,
    handleConfirmVideoUpload,
    handleCancelVideoUpload
  } = model;
  if (!isVideoUploadModalOpen) {
    return null;
  }
  const selectedVideoFileIds = new Set(videoFiles.map((file) => videoFileFingerprint(file)));
  const uploadableQueueCount = videoUploadQueue.filter((item) => item.status !== "completed" && selectedVideoFileIds.has(item.id)).length;
  const queueNeedsFileCount = videoUploadQueue.filter((item) => item.status === "needs_file").length;
  const queueFailedCount = videoUploadQueue.filter((item) => item.status === "failed").length;
  const canStartVideoUpload = uploadableQueueCount > 0 && !(videoFiles.length === 1 && !videoTitle.trim());
  const progressQueue = videoUploadQueue.filter((item) => item.status !== "needs_file" && item.status !== "failed");
  const videoModalProgress =
    progressQueue.length > 0
      ? Math.round(progressQueue.reduce((sum, item) => sum + item.progress, 0) / progressQueue.length)
      : videoUploadProgress;

  return (
    <div className="modal-backdrop">
      <aside className="panel video-upload-panel bili-modal-content">
        <div className="section-head">
          <div>
            <p className="eyebrow">上传视频</p>
            <h2>分片入库</h2>
          </div>
          <button className="close-modal" onClick={() => setIsVideoUploadModalOpen(false)}>关闭</button>
        </div>

        <label className="upload-box video-upload-box">
          <input type="file" accept={supportedVideoAccept} multiple onChange={(event) => handlePickVideoFile(event.target.files)} />
          <strong>{videoFiles.length === 1 ? videoFiles[0].name : videoFiles.length > 1 ? `已选 ${videoFiles.length} 个视频` : `选择视频（${supportedVideoFormatLabel}，可多选）`}</strong>
          <span>{videoFiles.length >= 1 ? videoFiles.map((f) => formatBytes(f.size)).join("、") : "支持长视频分片上传，上传后会自动转为网页可播放格式。"}</span>
        </label>

        {videoUploadQueue.length > 0 && (
          <div className="editor-block">
            <label>
              上传队列（{videoUploadQueue.length}）
              {queueNeedsFileCount > 0 && ` · ${queueNeedsFileCount} 个需重选文件`}
              {queueFailedCount > 0 && ` · ${queueFailedCount} 个失败`}
            </label>
            <div className="video-upload-queue">
              {videoUploadQueue.map((item) => (
                <article key={item.id} className="video-upload-queue-item">
                  <div className="pending-card-copy">
                    <strong>{item.title || item.filename}</strong>
                    <span>{item.filename} · {formatBytes(item.size)}</span>
                    <span>{videoQueueStatusLabel(item.status)} · {item.progress}%</span>
                    <div className="meter">
                      <span style={{ width: `${item.progress}%` }} />
                    </div>
                    {item.error && <small>{item.error}</small>}
                  </div>
                </article>
              ))}
            </div>
          </div>
        )}

        <div className="stack-editor">
          <input value={videoTitle} onChange={(event) => setVideoTitle(event.target.value)} placeholder="单个视频时可自定义标题" disabled={videoFiles.length > 1} />
          <textarea
            className="rich-text-editor compact"
            value={videoDescription}
            onChange={(event) => setVideoDescription(event.target.value)}
            placeholder="视频简介（批量上传时所有文件共用此简介）"
          />
        </div>

        <div className="editor-block">
          <label>视频大类形态</label>
          <div className="video-type-radio-group">
            <label className="video-type-radio-item">
              <input
                type="radio"
                name="videoUploadTypeMode"
                value="auto"
                checked={videoUploadTypeMode === "auto"}
                onChange={() => setVideoUploadTypeMode("auto")}
              />
              <span><b>自动判定</b>（≤5分钟为短视频，&gt;5分钟为长视频）</span>
            </label>
            <label className="video-type-radio-item">
              <input
                type="radio"
                name="videoUploadTypeMode"
                value="short"
                checked={videoUploadTypeMode === "short"}
                onChange={() => setVideoUploadTypeMode("short")}
              />
              <span className="radio-label-with-icon"><Sparkles size={14} /> <b>指定为短视频</b></span>
            </label>
            <label className="video-type-radio-item">
              <input
                type="radio"
                name="videoUploadTypeMode"
                value="long"
                checked={videoUploadTypeMode === "long"}
                onChange={() => setVideoUploadTypeMode("long")}
              />
              <span className="radio-label-with-icon"><Film size={14} /> <b>指定为长视频</b></span>
            </label>
          </div>
        </div>

        <div className="editor-block">
          <label>上传时绑定类别</label>
          <div className="chip-cloud compact">
            {videoCategoryTags.map((tag) => (
              <button
                key={tag.id}
                className={videoUploadCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                onClick={() => handleToggleVideoUploadCategory(tag.id)}
              >
                #{tag.name}
              </button>
            ))}
          </div>
          <input
            value={videoUploadNewCategories}
            onChange={(event) => setVideoUploadNewCategories(event.target.value)}
            placeholder="新类别标签，逗号分隔"
          />
        </div>

        <div className="editor-block">
          <label>上传时绑定人物</label>
          <div className="video-person-cloud compact">
            {videoPeople.map((person) => (
              <button
                key={person.id}
                className={videoUploadPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                onClick={() => handleToggleVideoUploadPerson(person.id)}
              >
                {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                <b>{person.name}</b>
              </button>
            ))}
          </div>
        </div>

        <label className="toggle-row subtitle-upload-toggle">
          <input
            type="checkbox"
            checked={videoUploadGenerateSubtitles}
            onChange={(event) => setVideoUploadGenerateSubtitles(event.target.checked)}
          />
          <span>自动生成中文字幕</span>
        </label>

        {error && <div className="error-banner modal-inline-error">{error}</div>}

        <div className="video-progress">
          <strong>{videoModalProgress}%</strong>
          <div className="meter"><span style={{ width: `${videoModalProgress}%` }} /></div>
          {videoUploadTotalCount > 0 && (
            <small>文件 {Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / {videoUploadTotalCount}</small>
          )}
          {videoUploadSession && <small>{videoUploadSession.uploaded_parts.length} / {videoUploadSession.total_parts} 分片</small>}
        </div>

        <div className="micro-row wrap">
          <button disabled={videoUploadBusy || !canStartVideoUpload} onClick={() => void handleConfirmVideoUpload()}>
            {videoUploadTotalCount > 0
              ? `上传中 (${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)}/${videoUploadTotalCount})`
              : videoUploadQueue.some((item) => item.status === "needs_file" || item.status === "failed")
                ? "继续上传"
                : "开始上传"}
          </button>
          <button className="ghost-button" disabled={videoUploadBusy} onClick={() => void handleCancelVideoUpload()}>
            清理续传会话
          </button>
        </div>
      </aside>
    </div>
  );
}