import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Images, RefreshCw, ScanSearch, Trash2 } from "lucide-react";

import {
  batchDeleteGalleryPhotos,
  createGallerySimilarityScan,
  getGallerySimilarityGroup,
  getGallerySimilarityScanOverview,
  getTask,
  listGallerySimilarityGroups
} from "./api";
import PhotoLightbox from "./PhotoLightbox";
import SearchableSelect from "./SearchableSelect";
import { filterPersonMatches, matchesPersonSearch } from "./personPicker";
import { chooseRecoveredScan, findScanForScope } from "./similarityScanState";
import type { GallerySimilarityGroup, GallerySimilarityScan, Person } from "./types";
import { formatDate, withImageWidth } from "./utils";

type SimilarityReviewProps = {
  persons: Person[];
  canEdit: boolean;
  canDelete: boolean;
};

const pageSize = 12;

export default function SimilarityReview({ persons, canEdit, canDelete }: SimilarityReviewProps) {
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
  const [dismissedIds, setDismissedIds] = useState<number[]>([]);
  const [preview, setPreview] = useState<{ groupId: number; photoId: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [deletingGroupIds, setDeletingGroupIds] = useState<number[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const visibleGroups = useMemo(
    () => groups.filter((group) => !dismissedIds.includes(group.id)),
    [groups, dismissedIds]
  );
  const previewGroup = preview ? groups.find((group) => group.id === preview.groupId) ?? null : null;
  const previewIndex = previewGroup && preview
    ? previewGroup.members.findIndex((member) => member.photo.id === preview.photoId)
    : -1;
  const previewMember = previewGroup && previewIndex >= 0 ? previewGroup.members[previewIndex] : null;
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

  const loadGroups = useCallback(async (targetScan: GallerySimilarityScan | null, nextOffset = 0) => {
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
    setSelectedIds([]);
    setDismissedIds([]);
    setPreview(null);
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

  async function refreshAffectedGroups(photoIds: number[]) {
    if (!resultScan) return;
    const photoIdSet = new Set(photoIds);
    const affectedGroupIds = groups
      .filter((group) => group.members.some((member) => photoIdSet.has(member.photo.id)))
      .map((group) => group.id);
    if (!affectedGroupIds.length) return;

    const refreshedGroups = await Promise.all(
      affectedGroupIds.map(async (groupId) => [
        groupId,
        await getGallerySimilarityGroup(resultScan.id, groupId)
      ] as const)
    );
    const refreshedById = new Map(refreshedGroups);
    const removedGroupIds = new Set(
      refreshedGroups.filter(([, group]) => group === null).map(([groupId]) => groupId)
    );
    setGroups((current) => current.flatMap((group) => {
      if (!refreshedById.has(group.id)) return [group];
      const refreshed = refreshedById.get(group.id);
      return refreshed ? [refreshed] : [];
    }));
    if (removedGroupIds.size) setTotal((current) => Math.max(0, current - removedGroupIds.size));
    setSelectedIds((current) => current.filter((photoId) => !photoIdSet.has(photoId)));
    setPreview((current) => {
      if (!current || photoIdSet.has(current.photoId) || removedGroupIds.has(current.groupId)) return null;
      return current;
    });
    if (groups.length === removedGroupIds.size) {
      await loadGroups(resultScan, offset);
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
    const confirmed = window.confirm(
      `确认开始相似图片扫描吗？\n\n扫描人物：${personLabel(personId)}\n匹配方式：${matchMode}\n\n扫描耗时较长，完成前会继续保留当前成功结果。`
    );
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
    if (!selectedIds.length || !window.confirm(`确认删除选中的 ${selectedIds.length} 张图片？原图也会被删除。`)) return;
    setBusy(true);
    try {
      const deleted = await batchDeleteGalleryPhotos(selectedIds);
      setNotice(`已删除 ${deleted} 张图片。当前扫描结果已标记为过期，建议处理完后重新扫描。`);
      await refreshAffectedGroups(selectedIds);
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
    const confirmed = window.confirm(
      `确认删除第 ${group.ordinal} 组已选中的 ${groupPhotoIds.length} 张图片吗？\n\n原图也会被删除，此操作不可撤销。`
    );
    if (!confirmed) return;

    setDeletingGroupIds((current) => [...current, group.id]);
    try {
      const deleted = await batchDeleteGalleryPhotos(groupPhotoIds);
      setNotice(`已删除第 ${group.ordinal} 组中的 ${deleted} 张图片。`);
      await refreshAffectedGroups(groupPhotoIds);
      await refreshOverviewAfterDelete(resultScan?.id ?? null);
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

        {visibleGroups.map((group) => (
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
                  disabled={deletingGroupIds.includes(group.id)}
                  onClick={() => setDismissedIds((current) => [...current, group.id])}
                >
                  暂不处理
                </button>
              </div>
            </header>
            <div className="similarity-member-grid">
              {group.members.map((member) => (
                <article className={`similarity-member ${member.recommended_keep ? "recommended" : ""}`} key={member.photo.id}>
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
                        onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, member.photo.id] : current.filter((id) => id !== member.photo.id))}
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
        {!busy && resultScan && visibleGroups.length === 0 && (
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
          meta={(
            <>
              <div className="lightbox-meta-head">
                <span>第 {previewGroup.ordinal} 组</span>
                <strong>{previewIndex + 1} / {previewGroup.members.length}</strong>
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
