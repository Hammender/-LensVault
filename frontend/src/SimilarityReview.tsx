import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Images, RefreshCw, ScanSearch, Trash2, X } from "lucide-react";

import {
  batchDeleteGalleryPhotos,
  createGallerySimilarityScan,
  getGallerySimilarityScanOverview,
  getTask,
  listGallerySimilarityGroups,
  updateGallerySimilarityGroup
} from "./api";
import PhotoLightbox from "./PhotoLightbox";
import { useConfirm } from "./ConfirmDialog";
import SearchableSelect from "./SearchableSelect";
import { filterPersonMatches, matchesPersonSearch } from "./personPicker";
import { chooseRecoveredScan, findScanForScope } from "./similarityScanState";
import { findPreviewAfterCurrentDelete, getSimilarityLightboxShortcut } from "./similarityReviewKeyboard";
import type { GallerySimilarityGroup, GallerySimilarityScan, Person } from "./types";
import { formatDate, withImageWidth } from "./utils";

type SimilarityReviewProps = {
  persons: Person[];
  canEdit: boolean;
  canDelete: boolean;
};

const pageSize = 12;

export default function SimilarityReview({ persons, canEdit, canDelete }: SimilarityReviewProps) {
  const confirm = useConfirm();
  const [personId, setPersonId] = useState<number | null>(null);
  const [personSearch, setPersonSearch] = useState("全部人物");
  const [includeCrossType, setIncludeCrossType] = useState(false);
  const [tier, setTier] = useState<"near_duplicate" | "same_scene">("near_duplicate");
  const [activeScan, setActiveScan] = useState<GallerySimilarityScan | null>(null);
  const [resultScan, setResultScan] = useState<GallerySimilarityScan | null>(null);
  const [scanHistory, setScanHistory] = useState<GallerySimilarityScan[]>([]);
  const [groups, setGroups] = useState<GallerySimilarityGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [preview, setPreview] = useState<{ groupId: number; photoId: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [deletingGroupIds, setDeletingGroupIds] = useState<number[]>([]);
  const [dismissingGroupIds, setDismissingGroupIds] = useState<number[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const previewGroup = preview ? groups.find((group) => group.id === preview.groupId) ?? null : null;
  const previewIndex = previewGroup && preview
    ? previewGroup.members.findIndex((member) => member.photo.id === preview.photoId)
    : -1;
  const previewMember = previewGroup && previewIndex >= 0 ? previewGroup.members[previewIndex] : null;
  const previewSelectedCount = previewGroup
    ? previewGroup.members.filter((member) => selectedIds.includes(member.photo.id)).length
    : 0;
  const selectedPersonLabel = personId === null
    ? "全部人物"
    : persons.find((person) => person.id === personId)?.display_name ?? "全部人物";
  const matchingScanPersons = useMemo(
    () => filterPersonMatches(persons, personSearch),
    [personSearch, persons]
  );
  const scanPersonOptions = useMemo(() => {
    const allOption = matchesPersonSearch("全部人物", personSearch)
      ? [{ value: "all", label: "全部人物", meta: "按每个人物分别扫描" }]
      : [];
    return [
      ...allOption,
      ...matchingScanPersons.map((person) => ({
        value: String(person.id),
        label: person.display_name,
        meta: `${person.gallery_photo_count} 张图库图片`
      }))
    ];
  }, [matchingScanPersons, personSearch]);
  const targetResult = useMemo(
    () => findScanForScope(scanHistory, personId, includeCrossType),
    [includeCrossType, personId, scanHistory]
  );

  function personLabel(targetPersonId: number | null): string {
    if (targetPersonId === null) return "全部人物";
    return persons.find((person) => person.id === targetPersonId)?.display_name ?? `人物 #${targetPersonId}`;
  }

  function syncScopeFromScan(targetScan: GallerySimilarityScan) {
    setPersonId(targetScan.person_id);
    setPersonSearch(personLabel(targetScan.person_id));
    setIncludeCrossType(targetScan.include_cross_type);
    setOffset(0);
  }

  function selectResult(targetScan: GallerySimilarityScan | null, syncScope = true) {
    setResultScan(targetScan);
    if (targetScan && syncScope) syncScopeFromScan(targetScan);
  }

  function selectScope(nextPersonId: number | null, nextIncludeCrossType: boolean) {
    setPersonId(nextPersonId);
    setPersonSearch(personLabel(nextPersonId));
    setIncludeCrossType(nextIncludeCrossType);
    setOffset(0);
    selectResult(findScanForScope(scanHistory, nextPersonId, nextIncludeCrossType), false);
  }

  function scanHistoryLabel(targetScan: GallerySimilarityScan): string {
    const scope = targetScan.include_cross_type ? "跨类型" : "分类型";
    const timestamp = formatDate(targetScan.completed_at || targetScan.created_at);
    return `${personLabel(targetScan.person_id)} · ${scope} · ${timestamp} · ${targetScan.group_count} 组${targetScan.is_stale ? " · 已过期" : ""}`;
  }

  const loadGroups = useCallback(async (
    targetScan: GallerySimilarityScan | null,
    nextOffset = 0,
    resetSelection = true,
    nextPreview?: { groupId: number; photoId: number } | null
  ) => {
    if (!targetScan || targetScan.status !== "completed") {
      setGroups([]);
      setTotal(0);
      return;
    }
    let response = await listGallerySimilarityGroups(targetScan.id, tier, nextOffset, pageSize);
    if (!response.items.length && response.total > 0 && nextOffset >= response.total) {
      const fallbackOffset = Math.max(0, Math.floor((response.total - 1) / pageSize) * pageSize);
      response = await listGallerySimilarityGroups(targetScan.id, tier, fallbackOffset, pageSize);
    }
    setGroups(response.items);
    setTotal(response.total);
    setOffset(response.offset);
    if (resetSelection) setSelectedIds([]);
    if (nextPreview && response.items.some((group) => group.id === nextPreview.groupId && group.members.some((member) => member.photo.id === nextPreview.photoId))) {
      setPreview(nextPreview);
    } else {
      setPreview(null);
    }
  }, [tier]);

  async function restoreOverview(preferredScanId?: string | null, showBusy = true) {
    if (showBusy) setBusy(true);
    try {
      const overview = await getGallerySimilarityScanOverview();
      setActiveScan(overview.active);
      setScanHistory(overview.results);
      const recovered = chooseRecoveredScan(
        overview.results,
        preferredScanId === undefined ? resultScan?.id : preferredScanId
      );
      selectResult(recovered);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "读取相似图片结果失败");
    } finally {
      if (showBusy) setBusy(false);
    }
  }

  async function refreshOverviewAfterDelete(preferredScanId: string | null) {
    const overview = await getGallerySimilarityScanOverview();
    setActiveScan(overview.active);
    setScanHistory(overview.results);
    setResultScan(chooseRecoveredScan(overview.results, preferredScanId));
  }

  async function refreshGroupsAfterDelete(
    nextPreview?: { groupId: number; photoId: number } | null,
    resetSelection = true
  ) {
    if (!resultScan) return;
    await loadGroups(resultScan, offset, resetSelection, nextPreview);
  }

  function toggleSelected(photoId: number) {
    setSelectedIds((current) => current.includes(photoId)
      ? current.filter((id) => id !== photoId)
      : [...current, photoId]);
  }

  async function dismissGroup(group: GallerySimilarityGroup) {
    if (!resultScan) return;
    setDismissingGroupIds((current) => [...current, group.id]);
    try {
      await updateGallerySimilarityGroup(resultScan.id, group.id, "dismissed");
      const groupPhotoIds = new Set(group.members.map((member) => member.photo.id));
      setSelectedIds((current) => current.filter((photoId) => !groupPhotoIds.has(photoId)));
      setNotice(`第 ${group.ordinal} 组已设为暂不处理，本次扫描中将不再显示。`);
      await loadGroups(resultScan, offset, false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "暂不处理失败");
    } finally {
      setDismissingGroupIds((current) => current.filter((groupId) => groupId !== group.id));
    }
  }

  useEffect(() => {
    void restoreOverview(null);
  }, []);

  useEffect(() => {
    void loadGroups(resultScan, 0);
  }, [loadGroups, resultScan?.id]);

  useEffect(() => {
    if (!activeScan?.task_id || !["pending", "running"].includes(activeScan.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const task = await getTask(activeScan.task_id!);
        setActiveScan((current) => current ? { ...current, task, status: task.status } : current);
        if (task.status === "completed" || task.status === "failed") {
          window.clearInterval(timer);
          if (task.status === "failed") {
            setNotice(task.message || "相似图片扫描失败，已保留上次成功结果。");
          }
          await restoreOverview(task.status === "completed" ? activeScan.id : resultScan?.id, false);
        }
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "扫描进度读取失败");
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeScan?.id, activeScan?.status, activeScan?.task_id, resultScan?.id]);

  async function startScan() {
    const matchMode = includeCrossType
      ? "允许普通图库与图文图库跨类型匹配"
      : "普通图库与图文图库分别匹配";
    const confirmed = await confirm({
      title: "开始相似图片扫描",
      message: `确认开始相似图片扫描吗？\n\n扫描人物：${personLabel(personId)}\n匹配方式：${matchMode}\n\n扫描耗时较长，完成前会继续保留当前成功结果。`,
      confirmLabel: "开始扫描"
    });
    if (!confirmed) return;

    setBusy(true);
    setNotice(null);
    try {
      const created = await createGallerySimilarityScan({ person_id: personId, include_cross_type: includeCrossType });
      setActiveScan(created);
      setSelectedIds([]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "发起扫描失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelected() {
    if (!selectedIds.length || !await confirm({ title: "删除相似图片", message: `确认删除选中的 ${selectedIds.length} 张图片？原图也会被删除。`, confirmLabel: "删除", tone: "danger" })) return;
    setBusy(true);
    try {
      const deleted = await batchDeleteGalleryPhotos(selectedIds);
      setNotice(`已删除 ${deleted} 张图片。当前扫描结果已标记为过期，建议处理完后重新扫描。`);
      await refreshGroupsAfterDelete();
      await refreshOverviewAfterDelete(resultScan?.id ?? null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除图片失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteGroupSelected(group: GallerySimilarityGroup) {
    const groupPhotoIds = group.members
      .filter((member) => selectedIds.includes(member.photo.id))
      .map((member) => member.photo.id);
    if (!groupPhotoIds.length) return;
    const confirmed = await confirm({
      title: `删除第 ${group.ordinal} 组图片`,
      message: `确认删除第 ${group.ordinal} 组已选中的 ${groupPhotoIds.length} 张图片吗？\n\n原图也会被删除，此操作不可撤销。`,
      confirmLabel: "删除",
      tone: "danger"
    });
    if (!confirmed) return;

    setDeletingGroupIds((current) => [...current, group.id]);
    try {
      const deleted = await batchDeleteGalleryPhotos(groupPhotoIds);
      setNotice(`已删除第 ${group.ordinal} 组中的 ${deleted} 张图片。`);
      await refreshGroupsAfterDelete();
      await refreshOverviewAfterDelete(resultScan?.id ?? null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除图片失败");
    } finally {
      setDeletingGroupIds((current) => current.filter((groupId) => groupId !== group.id));
    }
  }

  async function deleteCurrentPreviewPhoto(group: GallerySimilarityGroup, photoId: number) {
    const member = group.members.find((item) => item.photo.id === photoId);
    if (!member) return;
    const confirmed = await confirm({
      title: "删除当前图片",
      message: `确认删除当前图片“${member.photo.filename}”吗？\n\n原图也会被删除，此操作不可撤销。`,
      confirmLabel: "删除",
      tone: "danger"
    });
    if (!confirmed) return;

    const nextPhotoId = findPreviewAfterCurrentDelete(group.members.map((item) => item.photo.id), photoId);
    setDeletingGroupIds((current) => [...current, group.id]);
    try {
      const deleted = await batchDeleteGalleryPhotos([photoId]);
      setSelectedIds((current) => current.filter((id) => id !== photoId));
      setNotice(`已删除图片“${member.photo.filename}”。`);
      await refreshGroupsAfterDelete(nextPhotoId ? { groupId: group.id, photoId: nextPhotoId } : null, false);
      await refreshOverviewAfterDelete(resultScan?.id ?? null);
      if (!deleted) setNotice("图片未被删除，图库内容可能已经发生变化。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除图片失败");
    } finally {
      setDeletingGroupIds((current) => current.filter((groupId) => groupId !== group.id));
    }
  }

  return (
    <main className="similarity-page">
      <section className="panel similarity-hero">
        <div className="similarity-hero-copy">
          <p className="eyebrow">智能整理</p>
          <div className="similarity-hero-title">
            <h1>相似图片整理</h1>
            <ScanSearch size={46} aria-hidden="true" />
          </div>
          <p>仅在共享人物标签的图片中匹配。系统只给出质量建议，所有删除操作均由你确认。</p>
        </div>
      </section>

      <section className="panel similarity-controls">
        <div className="similarity-person-control">
          <span>扫描人物</span>
          <SearchableSelect
            id="similarity-person-picker"
            value={personId === null ? "all" : String(personId)}
            query={personSearch}
            options={scanPersonOptions}
            placeholder="搜索人物名称、拼音或首字母"
            emptyText="没有匹配的人物"
            disabled={busy}
            onOpen={() => setPersonSearch("")}
            onCancel={() => setPersonSearch(selectedPersonLabel)}
            onQueryChange={setPersonSearch}
            onSelect={(option) => {
              selectScope(option.value === "all" ? null : Number(option.value), includeCrossType);
            }}
          />
        </div>
        <label className="similarity-switch">
          <input
            type="checkbox"
            checked={includeCrossType}
            onChange={(event) => selectScope(personId, event.target.checked)}
          />
          <span>允许普通图库与图文图库跨类型匹配</span>
        </label>
        <button disabled={busy || deletingGroupIds.length > 0 || !canEdit || Boolean(activeScan)} onClick={() => void startScan()}>
          <RefreshCw size={16} /> {targetResult ? "重新扫描" : "开始扫描"}
        </button>
        <div className="similarity-history-control">
          <span>历史结果</span>
          <select
            aria-label="历史扫描结果"
            title="每个扫描范围保留最近一次成功结果"
            value={resultScan?.id ?? ""}
            disabled={busy || scanHistory.length === 0}
            onChange={(event) => {
              const selected = scanHistory.find((item) => item.id === event.target.value) ?? null;
              selectResult(selected);
            }}
          >
            {scanHistory.length === 0 && <option value="">暂无成功结果</option>}
            {scanHistory.map((item) => <option key={item.id} value={item.id}>{scanHistoryLabel(item)}</option>)}
          </select>
        </div>
      </section>

      {notice && <div className="panel similarity-notice">{notice}</div>}
      {activeScan && (
        <section className="panel similarity-status">
          <div>
            <strong>正在扫描</strong>
            <span>{activeScan.task?.message || `创建于 ${formatDate(activeScan.created_at)}`}</span>
          </div>
          {activeScan.task && <progress value={activeScan.task.progress} max={1} />}
          {resultScan && <small>扫描期间继续显示上一次成功结果</small>}
        </section>
      )}
      {resultScan && (
        <section className={`panel similarity-status ${resultScan.is_stale ? "stale" : ""}`}>
          <div>
            <strong>当前成功结果</strong>
            <span>{personLabel(resultScan.person_id)} · {resultScan.include_cross_type ? "跨类型" : "分类型"} · 完成于 {formatDate(resultScan.completed_at || resultScan.created_at)}</span>
          </div>
          <small>{resultScan.photo_count} 张图片 · {resultScan.candidate_pair_count} 个候选对 · {resultScan.group_count} 个相似组</small>
          {resultScan.is_stale && <b>图库内容已变化，当前结果可能过期</b>}
        </section>
      )}

      <section className="similarity-results">
        <div className="similarity-tabs">
          <button className={tier === "near_duplicate" ? "active" : ""} onClick={() => { setTier("near_duplicate"); setOffset(0); }}>近重复</button>
          <button className={tier === "same_scene" ? "active" : ""} onClick={() => { setTier("same_scene"); setOffset(0); }}>同场景相似</button>
          <span>{total} 组</span>
          <button className="danger-button" disabled={!canDelete || !selectedIds.length || busy} onClick={() => void deleteSelected()}>
            <Trash2 size={15} /> 删除选中（{selectedIds.length}）
          </button>
        </div>

        {groups.map((group) => (
          <article className="panel similarity-group" key={group.id}>
            <header>
              <div className="similarity-group-title">
                <strong>第 {group.ordinal} 组</strong>
                <span>{group.people.map((person) => person.display_name).join("、")}</span>
              </div>
              <small>最低相似度 {(group.min_score * 100).toFixed(1)}%</small>
              <div className="similarity-group-actions">
                <button
                  className="danger-button"
                  disabled={!canDelete || busy || deletingGroupIds.includes(group.id) || !group.members.some((member) => selectedIds.includes(member.photo.id))}
                  onClick={() => void deleteGroupSelected(group)}
                >
                  <Trash2 size={15} /> {deletingGroupIds.includes(group.id) ? "正在删除" : "删除图片"}
                </button>
                <button
                  className="ghost-button"
                  disabled={!canEdit || deletingGroupIds.includes(group.id) || dismissingGroupIds.includes(group.id)}
                  onClick={() => void dismissGroup(group)}
                >
                  {dismissingGroupIds.includes(group.id) ? "正在隐藏" : "暂不处理"}
                </button>
              </div>
            </header>
            <div className="similarity-member-grid">
              {group.members.map((member) => (
                <article className={`similarity-member ${member.recommended_keep ? "recommended" : ""} ${selectedIds.includes(member.photo.id) ? "selected" : ""}`} key={member.photo.id}>
                  <button
                    type="button"
                    className="similarity-image-button"
                    onClick={() => setPreview({ groupId: group.id, photoId: member.photo.id })}
                    aria-label={`大图查看 ${member.photo.filename}`}
                  >
                    <img src={withImageWidth(member.photo.thumbnail_url, 560)} alt={member.photo.filename} loading="lazy" />
                  </button>
                  <span className="similarity-member-type">{member.photo.is_rich_text ? "图文" : "普通"}</span>
                  {member.recommended_keep && <span className="keep-badge"><CheckCircle2 size={14} /> 建议保留</span>}
                  <div>
                    <label className="similarity-delete-choice">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(member.photo.id)}
                        disabled={!canDelete || deletingGroupIds.includes(group.id)}
                        onChange={() => toggleSelected(member.photo.id)}
                      />
                      <span>选择删除</span>
                    </label>
                    <span>相似 {(member.score_to_representative * 100).toFixed(1)}%</span>
                  </div>
                </article>
              ))}
            </div>
          </article>
        ))}
        {!busy && resultScan && groups.length === 0 && (
          <div className="panel empty-card"><Images size={30} /> 当前档位没有相似图片组。</div>
        )}
        {!resultScan && !busy && <div className="panel empty-card">当前范围没有成功扫描结果。可切换历史结果，或点击“开始扫描”。</div>}
        {total > pageSize && (
          <div className="pagination-row">
            <button disabled={offset === 0 || busy} onClick={() => void loadGroups(resultScan, Math.max(0, offset - pageSize))}>上一页</button>
            <span>{offset + 1} - {Math.min(offset + pageSize, total)} / {total}</span>
            <button disabled={offset + pageSize >= total || busy} onClick={() => void loadGroups(resultScan, offset + pageSize)}>下一页</button>
          </div>
        )}
      </section>
      {previewGroup && previewMember && (
        <PhotoLightbox
          shellClassName="similarity-review-lightbox"
          busy={deletingGroupIds.includes(previewGroup.id) || dismissingGroupIds.includes(previewGroup.id)}
          canGoPrevious={previewIndex > 0}
          canGoNext={previewIndex < previewGroup.members.length - 1}
          onClose={() => setPreview(null)}
          onPrevious={() => {
            const previous = previewGroup.members[previewIndex - 1];
            if (previous) setPreview({ groupId: previewGroup.id, photoId: previous.photo.id });
          }}
          onNext={() => {
            const next = previewGroup.members[previewIndex + 1];
            if (next) setPreview({ groupId: previewGroup.id, photoId: next.photo.id });
          }}
          onKeyDown={(event) => {
            const shortcut = getSimilarityLightboxShortcut(event.key);
            if (shortcut === "toggle_selection" && canDelete) {
              event.preventDefault();
              toggleSelected(previewMember.photo.id);
            } else if (shortcut === "delete_current" && canDelete) {
              event.preventDefault();
              void deleteCurrentPreviewPhoto(previewGroup, previewMember.photo.id);
            }
          }}
          meta={(
            <>
              <div className="lightbox-meta-head">
                <span>第 {previewGroup.ordinal} 组</span>
                <strong>{previewIndex + 1} / {previewGroup.members.length}</strong>
              </div>
              <div className="lightbox-meta-section similarity-review-strip-section">
                <span>组内图片</span>
                <div className="similarity-review-strip">
                  {previewGroup.members.map((member, index) => {
                    const isCurrent = member.photo.id === previewMember.photo.id;
                    const isSelected = selectedIds.includes(member.photo.id);
                    return (
                      <button
                        type="button"
                        className={`${isCurrent ? "current" : ""} ${isSelected ? "selected" : ""}`.trim()}
                        key={member.photo.id}
                        onClick={() => setPreview({ groupId: previewGroup.id, photoId: member.photo.id })}
                        aria-label={`查看第 ${index + 1} 张${isSelected ? "，已标记删除" : ""}`}
                        aria-current={isCurrent ? "true" : undefined}
                      >
                        <img src={withImageWidth(member.photo.thumbnail_url, 160)} alt="" />
                        <small>{index + 1}</small>
                        {isSelected && <CheckCircle2 size={16} aria-hidden="true" />}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="similarity-review-actions">
                <div>
                  <span>整理操作</span>
                  <strong>本组已标记 {previewSelectedCount} 张</strong>
                </div>
                <button
                  type="button"
                  className={`similarity-review-mark ${selectedIds.includes(previewMember.photo.id) ? "selected" : ""}`}
                  disabled={!canDelete || deletingGroupIds.includes(previewGroup.id)}
                  aria-pressed={selectedIds.includes(previewMember.photo.id)}
                  onClick={() => toggleSelected(previewMember.photo.id)}
                >
                  <CheckCircle2 size={18} aria-hidden="true" />
                  {selectedIds.includes(previewMember.photo.id) ? "取消标记当前图片" : "标记当前图片删除"}
                </button>
                <button
                  type="button"
                  className="danger-button"
                  disabled={!canDelete || deletingGroupIds.includes(previewGroup.id)}
                  onClick={() => void deleteCurrentPreviewPhoto(previewGroup, previewMember.photo.id)}
                >
                  <Trash2 size={17} aria-hidden="true" />
                  {deletingGroupIds.includes(previewGroup.id) ? "正在删除" : "删除当前"}
                </button>
                <button
                  type="button"
                  className="danger-button"
                  disabled={!canDelete || previewSelectedCount === 0 || deletingGroupIds.includes(previewGroup.id)}
                  onClick={() => void deleteGroupSelected(previewGroup)}
                >
                  <Trash2 size={17} aria-hidden="true" />
                  {deletingGroupIds.includes(previewGroup.id) ? "正在删除" : `删除本组已选（${previewSelectedCount}）`}
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!canEdit || deletingGroupIds.includes(previewGroup.id) || dismissingGroupIds.includes(previewGroup.id)}
                  onClick={() => void dismissGroup(previewGroup)}
                >
                  {dismissingGroupIds.includes(previewGroup.id) ? "正在隐藏" : "暂不处理本组"}
                </button>
                <button type="button" className="ghost-button" onClick={() => setPreview(null)}>
                  <X size={17} aria-hidden="true" /> 关闭预览
                </button>
                <p className="similarity-review-shortcuts">
                  <kbd>←</kbd><kbd>→</kbd> 切换　<kbd>Space</kbd> 标记　<kbd>Delete</kbd> 删除当前　<kbd>Esc</kbd> 关闭
                </p>
              </div>
              <div className="lightbox-meta-section">
                <span>对比信息</span>
                <div className="similarity-lightbox-facts">
                  <b>{previewMember.photo.is_rich_text ? "图文图片" : "普通图片"}</b>
                  <b>相似度 {(previewMember.score_to_representative * 100).toFixed(1)}%</b>
                  {previewMember.recommended_keep && <b className="similarity-keep-text">建议保留</b>}
                </div>
              </div>
              <div className="lightbox-meta-section">
                <span>人物标签</span>
                <div className="lightbox-meta-chips">
                  {previewGroup.people.map((person) => (
                    <small className="pill" key={person.id}>{person.display_name}</small>
                  ))}
                </div>
              </div>
              <div className="lightbox-meta-section">
                <span>普通标签</span>
                <div className="lightbox-meta-chips">
                  {previewMember.photo.tags.length > 0 ? previewMember.photo.tags.map((tag) => (
                    <small className="pill muted" key={tag.id}>#{tag.name}</small>
                  )) : <small className="lightbox-meta-empty">无普通标签</small>}
                </div>
              </div>
            </>
          )}
        >
          <img className="lightbox-image" src={previewMember.photo.original_url} alt={previewMember.photo.filename} />
        </PhotoLightbox>
      )}
    </main>
  );
}
