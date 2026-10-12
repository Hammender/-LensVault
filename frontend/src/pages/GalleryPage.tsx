import { Info, Pin, PinOff, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import PhotoLightbox from "../components/PhotoLightbox";
import SearchableSelect from "../components/SearchableSelect";
import { faceBindingSourceLabel, galleryFaceStatusKind, galleryFaceStatusLabel, personTagSourceLabel } from "../lib/galleryFaceStatus";
import { isGalleryPageSelected } from "../lib/gallerySelection";
import { filterPersonMatches } from "../lib/personPicker";
import type { GalleryModel } from "../hooks/useGallery";
import { sortByPinyinName } from "../lib/sort";
import {
  formatGalleryCardPersonNames,
  galleryCardNeedsReview,
  packGalleryMasonryPage,
  resolveGalleryColumnCount,
} from "../lib/galleryMasonryPack";
import { formatPhotoDate } from "../lib/utils";

export default function GalleryPage({ model }: { model: GalleryModel }) {
  const {
    busy,
    canAddGallery,
    canDeleteGallery,
    canEditGallery,
    galleryPhotos,
    galleryTotal,
    galleryOffset,
    galleryPageSize,
    gallerySelectionMode,
    selectedGalleryPhotoIds,
    lastSelectedGalleryPhotoId,
    selectedPersonIds,
    selectedTagIds,
    excludePersonIds,
    excludeTagIds,
    personSearch,
    tagSearch,
    richTag,
    normalTags,
    filteredPersons,
    allFilteredUnknownPersons,
    allFilteredUnknownSelected,
    filteredTags,
    availableExcludePersons,
    availableExcludeTags,
    selectedPhoto,
    galleryDrawer,
    galleryCompact,
    activeGalleryFilterSection,
    galleryFiltersExpanded,
    galleryDetailPinned,
    activeGalleryDetailTab,
    selectedFaceId,
    excludePersonSearch,
    excludeTagSearch,
    manualPersonId,
    manualPersonSearch,
    manualPersonNotice,
    manualTagId,
    manualTagSearch,
    manualTagNotice,
    manualTagName,
    richTextDraft,
    lightboxRichTextDraft,
    lightboxEditMode,
    galleryImportFileRef,
    galleryImportTask,
    jumpPageInput,
    galleryDetailRef,
    galleryDetailCloseRef,
    galleryFilterCount,
    includedKnownPersons,
    includedUnknownPersons,
    excludedKnownPersonResults,
    excludedTagResults,
    excludedUnknownPersonResults,
    totalPages,
    currentPage,
    galleryExportStartCount,
    galleryExportFiltersDisabled,
    galleryExportDisabled,
    matchingPersonsForPhoto,
    selectedPhotoTags,
    availableTagsForPhoto,
    matchingTagsForPhoto,
    unknownPersonCount,
    lightboxPhoto,
    isFirstOfPage,
    isLastOfPage,
    hasPrevPage,
    hasNextPage,
    canGoPrev,
    canGoNext,
    lightboxMeta,
    galleryExportModalOpen,
    galleryExportScope,
    galleryExportPersonIds,
    galleryExportTagIds,
    galleryExportExcludePersonIds,
    galleryExportExcludeTagIds,
    galleryExportStartPhotoId,
    persons,
    tags,
    setPersonSearch,
    setTagSearch,
    setGalleryFiltersExpanded,
    setActiveGalleryFilterSection,
    setExcludePersonSearch,
    setExcludeTagSearch,
    setManualPersonId,
    setManualPersonSearch,
    setManualPersonNotice,
    setManualTagId,
    setManualTagSearch,
    setManualTagNotice,
    setManualTagName,
    setRichTextDraft,
    setLightboxRichTextDraft,
    setLightboxEditMode,
    setJumpPageInput,
    setSelectedFaceId,
    setActiveGalleryDetailTab,
    setGalleryDetailPinned,
    setSelectedGalleryPhotoIds,
    setLastSelectedGalleryPhotoId,
    setGalleryExportModalOpen,
    setGalleryExportScope,
    setGalleryExportPersonIds,
    setGalleryExportTagIds,
    setGalleryExportExcludePersonIds,
    setGalleryExportExcludeTagIds,
    setRecognitionNotice,
    closeGalleryDrawer,
    refreshGallery,
    handleTogglePersonFilter,
    handleToggleTagFilter,
    handleToggleUnknownPersonFilters,
    handleClearGalleryFilters,
    toggleGalleryFilterSection,
    handleToggleExcludePerson,
    handleToggleExcludeTag,
    openGalleryPhoto,
    openGalleryExportModal,
    openSelectedGalleryExportModal,
    openGalleryExportFromPhoto,
    handleExportGalleryPhotos,
    handleToggleGalleryExportPerson,
    handleToggleGalleryExportTag,
    handlePickGalleryImportFile,
    handleGalleryImportFileChange,
    renderFaceMatchSource,
    faceRejectionReasonLabel,
    handleAddPhotoPerson,
    handlePromotePhotoPerson,
    handleBindFace,
    handlePromoteFace,
    handleUnbindFace,
    handleUndoPromotePhotoPerson,
    handleDeletePhotoPerson,
    handleAddExistingPhotoTag,
    handleCreateAndAddPhotoTag,
    handleDeletePhotoTag,
    handleSaveRichText,
    handleSaveLightboxRichText,
    toggleGallerySelectionMode,
    handleGalleryCardClick,
    handleGalleryCheckboxClick,
    toggleCurrentGalleryPageSelection,
    handleDeleteSelectedGalleryPhotos,
    handleDeleteCurrentPhoto,
    handleReRecognize,
    handleJumpToPage,
    goPrevLightbox,
    goNextLightbox,
    closeGalleryLightbox,
    recognitionNotice,
    photoIdSearchInput,
    setPhotoIdSearchInput,
    activePhotoIdSearch,
    photoIdSearchHint,
    handleClearPhotoIdSearch
  } = model;

  const galleryGridRef = useRef<HTMLDivElement | null>(null);
  const [galleryColumnCount, setGalleryColumnCount] = useState(4);
  useEffect(() => {
    const node = galleryGridRef.current;
    if (!node || typeof ResizeObserver === "undefined") {
      return;
    }
    const update = () => setGalleryColumnCount(resolveGalleryColumnCount(node.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const galleryMasonryColumns = useMemo(
    () => packGalleryMasonryPage(galleryPhotos, galleryColumnCount),
    [galleryPhotos, galleryColumnCount],
  );


  return (
    <>
      <main className={`page-grid gallery-page${galleryDetailPinned && galleryDrawer === "detail" ? " detail-pinned" : ""}`}>
          <section
            className="panel gallery-filter-bar"
            aria-labelledby="gallery-filter-title"
          >
            <div className="gallery-filter-bar-head">
              <div>
                <p className="eyebrow">筛选</p>
                <h2 id="gallery-filter-title">找人 · 编号</h2>
              </div>
              <div className="gallery-filter-bar-actions">
                <span className="gallery-filter-hint">可多选</span>
                <div className="gallery-photo-id-search-wrap">
                  <label className={`gallery-photo-id-search${photoIdSearchHint ? " invalid" : ""}`}>
                    <Search size={16} aria-hidden="true" />
                    <input
                      className="search-input subtle"
                      type="text"
                      inputMode="numeric"
                      value={photoIdSearchInput}
                      onChange={(event) => setPhotoIdSearchInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          handleClearPhotoIdSearch();
                        }
                      }}
                      placeholder="按图片编号搜索，如 123"
                      aria-label="按图片编号搜索"
                      aria-invalid={photoIdSearchHint ? true : undefined}
                      aria-describedby={photoIdSearchHint ? "gallery-photo-id-search-hint" : undefined}
                    />
                    {photoIdSearchInput !== "" && (
                      <button
                        type="button"
                        className="gallery-photo-id-search-clear"
                        onClick={handleClearPhotoIdSearch}
                        aria-label="清除编号搜索"
                        title="清除编号搜索"
                      >
                        <X size={14} aria-hidden="true" />
                      </button>
                    )}
                  </label>
                  {photoIdSearchHint && (
                    <span id="gallery-photo-id-search-hint" className="gallery-photo-id-search-hint" role="alert">
                      {photoIdSearchHint}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setGalleryFiltersExpanded((current) => !current)}
                  aria-expanded={galleryFiltersExpanded}
                  aria-controls="gallery-filter-workbench"
                >
                  <SlidersHorizontal size={17} aria-hidden="true" />
                  {galleryFiltersExpanded ? "收起筛选" : "展开筛选"}
                </button>
              </div>
            </div>

            <div className="gallery-filter-summary" aria-label="当前筛选条件">
              <div className="gallery-filter-summary-head">
                <strong>当前筛选</strong>
                <span>
                  {activePhotoIdSearch != null
                    ? galleryFilterCount > 0
                      ? "编号搜索中，人物 / 标签筛选暂不生效"
                      : "编号搜索中"
                    : galleryFilterCount > 0
                      ? `${galleryFilterCount} 项已生效`
                      : "尚未添加条件"}
                </span>
              </div>
              <div className="gallery-filter-summary-actions">
                <div className="gallery-filter-summary-tabs" role="group" aria-label="筛选条件分类">
                  {([
                    ["include-people", "含人物", selectedPersonIds.length],
                    ["include-tags", "含标签", selectedTagIds.length],
                    ["exclude-people", "排人物", excludePersonIds.length],
                    ["exclude-tags", "排标签", excludeTagIds.length]
                  ] as const).map(([section, label, count]) => (
                    <button
                      key={section}
                      className={`gallery-filter-summary-tab${activeGalleryFilterSection === section ? " active" : ""}${count > 0 ? " has-filters" : ""}`}
                      type="button"
                      onClick={() => {
                        setActiveGalleryFilterSection(section);
                        setGalleryFiltersExpanded(true);
                      }}
                    >
                      {label} <b>{count}</b>
                    </button>
                  ))}
                </div>
                <button
                  className="gallery-filter-clear"
                  type="button"
                  disabled={galleryFilterCount === 0 && activePhotoIdSearch == null}
                  onClick={handleClearGalleryFilters}
                >
                  清除全部
                </button>
              </div>

              {(galleryFilterCount > 0 || activePhotoIdSearch != null) && (
                <div className="gallery-active-filters" aria-label="已生效筛选条件列表">
                  {activePhotoIdSearch != null && (
                    <button
                      key="photo-id"
                      type="button"
                      className="gallery-active-filter-chip include-chip photo-id-chip"
                      onClick={handleClearPhotoIdSearch}
                      title={`点击移除编号搜索：#${activePhotoIdSearch}`}
                    >
                      <span className="chip-prefix">编号</span>
                      <span className="chip-label">#{activePhotoIdSearch}</span>
                      <X size={13} className="chip-remove-icon" aria-hidden="true" />
                    </button>
                  )}
                  {selectedPersonIds.map((id) => {
                    const person = persons.find((p) => p.id === id);
                    if (!person) return null;
                    return (
                      <button
                        key={`inc-p-${id}`}
                        type="button"
                        className={`gallery-active-filter-chip include-chip${person.is_unknown ? " unknown" : ""}`}
                        onClick={() => handleTogglePersonFilter(id)}
                        title={`点击移除人物筛选：${person.display_name}`}
                      >
                        <span className="chip-prefix">+</span>
                        <span className="chip-label">{person.display_name}</span>
                        <X size={13} className="chip-remove-icon" aria-hidden="true" />
                      </button>
                    );
                  })}
                  {selectedTagIds.map((id) => {
                    const tag = tags.find((t) => t.id === id);
                    if (!tag) return null;
                    return (
                      <button
                        key={`inc-t-${id}`}
                        type="button"
                        className="gallery-active-filter-chip include-chip tag-chip"
                        onClick={() => handleToggleTagFilter(id)}
                        title={`点击移除标签筛选：#${tag.name}`}
                      >
                        <span className="chip-prefix">+</span>
                        <span className="chip-label">#{tag.name}</span>
                        <X size={13} className="chip-remove-icon" aria-hidden="true" />
                      </button>
                    );
                  })}
                  {excludePersonIds.map((id) => {
                    const person = persons.find((p) => p.id === id);
                    if (!person) return null;
                    return (
                      <button
                        key={`exc-p-${id}`}
                        type="button"
                        className={`gallery-active-filter-chip exclude-chip${person.is_unknown ? " unknown" : ""}`}
                        onClick={() => handleToggleExcludePerson(id)}
                        title={`点击移除排除人物：${person.display_name}`}
                      >
                        <span className="chip-prefix">-</span>
                        <span className="chip-label">{person.display_name}</span>
                        <X size={13} className="chip-remove-icon" aria-hidden="true" />
                      </button>
                    );
                  })}
                  {excludeTagIds.map((id) => {
                    const tag = tags.find((t) => t.id === id);
                    if (!tag) return null;
                    return (
                      <button
                        key={`exc-t-${id}`}
                        type="button"
                        className="gallery-active-filter-chip exclude-chip tag-chip"
                        onClick={() => handleToggleExcludeTag(id)}
                        title={`点击移除排除标签：#${tag.name}`}
                      >
                        <span className="chip-prefix">-</span>
                        <span className="chip-label">#{tag.name}</span>
                        <X size={13} className="chip-remove-icon" aria-hidden="true" />
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {galleryFiltersExpanded && <div className="gallery-filter-accordions" id="gallery-filter-workbench" role="tablist" aria-label="筛选条件分类">
              <section className={`gallery-filter-accordion${activeGalleryFilterSection === "include-people" ? " is-open" : ""}`}>
                <button
                  className="gallery-filter-accordion-trigger"
                  type="button"
                  role="tab"
                  aria-selected={activeGalleryFilterSection === "include-people"}
                  onClick={() => toggleGalleryFilterSection("include-people")}
                  aria-expanded={activeGalleryFilterSection === "include-people"}
                  aria-controls="gallery-filter-include-people"
                >
                  <span>
                    <strong>包含人物</strong>
                    <small>{selectedPersonIds.length > 0 ? `${selectedPersonIds.length} 个已选` : `${filteredPersons.length} 个可选`}</small>
                  </span>
                  <b>{activeGalleryFilterSection === "include-people" ? "收起" : "展开"}</b>
                </button>
                {activeGalleryFilterSection === "include-people" && (
                  <div className="gallery-filter-accordion-content" id="gallery-filter-include-people">
                    <input
                      className="search-input subtle"
                      value={personSearch}
                      onChange={(event) => setPersonSearch(event.target.value)}
                      placeholder="搜索人物名称、拼音或首字母"
                    />
                    <div className="gallery-filter-results" aria-label="人物搜索结果">
                      <div className="gallery-filter-result-section">
                        <div className="gallery-filter-result-head">
                          <strong>正式人物</strong>
                          <span>{includedKnownPersons.length} 个</span>
                        </div>
                        <div className="chip-cloud compact">
                          {includedKnownPersons.map((person) => (
                            <button
                              key={person.id}
                              className={selectedPersonIds.includes(person.id) ? "soft-chip active" : "soft-chip"}
                              onClick={() => handleTogglePersonFilter(person.id)}
                            >
                              {person.display_name}
                            </button>
                          ))}
                          {includedKnownPersons.length === 0 && <span className="filter-empty">没有匹配的正式人物</span>}
                        </div>
                      </div>
                      <div className="gallery-filter-result-section">
                        <div className="gallery-filter-result-head">
                          <strong>未知人物</strong>
                          <span>{personSearch.trim() ? `${includedUnknownPersons.length} / ${unknownPersonCount}` : `${unknownPersonCount} 个`}</span>
                          <button
                            className="filter-bulk-action"
                            disabled={allFilteredUnknownPersons.length === 0}
                            onClick={handleToggleUnknownPersonFilters}
                            type="button"
                          >
                            {allFilteredUnknownSelected ? "全不选" : "全选"}
                          </button>
                        </div>
                        <div className="chip-cloud compact">
                          {includedUnknownPersons.map((person) => (
                            <button
                              key={person.id}
                              className={selectedPersonIds.includes(person.id) ? "soft-chip active unknown-chip" : "soft-chip unknown-chip"}
                              onClick={() => handleTogglePersonFilter(person.id)}
                            >
                              {person.display_name}
                            </button>
                          ))}
                          {includedUnknownPersons.length === 0 && <span className="filter-empty">没有匹配的未知人物</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </section>

              <section className={`gallery-filter-accordion${activeGalleryFilterSection === "include-tags" ? " is-open" : ""}`}>
                <button
                  className="gallery-filter-accordion-trigger"
                  type="button"
                  role="tab"
                  aria-selected={activeGalleryFilterSection === "include-tags"}
                  onClick={() => toggleGalleryFilterSection("include-tags")}
                  aria-expanded={activeGalleryFilterSection === "include-tags"}
                  aria-controls="gallery-filter-include-tags"
                >
                  <span>
                    <strong>包含标签</strong>
                    <small>{selectedTagIds.length > 0 ? `${selectedTagIds.length} 个已选` : `${filteredTags.length} 个可选`}</small>
                  </span>
                  <b>{activeGalleryFilterSection === "include-tags" ? "收起" : "展开"}</b>
                </button>
                {activeGalleryFilterSection === "include-tags" && (
                  <div className="gallery-filter-accordion-content" id="gallery-filter-include-tags">
                    <input
                      className="search-input subtle"
                      value={tagSearch}
                      onChange={(event) => setTagSearch(event.target.value)}
                      placeholder="搜索标签"
                    />
                    <div className="gallery-filter-results" aria-label="标签搜索结果">
                      <div className="chip-cloud compact">
                        {filteredTags.map((tag) => (
                          <button
                            key={tag.id}
                            className={selectedTagIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                            onClick={() => handleToggleTagFilter(tag.id)}
                          >
                            #{tag.name}
                          </button>
                        ))}
                        {filteredTags.length === 0 && <span className="filter-empty">没有匹配的普通标签</span>}
                      </div>
                    </div>
                  </div>
                )}
              </section>

              <section className={`gallery-filter-accordion${activeGalleryFilterSection === "exclude-people" ? " is-open" : ""}`}>
                <button
                  className="gallery-filter-accordion-trigger"
                  type="button"
                  role="tab"
                  aria-selected={activeGalleryFilterSection === "exclude-people"}
                  onClick={() => toggleGalleryFilterSection("exclude-people")}
                  aria-expanded={activeGalleryFilterSection === "exclude-people"}
                  aria-controls="gallery-filter-exclude-people"
                >
                  <span>
                    <strong>排除人物</strong>
                    <small>{excludePersonIds.length > 0 ? `${excludePersonIds.length} 个已选` : `${availableExcludePersons.length} 个可选`}</small>
                  </span>
                  <b>{activeGalleryFilterSection === "exclude-people" ? "收起" : "展开"}</b>
                </button>
                {activeGalleryFilterSection === "exclude-people" && (
                  <div className="gallery-filter-accordion-content" id="gallery-filter-exclude-people">
                    <input
                      className="search-input subtle"
                      value={excludePersonSearch}
                      onChange={(event) => setExcludePersonSearch(event.target.value)}
                      placeholder="搜索要排除的人物"
                    />
                    <div className="gallery-filter-results" aria-label="排除人物搜索结果">
                      <div className="gallery-filter-result-section">
                        <div className="gallery-filter-result-head">
                          <strong>正式人物</strong>
                          <span>{excludedKnownPersonResults.length} 个</span>
                        </div>
                        <div className="chip-cloud compact">
                          {excludedKnownPersonResults.map((person) => (
                            <button
                              key={person.id}
                              className={excludePersonIds.includes(person.id) ? "soft-chip active" : "soft-chip"}
                              onClick={() => handleToggleExcludePerson(person.id)}
                            >
                              {person.display_name}
                            </button>
                          ))}
                          {excludedKnownPersonResults.length === 0 && <span className="filter-empty">没有匹配的正式人物</span>}
                        </div>
                      </div>
                      <div className="gallery-filter-result-section">
                        <div className="gallery-filter-result-head">
                          <strong>未知人物</strong>
                          <span>{excludedUnknownPersonResults.length} 个</span>
                        </div>
                        <div className="chip-cloud compact">
                          {excludedUnknownPersonResults.map((person) => (
                            <button
                              key={person.id}
                              className={excludePersonIds.includes(person.id) ? "soft-chip active unknown-chip" : "soft-chip unknown-chip"}
                              onClick={() => handleToggleExcludePerson(person.id)}
                            >
                              {person.display_name}
                            </button>
                          ))}
                          {excludedUnknownPersonResults.length === 0 && <span className="filter-empty">没有匹配的未知人物</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </section>

              <section className={`gallery-filter-accordion${activeGalleryFilterSection === "exclude-tags" ? " is-open" : ""}`}>
                <button
                  className="gallery-filter-accordion-trigger"
                  type="button"
                  role="tab"
                  aria-selected={activeGalleryFilterSection === "exclude-tags"}
                  onClick={() => toggleGalleryFilterSection("exclude-tags")}
                  aria-expanded={activeGalleryFilterSection === "exclude-tags"}
                  aria-controls="gallery-filter-exclude-tags"
                >
                  <span>
                    <strong>排除标签</strong>
                    <small>{excludeTagIds.length > 0 ? `${excludeTagIds.length} 个已选` : `${availableExcludeTags.length} 个可选`}</small>
                  </span>
                  <b>{activeGalleryFilterSection === "exclude-tags" ? "收起" : "展开"}</b>
                </button>
                {activeGalleryFilterSection === "exclude-tags" && (
                  <div className="gallery-filter-accordion-content" id="gallery-filter-exclude-tags">
                    <input
                      className="search-input subtle"
                      value={excludeTagSearch}
                      onChange={(event) => setExcludeTagSearch(event.target.value)}
                      placeholder="搜索要排除的标签"
                    />
                    <div className="gallery-filter-results" aria-label="排除标签搜索结果">
                      <div className="chip-cloud compact">
                        {excludedTagResults.map((tag) => (
                          <button
                            key={tag.id}
                            className={excludeTagIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                            onClick={() => handleToggleExcludeTag(tag.id)}
                          >
                            #{tag.name}
                          </button>
                        ))}
                        {excludedTagResults.length === 0 && <span className="filter-empty">没有匹配的普通标签</span>}
                      </div>
                    </div>
                  </div>
                )}
              </section>
            </div>}
          </section>

          <section className="panel gallery-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">展示图库</p>
                <h2>写真浏览</h2>
              </div>
              <div className="micro-row section-actions">
                <span>{galleryTotal} 张结果</span>
                {gallerySelectionMode ? (
                  <>
                    <button disabled={busy} onClick={() => toggleGallerySelectionMode()}>取消选择</button>
                    <button disabled={busy || galleryPhotos.length === 0} onClick={toggleCurrentGalleryPageSelection}>
                      {isGalleryPageSelected(selectedGalleryPhotoIds, galleryPhotos.map((photo) => photo.id))
                        ? "取消本页"
                        : "选中本页"}
                    </button>
                    <button disabled={busy || selectedGalleryPhotoIds.length === 0} onClick={openSelectedGalleryExportModal}>
                      导出选中（{selectedGalleryPhotoIds.length}）
                    </button>
                    <button disabled={busy || selectedGalleryPhotoIds.length !== 1} onClick={() => openGalleryExportFromPhoto(selectedGalleryPhotoIds[0])}>
                      从此图开始导出
                    </button>
                    <button disabled={busy || selectedGalleryPhotoIds.length === 0} onClick={() => { setSelectedGalleryPhotoIds([]); setLastSelectedGalleryPhotoId(null); }}>
                      清空选择
                    </button>
                    {canDeleteGallery && (
                    <button disabled={busy || selectedGalleryPhotoIds.length === 0} onClick={() => void handleDeleteSelectedGalleryPhotos()}>
                      删除选中（{selectedGalleryPhotoIds.length}）
                    </button>
                    )}
                  </>
                ) : (
                  <>
                    <button disabled={busy} onClick={() => toggleGallerySelectionMode()}>选择图片</button>
                    <button disabled={busy} onClick={openGalleryExportModal}>导出展示图</button>
                    {canAddGallery && (
                    <button disabled={busy} onClick={handlePickGalleryImportFile}>导入展示图</button>
                    )}
                  </>
                )}
                <input
                  ref={galleryImportFileRef}
                  type="file"
                  accept=".zip"
                  style={{ display: "none" }}
                  onChange={(event) => void handleGalleryImportFileChange(event)}
                />
                {galleryImportTask && galleryImportTask.status !== "completed" && galleryImportTask.status !== "failed" && (
                  <div className="task-bar gallery-task">
                    <progress value={galleryImportTask.progress} max={1}></progress>
                    <span>{galleryImportTask.message}</span>
                  </div>
                )}
                {galleryImportTask && galleryImportTask.status === "completed" && (
                  <div className="task-bar success gallery-task">
                    <span>{galleryImportTask.message}</span>
                  </div>
                )}
                {galleryImportTask && galleryImportTask.status === "failed" && (
                  <div className="task-bar error gallery-task">
                    <span>导入失败：{galleryImportTask.message}</span>
                  </div>
                )}
              </div>
            </div>

            <div className="gallery-masonry" ref={galleryGridRef} style={{ ["--gallery-cols" as string]: galleryColumnCount }}>
              {galleryMasonryColumns.map((column, columnIndex) => (
                <div className="gallery-masonry-column" key={`col-${columnIndex}`}>
                  {column.map((photo) => {
                    const personLabel = formatGalleryCardPersonNames(photo.persons);
                    const needsReview = galleryCardNeedsReview(photo.persons);
                    const selected = selectedGalleryPhotoIds.includes(photo.id);
                    return (
                      <article
                        key={photo.id}
                        className={`photo-card-wrap gallery-masonry-item${photo.is_rich_text ? " rich-card-wrap" : ""}${needsReview ? " needs-review" : ""}`}
                      >
                        <button
                          type="button"
                          className={`photo-card${photo.is_rich_text ? " rich-card" : ""}${selected ? " selected" : ""}`}
                          onClick={(event) => {
                            handleGalleryCardClick(photo.id, event.shiftKey);
                          }}
                        >
                          {photo.is_rich_text ? (
                            <div className="rich-card-layout">
                              <img src={photo.animated_thumbnail_url} alt={personLabel} loading="lazy" />
                              <div className="rich-card-copy">
                                <p className="rich-snippet">{photo.rich_text || "未识别到文本，可在详情里手动补录。"}</p>
                              </div>
                            </div>
                          ) : (
                            <img
                              src={photo.animated_thumbnail_url}
                              alt={personLabel}
                              loading="lazy"
                              style={
                                photo.width && photo.height && photo.width > 0 && photo.height > 0
                                  ? { aspectRatio: `${photo.width} / ${photo.height}` }
                                  : undefined
                              }
                            />
                          )}
                          <div className="photo-card-caption">
                            <span className="photo-card-names">{personLabel}</span>
                            <span className="photo-card-id">#{photo.id}</span>
                          </div>
                        </button>
                        <button
                          type="button"
                          className={`photo-detail-trigger${needsReview ? " review" : ""}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            void openGalleryPhoto(photo.id);
                          }}
                          aria-label={needsReview ? `查看并纠正图片 #${photo.id}` : `查看图片 #${photo.id} 的详情`}
                          title={needsReview ? "详情 · 可能需纠正人物" : "详情"}
                        >
                          {needsReview ? <span className="photo-detail-dot" aria-hidden="true" /> : null}
                          <Info size={15} aria-hidden="true" />
                          <span>详情</span>
                        </button>
                        {gallerySelectionMode && (
                          <label
                            className="corner-check"
                            onClick={(event) => {
                              event.stopPropagation();
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              onClick={(event) => {
                                event.stopPropagation();
                              }}
                              onChange={(event) => {
                                const nativeEvent = event.nativeEvent as MouseEvent;
                                handleGalleryCheckboxClick(photo.id, Boolean(nativeEvent?.shiftKey));
                              }}
                            />
                          </label>
                        )}
                      </article>
                    );
                  })}
                </div>
              ))}
            </div>
              {galleryPhotos.length === 0 && activePhotoIdSearch != null && (
                <div className="empty-card gallery-photo-id-empty">
                  <span>未找到编号为 #{activePhotoIdSearch} 的图片</span>
                  <button type="button" onClick={handleClearPhotoIdSearch}>
                    <X size={15} aria-hidden="true" />
                    清除编号搜索
                  </button>
                </div>
              )}
              {galleryPhotos.length === 0 && activePhotoIdSearch == null && (
                <div className="empty-card">当前筛选条件下没有展示图。</div>
              )}

            <div className="pagination-row">
              <button disabled={galleryOffset === 0 || busy} onClick={() => void refreshGallery(Math.max(0, galleryOffset - galleryPageSize))}>
                上一页
              </button>
              <span>
                第 {currentPage} / {totalPages} 页 ({galleryTotal === 0 ? 0 : galleryOffset + 1} - {Math.min(galleryOffset + galleryPageSize, galleryTotal)} / {galleryTotal})
              </span>
              <button
                disabled={galleryOffset + galleryPageSize >= galleryTotal || busy}
                onClick={() => void refreshGallery(galleryOffset + galleryPageSize)}
              >
                下一页
              </button>
              <div className="jump-to-page">
                <input
                  type="number"
                  min={1}
                  max={totalPages}
                  value={jumpPageInput}
                  onChange={(e) => setJumpPageInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleJumpToPage();
                    }
                  }}
                  placeholder="页码"
                />
                <button disabled={busy || !jumpPageInput} onClick={() => handleJumpToPage()}>
                  跳转
                </button>
              </div>
            </div>
          </section>

          <aside
            id="gallery-detail-drawer"
            ref={galleryDetailRef}
            className={`panel detail-panel gallery-detail-inspector${galleryDrawer === "detail" ? " is-open" : ""}${galleryDetailPinned && galleryDrawer === "detail" ? " is-pinned" : ""}`}
            role={galleryCompact ? "dialog" : undefined}
            aria-modal={galleryCompact ? true : undefined}
            aria-hidden={galleryCompact ? galleryDrawer !== "detail" : undefined}
            aria-labelledby="gallery-detail-title"
            tabIndex={-1}
          >
            <div className="section-head detail-inspector-head">
              <div>
                <p className="eyebrow">详情</p>
                <h2 id="gallery-detail-title">单张图修正</h2>
              </div>
              <div className="micro-row">
                <span>{selectedPhoto ? `${selectedPhoto.faces.length} 条人脸记录` : "未选中图片"}</span>
                {canEditGallery && (
                <button disabled={busy || !selectedPhoto} onClick={() => void handleReRecognize()}>
                  重新识别
                </button>
                )}
                {canDeleteGallery && (
                <button disabled={busy || !selectedPhoto} onClick={() => void handleDeleteCurrentPhoto()}>
                  删除当前图
                </button>
                )}
                {!galleryCompact && (
                  <button
                    className="detail-pin-button"
                    type="button"
                    onClick={() => setGalleryDetailPinned((current) => !current)}
                    aria-pressed={galleryDetailPinned}
                    title={galleryDetailPinned ? "取消固定详情" : "固定详情栏"}
                  >
                    {galleryDetailPinned ? <PinOff size={17} aria-hidden="true" /> : <Pin size={17} aria-hidden="true" />}
                  </button>
                )}
                <button
                  ref={galleryDetailCloseRef}
                  className="detail-inspector-close"
                  type="button"
                  onClick={() => closeGalleryDrawer()}
                  aria-label="关闭图片详情"
                  title="关闭图片详情"
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
            </div>
            {selectedPhoto ? (
              <>
                <a className="detail-image-wrap" href={selectedPhoto.original_url} target="_blank" rel="noreferrer">
                  <span className="detail-image-stage">
                    <img className="detail-image" src={selectedPhoto.original_url} alt="原图预览" />
                    {selectedPhoto.display_width && selectedPhoto.display_height && selectedPhoto.faces.map((face) => (
                    <span
                      key={`face-box-${face.id}`}
                      className={`detail-face-box${selectedFaceId === face.id ? " selected" : ""}`}
                      style={{
                        left: `${(face.bbox_left / selectedPhoto.display_width!) * 100}%`,
                        top: `${(face.bbox_top / selectedPhoto.display_height!) * 100}%`,
                        width: `${((face.bbox_right - face.bbox_left) / selectedPhoto.display_width!) * 100}%`,
                        height: `${((face.bbox_bottom - face.bbox_top) / selectedPhoto.display_height!) * 100}%`
                      }}
                      role="button"
                      tabIndex={0}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setSelectedFaceId(face.id);
                        setActiveGalleryDetailTab("faces");
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedFaceId(face.id);
                          setActiveGalleryDetailTab("faces");
                        }
                      }}
                    >
                      <b>人脸 {face.face_index}</b>
                    </span>
                    ))}
                  </span>
                </a>
                <div className="detail-copy">
                  <p>{formatPhotoDate(selectedPhoto.taken_at, selectedPhoto.created_at)}</p>
                  <p className="detail-photo-id">图片编号 #{selectedPhoto.id}</p>
                  <p>
                    {selectedPhoto.width} × {selectedPhoto.height}
                  </p>
                </div>

                <div className="detail-tab-list" role="tablist" aria-label="图片详情分类">
                  <button className={activeGalleryDetailTab === "people" ? "active" : ""} type="button" role="tab" aria-selected={activeGalleryDetailTab === "people"} onClick={() => setActiveGalleryDetailTab("people")}>人物</button>
                  <button className={activeGalleryDetailTab === "tags" ? "active" : ""} type="button" role="tab" aria-selected={activeGalleryDetailTab === "tags"} onClick={() => setActiveGalleryDetailTab("tags")}>标签</button>
                  <button className={activeGalleryDetailTab === "faces" ? "active" : ""} type="button" role="tab" aria-selected={activeGalleryDetailTab === "faces"} onClick={() => setActiveGalleryDetailTab("faces")}>人脸 {selectedPhoto.faces.length}</button>
                  {selectedPhoto.is_rich_text && <button className={activeGalleryDetailTab === "rich-text" ? "active" : ""} type="button" role="tab" aria-selected={activeGalleryDetailTab === "rich-text"} onClick={() => setActiveGalleryDetailTab("rich-text")}>图文</button>}
                </div>

                {activeGalleryDetailTab === "people" && <div className="editor-block detail-tab-panel" role="tabpanel">
                  <label>人物标签</label>
                  <div className="micro-row wrap">
                    {selectedPhoto.persons.map((person) => (
                      <span key={person.person_id} className="micro-row">
                        <button
                          className={person.is_unknown ? "pill unknown action-pill" : "pill action-pill"}
                          onClick={() => canEditGallery && void handleDeletePhotoPerson(person.person_id)}
                          title={canEditGallery ? "移除此人物标签" : person.person_name}
                          disabled={!canEditGallery}
                        >
                          {person.person_name}
                          {personTagSourceLabel(person.source) && (
                            <small className="pill-source">{personTagSourceLabel(person.source)}</small>
                          )}
                        </button>
                        {!person.is_unknown && person.promoted_sample_id === null && (
                          <button
                            className="ghost-button"
                            disabled={busy || selectedPhoto.faces.length !== 1}
                            onClick={() => void handlePromotePhotoPerson(person.person_id)}
                          >
                            加入样本库
                          </button>
                        )}
                        {!person.is_unknown && person.promoted_sample_id !== null && (
                          <>
                            <button className="ghost-button" disabled>已加入样本库</button>
                            <button
                              className="ghost-button"
                              disabled={busy}
                              onClick={() => void handleUndoPromotePhotoPerson(person.person_id)}
                            >
                              撤销
                            </button>
                          </>
                        )}
                      </span>
                    ))}
                  </div>
                  <div className="searchable-picker-row">
                    <SearchableSelect
                      id="photo-person-picker"
                      value={manualPersonId}
                      query={manualPersonSearch}
                      options={matchingPersonsForPhoto.map((person) => ({
                        value: String(person.id),
                        label: person.display_name,
                        meta: `${person.gallery_photo_count} 张图库图片`
                      }))}
                      placeholder="搜索人物名称、拼音或首字母"
                      emptyText="没有匹配的人物"
                      disabled={busy}
                      onQueryChange={(query) => {
                        setManualPersonSearch(query);
                        setManualPersonId("");
                        setManualPersonNotice(null);
                      }}
                      onSelect={(option) => {
                        setManualPersonId(option.value);
                        setManualPersonSearch(option.label);
                        setManualPersonNotice(null);
                      }}
                      onEnter={() => void handleAddPhotoPerson()}
                    />
                    {canEditGallery && (
                    <button disabled={busy || !manualPersonSearch.trim()} onClick={() => void handleAddPhotoPerson()}>添加人物</button>
                    )}
                  </div>
                  {manualPersonNotice && <p className="searchable-picker-notice" role="alert">{manualPersonNotice}</p>}
                  <p className="tip">
                    添加人物只会给这张图打上人名，不会改人脸绑定。要给某张脸指定人物，请到「人脸」页。
                  </p>
                  {selectedPhoto.faces.length > 0 && (
                    <>
                      <label>人脸绑定</label>
                      <div className="face-binding-overview">
                        {selectedPhoto.faces.map((face) => (
                          <div key={face.id} className="face-binding-row">
                            <button type="button" className="face-binding-row-main" onClick={() => { setSelectedFaceId(face.id); setActiveGalleryDetailTab("faces"); }}>
                              <strong>人脸 {face.face_index}</strong>
                              <span className={face.matched_person_is_unknown || face.matched_person_id === null ? "pending-binding" : undefined}>
                                {face.matched_person_is_unknown ? "待绑定" : face.matched_person_name ?? "待绑定"}
                              </span>
                              <small>{faceBindingSourceLabel(face.binding_source)}</small>
                            </button>
                            {face.matched_person_id !== null && (
                              <button className="ghost-button face-binding-remove" type="button" disabled={busy} onClick={() => void (face.matched_person_is_unknown ? handleDeletePhotoPerson(face.matched_person_id!) : handleUnbindFace(face.id, false))}>
                                {face.matched_person_is_unknown ? "移除绑定" : "解除绑定"}
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>}

                {activeGalleryDetailTab === "tags" && <div className="editor-block detail-tab-panel" role="tabpanel">
                  <label>普通标签</label>
                  <div className="micro-row wrap">
                    {selectedPhotoTags.map((tag) => (
                      tag.is_system ? (
                        <span key={tag.id} className="pill muted">
                          #{tag.name}
                        </span>
                      ) : (
                        <button key={tag.id} className="pill muted action-pill" onClick={() => canEditGallery && void handleDeletePhotoTag(tag.id)} disabled={!canEditGallery}>
                          #{tag.name}
                        </button>
                      )
                    ))}
                  </div>
                  <div className="stack-editor">
                    <div className="searchable-picker-row">
                      <SearchableSelect
                        id="photo-tag-picker"
                        value={manualTagId}
                        query={manualTagSearch}
                        options={matchingTagsForPhoto.map((tag) => ({
                          value: String(tag.id),
                          label: `#${tag.name}`
                        }))}
                        placeholder="搜索已有标签"
                        emptyText="没有匹配的已有标签"
                        disabled={busy}
                        onQueryChange={(query) => {
                          setManualTagSearch(query.replace(/^#/, ""));
                          setManualTagId("");
                          setManualTagNotice(null);
                        }}
                        onSelect={(option) => {
                          const tag = availableTagsForPhoto.find((item) => String(item.id) === option.value);
                          setManualTagId(option.value);
                          setManualTagSearch(tag?.name ?? option.label.replace(/^#/, ""));
                          setManualTagNotice(null);
                        }}
                        onEnter={() => void handleAddExistingPhotoTag()}
                      />
                      {canEditGallery && (
                      <button disabled={busy || !manualTagSearch.trim()} onClick={() => void handleAddExistingPhotoTag()}>
                        添加已有标签
                      </button>
                      )}
                    </div>
                    {manualTagNotice && <p className="searchable-picker-notice" role="alert">{manualTagNotice}</p>}
                    <div className="inline-editor">
                      <input
                        value={manualTagName}
                        onChange={(event) => setManualTagName(event.target.value)}
                        placeholder="输入新标签名称"
                      />
                      {canEditGallery && (
                      <button disabled={busy || !manualTagName.trim()} onClick={() => void handleCreateAndAddPhotoTag()}>
                        新建并添加
                      </button>
                      )}
                    </div>
                  </div>
                </div>}

                {selectedPhoto.is_rich_text && activeGalleryDetailTab === "rich-text" && (
                  <div className="editor-block detail-tab-panel" role="tabpanel">
                    <label>图文文本（可手动编辑）</label>
                    <textarea
                      className="rich-text-editor"
                      value={richTextDraft}
                      onChange={(event) => setRichTextDraft(event.target.value)}
                      placeholder="输入或修正文案内容"
                    />
                    <div className="micro-row">
                      <span>OCR状态：{selectedPhoto.ocr_status ?? "unknown"}</span>
                      {canEditGallery && (
                      <button disabled={busy} onClick={() => void handleSaveRichText()}>
                        保存图文文本
                      </button>
                      )}
                    </div>
                  </div>
                )}

                {activeGalleryDetailTab === "faces" && <div className="face-list detail-tab-panel" role="tabpanel">
                  {selectedPhoto.faces.map((face) => (
                    <article className={`face-card${selectedFaceId === face.id ? " selected" : ""}`} key={face.id} onClick={() => setSelectedFaceId(face.id)}>
                      <header className="face-card-head">
                        <strong>人脸 {face.face_index} <small>#{face.id}</small></strong>
                        <span className={`face-status ${galleryFaceStatusKind(face)}`}>
                          {galleryFaceStatusLabel(face)}
                        </span>
                      </header>
                      <div className="face-candidates">
                        <div className="face-candidate-row current">
                          <span className="face-candidate-rank">当前绑定</span>
                          <strong>
                            {face.matched_person_id === null
                              ? "未绑定"
                              : face.matched_person_is_unknown
                                ? "未知人物"
                                : face.matched_person_name ?? "已删除人物"}
                          </strong>
                          <small>{faceBindingSourceLabel(face.binding_source)}</small>
                        </div>
                        {face.predicted_person_id !== null && face.match_score !== null ? (
                          <div className="face-candidate-row primary">
                            <span className="face-candidate-rank">第一候选</span>
                            <strong>{face.predicted_person_name ?? "已删除人物"}</strong>
                            <span className="face-score"><small>score</small>{face.match_score.toFixed(3)}</span>
                            <span className="face-source">
                              {renderFaceMatchSource(face.predicted_person_id, face.predicted_match_source, face.predicted_sample_photo_id)}
                            </span>
                            {face.needs_review && face.predicted_person_name && (
                              <button
                                type="button"
                                className="ghost-button face-candidate-fill"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setSelectedFaceId(face.id);
                                  setManualPersonId(String(face.predicted_person_id));
                                  setManualPersonSearch(face.predicted_person_name!);
                                  setManualPersonNotice(null);
                                }}
                                title="仅填入绑定人物输入框"
                              >
                                填入
                              </button>
                            )}
                          </div>
                        ) : (
                          <div className="face-empty-candidate">无第一候选</div>
                        )}
                        {face.second_person_id !== null && face.second_match_score !== null && (
                          <div className="face-candidate-row">
                            <span className="face-candidate-rank">第二候选</span>
                            <strong>{face.second_person_name ?? "已删除人物"}</strong>
                            <span className="face-score"><small>score</small>{face.second_match_score.toFixed(3)}</span>
                            <span className="face-source">
                              {renderFaceMatchSource(face.second_person_id, face.second_match_source, face.second_sample_photo_id)}
                            </span>
                            {face.needs_review && face.second_person_name && (
                              <button
                                type="button"
                                className="ghost-button face-candidate-fill"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setSelectedFaceId(face.id);
                                  setManualPersonId(String(face.second_person_id));
                                  setManualPersonSearch(face.second_person_name!);
                                  setManualPersonNotice(null);
                                }}
                                title="仅填入绑定人物输入框"
                              >
                                填入
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="face-card-actions" onClick={(event) => event.stopPropagation()}>
                        <SearchableSelect
                          id={`face-person-picker-${face.id}`}
                          value={selectedFaceId === face.id && !face.matched_person_is_unknown ? String(face.matched_person_id ?? "") : ""}
                          query={selectedFaceId === face.id ? manualPersonSearch : ""}
                          options={filterPersonMatches(persons.filter((person) => !person.is_unknown), selectedFaceId === face.id ? manualPersonSearch : "").map((person) => ({ value: String(person.id), label: person.display_name }))}
                          placeholder="绑定人物"
                          emptyText="没有匹配的人物"
                          disabled={busy || face.promoted_sample_id !== null}
                          onQueryChange={(query) => { setSelectedFaceId(face.id); setManualPersonSearch(query); setManualPersonId(""); }}
                          onSelect={(option) => { setSelectedFaceId(face.id); setManualPersonId(option.value); setManualPersonSearch(option.label); }}
                          onEnter={() => { if (manualPersonId) void handleBindFace(face.id, Number(manualPersonId)); }}
                        />
                        {face.promoted_sample_id !== null ? (
                          <>
                            <span className="face-promoted">已加入当前人物样本库</span>
                            <button className="ghost-button" disabled={busy} onClick={() => void handleUndoPromotePhotoPerson(face.matched_person_id!)}>撤销样本</button>
                          </>
                        ) : (
                          <>
                            <button disabled={busy || !manualPersonId} onClick={() => void handleBindFace(face.id, Number(manualPersonId))}>绑定此人</button>
                            {!face.matched_person_is_unknown && face.matched_person_id !== null && (
                              <button className="ghost-button" disabled={busy} onClick={() => void handlePromoteFace(face.id)}>加入当前人物样本库</button>
                            )}
                            {face.matched_person_is_unknown && <span className="tip">先绑定正式人物，再加入样本库</span>}
                            {face.matched_person_is_unknown && face.matched_person_id !== null && <button className="ghost-button" disabled={busy} onClick={() => void handleDeletePhotoPerson(face.matched_person_id!)}>移除绑定</button>}
                            {!face.matched_person_is_unknown && face.matched_person_id !== null && <button className="ghost-button" disabled={busy} onClick={() => void handleUnbindFace(face.id)}>解除绑定</button>}
                          </>
                        )}
                      </div>
                      {(face.match_margin !== null || face.rejection_reason) && (
                        <footer className={`face-card-foot${face.rejection_reason ? " has-rejection" : ""}`}>
                          {face.rejection_reason && (
                            <span className="face-rejection">
                              <b>拒绝原因</b>
                              <strong>{faceRejectionReasonLabel(face.rejection_reason)}</strong>
                            </span>
                          )}
                          {face.match_margin !== null && (
                            <span className="face-margin">候选差值 <strong>{face.match_margin.toFixed(3)}</strong></span>
                          )}
                        </footer>
                      )}
                    </article>
                  ))}
                </div>}
              </>
            ) : (
              <div className="empty-card">从图库卡片打开详情后，这里会显示识别结果和修正操作。</div>
            )}
          </aside>
          {galleryDrawer === "detail" && !galleryDetailPinned && (
            <button
              className="gallery-drawer-backdrop gallery-detail-backdrop"
              type="button"
              onClick={() => closeGalleryDrawer()}
              aria-label="关闭图片详情"
            />
          )}
        </main>
      {galleryExportModalOpen && (
        <div className="modal-backdrop" onClick={() => setGalleryExportModalOpen(false)}>
          <div className="export-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">导出展示图</p>
                <h2>选择导出范围</h2>
              </div>
              <button className="lightbox-close" onClick={() => setGalleryExportModalOpen(false)}>
                关闭
              </button>
            </div>

            <div className="export-choice-row">
              <button
                className={galleryExportScope === "selected" ? "soft-chip active" : "soft-chip"}
                disabled={selectedGalleryPhotoIds.length === 0}
                onClick={() => setGalleryExportScope("selected")}
              >
                已选图片
              </button>
              <button
                className={galleryExportScope === "from_start" ? "soft-chip active" : "soft-chip"}
                disabled={galleryExportStartPhotoId === null}
                onClick={() => setGalleryExportScope("from_start")}
              >
                从指定图片起
              </button>
              <button
                className={galleryExportScope === "filtered" ? "soft-chip active" : "soft-chip"}
                onClick={() => setGalleryExportScope("filtered")}
              >
                当前筛选结果
              </button>
              <button
                className={galleryExportScope === "all" ? "soft-chip active" : "soft-chip"}
                onClick={() => setGalleryExportScope("all")}
              >
                全部展示图
              </button>
              <span>
                {galleryExportScope === "selected" && `将导出跨页选中的 ${selectedGalleryPhotoIds.length} 张图片`}
                {galleryExportScope === "from_start" && (
                  galleryExportStartCount > 0
                    ? `将导出当前筛选结果中的前 ${galleryExportStartCount} 张，包含起点及所有更新图片`
                    : "将导出起点图片及当前筛选结果中所有更新图片"
                )}
                {galleryExportScope === "filtered" && (
                  `当前筛选：包含 ${galleryExportPersonIds.length} 个人物、${galleryExportTagIds.length} 个标签，排除 ${galleryExportExcludePersonIds.length} 个人物、${galleryExportExcludeTagIds.length} 个标签`
                )}
                {galleryExportScope === "all" && "将导出图库中的全部展示图"}
              </span>
            </div>

            <div className={galleryExportFiltersDisabled ? "export-filter-grid disabled" : "export-filter-grid"}>
              <section className="export-filter-block">
                <div className="filter-section-head">
                  <strong>人物标签</strong>
                  <span>{galleryExportPersonIds.length} 已选</span>
                </div>
                <div className="export-chip-cloud">
                  {sortByPinyinName(persons).map((person) => (
                    <button
                      key={`export-person-${person.id}`}
                      className={galleryExportPersonIds.includes(person.id) ? "soft-chip active" : "soft-chip"}
                      disabled={galleryExportFiltersDisabled}
                      onClick={() => handleToggleGalleryExportPerson(person.id)}
                    >
                      {person.display_name}
                    </button>
                  ))}
                  {persons.length === 0 && <span className="filter-empty">没有人物标签</span>}
                </div>
              </section>

              <section className="export-filter-block">
                <div className="filter-section-head">
                  <strong>普通标签</strong>
                  <span>{galleryExportTagIds.length} 已选</span>
                </div>
                <div className="export-chip-cloud compact">
                  {normalTags.map((tag) => (
                    <button
                      key={`export-tag-${tag.id}`}
                      className={galleryExportTagIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                      disabled={galleryExportFiltersDisabled}
                      onClick={() => handleToggleGalleryExportTag(tag.id)}
                    >
                      #{tag.name}
                    </button>
                  ))}
                  {normalTags.length === 0 && <span className="filter-empty">没有普通标签</span>}
                </div>
              </section>
            </div>
            {(galleryExportScope === "filtered" || galleryExportScope === "from_start") && (
              <p className="export-filter-note">
                排除条件：{galleryExportExcludePersonIds.length} 个人物、{galleryExportExcludeTagIds.length} 个普通标签。
                {galleryExportScope === "from_start" && " 起点导出固定沿用打开弹窗时的图库筛选条件。"}
              </p>
            )}

            <div className="modal-actions">
              <button
                onClick={() => {
                  setGalleryExportScope("filtered");
                  setGalleryExportPersonIds([]);
                  setGalleryExportTagIds([]);
                  setGalleryExportExcludePersonIds([]);
                  setGalleryExportExcludeTagIds([]);
                }}
              >
                清空筛选
              </button>
              <button disabled={galleryExportDisabled} onClick={() => void handleExportGalleryPhotos()}>
                {busy ? "正在生成 ZIP" : "导出 ZIP"}
              </button>
            </div>
          </div>
        </div>
      )}
      {lightboxPhoto && (
        <PhotoLightbox
          image={{ src: lightboxPhoto.original_url, alt: lightboxPhoto.is_rich_text ? "图文大图预览" : "大图预览" }}
          shellClassName={`gallery-lightbox${lightboxPhoto.is_rich_text ? " rich-lightbox" : ""}`}
          meta={lightboxMeta}
          busy={busy}
          keyboardEnabled={!lightboxEditMode}
          canGoPrevious={canGoPrev}
          canGoNext={canGoNext}
          previousLabel={isFirstOfPage && hasPrevPage ? "上一页" : undefined}
          nextLabel={isLastOfPage && hasNextPage ? "下一页" : undefined}
          onClose={closeGalleryLightbox}
          onPrevious={goPrevLightbox}
          onNext={goNextLightbox}
        >
          {(image) => lightboxPhoto.is_rich_text ? (
              <div className="rich-lightbox-layout">
                <div className="rich-lightbox-image-wrap">
                  {image}
                </div>
                <aside className="rich-lightbox-copy">
                  <h3>图文内容</h3>
                  {lightboxEditMode ? (
                    <textarea
                      className="rich-text-editor lightbox-editor"
                      value={lightboxRichTextDraft}
                      onChange={(event) => setLightboxRichTextDraft(event.target.value)}
                      placeholder="可在此编辑图文文本"
                    />
                  ) : (
                    <p>{lightboxPhoto.rich_text || "未识别到文本，点击编辑按钮手动补录。"}</p>
                  )}
                  <div className="micro-row">
                    <span>OCR状态：{lightboxPhoto.ocr_status ?? "unknown"}</span>
                    {lightboxEditMode ? (
                      <button
                        disabled={busy}
                        onClick={() => {
                          void handleSaveLightboxRichText();
                          setLightboxEditMode(false);
                        }}
                      >
                        保存图文文本
                      </button>
                    ) : (
                      <button
                        disabled={busy}
                        onClick={() => {
                          setLightboxRichTextDraft(lightboxPhoto.rich_text || "");
                          setLightboxEditMode(true);
                        }}
                      >
                        编辑图文文本
                      </button>
                    )}
                  </div>
                  <div className="micro-row wrap">
                    {lightboxPhoto.persons.map((person) => (
                      <small key={`lb-p-${lightboxPhoto.id}-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                        {person.person_name}
                      </small>
                    ))}
                  </div>
                  <div className="micro-row wrap">
                    {sortByPinyinName(lightboxPhoto.tags).map((tag) => (
                      <small key={`lb-t-${lightboxPhoto.id}-${tag.id}`} className="pill muted">
                        #{tag.name}
                      </small>
                    ))}
                  </div>
                </aside>
              </div>
            ) : image}
        </PhotoLightbox>
      )}
      {recognitionNotice && (
        <div className="recognition-notice" role="status" aria-live="polite">
          <div>
            <strong>重新识别完成</strong>
            <span>{recognitionNotice.message}</span>
          </div>
          <button type="button" onClick={() => setRecognitionNotice(null)}>知道了</button>
          <i aria-hidden="true" />
        </div>
      )}
    </>
  );
}
