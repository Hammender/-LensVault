import { Download, FileUp, RotateCcw, Search, Trash2, UserPlus, XCircle } from "lucide-react";

import type { PeopleModel } from "../hooks/usePeople";
import { isSystemUnknownPerson } from "../lib/personPicker";
import { sortByPinyinName } from "../lib/sort";
import { formatPhotoDate, withImageWidth } from "../lib/utils";

export default function PeoplePage({ model }: { model: PeopleModel }) {
  const {
    busy,
    canAddSamples,
    canDeleteSamples,
    canEditSamples,
    canEditGallery,
    persons,
    tags,
    selectedPerson,
    peopleSearch,
    peopleBatchDeleteMode,
    selectedPersonDeleteIds,
    samples,
    personTags,
    personTagSelectId,
    personTagName,
    newPersonName,
    renameValue,
    importFileRef,
    importTask,
    pendingSampleUploads,
    highlightedSampleId,
    peopleMainRef,
    filteredPeopleInLibrary,
    unknownPersonCount,
    selectedPersonIsSystemUnknown,
    selectedPersonDeleteCount,
    setPeopleSearch,
    setNewPersonName,
    setRenameValue,
    setPersonTagSelectId,
    setPersonTagName,
    setSelectedPersonDeleteIds,
    handleCreatePerson,
    handleRenamePerson,
    handlePickSampleFiles,
    handleConfirmSampleUpload,
    handleRemovePendingSample,
    handleDeleteSample,
    togglePeopleBatchDeleteMode,
    handleDeleteSelectedPersons,
    handleDeleteCurrentPerson,
    handleReRecognizeAllUnknownPhotos,
    handleClearUnknownPersonTags,
    handleExportPersons,
    handlePickImportFile,
    handleImportFileChange,
    handleSelectPerson,
    handleOpenSampleSource,
    handleBindPersonTag,
    handleUnbindPersonTag
  } = model;

  return (
        <main className="page-grid people-page">
          <section className="panel people-sidebar">
            <div className="section-head">
              <div>
                <p className="eyebrow">人物库</p>
                <h2>创建与选择人物</h2>
              </div>
              <div className="people-count-badge">
                <span>{persons.length} 人</span>
              </div>
            </div>

            <div className="people-commandbar">
              {canDeleteSamples && (
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy} onClick={() => togglePeopleBatchDeleteMode()}>
                  <Trash2 size={15} aria-hidden="true" />
                  {peopleBatchDeleteMode ? "取消批量" : "批量删除"}
                </button>
                <button
                  disabled={busy || !peopleBatchDeleteMode || selectedPersonDeleteCount === 0}
                  onClick={() => void handleDeleteSelectedPersons()}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  删除选中（{selectedPersonDeleteCount}）
                </button>
              </div>
              )}
              {canEditGallery && (
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleReRecognizeAllUnknownPhotos()}>
                  <RotateCcw size={15} aria-hidden="true" />
                  一键重新识别所有未知人物
                </button>
                <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleClearUnknownPersonTags()}>
                  <XCircle size={15} aria-hidden="true" />
                  一键清空未知人物标签
                </button>
              </div>
              )}
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy} onClick={() => void handleExportPersons()}>
                  <Download size={15} aria-hidden="true" />
                  导出样本库
                </button>
                {canAddSamples && (
                <button disabled={busy} onClick={handlePickImportFile}>
                  <FileUp size={15} aria-hidden="true" />
                  导入样本库
                </button>
                )}
              </div>
                <input
                  ref={importFileRef}
                  type="file"
                  accept=".zip"
                  style={{ display: "none" }}
                  onChange={(event) => void handleImportFileChange(event)}
                />
                {importTask && importTask.status !== "completed" && importTask.status !== "failed" && (
                  <div className="task-bar">
                    <progress value={importTask.progress} max={1}></progress>
                    <span>{importTask.message}</span>
                  </div>
                )}
                {importTask && importTask.status === "completed" && (
                  <div className="task-bar success">
                    <span>{importTask.message}</span>
                  </div>
                )}
                {importTask && importTask.status === "failed" && (
                  <div className="task-bar error">
                    <span>导入失败：{importTask.message}</span>
                  </div>
                )}
            </div>

            {canAddSamples && (
            <div className="inline-editor people-create-row">
              <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} placeholder="输入新人物名称" />
              <button disabled={busy || !newPersonName.trim()} onClick={() => void handleCreatePerson()}>
                <UserPlus size={15} aria-hidden="true" />
                创建人物
              </button>
            </div>
            )}

            <label className="people-search">
              <Search size={16} aria-hidden="true" />
              <input
                className="search-input subtle"
                value={peopleSearch}
                onChange={(event) => setPeopleSearch(event.target.value)}
                placeholder="搜索人物名称、拼音或首字母"
              />
            </label>

            <div className="person-list">
              {filteredPeopleInLibrary.map((person) => (
                <article key={person.id} className="person-card-wrap">
                  <button
                    className={selectedPerson?.id === person.id ? "person-card active" : "person-card"}
                    onClick={() => handleSelectPerson(person)}
                  >
                    <span className={person.is_unknown ? "person-avatar-marker unknown" : "person-avatar-marker"}>
                      {person.display_name.slice(0, 1)}
                    </span>
                    <div className="person-card-main">
                      <strong>{person.display_name}</strong>
                      <span>{person.is_unknown ? "未知人物" : "正式人物"}</span>
                    </div>
                    <small className="person-card-stats">
                      <b>{person.sample_count}</b>
                      <span>样本</span>
                      <b>{person.gallery_photo_count}</b>
                      <span>图库</span>
                    </small>
                  </button>
                  {peopleBatchDeleteMode && (
                    <label className="row-check">
                      <input
                        type="checkbox"
                        disabled={isSystemUnknownPerson(person)}
                        checked={selectedPersonDeleteIds.includes(person.id)}
                        onChange={(event) => {
                          if (isSystemUnknownPerson(person)) {
                            return;
                          }
                          setSelectedPersonDeleteIds((current) =>
                            event.target.checked ? [...current, person.id] : current.filter((id) => id !== person.id)
                          );
                        }}
                      />
                      <span>选中删除</span>
                    </label>
                  )}
                </article>
              ))}
              {filteredPeopleInLibrary.length === 0 && <div className="empty-card">没有匹配的人物。</div>}
            </div>
          </section>

          <section ref={peopleMainRef} className="panel people-main">
            {selectedPerson ? (
              <>
                <div className="section-head">
                  <div>
                    <p className="eyebrow">人物详情</p>
                    <h2>{selectedPerson.display_name}</h2>
                  </div>
                  <div className="micro-row">
                    <span>{selectedPersonIsSystemUnknown ? "图库未知标签" : selectedPerson.is_unknown ? "未知人物" : "样本库维护"}</span>
                    {canDeleteSamples && (
                    <button disabled={busy || selectedPersonIsSystemUnknown} onClick={() => void handleDeleteCurrentPerson()}>
                      删除当前人物
                    </button>
                    )}
                  </div>
                </div>

                {!selectedPersonIsSystemUnknown && (
                  <>
                    {canEditSamples && (
                    <div className="rename-strip">
                      <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} placeholder="输入新名字" />
                      <button disabled={busy || !renameValue.trim()} onClick={() => void handleRenamePerson()}>
                        {selectedPerson.is_unknown ? "转正并改名" : "更新名称"}
                      </button>
                    </div>
                    )}

                    <div className="editor-block">
                      <label>人物普通标签（自动继承到该人物相关图库图片）</label>
                      <div className="micro-row wrap">
                        {personTags.map((tag) =>
                          canEditSamples ? (
                          <button key={tag.id} className="pill muted action-pill" onClick={() => void handleUnbindPersonTag(tag.id)}>
                            #{tag.name}
                          </button>
                          ) : (
                          <span key={tag.id} className="pill muted">#{tag.name}</span>
                          )
                        )}
                        {personTags.length === 0 && <span className="tip">还没有人物级普通标签。</span>}
                      </div>
                      {canEditSamples && (
                      <div className="stack-editor">
                        <div className="inline-editor">
                          <select value={personTagSelectId} onChange={(event) => setPersonTagSelectId(event.target.value)}>
                            <option value="">从已有标签添加</option>
                            {sortByPinyinName(tags.filter((tag) => !personTags.some((item) => item.id === tag.id))).map((tag) => (
                              <option key={tag.id} value={tag.id}>
                                #{tag.name}
                              </option>
                            ))}
                          </select>
                          <button disabled={busy || !personTagSelectId} onClick={() => void handleBindPersonTag()}>
                            添加已有标签
                          </button>
                        </div>
                        <div className="inline-editor">
                          <input
                            value={personTagName}
                            onChange={(event) => setPersonTagName(event.target.value)}
                            placeholder="输入新标签名称"
                          />
                          <button disabled={busy || !personTagName.trim()} onClick={() => void handleBindPersonTag()}>
                            新建并添加
                          </button>
                        </div>
                      </div>
                      )}
                    </div>

                    {canAddSamples && (
                    <label className="upload-box">
                      <input type="file" multiple accept="image/*" onChange={(event) => handlePickSampleFiles(event.target.files)} />
                      <strong>上传人物样本图</strong>
                      <span>先预览样本，再点击确认上传；仅接受单张照片恰好一张脸的样本进入向量库。</span>
                    </label>
                    )}
                  </>
                )}

                {!selectedPersonIsSystemUnknown && pendingSampleUploads.length > 0 && (
                  <div className="editor-block">
                    <label>待上传样本预览（{pendingSampleUploads.length}）</label>
                    <div className="pending-grid">
                      {pendingSampleUploads.map((item, index) => (
                        <article key={`${item.file.name}-${index}`} className="pending-card">
                          <img src={item.previewUrl} alt="样本预览" />
                          <div>
                            <strong>待上传样本 {index + 1}</strong>
                            <span>{Math.round(item.file.size / 1024)} KB</span>
                          </div>
                          <button className="ghost-button" onClick={() => handleRemovePendingSample(index)}>
                            移除
                          </button>
                        </article>
                      ))}
                    </div>
                    <button disabled={busy} onClick={() => void handleConfirmSampleUpload()}>
                      确认上传样本
                    </button>
                  </div>
                )}

                <div className="sample-grid">
                  {samples.map((sample) => {
                    const isLandscape = sample.width && sample.height && sample.width / sample.height > 1.15;
                    const cardClass = `sample-card ${isLandscape ? "span-2" : ""}`;

                    return (
                      <article id={`sample-${sample.id}`} key={sample.id} className={`${cardClass}${highlightedSampleId === sample.id ? " matched-sample-highlight" : ""}`}>
                        <a href={sample.original_url} target="_blank" rel="noreferrer">
                          <img src={withImageWidth(sample.thumbnail_url, 480)} alt="样本缩略图" />
                        </a>
                        <div className="sample-copy">
                          <strong>样本记录 #{sample.id}</strong>
                          <span>{formatPhotoDate(sample.taken_at, sample.created_at)}</span>
                          <small className={`status-pill status-${sample.status}`}>{sample.status}</small>
                          {sample.error_message && <p>{sample.error_message}</p>}
                          {sample.source_type === "gallery_face" && (
                            sample.source_gallery_photo_id !== null ? (
                              <button
                                className="ghost-button"
                                onClick={() => void handleOpenSampleSource(sample.source_gallery_photo_id!)}
                              >
                                来源：展示图库 #{sample.source_gallery_photo_id}
                              </button>
                            ) : (
                              <small>来源展示图已删除</small>
                            )
                          )}
                        </div>
                        {!selectedPersonIsSystemUnknown && canDeleteSamples && (
                          <button className="ghost-button" onClick={() => void handleDeleteSample(sample.id)}>
                            删除样本
                          </button>
                        )}
                      </article>
                    );
                  })}
                  {samples.length === 0 && <div className="empty-card">当前人物还没有样本图片。</div>}
                </div>
              </>
            ) : (
              <div className="empty-card">左侧选择一个人物后，在这里维护样本图。</div>
            )}
          </section>
        </main>
  );
}
