import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Images, Layers, RefreshCw, ScanSearch, Trash2, X } from "lucide-react";

import {
  autoDeleteExactMirrorGroups,
  batchDeleteGalleryPhotos,
  createGallerySimilarityScan,
  getGallerySimilarityScanOverview,
  getTask,
  listGallerySimilarityGroups,
  previewNormalNearDuplicateAutoDelete,
  updateGallerySimilarityGroup
} from "./api";
import PhotoLightbox from "./PhotoLightbox";
import { useConfirm } from "./ConfirmDialog";
import SearchableSelect from "./SearchableSelect";
import { filterPersonMatches, matchesPersonSearch } from "./personPicker";
import { chooseRecoveredScan, findScanForScope } from "./similarityScanState";
import { findPreviewAfterCurrentDelete, getSimilarityLightboxShortcut } from "./similarityReviewKeyboard";
import type {
  GallerySimilarityAutoDeletePreview,
  GallerySimilarityAutoDeletePreviewCluster,
  GallerySimilarityAutoDeletePreviewMember,
  GallerySimilarityCluster,
  GallerySimilarityGroup,
  GallerySimilarityMember,
  GallerySimilarityScan,
  Person
} from "./types";
import { formatBytes, formatDate, withImageWidth } from "./utils";

type SimilarityReviewProps = {
  persons: Person[];
  canEdit: boolean;
  canDelete: boolean;
};

const pageSize = 12;

type SimilarityGroupSection = {
  key: string;
  cluster: GallerySimilarityCluster | null;
  members: GallerySimilarityMember[];
};

function buildGroupSections(group: GallerySimilarityGroup): SimilarityGroupSection[] | null {
  if (group.clusters.length === 0) return null;
  const membersById = new Map(group.members.map((member) => [member.photo.id, member]));
  const sections: SimilarityGroupSection[] = group.clusters
    .slice()
    .sort((a, b) => b.member_photo_ids.length - a.member_photo_ids.length || b.min_pair_score - a.min_pair_score)
    .map((cluster) => {
      const members = cluster.member_photo_ids
        .map((photoId) => membersById.get(photoId))
        .filter((member): member is GallerySimilarityMember => Boolean(member));
      members.sort(
        (a, b) => Number(b.recommended_keep) - Number(a.recommended_keep) || b.quality_score - a.quality_score
      );
      return { key: `cluster-${cluster.index}`, cluster, members };
    });
  const scattered = group.members.filter((member) => member.auto_cluster_index === null);
  if (scattered.length > 0) sections.push({ key: "scattered", cluster: null, members: scattered });
  return sections;
}

function clusterSizeWarningText(cluster: GallerySimilarityAutoDeletePreviewCluster): string | null {
  if (cluster.status !== "ready") return null;
  const retainedMembers = cluster.members.filter((member) => member.retained);
  if (retainedMembers.length !== 1 || retainedMembers[0].size_bytes === null) return null;
  const sizes = cluster.members
    .map((member) => member.size_bytes)
    .filter((size): size is number => size !== null);
  if (sizes.length === 0) return null;
  const maxSize = Math.max(...sizes);
  if (maxSize <= retainedMembers[0].size_bytes) return null;
  return `建议保留图非最大文件（最大 ${formatBytes(maxSize)}），请检查`;
}

