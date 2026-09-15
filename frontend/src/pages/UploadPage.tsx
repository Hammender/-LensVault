import { Clapperboard, ImagePlus, UploadCloud } from "lucide-react";

import UploadPersonPicker from "../components/UploadPersonPicker";
import VideoUploadModal from "../components/VideoUploadModal";
import type { UploadModel } from "../hooks/useUpload";
import type { VideosModel } from "../hooks/useVideos";
import { mergePersonIds } from "../lib/personPicker";

export default function UploadPage({ upload, videos }: { upload: UploadModel; videos: VideosModel }) {
  const model = { ...videos, ...upload };
  const {
    canAddGallery,
    canAddVideos,
    persons,
    pendingGalleryUploads,
    batchApplyPersonIds,
    batchApplyPersonSearch,
    batchApplyPersonNotice,
    batchApplyTagNames,
    uploadMode,
    galleryUploadBusy,
    task,
    richTag,
    setUploadMode,
    setBatchApplyPersonIds,
    setBatchApplyPersonSearch,
    setBatchApplyPersonNotice,
    setBatchApplyTagNames,
    handlePickGalleryFiles,
    handleUpdatePendingGallery,
    handleApplyBatchMetadataToAll,
    handleRemovePendingGallery,
    handleConfirmGalleryUpload,
    videoUploadQueue,
    videoUploadBusy,
    videoUploadTotalCount,
    videoUploadCurrentIndex,
    videoFiles,
    videoUploadProgress,
    videoUploadGenerateSubtitles,
    setIsVideoUploadModalOpen
  } = model;
    const queueTotal = videoUploadQueue.length;
    const queueCompleted = videoUploadQueue.filter((item) => item.status === "completed").length;
    const queueFailed = videoUploadQueue.filter((item) => item.status === "failed").length;
    const queueNeedsFile = videoUploadQueue.filter((item) => item.status === "needs_file").length;
    const queueUploading = videoUploadQueue.find((item) => item.status === "uploading");
    const progressQueue = videoUploadQueue.filter((item) => item.status !== "needs_file" && item.status !== "failed");
    const queueProgress =
      progressQueue.length > 0
        ? Math.round(progressQueue.reduce((sum, item) => sum + item.progress, 0) / progressQueue.length)
        : videoUploadProgress;
    let videoUploadState = "待选择";
    if (queueTotal > 0) {
      videoUploadState =
        videoUploadBusy && videoUploadTotalCount > 0
          ? `上传中 ${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / ${videoUploadTotalCount}`
          : `队列 ${queueTotal} 个，完成 ${queueCompleted} 个`;
    } else if (videoUploadTotalCount > 0) {
      videoUploadState = `上传中 ${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / ${videoUploadTotalCount}`;
    } else if (videoFiles.length > 0) {
      videoUploadState = `已选择 ${videoFiles.length} 个视频`;
    }
    let videoUploadNote = "支持长视频分片上传，上传后自动转为网页可播放格式。";
    if (queueNeedsFile > 0) {
      videoUploadNote = `${queueNeedsFile} 个视频需要重新选择原文件后继续上传。`;
    } else if (queueFailed > 0) {
      videoUploadNote = `${queueFailed} 个视频上传失败，可重新选择原文件后继续。`;
    } else if (queueUploading) {
      videoUploadNote = queueUploading.filename;
    } else if (videoUploadQueue.length > 0) {
      videoUploadNote = videoUploadQueue.map((item) => item.filename).join("、");
    } else if (videoFiles.length > 0) {
      videoUploadNote = videoFiles.map((file) => file.name).join("、");
    }

  return (
    <>
        <main className="page-grid upload-page">
          <section className="panel upload-main">
            <div className="section-head">
              <div>
                <p className="eyebrow">素材上传</p>
                <h2>图片与视频统一入库</h2>
              </div>
              <span>批量导入工作台</span>
            </div>

            <div className="upload-channel-grid">
              <article className="upload-channel-card upload-channel-card-image">
                <div className="upload-channel-head">
                  <span className="upload-channel-icon">
                    <ImagePlus size={22} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="eyebrow">图片入库</p>
                    <h3>展示图识别</h3>
                  </div>
                </div>
                <div className="upload-mode-switch">
                  <button
                    className={uploadMode === "normal" ? "soft-chip active" : "soft-chip"}
                    onClick={() => setUploadMode("normal")}
                  >
                    普通图片
                  </button>
                  <button className={uploadMode === "rich" ? "soft-chip active" : "soft-chip"} onClick={() => setUploadMode("rich")}>
                    图文图片
                  </button>
                </div>
                {canAddGallery ? (
                <>
                <label className="upload-box large upload-box-image">
                  <input type="file" multiple accept="image/*" onChange={(event) => handlePickGalleryFiles(event.target.files)} />
                  <strong>{uploadMode === "rich" ? "选择图文图片" : "选择展示图片"}</strong>
                  <span>
                    {uploadMode === "rich"
                      ? "可补录文本或留空走 OCR，并自动执行人脸识别。"
                      : "预览后填写人物和标签，再统一提交到识别队列。"}
                  </span>
                </label>
                <small className="upload-channel-note">
                  {uploadMode === "rich"
                    ? `将自动打 #图文 标签${richTag ? "" : "（系统会自动创建）"}`
                    : "沿用普通图片流程：人脸识别 + 人物标签 + 普通标签"}
                </small>
                </>
                ) : (
                  <p className="tip">当前账号没有新增展示图权限。</p>
                )}
              </article>

              <article className="upload-channel-card upload-channel-card-video">
                <div className="upload-channel-head">
                  <span className="upload-channel-icon">
                    <Clapperboard size={22} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="eyebrow">视频入库</p>
                    <h3>分片上传</h3>
                  </div>
                </div>
                <div className="upload-channel-status">
                  <strong>{videoUploadState}</strong>
                  <span>{videoUploadNote}</span>
                </div>
                <div className="upload-channel-progress">
                  <div className="meter">
                    <span style={{ width: `${queueProgress}%` }} />
                  </div>
                  <small>{queueProgress}%</small>
                </div>
                {canAddVideos && (
                <button className="primary upload-video-entry" onClick={() => setIsVideoUploadModalOpen(true)}>
                  <UploadCloud size={16} aria-hidden="true" />
                  上传视频
                </button>
                )}
              </article>
            </div>

            {pendingGalleryUploads.length > 0 && (
              <div className="editor-block">
                <div className="stack-editor">
                  <label>批量套用到全部待上传图片</label>
                  <div className="upload-batch-editor">
                    <UploadPersonPicker
                      id="batch-gallery-person-picker"
                      persons={persons}
                      selectedIds={batchApplyPersonIds}
                      query={batchApplyPersonSearch}
                      notice={batchApplyPersonNotice}
                      disabled={galleryUploadBusy}
                      onQueryChange={setBatchApplyPersonSearch}
                      onNoticeChange={setBatchApplyPersonNotice}
                      onAdd={(personId) => setBatchApplyPersonIds((current) => mergePersonIds(current, [personId]))}
                      onRemove={(personId) => setBatchApplyPersonIds((current) => current.filter((id) => id !== personId))}
                    />
                    <input
                      value={batchApplyTagNames}
                      onChange={(event) => setBatchApplyTagNames(event.target.value)}
                      placeholder="普通标签（逗号分隔）"
                    />
                    <button disabled={galleryUploadBusy} onClick={() => handleApplyBatchMetadataToAll()}>
                      批量套用
                    </button>
                  </div>
                </div>
                <label>待上传图片（{pendingGalleryUploads.length}）</label>
                <div className="pending-grid pending-grid-gallery">
                  {pendingGalleryUploads.map((item, index) => (
                    <article key={`${item.file.name}-${index}`} className="pending-card pending-card-gallery">
                      <img src={item.previewUrl} alt="待上传预览" />
                      <div className="pending-card-copy">
                        <strong>待上传图片 {index + 1}</strong>
                        <span>{Math.round(item.file.size / 1024)} KB</span>
                        <UploadPersonPicker
                          id={`gallery-person-picker-${index}`}
                          persons={persons}
                          selectedIds={item.personIds}
                          query={item.personSearch}
                          notice={item.personNotice}
                          disabled={galleryUploadBusy}
                          onQueryChange={(personSearch) => handleUpdatePendingGallery(index, { personSearch })}
                          onNoticeChange={(personNotice) => handleUpdatePendingGallery(index, { personNotice })}
                          onAdd={(personId) => handleUpdatePendingGallery(index, {
                            personIds: mergePersonIds(item.personIds, [personId])
                          })}
                          onRemove={(personId) => handleUpdatePendingGallery(index, {
                            personIds: item.personIds.filter((id) => id !== personId)
                          })}
                        />
                        <input
                          value={item.tagNamesText}
                          onChange={(event) => handleUpdatePendingGallery(index, { tagNamesText: event.target.value })}
                          placeholder="普通标签（逗号分隔，可留空）"
                        />
                        {uploadMode === "rich" && (
                          <textarea
                            className="rich-text-editor compact"
                            value={item.richText}
                            onChange={(event) => handleUpdatePendingGallery(index, { richText: event.target.value })}
                            placeholder="图文文本（可留空，后端自动OCR）"
                          />
                        )}
                      </div>
                      <button className="ghost-button" onClick={() => handleRemovePendingGallery(index)}>
                        移除
                      </button>
                    </article>
                  ))}
                </div>
                <button disabled={galleryUploadBusy} onClick={() => void handleConfirmGalleryUpload()}>
                  确认上传（批量）
                </button>
              </div>
            )}
          </section>

          <aside className="panel upload-side">
            <div className="section-head">
              <div>
                <p className="eyebrow">任务状态</p>
                <h2>识别进度</h2>
              </div>
            </div>

            <div className="task-box">
              <strong>{task ? task.status : "idle"}</strong>
              <p>{task?.message ?? "上传后会在这里看到导入进度和识别摘要。"}</p>
              <div className="meter">
                <span style={{ width: `${Math.round((task?.progress ?? 0) * 100)}%` }} />
              </div>
            </div>

            <div className="info-list">
              <article>
                <strong>已知人物</strong>
                <span>命中阈值后会直接写入展示图人物标签。</span>
              </article>
              <article>
                <strong>未知人物</strong>
                <span>未命中样本库时统一标记为“未知人物”，可在图库详情中重新识别或改为正式人物。</span>
              </article>
              <article>
                <strong>普通标签</strong>
                <span>支持选已有，也支持上传时现场新增，供展示图库组合检索。</span>
              </article>
            </div>

            <div className="info-list upload-video-info">
              <article>
                <strong>视频状态</strong>
                <span>{videoUploadState}</span>
              </article>
              <article>
                <strong>字幕处理</strong>
                <span>{videoUploadGenerateSubtitles ? "上传完成后自动提交中文字幕生成。" : "可在视频上传弹窗中开启中文字幕生成。"}</span>
              </article>
            </div>
          </aside>
        </main>
        <VideoUploadModal model={videos} />
    </>
  );
}
