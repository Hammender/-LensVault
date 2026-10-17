import { Download, FileUp, RotateCcw, Search, Trash2, UserPlus, XCircle, Tags, UsersRound, Plus, ArrowUpRight, X } from "lucide-react";
import { useRef, useState } from "react";

import type { PeopleModel } from "../hooks/usePeople";
import { isSystemUnknownPerson } from "../lib/personPicker";
import { sortByPinyinName } from "../lib/sort";
import { formatPhotoDate, withImageWidth } from "../lib/utils";
import "./PeoplePage.css";

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
    personTags,
    personTagSelectId,
    personTagName,
    renameValue,
    importFileRef,
    importTask,
    pendingSampleUploads,
    peopleMainRef,
    filteredPeopleInLibrary,
    unknownPersonCount,
    selectedPersonIsSystemUnknown,
    selectedPersonDeleteCount,
    setPeopleSearch,
    setRenameValue,
    setPersonTagSelectId,
    setPersonTagName,
    setSelectedPersonDeleteIds,
    handleRenamePerson,
    handlePickSampleFiles,
    handleConfirmSampleUpload,
    handleRemovePendingSample,
    togglePeopleBatchDeleteMode,
    handleDeleteSelectedPersons,
    handleDeleteCurrentPerson,
    handleReRecognizeAllUnknownPhotos,
    handleClearUnknownPersonTags,
    handleExportPersons,
    handlePickImportFile,
    handleImportFileChange,
    handleSelectPerson,
    handleBindPersonTag,
    handleUnbindPersonTag
  } = model;

  const { tagView, setTagView, peopleTagFilter, setPeopleTagFilter, filteredTags,
    tagSearch, setTagSearch, newTagName, setNewTagName, selectedTag, setSelectedTagId,
    tagPersonCounts, handleCreateTag } = model;

  return (
    <main className="tag-library">
      <header className="tag-library-header">
        <div>
          <p className="eyebrow">标签与识别样本</p>
          <h1>图片标签</h1>
          <p className="tag-library-description">整理人物与普通标签，让每一张图片都有迹可循。</p>
        </div>
        <div className="tag-library-header-actions">
          <div className="tag-library-switch" aria-label="标签类型">
            <button className={tagView === "people" ? "active" : ""} aria-pressed={tagView === "people"}
              disabled={busy} onClick={() => setTagView("people")}>
              <UsersRound size={17} />人物标签 <span>{persons.length}</span>
            </button>
            <button className={tagView === "tags" ? "active" : ""} aria-pressed={tagView === "tags"}
              disabled={busy} onClick={() => setTagView("tags")}>
              <Tags size={17} />普通标签 <span>{tags.length}</span>
            </button>
          </div>
          {canAddSamples && tagView === "people" && <CreatePersonAction model={model} />}
        </div>
      </header>
      <div className="page-grid people-page">
        <section className="panel people-sidebar">
          <div className="section-head">
            <div>
              <p className="eyebrow">{tagView === "people" ? "人物索引" : "标签索引"}</p>
              <h2>{tagView === "people" ? "选择人物标签" : "管理普通标签"}</h2>
            </div>
            <span className="people-count-badge">
              {tagView === "people" ? filteredPeopleInLibrary.length : filteredTags.length} / {tagView === "people" ? persons.length : tags.length}
            </span>
          </div>
          {tagView === "people" ? <>
            <div className="tag-library-filters">
              <label className="people-search">
                <Search size={16} aria-hidden="true" />
                <input className="search-input subtle" aria-label="搜索人物" disabled={busy} value={peopleSearch}
                  onChange={(event) => setPeopleSearch(event.target.value)} placeholder="搜索人物名称、拼音或首字母" />
              </label>
              <label className="tag-library-filter">
                <span>按普通标签筛选人物</span>
                <select disabled={busy} value={peopleTagFilter} onChange={(event) => setPeopleTagFilter(event.target.value)}>
                  <option value="">全部人物</option>
                  {sortByPinyinName(tags).map((tag) => <option key={tag.id} value={tag.id}>#{tag.name}（{tagPersonCounts.get(tag.id) ?? 0} 人）</option>)}
                </select>
              </label>
            </div>
            {peopleTagFilter && <div className="tag-library-filter-summary">
              <span>已筛选绑定「{tags.find((tag) => String(tag.id) === peopleTagFilter)?.name}」的人物</span>
              <button className="ghost-button" disabled={busy} onClick={() => setPeopleTagFilter("")}>清除筛选</button>
            </div>}

            {canDeleteSamples && <div className="micro-row people-batch-actions">
              <button disabled={busy} onClick={() => togglePeopleBatchDeleteMode()}>
                <Trash2 size={15} />{peopleBatchDeleteMode ? "取消批量" : "批量删除"}
              </button>
              {peopleBatchDeleteMode && <button disabled={busy || selectedPersonDeleteCount === 0} onClick={() => void handleDeleteSelectedPersons()}>
                删除选中（{selectedPersonDeleteCount}）
              </button>}
            </div>}
            <div className="person-list" aria-label="人物标签列表">
              {filteredPeopleInLibrary.map((person) => (
                <article key={person.id} className="person-card-wrap">
                  <button disabled={busy} aria-pressed={selectedPerson?.id === person.id}
                    className={selectedPerson?.id === person.id ? "person-card active" : "person-card"}
                    onClick={() => handleSelectPerson(person)}>
                    <span className={person.is_unknown ? "person-avatar-marker unknown" : "person-avatar-marker"}>{person.display_name.slice(0, 1)}</span>
                    <div className="person-card-main">
                      <strong>{person.display_name}</strong>
                      <span>{person.is_unknown ? "未知人物" : "人物标签"} · {person.tag_ids?.length ?? 0} 个普通标签</span>
                    </div>
                    <small className="person-card-stats"><b>{person.sample_count}</b><span>样本</span><b>{person.gallery_photo_count}</b><span>图片</span></small>
                  </button>
                  {peopleBatchDeleteMode && <label className="row-check">
                    <input type="checkbox" aria-label={`选中删除 ${person.display_name}`} disabled={busy || isSystemUnknownPerson(person)}
                      checked={selectedPersonDeleteIds.includes(person.id)} onChange={(event) => {
                        if (isSystemUnknownPerson(person)) return;
                        setSelectedPersonDeleteIds((current) => event.target.checked ? [...current, person.id] : current.filter((id) => id !== person.id));
                      }} />选中删除
                  </label>}
                </article>
              ))}
              {filteredPeopleInLibrary.length === 0 && <div className="empty-card">没有匹配的人物，请调整搜索或普通标签筛选。</div>}
            </div>
            <details className="people-maintenance">
              <summary>样本库导入导出与未知人物维护</summary>
              <div className="people-commandbar">
                <div className="micro-row section-actions people-command-row">
                  <button disabled={busy} onClick={() => void handleExportPersons()}><Download size={15} />导出样本库</button>
                  {canAddSamples && <button disabled={busy} onClick={handlePickImportFile}><FileUp size={15} />导入样本库</button>}
                </div>
                {canEditGallery && <div className="micro-row section-actions people-command-row">
                  <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleReRecognizeAllUnknownPhotos()}><RotateCcw size={15} />重新识别所有未知人物</button>
                  <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleClearUnknownPersonTags()}><XCircle size={15} />清空未知人物标签</button>
                </div>}
              </div>
            </details>
          </> : <>
            <label className="people-search">
              <Search size={16} aria-hidden="true" />
              <input className="search-input subtle" aria-label="搜索普通标签" value={tagSearch}
                onChange={(event) => setTagSearch(event.target.value)} placeholder="搜索标签名称、拼音或首字母" />
            </label>
            {canEditGallery && <form className="inline-editor people-create-row" onSubmit={(event) => { event.preventDefault(); void handleCreateTag(); }}>
              <input aria-label="新普通标签名称" maxLength={128} disabled={busy} value={newTagName}
                onChange={(event) => setNewTagName(event.target.value)} placeholder="输入新普通标签名称" />
              <button disabled={busy || !newTagName.trim()}><Plus size={15} />新建标签</button>
            </form>}
            <div className="person-list ordinary-tag-list" aria-label="普通标签列表">
              {filteredTags.map((tag) => <button key={tag.id} disabled={busy} aria-pressed={selectedTag?.id === tag.id}
                className={selectedTag?.id === tag.id ? "ordinary-tag-card active" : "ordinary-tag-card"} onClick={() => setSelectedTagId(tag.id)}>
                <Tags size={20} aria-hidden="true" />
                <strong>#{tag.name}</strong>
                <span>{tag.is_system ? "系统标签" : "普通标签"} · {tagPersonCounts.get(tag.id) ?? 0} 个关联人物</span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>)}
              {filteredTags.length === 0 && <div className="empty-card">没有匹配的普通标签。</div>}
            </div>
          </>}
          <input ref={importFileRef} type="file" accept=".zip" hidden onChange={(event) => void handleImportFileChange(event)} />
          {importTask && <div className={`task-bar ${importTask.status === "completed" ? "success" : importTask.status === "failed" ? "error" : ""}`}>
            {!["completed", "failed", "canceled"].includes(importTask.status) && <progress value={importTask.progress} max={1} />}
            <span>{importTask.message}</span>
          </div>}
        </section>
        <section key={tagView === "people" ? `person-${selectedPerson?.id}` : `tag-${selectedTag?.id}`} ref={peopleMainRef} className="panel people-main">
          {tagView === "tags" ? <TagDetails model={model} /> : selectedPerson ? (
            <>
              <div className="section-head">
                <div>
                  <p className="eyebrow">人物详情</p>
                  <h2>{selectedPerson.display_name}</h2>
                </div>
                <div className="micro-row">
                  <span>{selectedPerson.sample_count} 个样本 · {selectedPerson.gallery_photo_count} 张图片</span>
                </div>
              </div>

              <PersonSamples key={selectedPerson.id} model={model} />
              {!selectedPersonIsSystemUnknown && <details className="person-editor">
                <summary>编辑人物资料、标签与样本</summary>
                <div className="person-editor-content">
                  {canEditSamples && (
                    <div className="rename-strip">
                      <input aria-label="人物名称" maxLength={256} disabled={busy} value={renameValue} onChange={(event) => setRenameValue(event.target.value)} placeholder="输入新名字" />
                      <button disabled={busy || !renameValue.trim() || renameValue.trim() === selectedPerson.display_name} onClick={() => void handleRenamePerson()}>
                        {selectedPerson.is_unknown ? "转正并改名" : "更新名称"}
                      </button>
                    </div>
                  )}

                  <div className="editor-block">
                    <label>绑定的普通标签</label>
                    <p className="tip">绑定后自动继承到该人物相关的图库图片。{canDeleteSamples && "点击标签可解除绑定。"}</p>
                    <div className="micro-row wrap">
                      {personTags.map((tag) =>
                        canDeleteSamples ? (
                          <button disabled={busy || model.detailsLoading} title="解除绑定" aria-label={`解除绑定标签 ${tag.name}`} key={tag.id} className="pill muted action-pill" onClick={() => void handleUnbindPersonTag(tag.id)}>
                            #{tag.name} ×
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
                          <select aria-label="选择要绑定的普通标签" disabled={busy || model.detailsLoading} value={personTagSelectId} onChange={(event) => setPersonTagSelectId(event.target.value)}>
                            <option value="">从已有标签添加</option>
                            {sortByPinyinName(tags.filter((tag) => !personTags.some((item) => item.id === tag.id))).map((tag) => (
                              <option key={tag.id} value={tag.id}>
                                #{tag.name}
                              </option>
                            ))}
                          </select>
                          <button disabled={busy || model.detailsLoading || !personTagSelectId} onClick={() => void handleBindPersonTag()}>
                            添加已有标签
                          </button>
                        </div>
                        <div className="inline-editor">
                          <input
                            aria-label="新建并绑定普通标签"
                            maxLength={128}
                            disabled={busy}
                            value={personTagName}
                            onChange={(event) => setPersonTagName(event.target.value)}
                            placeholder="输入新标签名称"
                          />
                          <button disabled={busy || model.detailsLoading || !personTagName.trim()} onClick={() => void handleBindPersonTag("new")}>
                            新建并添加
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {canAddSamples && (
                    <label className="upload-box">
                      <input disabled={busy || model.detailsLoading} type="file" multiple accept="image/*" onChange={(event) => handlePickSampleFiles(event.target.files)} />
                      <strong>上传人物样本图</strong>
                      <span>先预览样本，再点击确认上传；仅接受单张照片恰好一张脸的样本进入向量库。</span>
                    </label>
                  )}

                  {pendingSampleUploads.length > 0 && (
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
                            <button className="ghost-button" disabled={busy} onClick={() => handleRemovePendingSample(index)}>
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
                  {canDeleteSamples && <button className="ghost-button person-delete-button" disabled={busy} onClick={() => void handleDeleteCurrentPerson()}>删除当前人物</button>}
                </div>
              </details>}

            </>
          ) : (
            <div className="empty-card">选择一个人物标签，维护名称、普通标签和识别样本。</div>
          )}
        </section>
      </div>
    </main>
  );
}

function CreatePersonAction({ model }: { model: PeopleModel }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const { busy, error, newPersonName, setNewPersonName, setError, handleCreatePerson } = model;
  return <>
    <button className="person-create-button" disabled={busy} onClick={() => {
      setError(null);
      dialogRef.current?.showModal();
      dialogRef.current?.querySelector("input")?.focus();
    }}><UserPlus size={17} aria-hidden="true" />新建人物</button>
    <dialog ref={dialogRef} className="person-create-dialog" aria-labelledby="person-create-title"
      onCancel={(event) => { if (busy) event.preventDefault(); }} onClose={() => setNewPersonName("")}>
      <div className="person-create-dialog-heading">
        <div><h2 id="person-create-title">新建人物</h2><p>先创建人物，再为他添加照片和普通标签。</p></div>
        <button className="ghost-button" type="button" aria-label="关闭新建人物" disabled={busy} onClick={() => dialogRef.current?.close()}><X size={18} /></button>
      </div>
      <form onSubmit={async (event) => {
        event.preventDefault();
        if (await handleCreatePerson()) dialogRef.current?.close();
      }}>
        <label>人物名称<input autoFocus required maxLength={256} disabled={busy} value={newPersonName}
          onChange={(event) => setNewPersonName(event.target.value)} placeholder="输入新人物名称" /></label>
        {error && <p role="alert" className="person-create-error">{error}</p>}
        <div className="person-create-dialog-actions">
          <button type="button" className="ghost-button" disabled={busy} onClick={() => dialogRef.current?.close()}>取消</button>
          <button disabled={busy || !newPersonName.trim()}>{busy ? "正在创建…" : "创建人物"}</button>
        </div>
      </form>
    </dialog>
  </>;
}

function PersonSamples({ model }: { model: PeopleModel }) {
  const [showAll, setShowAll] = useState(false);
  const { samples, detailsLoading, selectedPerson, highlightedSampleId, selectedPersonIsSystemUnknown,
    canDeleteSamples, busy, handleOpenSampleSource, handleDeleteSample } = model;
  const expanded = showAll || highlightedSampleId !== null;
  const visibleSamples = expanded ? samples : samples.slice(0, 4);
  return <section className="person-photo-preview" aria-label="人物照片预览">
    <div className="sample-section-heading"><h3>人物照片</h3><span>{samples.length} 张样本照片</span></div>
    {detailsLoading && <p role="status" className="tip">正在加载人物详情…</p>}
    <div className="sample-grid" aria-busy={detailsLoading}>
      {visibleSamples.map((sample) => (
        <article id={`sample-${sample.id}`} key={sample.id} className={`sample-card${highlightedSampleId === sample.id ? " matched-sample-highlight" : ""}`}>
          <a href={sample.original_url} target="_blank" rel="noreferrer">
            <img src={withImageWidth(sample.thumbnail_url, 480)} alt={`${selectedPerson?.display_name}的样本照片`} />
          </a>
          <details className="sample-photo-details" open={highlightedSampleId === sample.id || sample.status === "failed"}>
            <summary>样本 #{sample.id} · 详情与操作</summary>
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
              <button className="ghost-button" disabled={busy} onClick={() => void handleDeleteSample(sample.id)}>
                删除样本
              </button>
            )}
          </details>
        </article>
      ))}
      {!detailsLoading && samples.length === 0 && <div className="empty-card">当前人物还没有样本图片。</div>}
    </div>
    {samples.length > 4 && highlightedSampleId === null && <button type="button" className="ghost-button sample-preview-toggle" onClick={() => setShowAll((current) => !current)}>
      {showAll ? "收起照片" : `查看全部 ${samples.length} 张照片`}
    </button>}
  </section>;
}

function TagDetails({ model }: { model: PeopleModel }) {
  const { selectedTag, tagRenameValue, setTagRenameValue, busy, canEditGallery,
    linkedTagPersons, handleRenameTag, handleDeleteTag, handleViewTagPeople, setTagView, handleSelectPerson } = model;
  if (!selectedTag) return <div className="tag-detail-empty">
    <Tags size={32} aria-hidden="true" />
    <h2>让标签成为人物的索引</h2>
    <p>选择一个普通标签，修改名称、查看关联人物，或继续维护人物绑定。</p>
  </div>;
  return <>
    <div className="section-head"><div><p className="eyebrow">普通标签详情</p><h2>#{selectedTag.name}</h2></div></div>
    <p className="tip">{selectedTag.is_system ? "系统标签由系统维护。" : "名称变更会同步显示在已绑定的人物和图库图片中。"}</p>
    {canEditGallery && !selectedTag.is_system && <form className="rename-strip" onSubmit={(event) => { event.preventDefault(); void handleRenameTag(); }}>
      <input aria-label="普通标签名称" maxLength={128} disabled={busy} value={tagRenameValue} onChange={(event) => setTagRenameValue(event.target.value)} />
      <button disabled={busy || !tagRenameValue.trim() || tagRenameValue.trim() === selectedTag.name}>保存名称</button>
    </form>}
    <div className="editor-block tag-linked-people">
      <div className="sample-section-heading"><h3>绑定的人物</h3><span>{linkedTagPersons.length} 人</span></div>
      <p className="tip">这里只列出直接绑定此普通标签的人物。可在人物详情中添加或解除绑定。</p>
      <div className="tag-linked-list">
        {linkedTagPersons.map((person) => <button className="ghost-button" disabled={busy} key={person.id} onClick={() => {
          handleViewTagPeople(selectedTag.id); handleSelectPerson(person); setTagView("people");
        }}><UsersRound size={15} /><span>{person.display_name}</span><ArrowUpRight size={14} /></button>)}
        {linkedTagPersons.length === 0 && <div className="empty-card">还没有人物绑定此标签；标签仍可用于图库图片。</div>}
      </div>
      <button className="ghost-button" disabled={busy} onClick={() => handleViewTagPeople(selectedTag.id)}>按此标签筛选人物 <ArrowUpRight size={15} /></button>
    </div>
    {canEditGallery && !selectedTag.is_system && <div className="tag-delete-zone">
      <p className="tip">删除标签会解除所有人物和图片关联，保留图片与人物。</p>
      <button className="ghost-button" disabled={busy} onClick={() => void handleDeleteTag()}><Trash2 size={15} />删除普通标签</button>
    </div>}
  </>;
}