export default function SimilarityReview({ persons, canEdit, canDelete }: SimilarityReviewProps) {
  const confirm = useConfirm();
  const [personId, setPersonId] = useState<number | null>(null);
  const [personSearch, setPersonSearch] = useState("全部人物");
  const [includeCrossType, setIncludeCrossType] = useState(false);
  const [scanType, setScanType] = useState<"normal" | "mirror">("normal");
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
  const [autoDeletePreview, setAutoDeletePreview] = useState<GallerySimilarityAutoDeletePreview | null>(null);
  const [previewOverrides, setPreviewOverrides] = useState<Record<number, boolean>>({});
  const [enlargedPreviewContext, setEnlargedPreviewContext] = useState<{
    members: GallerySimilarityAutoDeletePreviewMember[];
    index: number;
  } | null>(null);
  const enlargedPreviewMember = enlargedPreviewContext
    ? enlargedPreviewContext.members[enlargedPreviewContext.index] ?? null
    : null;

  const previewGroup = preview ? groups.find((group) => group.id === preview.groupId) ?? null : null;
  const previewOrderedMembers = useMemo(() => {
    if (!previewGroup) return [] as GallerySimilarityMember[];
    const sections = buildGroupSections(previewGroup);
    if (!sections) return previewGroup.members;
    return sections.flatMap((section) => section.members);
  }, [previewGroup]);
  const previewIndex = previewGroup && preview
    ? previewOrderedMembers.findIndex((member) => member.photo.id === preview.photoId)
    : -1;
  const previewMember = previewGroup && previewIndex >= 0 ? previewOrderedMembers[previewIndex] : null;
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
    () => findScanForScope(scanHistory, personId, includeCrossType, scanType),
    [includeCrossType, personId, scanHistory, scanType]
  );

  function personLabel(targetPersonId: number | null): string {
    if (targetPersonId === null) return "全部人物";
    return persons.find((person) => person.id === targetPersonId)?.display_name ?? `人物 #${targetPersonId}`;
  }

  function syncScopeFromScan(targetScan: GallerySimilarityScan) {
    setPersonId(targetScan.person_id);
    setPersonSearch(personLabel(targetScan.person_id));
    setIncludeCrossType(targetScan.include_cross_type);
    setScanType(targetScan.scan_type);
    if (targetScan.scan_type === "mirror") setTier("near_duplicate");
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
    selectResult(findScanForScope(scanHistory, nextPersonId, nextIncludeCrossType, scanType), false);
  }

  function selectScanType(nextScanType: "normal" | "mirror") {
    setScanType(nextScanType);
    if (nextScanType === "mirror") setTier("near_duplicate");
    setOffset(0);
    selectResult(findScanForScope(scanHistory, personId, includeCrossType, nextScanType), false);
  }

  function scanHistoryLabel(targetScan: GallerySimilarityScan): string {
    const scope = targetScan.include_cross_type ? "跨类型" : "分类型";
    const timestamp = formatDate(targetScan.completed_at || targetScan.created_at);
    const type = targetScan.scan_type === "mirror" ? "镜像相似" : "普通相似";
    return `${type} · ${personLabel(targetScan.person_id)} · ${scope} · ${timestamp} · ${targetScan.group_count} 组${targetScan.is_stale ? " · 已过期" : ""}`;
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
      return null;
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
    return response;
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

  async function navigateGroup(direction: "previous" | "next") {
    if (!resultScan || !previewGroup || busy) return;
    const currentIndex = groups.findIndex((group) => group.id === previewGroup.id);
    if (currentIndex < 0) return;
    const targetIndex = direction === "previous" ? currentIndex - 1 : currentIndex + 1;
    if (targetIndex >= 0 && targetIndex < groups.length) {
      const target = groups[targetIndex];
      const member = target.members[0];
      if (member) setPreview({ groupId: target.id, photoId: member.photo.id });
      return;
    }
    const nextOffset = direction === "previous" ? offset - pageSize : offset + pageSize;
    if (nextOffset < 0 || nextOffset >= total) return;
    const response = await loadGroups(resultScan, nextOffset, false);
    const target = direction === "previous"
      ? response?.items[response.items.length - 1]
      : response?.items[0];
    const member = target?.members[0];
    if (target && member) setPreview({ groupId: target.id, photoId: member.photo.id });
  }

  async function openNextGroupAfterCompletion(groupOrdinal: number) {
    if (!resultScan) {
      setPreview(null);
      return;
    }
    const response = await loadGroups(resultScan, offset, false);
    const target = response?.items.find((group) => group.ordinal > groupOrdinal) ?? null;
    if (target?.members[0]) {
      setPreview({ groupId: target.id, photoId: target.members[0].photo.id });
      return;
    }
    const nextOffset = response ? response.offset + pageSize : offset + pageSize;
    if (response && nextOffset < response.total) {
      const nextPage = await loadGroups(resultScan, nextOffset, false);
      const nextGroup = nextPage?.items[0];
      if (nextGroup?.members[0]) {
        setPreview({ groupId: nextGroup.id, photoId: nextGroup.members[0].photo.id });
        return;
      }
    }
    setPreview(null);
  }

  async function dismissGroup(group: GallerySimilarityGroup, advanceToNext = false) {
    if (!resultScan) return;
    setDismissingGroupIds((current) => [...current, group.id]);
    try {
      await updateGallerySimilarityGroup(resultScan.id, group.id, "dismissed");
      const groupPhotoIds = new Set(group.members.map((member) => member.photo.id));
      setSelectedIds((current) => current.filter((photoId) => !groupPhotoIds.has(photoId)));
      setNotice(`第 ${group.ordinal} 组已设为暂不处理，本次扫描中将不再显示。`);
      if (advanceToNext) {
        await openNextGroupAfterCompletion(group.ordinal);
      } else {
        await loadGroups(resultScan, offset, false);
      }
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
      message: `确认开始${scanType === "mirror" ? "镜像相似" : "普通相似"}图片扫描吗？\n\n扫描人物：${personLabel(personId)}\n匹配方式：${matchMode}\n\n扫描耗时较长，完成前会继续保留当前成功结果。`,
      confirmLabel: "开始扫描"
    });
    if (!confirmed) return;

    setBusy(true);
    setNotice(null);
    try {
      const created = await createGallerySimilarityScan({
        person_id: personId,
        include_cross_type: includeCrossType,
        scan_type: scanType
      });
      setActiveScan(created);
      setSelectedIds([]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "发起扫描失败");
    } finally {
      setBusy(false);
    }
  }

  async function openAutoDeletePreview() {
    if (!resultScan) return;
    setBusy(true);
    setNotice(null);
    try {
      const data = await previewNormalNearDuplicateAutoDelete(resultScan.id);
      setAutoDeletePreview(data);
      setPreviewOverrides({});
      setEnlargedPreviewContext(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "读取自动整理预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function autoDeleteCurrentExactMirrorGroups() {
    if (!resultScan || !await confirm({
      title: "自动整理 100% 镜像组",
      message: "将按系统建议保留图片；没有建议时保留唯一体积最大的图片，并永久删除其余图片。\n\n仅处理当前未过期结果中相似度为 100% 的镜像组。此操作不可撤销。",
      confirmLabel: "执行删除",
      tone: "danger"
    })) return;
    setBusy(true);
    try {
      const response = await autoDeleteExactMirrorGroups(resultScan.id);
      setResultScan(response.scan);
      setScanHistory((current) => current.map((scan) => scan.id === response.scan.id ? response.scan : scan));
      setNotice(`已自动整理删除 ${response.deleted} 张图片，累计自动删除 ${response.scan.auto_deleted_count} 张。`);
      await loadGroups(response.scan, 0);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "自动整理失败");
    } finally {
      setBusy(false);
    }
  }

  async function executeAutoDeleteFromPreview() {
    if (!resultScan || !autoDeletePreview || !await confirm({
      title: "确认自动整理",
      message: `将按当前预览方案永久删除 ${previewDeleteIds.length} 张图片，原图也会被删除，此操作不可撤销。`,
      confirmLabel: "执行删除",
      tone: "danger"
    })) return;
    setBusy(true);
    try {
      const response = await autoDeleteExactMirrorGroups(resultScan.id, previewDeleteIds);
      setAutoDeletePreview(null);
      setResultScan(response.scan);
      setScanHistory((current) => current.map((scan) => scan.id === response.scan.id ? response.scan : scan));
      setNotice(`已按预览方案删除 ${response.deleted} 张图片，累计自动删除 ${response.scan.auto_deleted_count} 张。`);
      await loadGroups(response.scan, 0);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "自动整理失败");
    } finally {
      setBusy(false);
    }
  }

  function effectiveMemberDeleted(member: GallerySimilarityAutoDeletePreviewMember): boolean {
    return previewOverrides[member.photo_id] ?? !member.retained;
  }

  function togglePreviewMember(
    cluster: GallerySimilarityAutoDeletePreviewCluster,
    member: GallerySimilarityAutoDeletePreviewMember
  ) {
    if (cluster.status !== "ready") return;
    setPreviewOverrides((current) => {
      const nextIsDeleted = !(current[member.photo_id] ?? !member.retained);
      const next = { ...current };
      if (!nextIsDeleted) {
        next[member.photo_id] = false;
        return next;
      }
      // 每簇至少保留一张：翻转后若整簇都被标记删除则拒绝。
      const wouldKeepNone = cluster.members.every((item) =>
        item.photo_id === member.photo_id ? true : current[item.photo_id] ?? !item.retained
      );
      if (wouldKeepNone) return current;
      next[member.photo_id] = true;
      return next;
    });
  }

  const orderedPreviewClusters = useMemo(() => {
    if (!autoDeletePreview) return [] as GallerySimilarityAutoDeletePreviewCluster[];
    const rank = (cluster: GallerySimilarityAutoDeletePreviewCluster) =>
      cluster.status !== "ready" ? 2 : clusterSizeWarningText(cluster) !== null ? 0 : 1;
    return [...autoDeletePreview.clusters].sort((a, b) => rank(a) - rank(b));
  }, [autoDeletePreview]);

  const previewDeleteIds = autoDeletePreview
    ? autoDeletePreview.clusters
        .filter((cluster) => cluster.status === "ready")
        .flatMap((cluster) =>
          cluster.members.filter((member) => effectiveMemberDeleted(member)).map((member) => member.photo_id)
        )
    : [];

  async function deleteSelected() {
    if (!selectedIds.length || !await confirm({ title: "删除相似图片", message: `确认删除选中的 ${selectedIds.length} 张图片（含其他页选中的图片）？原图也会被删除。`, confirmLabel: "删除", tone: "danger" })) return;
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
    const removesGroup = group.members.length - groupPhotoIds.length < 2;
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
      if (removesGroup) {
        await openNextGroupAfterCompletion(group.ordinal);
      } else {
        await refreshGroupsAfterDelete();
      }
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
      if (nextPhotoId && group.members.length - 1 >= 2) {
        await refreshGroupsAfterDelete({ groupId: group.id, photoId: nextPhotoId }, false);
      } else {
        await openNextGroupAfterCompletion(group.ordinal);
      }
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
        <div className="similarity-check-type" aria-label="相似检查类型">
          <button type="button" className={scanType === "normal" ? "active" : ""} onClick={() => selectScanType("normal")}>普通相似</button>
          <button type="button" className={scanType === "mirror" ? "active" : ""} onClick={() => selectScanType("mirror")}>镜像相似</button>
        </div>
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
            <span>{resultScan.scan_type === "mirror" ? "镜像相似" : "普通相似"} · {personLabel(resultScan.person_id)} · {resultScan.include_cross_type ? "跨类型" : "分类型"} · 完成于 {formatDate(resultScan.completed_at || resultScan.created_at)}</span>
          </div>
          <small>{resultScan.photo_count} 张图片 · {resultScan.candidate_pair_count} 个候选对 · {resultScan.group_count} 个相似组</small>
          {!resultScan.is_stale && resultScan.scan_type === "mirror" && (
            <button
              className="danger-button similarity-auto-delete-button"
              disabled={!canDelete || busy || Boolean(activeScan)}
              onClick={() => void autoDeleteCurrentExactMirrorGroups()}
            >
              <Trash2 size={15} /> 自动整理 100% 镜像组
            </button>
          )}
          {!resultScan.is_stale && resultScan.scan_type === "normal" && (
            <button
              className="similarity-auto-delete-button"
              disabled={!canDelete || busy || Boolean(activeScan)}
              onClick={() => void openAutoDeletePreview()}
            >
              <Layers size={15} /> 预览自动整理
            </button>
          )}
          {resultScan.auto_deleted_count > 0 && <small>累计自动删除 {resultScan.auto_deleted_count} 张图片</small>}
          {resultScan.is_stale && <b>图库内容已变化，当前结果可能过期</b>}
        </section>
      )}

      <section className="similarity-results">
        <div className="similarity-tabs">
          <button className={tier === "near_duplicate" ? "active" : ""} onClick={() => { setTier("near_duplicate"); setOffset(0); }}>近重复</button>
          {resultScan?.scan_type !== "mirror" && <button className={tier === "same_scene" ? "active" : ""} onClick={() => { setTier("same_scene"); setOffset(0); }}>同场景相似</button>}
          <span>{total} 组</span>
          <button className="danger-button" disabled={!canDelete || !selectedIds.length || busy} onClick={() => void deleteSelected()}>
            <Trash2 size={15} /> 删除选中（{selectedIds.length}）
          </button>
        </div>

        {groups.map((group) => {
          const sections = buildGroupSections(group);
          const renderMemberCard = (member: GallerySimilarityMember) => (
            <article
              className={`similarity-member ${member.recommended_keep ? "recommended" : ""} ${selectedIds.includes(member.photo.id) ? "selected" : ""}`}
              key={member.photo.id}
            >
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
              <div className="similarity-member-facts">
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
                <span>综合 {member.quality_score.toFixed(1)} · 整体 {member.overall_quality_score.toFixed(1)}{member.face_quality_score !== null ? ` · 人脸 ${member.face_quality_score.toFixed(1)}` : ""}</span>
                <span>文件大小 {formatBytes(member.photo.size_bytes)}</span>
              </div>
            </article>
          );
          return (
            <article className="panel similarity-group" key={group.id}>
              <header>
                <div className="similarity-group-title">
                  <strong>第 {group.ordinal} 组</strong>
                  <span>{group.people.map((person) => person.display_name).join("、")}</span>
                </div>
                <small>最低相似度 {(group.min_score * 100).toFixed(1)}%</small>
                <small>{group.recommendation_status === "close_quality" ? "质量接近，未强制推荐" : group.face_quality_enabled ? "整体 55% + 人脸 45%" : "仅按整体质量"}</small>
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
              {!sections && (
                <div className="similarity-member-grid">{group.members.map(renderMemberCard)}</div>
              )}
              {sections && sections.length === 0 && (
                <div className="similarity-member-grid">{group.members.map(renderMemberCard)}</div>
              )}
              {sections && sections.length > 0 && (
                <div className="similarity-cluster-list">
                  {sections.map((section) =>
                    section.cluster ? (
                      <section className="similarity-cluster-block" key={section.key}>
                        <header className="similarity-cluster-head">
                          <span className="similarity-cluster-badge">
                            <Layers size={13} aria-hidden="true" /> 几乎完全相同 · {section.members.length} 张
                          </span>
                          <small>
                            簇内相似度最低 {(section.cluster.min_pair_score * 100).toFixed(1)}% · 平均 {(section.cluster.average_pair_score * 100).toFixed(1)}%
                          </small>
                        </header>
                        <div className="similarity-member-grid">{section.members.map(renderMemberCard)}</div>
                      </section>
                    ) : (
                      <section className="similarity-scatter-block" key={section.key}>
                        <header className="similarity-cluster-head">
                          <span className="similarity-scatter-label">其他相似图片（未构成相同簇）</span>
                        </header>
                        <div className="similarity-member-grid">{section.members.map(renderMemberCard)}</div>
                      </section>
                    )
                  )}
                </div>
              )}
            </article>
          );
        })}
        {!busy && resultScan && groups.length === 0 && (
          <div className="panel empty-card"><Images size={30} /> 当前档位没有相似图片组。</div>
        )}
        {!resultScan && !busy && <div className="panel empty-card">当前范围没有成功扫描结果。可切换历史结果，或点击“开始扫描”。</div>}
        {total > pageSize && (
          <div className="pagination-row">
            <button disabled={offset === 0 || busy} onClick={() => void loadGroups(resultScan, Math.max(0, offset - pageSize), false)}>上一页</button>
            <span>{offset + 1} - {Math.min(offset + pageSize, total)} / {total}</span>
            <button disabled={offset + pageSize >= total || busy} onClick={() => void loadGroups(resultScan, offset + pageSize, false)}>下一页</button>
          </div>
        )}
      </section>
      {previewGroup && previewMember && (
        <PhotoLightbox
          shellClassName="similarity-review-lightbox"
          busy={deletingGroupIds.includes(previewGroup.id) || dismissingGroupIds.includes(previewGroup.id)}
          canGoPrevious={previewIndex > 0}
          canGoNext={previewIndex < previewOrderedMembers.length - 1}
          onClose={() => setPreview(null)}
          onPrevious={() => {
            const previous = previewOrderedMembers[previewIndex - 1];
            if (previous) setPreview({ groupId: previewGroup.id, photoId: previous.photo.id });
          }}
          onNext={() => {
            const next = previewOrderedMembers[previewIndex + 1];
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
            } else if (shortcut === "previous_group" || shortcut === "next_group") {
              event.preventDefault();
              void navigateGroup(shortcut === "previous_group" ? "previous" : "next");
            } else if (shortcut === "dismiss_group" && canEdit) {
              event.preventDefault();
              void dismissGroup(previewGroup, true);
            }
          }}
          meta={(
            <>
              <div className="lightbox-meta-head">
                <span>第 {previewGroup.ordinal} 组</span>
                <strong>{previewIndex + 1} / {previewOrderedMembers.length}</strong>
              </div>
              <div className="lightbox-meta-section similarity-review-strip-section">
                <span>组内图片</span>
                <div className="similarity-review-strip">
                  {previewOrderedMembers.map((member, index) => {
                    const isCurrent = member.photo.id === previewMember.photo.id;
                    const isSelected = selectedIds.includes(member.photo.id);
                    return (
                      <button
                        type="button"
                        className={`${isCurrent ? "current" : ""} ${isSelected ? "selected" : ""}`.trim()}
                        key={member.photo.id}
                        onClick={() => setPreview({ groupId: previewGroup.id, photoId: member.photo.id })}
                        aria-label={`查看第 ${index + 1} 张${isSelected ? "，已标记删除" : ""}${member.auto_cluster_index !== null ? `，属于相同簇 ${member.auto_cluster_index}` : "，散图"}`}
                        aria-current={isCurrent ? "true" : undefined}
                      >
                        <img src={withImageWidth(member.photo.thumbnail_url, 160)} alt="" />
                        <small>{index + 1}</small>
                        {member.auto_cluster_index !== null
                          ? <span className="strip-cluster-badge">簇 {member.auto_cluster_index}</span>
                          : <span className="strip-cluster-badge scattered">散</span>}
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
                  onClick={() => void dismissGroup(previewGroup, true)}
                >
                  {dismissingGroupIds.includes(previewGroup.id) ? "正在隐藏" : "暂不处理本组"}
                </button>
                <button type="button" className="ghost-button" onClick={() => setPreview(null)}>
                  <X size={17} aria-hidden="true" /> 关闭预览
                </button>
                <p className="similarity-review-shortcuts">
                  <kbd>←</kbd><kbd>→</kbd> 组内切换　<kbd>↑</kbd><kbd>↓</kbd> 切换组　<kbd>Space</kbd> 标记　<kbd>Delete</kbd> 删除当前　<kbd>P</kbd> 暂不处理本组　<kbd>Esc</kbd> 关闭
                </p>
              </div>
              <div className="lightbox-meta-section">
                <span>对比信息</span>
                <div className="similarity-lightbox-facts">
                  <b>{previewMember.photo.is_rich_text ? "图文图片" : "普通图片"}</b>
                  <b>文件大小 {formatBytes(previewMember.photo.size_bytes)}</b>
                  <b>相似度 {(previewMember.score_to_representative * 100).toFixed(1)}%</b>
                  <b>质量评分 综合 {previewMember.quality_score.toFixed(1)} · 整体 {previewMember.overall_quality_score.toFixed(1)}{previewMember.face_quality_score !== null ? ` · 人脸 ${previewMember.face_quality_score.toFixed(1)}` : ""}</b>
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
      {autoDeletePreview && (
        <div className="modal-backdrop similarity-preview-backdrop" onClick={() => setAutoDeletePreview(null)}>
          <section
            className="panel similarity-preview-modal"
            role="dialog"
            aria-label="自动整理预览"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="similarity-preview-head">
              <div className="similarity-preview-title">
                <strong>自动整理预览</strong>
                <span>
                  {previewDeleteIds.length > 0
                    ? `将永久删除 ${previewDeleteIds.length} 张几乎完全相同的图片；点击徽标可手动调整`
                    : "没有可自动删除的图片"}
                </span>
              </div>
              <button type="button" className="ghost-button" onClick={() => setAutoDeletePreview(null)}>
                <X size={15} /> 关闭
              </button>
            </header>
            {autoDeletePreview.skipped_cluster_count > 0 && (
              <p className="similarity-preview-skip">
                有 {autoDeletePreview.skipped_cluster_count} 个簇因跨组重叠或无法确定唯一保留图而跳过，不会删除。
              </p>
            )}
            <div className="similarity-preview-clusters">
              {orderedPreviewClusters.map((cluster, index) => {
                const warningText = clusterSizeWarningText(cluster);
                return (
                <section
                  className={`similarity-preview-cluster ${cluster.status === "ready" ? "" : "skipped"}`.trim()}
                  key={`${cluster.retained_photo_id ?? "none"}-${index}`}
                >
                  <header>
                    <strong>相同簇 {index + 1}</strong>
                    {cluster.status === "ready" && <span>删除 {cluster.members.filter((member) => effectiveMemberDeleted(member)).length} 张</span>}
                    {cluster.status === "skipped_overlap" && <span>跨组重叠，已跳过</span>}
                    {cluster.status === "skipped_no_retention" && <span>无法确定唯一保留图，已跳过</span>}
                    {warningText && (
                      <span className="similarity-size-warning" role="status">⚠ {warningText}</span>
                    )}
                  </header>
                  <div className="similarity-preview-strip">
                    {cluster.members.map((member, memberIndex) => {
                      const kept = !effectiveMemberDeleted(member);
                      return (
                      <figure
                        className={kept ? "retained" : "drop"}
                        key={member.photo_id}
                      >
                        <button
                          type="button"
                          className="similarity-preview-image-button"
                          onClick={() => setEnlargedPreviewContext({ members: cluster.members, index: memberIndex })}
                          aria-label={`大图查看 ${member.filename}，可左右翻页对比本簇图片`}
                        >
                          <img src={member.thumbnail_url} alt={member.filename} loading="lazy" />
                        </button>
                        <figcaption>
                          <button
                            type="button"
                            className={`badge-toggle ${kept ? "badge-keep" : "badge-drop"}`.trim()}
                            disabled={cluster.status !== "ready" || busy}
                            title={cluster.status === "ready" ? "点击切换保留/删除" : "该簇已跳过，不可调整"}
                            onClick={() => togglePreviewMember(cluster, member)}
                          >
                            {kept ? "保留" : "删除"}
                          </button>
                          <small>
                            质量 {member.quality_score.toFixed(1)}
                            {member.size_bytes !== null ? ` · ${formatBytes(member.size_bytes)}` : ""}
                          </small>
                        </figcaption>
                      </figure>
                      );
                    })}
                  </div>
                </section>
                );
              })}
              {autoDeletePreview.clusters.length === 0 && (
                <p className="similarity-preview-empty">当前结果中没有发现几乎完全相同的图片簇。</p>
              )}
            </div>
            <footer className="modal-actions">
              <button type="button" className="ghost-button" onClick={() => setAutoDeletePreview(null)}>
                取消
              </button>
              <button
                type="button"
                className="danger-button"
                disabled={busy || !canDelete || previewDeleteIds.length === 0}
                onClick={() => void executeAutoDeleteFromPreview()}
              >
                <Trash2 size={15} /> 确认删除（{previewDeleteIds.length} 张）
              </button>
            </footer>
          </section>
        </div>
      )}
      {enlargedPreviewContext && enlargedPreviewMember && (
        <PhotoLightbox
          backdropClassName="similarity-preview-lightbox-backdrop"
          canGoPrevious={enlargedPreviewContext.index > 0}
          canGoNext={enlargedPreviewContext.index < enlargedPreviewContext.members.length - 1}
          onClose={() => setEnlargedPreviewContext(null)}
          onPrevious={() =>
            setEnlargedPreviewContext((current) =>
              current ? { ...current, index: Math.max(0, current.index - 1) } : current
            )
          }
          onNext={() =>
            setEnlargedPreviewContext((current) =>
              current ? { ...current, index: Math.min(current.members.length - 1, current.index + 1) } : current
            )
          }
          meta={(
            <div className="lightbox-meta-section">
              <span>相同簇对比</span>
              <div className="lightbox-meta-head">
                <strong>{enlargedPreviewContext.index + 1} / {enlargedPreviewContext.members.length}</strong>
              </div>
              <div className="similarity-lightbox-facts">
                <b>{enlargedPreviewMember.retained ? "当前方案：保留这张" : "当前方案：删除这张"}</b>
                <b>文件大小 {enlargedPreviewMember.size_bytes !== null ? formatBytes(enlargedPreviewMember.size_bytes) : "未知"}</b>
                <b>质量评分 {enlargedPreviewMember.quality_score.toFixed(1)}</b>
              </div>
              <small className="similarity-preview-hint">←/→ 方向键在本簇内翻页对比</small>
            </div>
          )}
        >
          <img className="lightbox-image" src={enlargedPreviewMember.original_url} alt={enlargedPreviewMember.filename} />
        </PhotoLightbox>
      )}
    </main>
  );
}
