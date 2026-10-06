import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Archive, Check, CheckCheck, ChevronLeft, ChevronRight, Download, FolderPlus, Images, Link2, LoaderCircle, LogOut, Pencil, Play, Plus, RotateCcw, ScanSearch, Square, Trash2, Video, X } from "lucide-react";

import {
  acquisitionDownloadUrl,
  bindAcquisitionScript,
  changeAcquisitionAssets,
  createAcquisitionCategory,
  createAcquisitionExport,
  createTelegramChannel,
  createAcquisitionSource,
  deleteAcquisitionCategory,
  deleteAcquisitionSource,
  getAcquisitionAsset,
  getAcquisitionAssetSummary,
  getTelegramAccount,
  listTelegramDialogs,
  listTelegramTopics,
  scanTelegramForumTopics,
  listAcquisitionAssetIds,
  listAcquisitionAssets,
  listAcquisitionCategories,
  listAcquisitionExports,
  listAcquisitionImportBatchItems,
  listAcquisitionImportBatches,
  listAcquisitionRuns,
  listAcquisitionRunPage,
  listAcquisitionScripts,
  listAcquisitionSimilarity,
  listAcquisitionSources,
  listAcquisitionSourcePage,
  startAcquisitionRun,
  startAcquisitionSimilarityScan,
  stopAcquisitionRun,
  startTelegramLogin,
  resendTelegramLogin,
  cancelTelegramLogin,
  unbindAcquisitionScript,
  updateAcquisitionCategory,
  updateAcquisitionSource,
  verifyTelegramLogin,
  logoutTelegramAccount
} from "../api/acquisition";
import {
  acquisitionAssetPageSize,
  clampAcquisitionOffset,
  createAcquisitionStatusReset,
  getAcquisitionAssetPageOffset,
  getAcquisitionPageFill,
  getAcquisitionPreviewUrl,
  handleAcquisitionLightboxShortcut,
  getAcquisitionPagination,
  getNextAcquisitionSnapshotIndex,
  hasSelectedAllAcquisitionAssets,
  isAcquisitionImportBatchActive,
  isAcquisitionPageFillValid,
  isAcquisitionPageSelected,
  removeAcquisitionSelection,
  selectAcquisitionAssetRange,
  selectAcquisitionPage,
  deselectAcquisitionPage,
  toggleAcquisitionSelection
} from "../lib/acquisitionReview";
import {
  defaultAcquisitionRunParameters,
  getAcquisitionRunFormConfiguration,
  serializeAcquisitionRunParameters
} from "../lib/acquisitionRunForm";
import { canUsePluginCredential, requiresPluginCredential } from "../lib/acquisitionRunForm";
import { useConfirm } from "../components/ConfirmDialog";
import AcquisitionReviewLightbox from "../components/AcquisitionReviewLightbox";
import AcquisitionPluginsPanel from "../components/AcquisitionPluginsPanel";
import { listPluginCredentials, previewPlugin, type AcquisitionPluginCredential, type PluginPreviewItem } from "../api/acquisitionPlugins";
import PhotoLightbox from "../components/PhotoLightbox";
import type {
  AcquisitionAsset,
  AcquisitionCaptureResult,
  AcquisitionAssetSummary,
  AcquisitionCategory,
  AcquisitionExport,
  AcquisitionImportBatch,
  AcquisitionImportBatchItemDetail,
  AcquisitionRun,
  AcquisitionScript,
  AcquisitionSimilarityResult,
  AcquisitionSource,
  PaginatedAcquisitionAssets
} from "../types";
import type { TelegramAccount, TelegramDialog, TelegramForumScan, TelegramTopic } from "../types/telegram";
import { formatBytes, formatDate, formatDurationSeconds, toShanghaiDateTimeBoundary } from "../lib/utils";
import "./AcquisitionCenter.css";

type Tab = "sources" | "plugins" | "runs" | "review" | "history";

type AcquisitionCenterProps = {
  canEdit: boolean;
  canAdd: boolean;
  canDelete: boolean;
  canAdmin: boolean;
  canManageAccounts: boolean;
};

const tabs: Array<{ key: Tab; label: string }> = [
  { key: "sources", label: "站点与分类" },
  { key: "plugins", label: "采集插件" },
  { key: "runs", label: "运行" },
  { key: "review", label: "待审核" },
  { key: "history", label: "入库与导出" }
];

const importBatchPageSize = 15;
const importBatchItemPageSize = 40;
const similarityGroupPageSize = 12;
const managementPageSize = 10;

function statusLabel(status: string): string {
  return ({
    pending: "等待中", running: "运行中", completed: "已完成", interrupted: "已中断", failed: "失败",
    pending_review: "待审核", imported: "已入库", rejected: "已丢弃",
    import_queued: "等待入库", importing: "正在入库", import_failed: "入库失败",
    gallery_duplicate: "库中已存在", completed_with_errors: "部分失败", ready: "可下载", downloaded: "已下载", expired: "已过期"
  } as Record<string, string>)[status] ?? status;
}

function telegramDialogTitle(dialog: TelegramDialog): string {
  return dialog.title.replace(/\s*[·•]\s*(?:频道|群组|机器人|论坛)(?:\s*[·•]\s*(?:频道|群组|机器人|论坛))*\s*$/u, "").trim() || dialog.title;
}

function selectedTelegramMediaTypes(value: string | boolean | undefined): string[] {
  return String(value ?? "").split(",").map((item) => item.trim()).filter((item) => item === "image" || item === "video");
}

function telegramCategoryLabel(category: AcquisitionCategory): string {
  if (!category.telegram_topic_title || category.name.includes(category.telegram_topic_title)) return category.name;
  return `${category.name} / ${category.telegram_topic_title}`;
}

function runStopLabel(run: AcquisitionRun): string | null {
  if (run.status === "interrupted" && run.stop_reason === "requested_end") return "用户已停止";
  if (run.scan_start_page == null || run.scan_end_page == null) return null;
  const reason = ({
    collection_end: "已到网站末页",
    requested_end: "已到指定末页",
    known_page: "整页均已采集",
    empty_page: "页面为空"
  } as Record<string, string>)[run.stop_reason ?? ""];
  return `页码 ${run.scan_start_page}-${run.scan_end_page}${reason ? ` · ${reason}` : ""}`;
}

function findPreviewableIndexInDirection(assets: AcquisitionAsset[], start: number, step: -1 | 1): number {
  for (let index = start; index >= 0 && index < assets.length; index += step) {
    if (assets[index].preview_url) return index;
  }
  return -1;
}

async function settleRequest<T>(request: Promise<T>): Promise<{ data: T | null; error: Error | null }> {
  try {
    return { data: await request, error: null };
  } catch (error) {
    return { data: null, error: error instanceof Error ? error : new Error(String(error)) };
  }
}

export default function AcquisitionCenter({ canEdit, canAdd, canDelete, canAdmin, canManageAccounts }: AcquisitionCenterProps) {
  const confirm = useConfirm();
  const [tab, setTab] = useState<Tab>("sources");
  const [sources, setSources] = useState<AcquisitionSource[]>([]);
  const [categories, setCategories] = useState<AcquisitionCategory[]>([]);
  const [scripts, setScripts] = useState<AcquisitionScript[]>([]);
  const [runCredentials, setRunCredentials] = useState<AcquisitionPluginCredential[]>([]);
  const [runCredentialId, setRunCredentialId] = useState("");
  const [previewItems, setPreviewItems] = useState<PluginPreviewItem[]>([]);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [runs, setRuns] = useState<AcquisitionRun[]>([]);
  const [sourcePageItems, setSourcePageItems] = useState<AcquisitionSource[]>([]);
  const [sourcePageTotal, setSourcePageTotal] = useState(0);
  const [sourcePageOffset, setSourcePageOffset] = useState(0);
  const [sourcePageLoading, setSourcePageLoading] = useState(false);
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null);
  const [categoryPageOffset, setCategoryPageOffset] = useState(0);
  const [runPageItems, setRunPageItems] = useState<AcquisitionRun[]>([]);
  const [runPageTotal, setRunPageTotal] = useState(0);
  const [runPageOffset, setRunPageOffset] = useState(0);
  const [runPageLoading, setRunPageLoading] = useState(false);
  const [assets, setAssets] = useState<AcquisitionAsset[]>([]);
  const [assetsTotal, setAssetsTotal] = useState(0);
  const [assetOffset, setAssetOffset] = useState(0);
  const [assetJumpPage, setAssetJumpPage] = useState("");
  const [assetLoading, setAssetLoading] = useState(false);
  const [lightboxSelection, setLightboxSelection] = useState<{ asset: AcquisitionAsset; globalIndex: number } | null>(null);
  const [lightboxSnapshotIds, setLightboxSnapshotIds] = useState<string[]>([]);
  const [lightboxSnapshotIndex, setLightboxSnapshotIndex] = useState(-1);
  const [lightboxNavigationBusy, setLightboxNavigationBusy] = useState(false);
  const [assetSummary, setAssetSummary] = useState<AcquisitionAssetSummary>({ total: 0, status_counts: {} });
  const [importBatches, setImportBatches] = useState<AcquisitionImportBatch[]>([]);
  const [importBatchesTotal, setImportBatchesTotal] = useState(0);
  const [importBatchOffset, setImportBatchOffset] = useState(0);
  const [unassignedImportedCount, setUnassignedImportedCount] = useState(0);
  const [selectedImportBatchId, setSelectedImportBatchId] = useState<string | null>(null);
  const [importBatchItems, setImportBatchItems] = useState<AcquisitionImportBatchItemDetail[]>([]);
  const [importBatchItemsTotal, setImportBatchItemsTotal] = useState(0);
  const [importBatchItemOffset, setImportBatchItemOffset] = useState(0);
  const [importBatchItemStatus, setImportBatchItemStatus] = useState("all");
  const [expandedImportAssetId, setExpandedImportAssetId] = useState<string | null>(null);
  const [importHistoryLoading, setImportHistoryLoading] = useState(false);
  const [exports, setExports] = useState<AcquisitionExport[]>([]);
  const [reviewMode, setReviewMode] = useState<"list" | "similarity">("list");
  const [similarityScanType, setSimilarityScanType] = useState<"normal" | "mirror">("normal");
  const [similarityScope, setSimilarityScope] = useState<"pending_only" | "pending_to_gallery">("pending_only");
  const [similarity, setSimilarity] = useState<AcquisitionSimilarityResult>({
    scan_type: "normal", scope: "pending_only", task: null, generated_at: null, is_stale: false, groups: [], total: 0, offset: 0, limit: similarityGroupPageSize
  });
  const [similarityOffset, setSimilarityOffset] = useState(0);
  const [similarityLoading, setSimilarityLoading] = useState(false);
  const [similarityLightbox, setSimilarityLightbox] = useState<{ groupId: string; assetId: string } | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [lastSelectedReviewAssetId, setLastSelectedReviewAssetId] = useState<string | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceNotes, setSourceNotes] = useState("");
  const [sourceScriptKey, setSourceScriptKey] = useState("");
  const [editingSourceId, setEditingSourceId] = useState<number | null>(null);
  const [telegramCredentialEditing, setTelegramCredentialEditing] = useState(false);
  const [sourceScriptChoices, setSourceScriptChoices] = useState<Record<number, string>>({});
  const [categorySourceId, setCategorySourceId] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const categoryNameTouchedRef = useRef(false);
  const [categoryUrl, setCategoryUrl] = useState("");
  const [categoryNotes, setCategoryNotes] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [runCategoryId, setRunCategoryId] = useState("");
  const [runScriptKey, setRunScriptKey] = useState("");
  const [runParameters, setRunParameters] = useState<Record<string, string | boolean>>({});
  const [telegramAccount, setTelegramAccount] = useState<TelegramAccount | null>(null);
  const [telegramDialogs, setTelegramDialogs] = useState<TelegramDialog[]>([]);
  const [telegramTopics, setTelegramTopics] = useState<TelegramTopic[]>([]);
  const [telegramDialogLoading, setTelegramDialogLoading] = useState(false);
  const [telegramDialogError, setTelegramDialogError] = useState<string | null>(null);
  const [telegramDialogRetry, setTelegramDialogRetry] = useState(0);
  const telegramDialogLoadKeyRef = useRef<string | null>(null);
  const pluginsRefreshRef = useRef<(() => Promise<void>) | null>(null);
  const [telegramTopicLoading, setTelegramTopicLoading] = useState(false);
  const [telegramTopicError, setTelegramTopicError] = useState<string | null>(null);
  const [telegramTargetMode, setTelegramTargetMode] = useState<"dialog" | "manual">("dialog");
  const [telegramDialogPeerId, setTelegramDialogPeerId] = useState("");
  const [telegramTopicId, setTelegramTopicId] = useState("");
  const [telegramTopicTitle, setTelegramTopicTitle] = useState("");
  const [telegramManualScan, setTelegramManualScan] = useState<Omit<TelegramForumScan, "topics"> | null>(null);
  const [telegramMediaTypes, setTelegramMediaTypes] = useState<string[]>(["image", "video"]);
  const [telegramCollectComments, setTelegramCollectComments] = useState(false);
  const [telegramApiId, setTelegramApiId] = useState("");
  const [telegramApiHash, setTelegramApiHash] = useState("");
  const [telegramPhone, setTelegramPhone] = useState("");
  const [telegramCode, setTelegramCode] = useState("");
  const [telegramPassword, setTelegramPassword] = useState("");
  const [runMode, setRunMode] = useState<"incremental" | "full" | "verify">("incremental");
  const [assetStatus, setAssetStatus] = useState("pending_review");
  const [mediaFilter, setMediaFilter] = useState<"all" | "image" | "video">("all");
  const [importAsRichText, setImportAsRichText] = useState(false);
  const [assetActionBusy, setAssetActionBusy] = useState(false);
  const [runSubmitting, setRunSubmitting] = useState(false);
  const [currentTabRefreshing, setCurrentTabRefreshing] = useState(false);
  const [exportScope, setExportScope] = useState<"all" | "source" | "category" | "run">("all");
  const [exportScopeId, setExportScopeId] = useState("");
  const [batchDateFrom, setBatchDateFrom] = useState("");
  const [batchDateTo, setBatchDateTo] = useState("");
  const [exportDateFrom, setExportDateFrom] = useState("");
  const [exportDateTo, setExportDateTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const assetRequestIdRef = useRef(0);
  const lightboxSnapshotRequestIdRef = useRef(0);
  const lightboxAssetCacheRef = useRef(new Map<string, AcquisitionAsset>());
  const unavailableLightboxAssetIdsRef = useRef(new Set<string>());
  const lightboxRejectPendingRef = useRef(false);
  const reviewReconcileNeededRef = useRef(false);
  const runLauncherRef = useRef<HTMLDivElement>(null);

  const sourceById = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const categoryById = useMemo(() => new Map(categories.map((category) => [category.id, category])), [categories]);
  const scriptByKey = useMemo(() => new Map(scripts.map((script) => [script.key, script])), [scripts]);
  const selectedRunCategory = categoryById.get(Number(runCategoryId));
  const selectedRunSource = selectedRunCategory ? sourceById.get(selectedRunCategory.source_id) : undefined;
  const availableRunScripts = useMemo(() => selectedRunSource
    ? selectedRunSource.script_keys.map((key) => scriptByKey.get(key)).filter((script): script is AcquisitionScript => Boolean(script))
    : [], [scriptByKey, selectedRunSource]);
  const selectedRunScript = scriptByKey.get(runScriptKey);
  const runRequiresCredential = requiresPluginCredential(selectedRunScript?.credentials);
  const runCredentialUsable = canUsePluginCredential(selectedRunScript?.credentials, runCredentialId, runCredentials);
  useEffect(() => {
    if (!runScriptKey || !selectedRunScript?.credentials?.length) { setRunCredentials([]); setRunCredentialId(""); return; }
    let cancelled = false;
    void listPluginCredentials(runScriptKey).then((items) => {
      if (cancelled) return;
      setRunCredentials(items);
      setRunCredentialId((current) => items.some((item) => String(item.id) === current) ? current : runRequiresCredential && items.length === 1 && items[0].status === "valid" ? String(items[0].id) : "");
    }).catch(() => { if (!cancelled) { setRunCredentials([]); setRunCredentialId(""); } });
    return () => { cancelled = true; };
  }, [runScriptKey, selectedRunScript?.version, selectedRunScript?.credentials?.length, runRequiresCredential, tab]);
  const selectedSourceCategories = useMemo(
    () => selectedSourceId == null ? [] : categories.filter((category) => category.source_id === selectedSourceId),
    [categories, selectedSourceId]
  );
  const categoryPageTotal = selectedSourceCategories.length;
  const categoryPageItems = selectedSourceCategories.slice(categoryPageOffset, categoryPageOffset + managementPageSize);
  const assetPagination = getAcquisitionPagination(assetsTotal, assetOffset, assets.length, acquisitionAssetPageSize);
  const sourcePagePagination = getAcquisitionPagination(sourcePageTotal, sourcePageOffset, sourcePageItems.length, managementPageSize);
  const categoryPagePagination = getAcquisitionPagination(categoryPageTotal, categoryPageOffset, categoryPageItems.length, managementPageSize);
  const runPagePagination = getAcquisitionPagination(runPageTotal, runPageOffset, runPageItems.length, managementPageSize);
  const areAllReviewAssetsSelected = hasSelectedAllAcquisitionAssets(selectedAssets, assetsTotal);
  const reviewPageAssetIds = assets.map((asset) => asset.id);
  const areCurrentReviewPageSelected = isAcquisitionPageSelected(selectedAssets, reviewPageAssetIds);
  const lightboxAsset = lightboxSelection?.asset ?? null;
  const lightboxGlobalIndex = lightboxSnapshotIndex;
  const canGoToPreviousAsset = lightboxSnapshotIndex > 0;
  const canGoToNextAsset = lightboxSnapshotIndex >= 0 && lightboxSnapshotIndex + 1 < lightboxSnapshotIds.length;
  const importBatchPagination = getAcquisitionPagination(importBatchesTotal, importBatchOffset, importBatches.length, importBatchPageSize);
  const importBatchItemPagination = getAcquisitionPagination(importBatchItemsTotal, importBatchItemOffset, importBatchItems.length, importBatchItemPageSize);
  const similarityPagination = getAcquisitionPagination(similarity.total, similarity.offset, similarity.groups.length, similarityGroupPageSize);
  const similarityLightboxGroup = similarityLightbox
    ? similarity.groups.find((group) => group.id === similarityLightbox.groupId) ?? null
    : null;
  const similarityLightboxIndex = similarityLightboxGroup && similarityLightbox
    ? similarityLightboxGroup.members.findIndex((asset) => asset.id === similarityLightbox.assetId)
    : -1;
  const similarityLightboxAsset = similarityLightboxGroup && similarityLightboxIndex >= 0
    ? similarityLightboxGroup.members[similarityLightboxIndex]
    : null;

  const refreshReferenceData = useCallback(async () => {
    const [scriptsResult, sourcesResult, categoriesResult, runsResult, exportsResult, summaryResult, telegramResult] = await Promise.all([
      settleRequest(listAcquisitionScripts()), settleRequest(listAcquisitionSources()),
      settleRequest(listAcquisitionCategories()), settleRequest(listAcquisitionRuns()),
      settleRequest(listAcquisitionExports()), settleRequest(getAcquisitionAssetSummary()), settleRequest(getTelegramAccount())
    ]);
    if (scriptsResult.data) setScripts(scriptsResult.data);
    if (sourcesResult.data) {
      setSources(sourcesResult.data);
      setCategorySourceId((current) => current || (sourcesResult.data?.[0] ? String(sourcesResult.data[0].id) : ""));
      setSelectedSourceId((current) => current != null && sourcesResult.data?.some((source) => source.id === current)
        ? current
        : sourcesResult.data?.[0]?.id ?? null);
    }
    if (categoriesResult.data) {
      setCategories(categoriesResult.data);
      setRunCategoryId((current) => categoriesResult.data?.some((category) => String(category.id) === current) ? current : "");
    }
    if (runsResult.data) setRuns(runsResult.data);
    if (exportsResult.data) setExports(exportsResult.data);
    if (summaryResult.data) setAssetSummary(summaryResult.data);
    if (telegramResult.data !== undefined) setTelegramAccount(telegramResult.data);
    const failed = [scriptsResult, sourcesResult, categoriesResult, runsResult, exportsResult, summaryResult, telegramResult]
      .find((result) => result.error);
    if (failed?.error) throw failed.error;
  }, []);

  const loadSourcePage = useCallback(async (requestedOffset: number) => {
    setSourcePageLoading(true);
    try {
      let page = await listAcquisitionSourcePage(Math.max(0, requestedOffset), managementPageSize);
      const validOffset = clampAcquisitionOffset(page.total, requestedOffset, managementPageSize);
      if (validOffset !== page.offset) page = await listAcquisitionSourcePage(validOffset, managementPageSize);
      setSourcePageItems(page.items);
      setSourcePageTotal(page.total);
      setSourcePageOffset(page.offset);
      setSelectedSourceId((current) => page.items.some((source) => source.id === current) ? current : page.items[0]?.id ?? null);
    } finally {
      setSourcePageLoading(false);
    }
  }, []);

  const loadRunPage = useCallback(async (requestedOffset: number) => {
    setRunPageLoading(true);
    try {
      let page = await listAcquisitionRunPage(Math.max(0, requestedOffset), managementPageSize);
      const validOffset = clampAcquisitionOffset(page.total, requestedOffset, managementPageSize);
      if (validOffset !== page.offset) page = await listAcquisitionRunPage(validOffset, managementPageSize);
      setRunPageItems(page.items);
      setRunPageTotal(page.total);
      setRunPageOffset(page.offset);
    } finally {
      setRunPageLoading(false);
    }
  }, []);

  const loadImportBatchPage = useCallback(async (requestedOffset: number) => {
    setImportHistoryLoading(true);
    try {
      let page = await listAcquisitionImportBatches(Math.max(0, requestedOffset), importBatchPageSize, batchDateFrom, batchDateTo);
      const validOffset = clampAcquisitionOffset(page.total, requestedOffset, importBatchPageSize);
      if (validOffset !== page.offset) {
        page = await listAcquisitionImportBatches(validOffset, importBatchPageSize, batchDateFrom, batchDateTo);
      }
      setImportBatches(page.items);
      setImportBatchesTotal(page.total);
      setImportBatchOffset(page.offset);
      setUnassignedImportedCount(page.unassigned_imported_count);
      setSelectedImportBatchId((current) => {
        if (current === "unassigned" && page.unassigned_imported_count > 0) return current;
        if (page.items.some((batch) => batch.id === current)) return current;
        return page.items[0]?.id ?? (page.unassigned_imported_count > 0 ? "unassigned" : null);
      });
    } finally {
      setImportHistoryLoading(false);
    }
  }, [batchDateFrom, batchDateTo]);

  const loadImportBatchItemPage = useCallback(async (batchId: string, requestedOffset: number) => {
    setImportHistoryLoading(true);
    try {
      let page = await listAcquisitionImportBatchItems(batchId, importBatchItemStatus, Math.max(0, requestedOffset), importBatchItemPageSize, batchDateFrom, batchDateTo);
      const validOffset = clampAcquisitionOffset(page.total, requestedOffset, importBatchItemPageSize);
      if (validOffset !== page.offset) {
        page = await listAcquisitionImportBatchItems(batchId, importBatchItemStatus, validOffset, importBatchItemPageSize, batchDateFrom, batchDateTo);
      }
      setImportBatchItems(page.items);
      setImportBatchItemsTotal(page.total);
      setImportBatchItemOffset(page.offset);
      setExpandedImportAssetId((current) => page.items.some((item) => item.asset_id === current) ? current : null);
    } finally {
      setImportHistoryLoading(false);
    }
  }, [batchDateFrom, batchDateTo, importBatchItemStatus]);

  const loadAssetPage = useCallback(async (
    status: string,
    requestedOffset: number,
    showLoading = true,
    pageMediaFilter: "all" | "image" | "video" = mediaFilter
  ): Promise<PaginatedAcquisitionAssets | null> => {
    const requestId = assetRequestIdRef.current + 1;
    assetRequestIdRef.current = requestId;
    if (showLoading) setAssetLoading(true);
    try {
      const mediaType = pageMediaFilter === "all" ? undefined : pageMediaFilter;
      let page = await listAcquisitionAssets(status, Math.max(0, requestedOffset), acquisitionAssetPageSize, mediaType);
      const validOffset = clampAcquisitionOffset(page.total, requestedOffset, acquisitionAssetPageSize);
      if (validOffset !== page.offset) {
        page = await listAcquisitionAssets(status, validOffset, acquisitionAssetPageSize, mediaType);
      }
      if (requestId !== assetRequestIdRef.current) return null;
      setAssets(page.items);
      setAssetsTotal(page.total);
      setAssetOffset(page.offset);
      return page;
    } finally {
      if (requestId === assetRequestIdRef.current) setAssetLoading(false);
    }
  }, [mediaFilter]);

  const reconcileAssetPageAfterRemoval = useCallback(async (
    remainingAssets: AcquisitionAsset[],
    remainingTotal: number
  ): Promise<PaginatedAcquisitionAssets | null> => {
    const localPage: PaginatedAcquisitionAssets = {
      items: remainingAssets,
      total: remainingTotal,
      offset: assetOffset,
      limit: acquisitionAssetPageSize
    };
    const fill = getAcquisitionPageFill(remainingAssets.length, assetOffset, remainingTotal);
    if (!fill) {
      if (remainingAssets.length === 0 && remainingTotal > 0) {
        return loadAssetPage(assetStatus, assetOffset, false);
      }
      setAssets(remainingAssets);
      setAssetsTotal(remainingTotal);
      return localPage;
    }

    const requestId = assetRequestIdRef.current + 1;
    assetRequestIdRef.current = requestId;
    setAssets(remainingAssets);
    setAssetsTotal(remainingTotal);
    try {
      const mediaType = mediaFilter === "all" ? undefined : mediaFilter;
      const fillPage = await listAcquisitionAssets(assetStatus, fill.offset, fill.limit, mediaType);
      if (requestId !== assetRequestIdRef.current) return null;
      if (!isAcquisitionPageFillValid(
        remainingAssets.map((asset) => asset.id),
        remainingTotal,
        fill,
        fillPage
      )) {
        throw new Error("审核素材列表已发生变化");
      }
      const page = { ...localPage, items: [...remainingAssets, ...fillPage.items] };
      setAssets(page.items);
      setAssetsTotal(page.total);
      return page;
    } catch {
      if (requestId !== assetRequestIdRef.current) return null;
      try {
        return await loadAssetPage(assetStatus, assetOffset, false);
      } catch {
        throw new Error("审核素材列表刷新失败");
      }
    }
  }, [assetOffset, assetStatus, loadAssetPage, mediaFilter]);

  const loadSimilarityPage = useCallback(async (requestedOffset: number): Promise<AcquisitionSimilarityResult> => {
    setSimilarityLoading(true);
    try {
      let result = await listAcquisitionSimilarity(Math.max(0, requestedOffset), similarityGroupPageSize, similarityScanType, similarityScope);
      const validOffset = clampAcquisitionOffset(result.total, requestedOffset, similarityGroupPageSize);
      if (validOffset !== result.offset) {
        result = await listAcquisitionSimilarity(validOffset, similarityGroupPageSize, similarityScanType, similarityScope);
      }
      setSimilarity(result);
      setSimilarityOffset(result.offset);
      setSimilarityLightbox((current) => {
        if (!current) return null;
        const group = result.groups.find((item) => item.id === current.groupId);
        if (!group) return null;
        if (group.members.some((asset) => asset.id === current.assetId)) return current;
        const nextAsset = group.members[0];
        return nextAsset ? { groupId: group.id, assetId: nextAsset.id } : null;
      });
      return result;
    } finally {
      setSimilarityLoading(false);
    }
  }, [similarityScanType, similarityScope]);

  const refreshCurrentTab = useCallback(async () => {
    setCurrentTabRefreshing(true);
    try {
      if (tab === "sources") {
        await Promise.all([
          refreshReferenceData(),
          loadSourcePage(sourcePageOffset)
        ]);
        return;
      }
      if (tab === "runs") {
        await Promise.all([refreshReferenceData(), loadRunPage(runPageOffset)]);
        return;
      }
      if (tab === "review") {
        const requests: Promise<unknown>[] = [
          getAcquisitionAssetSummary().then((summary) => setAssetSummary(summary))
        ];
        if (reviewMode === "similarity") requests.push(loadSimilarityPage(similarityOffset));
        else if (!lightboxSelection) requests.push(loadAssetPage(assetStatus, assetOffset, false));
        await Promise.all(requests);
        return;
      }
      if (tab === "plugins") {
        await pluginsRefreshRef.current?.();
        return;
      }
      const requests: Promise<unknown>[] = [
        refreshReferenceData(),
        loadImportBatchPage(importBatchOffset)
      ];
      if (selectedImportBatchId) requests.push(loadImportBatchItemPage(selectedImportBatchId, importBatchItemOffset));
      await Promise.all(requests);
    } finally {
      setCurrentTabRefreshing(false);
    }
  }, [assetOffset, assetStatus, importBatchItemOffset, importBatchOffset, lightboxSelection, loadAssetPage, loadImportBatchItemPage, loadImportBatchPage, loadRunPage, loadSimilarityPage, loadSourcePage, refreshReferenceData, reviewMode, runPageOffset, selectedImportBatchId, similarityOffset, sourcePageOffset, tab]);

  useEffect(() => { void refreshReferenceData().catch((error: Error) => setNotice(error.message)); }, [refreshReferenceData]);

  useEffect(() => {
    const selectedSource = sourceById.get(Number(categorySourceId));
    const isTelegramCategory = selectedSource?.page_format_key === "telegram-channel-v1";
    if (!isTelegramCategory) {
      telegramDialogLoadKeyRef.current = null;
      setTelegramDialogPeerId("");
      setTelegramTopics([]);
      setTelegramTopicError(null);
      setTelegramDialogError(null);
      return;
    }
    if (telegramAccount?.status !== "active") return;
    const loadKey = `${telegramAccount.telegram_user_id ?? telegramAccount.phone_masked ?? "active"}:${categorySourceId}`;
    if (telegramDialogLoadKeyRef.current === loadKey) return;
    telegramDialogLoadKeyRef.current = loadKey;
    let cancelled = false;
    setTelegramDialogLoading(true);
    setTelegramDialogError(null);
    void listTelegramDialogs()
      .then((items) => { if (!cancelled) setTelegramDialogs(items); })
      .catch((error: Error) => { if (!cancelled) setTelegramDialogError(error.message); })
      .finally(() => { if (!cancelled) setTelegramDialogLoading(false); });
    return () => { cancelled = true; };
  }, [categorySourceId, sourceById, telegramAccount?.phone_masked, telegramAccount?.status, telegramAccount?.telegram_user_id, telegramDialogRetry]);

  useEffect(() => {
    if (telegramTargetMode !== "dialog") return;
    if (!telegramDialogPeerId) { setTelegramTopics([]); setTelegramTopicError(null); return; }
    const dialog = telegramDialogs.find((item) => item.peer_id === telegramDialogPeerId);
    if (!dialog || dialog.entity_type === "bot" || !dialog.is_forum) { setTelegramTopics([]); setTelegramTopicError(null); return; }
    let cancelled = false;
    setTelegramTopicLoading(true);
    setTelegramTopicError(null);
    void listTelegramTopics(telegramDialogPeerId)
      .then((items) => { if (!cancelled) setTelegramTopics(items); })
      .catch((error: Error) => { if (!cancelled) { setTelegramTopics([]); setTelegramTopicError(error.message); } })
      .finally(() => { if (!cancelled) setTelegramTopicLoading(false); });
    return () => { cancelled = true; };
  }, [telegramDialogPeerId, telegramDialogs, telegramTargetMode]);

  useEffect(() => {
    if (editingCategoryId != null || telegramTargetMode !== "dialog" || !telegramDialogPeerId) return;
    const dialog = telegramDialogs.find((item) => item.peer_id === telegramDialogPeerId);
    if (!dialog || categoryNameTouchedRef.current) return;
    setCategoryName(telegramDialogTitle(dialog));
  }, [editingCategoryId, telegramDialogPeerId, telegramDialogs, telegramTargetMode]);

  useEffect(() => {
    if (tab !== "sources") return;
    void loadSourcePage(sourcePageOffset).catch((error: Error) => setNotice(error.message));
  }, [loadSourcePage, sourcePageOffset, tab]);

  useEffect(() => {
    if (selectedSourceId == null) {
      setCategoryPageOffset(0);
      return;
    }
    setCategoryPageOffset((current) => Math.min(current, Math.max(0, Math.floor((selectedSourceCategories.length - 1) / managementPageSize) * managementPageSize)));
  }, [selectedSourceCategories.length, selectedSourceId]);

  useEffect(() => {
    if (tab !== "runs") return;
    void loadRunPage(runPageOffset).catch((error: Error) => setNotice(error.message));
  }, [loadRunPage, runPageOffset, tab]);

  useEffect(() => {
    if (tab !== "review" || reviewMode !== "similarity") return;
    void loadSimilarityPage(similarityOffset).catch((error: Error) => setNotice(error.message));
  }, [loadSimilarityPage, reviewMode, similarityOffset, tab]);

  useEffect(() => {
    if (tab !== "review" || reviewMode !== "list") return;
    void loadAssetPage(assetStatus, 0).catch((error: Error) => setNotice(error.message));
  }, [assetStatus, loadAssetPage, mediaFilter, reviewMode, tab]);

  useEffect(() => {
    if (tab !== "history") return;
    void loadImportBatchPage(importBatchOffset).catch((error: Error) => setNotice(error.message));
  }, [importBatchOffset, loadImportBatchPage, tab]);

  useEffect(() => {
    if (tab !== "history") return;
    if (!selectedImportBatchId) {
      setImportBatchItems([]);
      setImportBatchItemsTotal(0);
      return;
    }
    void loadImportBatchItemPage(selectedImportBatchId, importBatchItemOffset)
      .catch((error: Error) => setNotice(error.message));
  }, [importBatchItemOffset, loadImportBatchItemPage, selectedImportBatchId, tab]);

  useEffect(() => {
    if (tab !== "runs" || !runPageItems.some((run) => run.status === "pending" || run.status === "running")) return;
    const timer = window.setInterval(() => {
      void Promise.all([listAcquisitionRuns(), loadRunPage(runPageOffset)])
        .then(([nextRuns]) => setRuns(nextRuns))
        .catch((error: Error) => setNotice(error.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [loadRunPage, runPageItems, runPageOffset, tab]);

  useEffect(() => {
    if (!importBatches.some((batch) => isAcquisitionImportBatchActive(batch.status))) return;
    const timer = window.setInterval(() => {
      const requests: Promise<unknown>[] = [
        loadImportBatchPage(importBatchOffset),
        getAcquisitionAssetSummary().then((summary) => setAssetSummary(summary))
      ];
      if (tab === "history" && selectedImportBatchId) {
        requests.push(loadImportBatchItemPage(selectedImportBatchId, importBatchItemOffset));
      }
      void Promise.all(requests).catch((error: Error) => setNotice(error.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [importBatchItemOffset, importBatchOffset, importBatches, loadImportBatchItemPage, loadImportBatchPage, selectedImportBatchId, tab]);

  useEffect(() => {
    if (tab !== "review" || reviewMode !== "similarity" || !similarity.task || !["pending", "running"].includes(similarity.task.status)) return;
    const timer = window.setInterval(() => {
      void loadSimilarityPage(similarityOffset).catch((error: Error) => setNotice(error.message));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [loadSimilarityPage, reviewMode, similarity.task, similarityOffset, tab]);

  useEffect(() => {
    if (availableRunScripts.some((script) => script.key === runScriptKey)) return;
    const fallback = availableRunScripts[0];
    setRunScriptKey(fallback?.key ?? "");
    setRunParameters(defaultAcquisitionRunParameters(fallback));
  }, [availableRunScripts, runScriptKey]);

  async function perform(action: () => Promise<void>, message: string) {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      setNotice(message);
      await refreshCurrentTab();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作未完成");
    } finally {
      setBusy(false);
    }
  }

  async function performSelectedAssetAction(action: "import" | "reject", message: string) {
    const assetIds = [...selectedAssets];
    if (!assetIds.length) return;
    const processed = new Set(assetIds);
    const remainingAssets = assets.filter((asset) => !processed.has(asset.id));
    const remainingTotal = Math.max(0, assetsTotal - assetIds.length);
    if (action === "import") {
      setAssetActionBusy(true);
      setNotice(null);
      try {
        await changeAcquisitionAssets("import", assetIds, importAsRichText);
        setSelectedAssets((current) => removeAcquisitionSelection(current, assetIds));
        setAssetSummary((current) => {
          const statusCounts = { ...current.status_counts };
          statusCounts[assetStatus] = Math.max(0, (statusCounts[assetStatus] ?? 0) - assetIds.length);
          statusCounts.import_queued = (statusCounts.import_queued ?? 0) + assetIds.length;
          return { ...current, status_counts: statusCounts };
        });
        try {
          await Promise.all([
            reconcileAssetPageAfterRemoval(remainingAssets, remainingTotal),
            loadImportBatchPage(importBatchOffset)
          ]);
          setNotice(message);
        } catch {
          setNotice(`${message}，但列表补位失败`);
        }
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "素材入库失败");
      } finally {
        setAssetActionBusy(false);
      }
      return;
    }
    setAssetActionBusy(true);
    setNotice(null);
    try {
      await changeAcquisitionAssets(action, assetIds);
      setSelectedAssets((current) => removeAcquisitionSelection(current, assetIds));
      setAssetSummary((current) => {
        const statusCounts = { ...current.status_counts };
        statusCounts[assetStatus] = Math.max(0, (statusCounts[assetStatus] ?? 0) - assetIds.length);
        statusCounts.rejected = (statusCounts.rejected ?? 0) + assetIds.length;
        return { ...current, status_counts: statusCounts };
      });
      if (lightboxAsset && assetIds.includes(lightboxAsset.id)) setLightboxSelection(null);
      try {
        await reconcileAssetPageAfterRemoval(remainingAssets, remainingTotal);
        setNotice(message);
      } catch {
        setNotice(`${message}，但列表补位失败`);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "素材丢弃失败");
    } finally {
      setAssetActionBusy(false);
    }
  }

  async function startSimilarityScan() {
    setBusy(true);
    setNotice(null);
    try {
      const task = await startAcquisitionSimilarityScan(similarityScanType, similarityScope);
      changeReviewMode("similarity");
      setSimilarity((current) => ({ ...current, task }));
      setNotice(task.status === "running" ? "相似扫描正在进行" : "相似扫描已进入队列");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "相似扫描启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function rejectSimilarityAssets(assetIds: string[]) {
    const availableIds = new Set(similarity.groups.flatMap((group) => group.members.map((asset) => asset.id)));
    const uniqueIds = [...new Set(assetIds)].filter((assetId) => availableIds.has(assetId));
    if (!uniqueIds.length || !canDelete) return;
    const confirmed = await confirm({
      title: `丢弃选中的 ${uniqueIds.length} 项素材？`,
      message: "将立即删除这些临时文件并保留拒绝状态和来源记录，此操作无法撤销。",
      confirmLabel: "确认丢弃",
      tone: "danger"
    });
    if (!confirmed) return;
    setAssetActionBusy(true);
    setNotice(null);
    try {
      await changeAcquisitionAssets("reject", uniqueIds);
      setSelectedAssets((current) => removeAcquisitionSelection(current, uniqueIds));
      await Promise.all([
        loadSimilarityPage(similarityOffset),
        getAcquisitionAssetSummary().then((summary) => setAssetSummary(summary))
      ]);
      setNotice(`已丢弃 ${uniqueIds.length} 项临时素材`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "素材丢弃失败");
    } finally {
      setAssetActionBusy(false);
    }
  }

  function goToSimilarityOffset(nextOffset: number) {
    setSelectedAssets([]);
    setLastSelectedReviewAssetId(null);
    setSimilarityLightbox(null);
    setSimilarityOffset(Math.max(0, nextOffset));
  }

  function resetSourceForm() {
    setEditingSourceId(null);
    setSourceName("");
    setSourceUrl("");
    setSourceNotes("");
    setSourceScriptKey("");
    setTelegramCredentialEditing(false);
  }

  function editSource(source: AcquisitionSource) {
    setEditingSourceId(source.id);
    setSourceName(source.name);
    setSourceUrl(source.base_url);
    setSourceNotes(source.notes ?? "");
    setSourceScriptKey(source.script_keys[0] ?? "");
    setTelegramCredentialEditing(false);
  }

  function isTelegramScript(scriptKey: string) {
    return scriptKey === "telegram-channel-mtproto" || scriptByKey.get(scriptKey)?.page_format_key === "telegram-channel-v1";
  }

  function telegramDeliveryMessage(delivery: string | null | undefined) {
    if (delivery === "app") return "验证码已发到 Telegram App：打开与官方账号「Telegram」（777000）的对话，也可检查已登录的电脑端";
    if (delivery === "sms") return "请查收手机短信中的登录验证码；国内号有时收不到短信，可改在 App 中查看";
    if (delivery === "call") return "请留意来电或未接来电中的验证码";
    return "请打开 Telegram App 与官方账号「Telegram」（777000）的对话查看验证码，国内号通常不会发短信";
  }

  function normalizeTelegramPhone(value: string): string {
    const compact = Array.from(value.trim()).map((char) => {
      const code = char.charCodeAt(0);
      if (code >= 0xff10 && code <= 0xff19) return String.fromCharCode(code - 0xff10 + 48);
      return char === "＋" ? "+" : char;
    }).join("").replace(/[^\d+]/g, "");
    if (!compact) throw new Error("请输入手机号，例如 +86138xxxx 或 11 位国内手机号");
    const phone = compact.startsWith("00") ? `+${compact.slice(2)}` : compact;
    if (phone.startsWith("+")) {
      const digits = phone.slice(1);
      if (!/^\d{8,15}$/.test(digits)) throw new Error("国际手机号格式无效，请使用例如 +86138xxxx");
      if (digits.length === 11 && digits.startsWith("1")) return `+86${digits}`;
      return `+${digits}`;
    }
    if (!/^\d+$/.test(phone)) throw new Error("手机号只能包含数字和可选的 + 号");
    if (phone.length === 11 && phone.startsWith("1")) return `+86${phone}`;
    if (phone.startsWith("86") && phone.length >= 12 && phone.length <= 13) return `+${phone}`;
    throw new Error("请填写含国家区号的手机号，例如 +86138xxxx 或 11 位国内手机号");
  }

  async function submitSource(event: FormEvent) {
    event.preventDefault();
    if (!sourceName.trim()) return;
    const creatingTelegram = !editingSourceId && isTelegramScript(sourceScriptKey);
    if (!editingSourceId && !sourceScriptKey) {
      setNotice("请选择采集脚本");
      return;
    }
    if (!creatingTelegram && !sourceUrl.trim()) {
      setNotice("请填写站点 URL");
      return;
    }
    if (creatingTelegram && telegramAccount?.status !== "active") {
      setNotice("请先完成 Telegram 账号登录后再创建站点");
      return;
    }
    await perform(async () => {
      if (editingSourceId) {
        await updateAcquisitionSource(editingSourceId, {
          name: sourceName.trim(),
          base_url: sourceUrl.trim(),
          notes: sourceNotes.trim() || null
        });
      } else {
        await createAcquisitionSource({
          name: sourceName.trim(),
          base_url: creatingTelegram ? null : sourceUrl.trim(),
          notes: sourceNotes.trim() || null,
          script_key: sourceScriptKey
        });
      }
      resetSourceForm();
    }, editingSourceId ? "站点信息已更新" : "站点已创建");
  }

  function resetCategoryForm() {
    setEditingCategoryId(null);
    setCategoryName("");
    categoryNameTouchedRef.current = false;
    setCategoryUrl("");
    setCategoryNotes("");
  }

  function resetTelegramTopicState() {
    setTelegramTopics([]);
    setTelegramTopicError(null);
    setTelegramTopicId("");
    setTelegramTopicTitle("");
    setTelegramManualScan(null);
    setTelegramTopicLoading(false);
  }

  function switchTelegramTargetMode(mode: "dialog" | "manual") {
    if (mode === telegramTargetMode) return;
    setTelegramTargetMode(mode);
    resetTelegramTopicState();
  }

  function applyTelegramTopicSelection(topicId: string) {
    const topic = telegramTopics.find((item) => String(item.topic_id) === topicId);
    setTelegramTopicId(topicId);
    setTelegramTopicTitle(topic?.title ?? "");
    if (categoryNameTouchedRef.current) return;
    const dialog = telegramDialogs.find((item) => item.peer_id === telegramDialogPeerId);
    const baseTitle = telegramTargetMode === "dialog"
      ? (dialog ? telegramDialogTitle(dialog) : "")
      : telegramManualScan?.title ?? "";
    if (!baseTitle) return;
    setCategoryName(topic ? `${baseTitle} / ${topic.title}` : baseTitle);
  }

  async function scanManualForumTopics() {
    const channelRef = categoryUrl.trim();
    if (!channelRef) {
      setTelegramTopicError("请先输入频道链接");
      setTelegramTopics([]);
      setTelegramManualScan(null);
      return;
    }
    setTelegramTopicLoading(true);
    setTelegramTopicError(null);
    setTelegramTopics([]);
    setTelegramTopicId("");
    setTelegramTopicTitle("");
    setTelegramManualScan(null);
    try {
      const result = await scanTelegramForumTopics(channelRef);
      setTelegramManualScan({
        is_forum: result.is_forum,
        peer_id: result.peer_id,
        title: result.title,
        username: result.username,
        entity_type: result.entity_type
      });
      setTelegramTopics(result.is_forum ? result.topics : []);
      if (!categoryNameTouchedRef.current && result.title) setCategoryName(result.title);
    } catch (error) {
      setTelegramTopics([]);
      setTelegramManualScan(null);
      setTelegramTopicError(error instanceof Error ? error.message : String(error));
    } finally {
      setTelegramTopicLoading(false);
    }
  }

  function editCategory(category: AcquisitionCategory) {
    setEditingCategoryId(category.id);
    setCategorySourceId(String(category.source_id));
    setCategoryName(category.name);
    categoryNameTouchedRef.current = true;
    setCategoryUrl(category.crawl_url);
    setCategoryNotes(category.notes ?? "");
  }

  async function submitCategory(event: FormEvent) {
    event.preventDefault();
    if (!categorySourceId || !categoryName.trim()) return;
    await perform(async () => {
      const payload = { name: categoryName.trim(), crawl_url: categoryUrl.trim(), notes: categoryNotes.trim() || null };
      if (editingCategoryId) await updateAcquisitionCategory(editingCategoryId, payload);
      else if (sourceById.get(Number(categorySourceId))?.page_format_key === "telegram-channel-v1") {
        const dialog = telegramDialogs.find((item) => item.peer_id === telegramDialogPeerId);
        const scannedEntityType = telegramManualScan?.entity_type === "channel" || telegramManualScan?.entity_type === "group" || telegramManualScan?.entity_type === "bot"
          ? telegramManualScan.entity_type
          : undefined;
        await createTelegramChannel(Number(categorySourceId), {
          name: payload.name,
          channel_ref: categoryUrl.trim() || (dialog?.username ? `@${dialog.username}` : telegramDialogPeerId),
          notes: payload.notes,
          peer_id: telegramTargetMode === "dialog" ? telegramDialogPeerId || null : telegramManualScan?.peer_id || null,
          entity_type: telegramTargetMode === "dialog" ? dialog?.entity_type : scannedEntityType,
          username: telegramTargetMode === "dialog" ? dialog?.username : telegramManualScan?.username ?? undefined,
          topic_id: telegramTopicId ? Number(telegramTopicId) : null,
          topic_title: telegramTopicTitle.trim() || null,
          source_mode: telegramTargetMode,
        });
      } else await createAcquisitionCategory(Number(categorySourceId), payload);
      resetCategoryForm();
    }, editingCategoryId ? "分类信息已更新" : "分类已创建");
  }

  function selectRunCategory(categoryId: string) {
    setRunCategoryId(categoryId);
    setPreviewItems([]);
    const category = categoryById.get(Number(categoryId));
    if (category?.telegram_entity_type === "bot" || category?.telegram_entity_type === "group" || category?.telegram_topic_id != null) {
      setRunParameters((current) => ({ ...current, collect_comments: false, comments_only: false }));
    }
    const source = category ? sourceById.get(category.source_id) : undefined;
    const nextScripts = source
      ? source.script_keys.map((key) => scriptByKey.get(key)).filter((script): script is AcquisitionScript => Boolean(script))
      : [];
    if (nextScripts.some((script) => script.key === runScriptKey)) return;
    const fallback = nextScripts[0];
    setRunScriptKey(fallback?.key ?? "");
    setRunParameters(defaultAcquisitionRunParameters(fallback));
  }

  function selectRunScript(scriptKey: string) {
    setRunScriptKey(scriptKey);
    setPreviewItems([]);
    setRunParameters(defaultAcquisitionRunParameters(scriptByKey.get(scriptKey)));
  }

  function loadRunConfiguration(run: AcquisitionRun) {
    const configuration = getAcquisitionRunFormConfiguration(run, categories, sources, scripts);
    if (!configuration) {
      setNotice("此运行的原分类或脚本已不可用，无法载入配置");
      return;
    }
    setRunCategoryId(configuration.categoryId);
    setRunScriptKey(configuration.scriptKey);
    setRunMode(configuration.mode);
    setRunParameters(configuration.parameters);
    setRunCredentialId(run.credential_id == null ? "" : String(run.credential_id));
    setNotice(`已载入“${run.category_name}”的运行配置，请确认后开始采集`);
    window.requestAnimationFrame(() => runLauncherRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  async function startRun() {
    if (!runCategoryId || !runScriptKey || runSubmitting) return;
    if (selectedRunScript?.parameters.some((parameter) => parameter.key === "media_types") && selectedTelegramMediaTypes(runParameters.media_types).length === 0) {
      setNotice("至少选择一种采集媒体：图片或视频");
      return;
    }
    setRunSubmitting(true);
    setNotice(null);
    try {
      await startAcquisitionRun(Number(runCategoryId), {
        script_key: runScriptKey,
        credential_id: runCredentialId ? Number(runCredentialId) : null,
        mode: runMode,
        parameters: runPayloadParameters()
      });
      setNotice("采集任务已进入队列");
      await Promise.all([refreshReferenceData(), loadRunPage(runPageOffset)]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "采集任务创建失败");
    } finally {
      setRunSubmitting(false);
    }
  }

  async function previewRun() {
    if (!runCategoryId || !runScriptKey || previewBusy) return;
    setPreviewBusy(true);
    setPreviewItems([]);
    setNotice(null);
    try {
      const result = await previewPlugin(runScriptKey, {
        category_id: Number(runCategoryId),
        credential_id: runCredentialId ? Number(runCredentialId) : null,
        parameters: runPayloadParameters(), limit: 3
      });
      setPreviewItems(result.items);
      setNotice(result.items.length ? `已试采 ${result.items.length} 项；临时文件已清理` : "未发现可采集媒体");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "试采失败");
    } finally {
      setPreviewBusy(false);
    }
  }

  function runPayloadParameters(): Record<string, unknown> {
    return serializeAcquisitionRunParameters(selectedRunScript, runParameters);
  }

  function toggleAsset(id: string) {
    setSelectedAssets((items) => toggleAcquisitionSelection(items, id));
    setLastSelectedReviewAssetId(id);
  }

  function handleReviewListSelect(id: string, shiftKey: boolean) {
    if (shiftKey) {
      setSelectedAssets((current) => selectAcquisitionAssetRange(current, reviewPageAssetIds, lastSelectedReviewAssetId, id));
      setLastSelectedReviewAssetId(id);
      return;
    }
    toggleAsset(id);
  }

  function handleReviewMediaClick(asset: AcquisitionAsset, event: { preventDefault(): void; shiftKey: boolean; metaKey: boolean; ctrlKey: boolean }) {
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      event.preventDefault();
      handleReviewListSelect(asset.id, event.shiftKey);
      return;
    }
    showLightboxAsset(asset);
  }

  function toggleCurrentReviewPageSelection() {
    if (reviewPageAssetIds.length === 0) return;
    const pageSelected = areCurrentReviewPageSelected;
    setSelectedAssets((current) => pageSelected
      ? deselectAcquisitionPage(current, reviewPageAssetIds)
      : selectAcquisitionPage(current, reviewPageAssetIds));
    if (!pageSelected) setLastSelectedReviewAssetId(reviewPageAssetIds[reviewPageAssetIds.length - 1]);
  }

  async function submitTelegramLogin(event?: FormEvent) {
    event?.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const phoneNumber = normalizeTelegramPhone(telegramPhone);
      setTelegramPhone(phoneNumber);
      const account = await startTelegramLogin({
        api_id: Number(telegramApiId),
        api_hash: telegramApiHash.trim(),
        phone_number: phoneNumber
      });
      setTelegramAccount(account);
      setTelegramCredentialEditing(false);
      setTelegramCode("");
      setTelegramPassword("");
      setNotice(telegramDeliveryMessage(account.code_delivery));
      await refreshCurrentTab();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作未完成");
    } finally {
      setBusy(false);
    }
  }

  async function submitTelegramVerify(event?: FormEvent) {
    event?.preventDefault();
    if (!telegramCode.trim()) {
      setNotice("请输入登录验证码");
      return;
    }
    await perform(async () => {
      const account = await verifyTelegramLogin({ code: telegramCode.trim(), password: telegramPassword.trim() || undefined });
      setTelegramAccount(account);
      setTelegramCode("");
      setTelegramPassword("");
      setTelegramCredentialEditing(false);
    }, "Telegram 账号已连接");
  }

  async function resendTelegramCode() {
    setBusy(true);
    setNotice(null);
    try {
      const account = await resendTelegramLogin();
      setTelegramAccount(account);
      setTelegramCode("");
      setNotice(telegramDeliveryMessage(account.code_delivery));
      await refreshCurrentTab();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作未完成");
    } finally {
      setBusy(false);
    }
  }

  async function cancelPendingTelegramLogin() {
    await perform(async () => {
      const account = await cancelTelegramLogin();
      setTelegramAccount(account);
      setTelegramCredentialEditing(true);
      setTelegramCode("");
      setTelegramPassword("");
    }, "已返回修改 Telegram 凭证");
  }

  async function syncReviewPageToLightboxAsset(
    assetId: string,
    expectedGeneration: number,
    filter?: { status: string; mediaType: "image" | "video" }
  ) {
    if (lightboxSnapshotRequestIdRef.current !== expectedGeneration) return;
    if (!filter && assets.some((asset) => asset.id === assetId)) return;
    const status = filter?.status ?? assetStatus;
    const pageMediaFilter = filter?.mediaType ?? mediaFilter;
    // 灯箱快照只含可预览项，列表页的位置必须按完整列表的当前顺序计算。
    const ids = await listAcquisitionAssetIds(status, false, pageMediaFilter === "all" ? undefined : pageMediaFilter);
    if (lightboxSnapshotRequestIdRef.current !== expectedGeneration) return;
    const offset = getAcquisitionAssetPageOffset(ids, assetId);
    if (offset === null) throw new Error("当前素材已不在审核列表中");
    await loadAssetPage(status, offset, false, pageMediaFilter);
  }

  function showLightboxAsset(asset: AcquisitionAsset, filter?: { status: string; mediaType: "image" | "video" }) {
    const requestId = lightboxSnapshotRequestIdRef.current + 1;
    lightboxSnapshotRequestIdRef.current = requestId;
    lightboxAssetCacheRef.current.set(asset.id, asset);
    unavailableLightboxAssetIdsRef.current.clear();
    setLightboxSelection({ asset, globalIndex: 0 });
    setLightboxSnapshotIds([asset.id]);
    setLightboxSnapshotIndex(0);
    setLightboxNavigationBusy(true);
    void listAcquisitionAssetIds(filter?.status ?? assetStatus, true, filter?.mediaType ?? (mediaFilter === "all" ? undefined : mediaFilter)).then(async (ids) => {
      if (requestId !== lightboxSnapshotRequestIdRef.current) return;
      const currentIndex = ids.indexOf(asset.id);
      if (currentIndex < 0) {
        setLightboxSelection(null);
        setNotice("当前素材已不在待审核列表中");
        return;
      }
      setLightboxSnapshotIds(ids);
      setLightboxSnapshotIndex(currentIndex);
      await syncReviewPageToLightboxAsset(asset.id, requestId, filter);
    }).catch((error: Error) => {
      if (requestId === lightboxSnapshotRequestIdRef.current) setNotice(error.message);
    }).finally(() => {
      if (requestId === lightboxSnapshotRequestIdRef.current) setLightboxNavigationBusy(false);
    });
  }

  function changeReviewMode(nextMode: "list" | "similarity") {
    setReviewMode(nextMode);
    setSelectedAssets([]);
    setLastSelectedReviewAssetId(null);
    setLightboxSelection(null);
    setSimilarityLightbox(null);
  }

  async function selectAllReviewAssets() {
    if (busy || assetsTotal === 0) return;
    if (areAllReviewAssetsSelected) {
      setSelectedAssets([]);
      setLastSelectedReviewAssetId(null);
      setNotice("已取消选择全部素材");
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const assetIds = await listAcquisitionAssetIds(assetStatus, false, mediaFilter === "all" ? undefined : mediaFilter);
      setSelectedAssets(assetIds);
      setNotice(`已选中当前状态下的全部 ${assetIds.length} 项素材`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "全选素材失败");
    } finally {
      setBusy(false);
    }
  }

  function changeAssetStatus(nextStatus: string) {
    const reset = createAcquisitionStatusReset(nextStatus);
    setAssets([]);
    setAssetsTotal(0);
    setAssetLoading(true);
    setSelectedAssets(reset.selectedIds);
    setLastSelectedReviewAssetId(null);
    setLightboxSelection(null);
    setAssetOffset(reset.offset);
    setAssetJumpPage(reset.jumpPage);
    setAssetStatus(reset.status);
  }

  function changeMediaFilter(nextFilter: "all" | "image" | "video") {
    if (nextFilter === mediaFilter) return;
    setMediaFilter(nextFilter);
    setAssets([]);
    setAssetsTotal(0);
    setAssetLoading(true);
    setSelectedAssets([]);
    setLastSelectedReviewAssetId(null);
    setLightboxSelection(null);
    setAssetOffset(0);
    setAssetJumpPage("");
  }

  async function goToAssetOffset(nextOffset: number) {
    setNotice(null);
    try {
      await loadAssetPage(assetStatus, nextOffset);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "素材列表加载失败");
    }
  }

  function submitAssetPageJump(event: FormEvent) {
    event.preventDefault();
    const pageNumber = Number(assetJumpPage);
    if (!Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > assetPagination.totalPages) {
      setNotice(`请输入 1 至 ${assetPagination.totalPages} 之间的页码`);
      return;
    }
    setAssetJumpPage("");
    void goToAssetOffset((pageNumber - 1) * acquisitionAssetPageSize);
  }

  async function selectLightboxSnapshotAsset(
    snapshotIds: string[],
    index: number,
    expectedGeneration = lightboxSnapshotRequestIdRef.current
  ): Promise<boolean> {
    const assetId = snapshotIds[index];
    if (!assetId || unavailableLightboxAssetIdsRef.current.has(assetId)) return false;
    try {
      const asset = lightboxAssetCacheRef.current.get(assetId) ?? await getAcquisitionAsset(assetId);
      if (!asset.original_url) throw new Error("该素材已不可预览");
      if (lightboxSnapshotRequestIdRef.current !== expectedGeneration) return false;
      lightboxAssetCacheRef.current.set(asset.id, asset);
      setLightboxSelection({ asset, globalIndex: index });
      setLightboxSnapshotIndex(index);
      try {
        await syncReviewPageToLightboxAsset(asset.id, expectedGeneration);
      } catch (error) {
        if (lightboxSnapshotRequestIdRef.current === expectedGeneration) {
          setNotice(error instanceof Error ? `列表页同步失败：${error.message}` : "列表页同步失败");
        }
      }
      return true;
    } catch (error) {
      if (lightboxSnapshotRequestIdRef.current !== expectedGeneration) return false;
      unavailableLightboxAssetIdsRef.current.add(assetId);
      if (!(error instanceof Error) || !error.message.includes("不存在")) setNotice(error instanceof Error ? error.message : "素材加载失败");
      return false;
    }
  }

  async function navigateLightbox(direction: -1 | 1) {
    if (lightboxNavigationBusy) return;
    const generation = lightboxSnapshotRequestIdRef.current;
    setLightboxNavigationBusy(true);
    try {
      let index = getNextAcquisitionSnapshotIndex(
        lightboxSnapshotIds,
        lightboxSnapshotIndex,
        direction,
        unavailableLightboxAssetIdsRef.current
      );
      while (index >= 0 && lightboxSnapshotRequestIdRef.current === generation) {
        if (await selectLightboxSnapshotAsset(lightboxSnapshotIds, index, generation)) return;
        index = getNextAcquisitionSnapshotIndex(
          lightboxSnapshotIds,
          index,
          direction,
          unavailableLightboxAssetIdsRef.current
        );
      }
    } finally {
      if (lightboxSnapshotRequestIdRef.current === generation) setLightboxNavigationBusy(false);
    }
  }

  async function rejectLightboxAsset() {
    if (!lightboxAsset || !canDelete || lightboxRejectPendingRef.current) return;
    try {
      const confirmed = await confirm({
        title: "丢弃这项采集素材？",
        message: `将立即删除临时文件“${lightboxAsset.filename}”，同时保留拒绝状态和来源记录。`,
        confirmLabel: "确认丢弃",
        tone: "danger",
        backdrop: "transparent"
      });
      if (!confirmed || lightboxRejectPendingRef.current) return;

      const rejectedId = lightboxAsset.id;
      const rejectedSnapshotIndex = lightboxSnapshotIndex;
      const remainingAssets = assets.filter((asset) => asset.id !== rejectedId);
      const remainingTotal = Math.max(0, assetsTotal - 1);
      const closeGeneration = lightboxSnapshotRequestIdRef.current;
      lightboxRejectPendingRef.current = true;
      setAssetActionBusy(true);
      setNotice(null);
      await changeAcquisitionAssets("reject", [rejectedId]);
      setSelectedAssets((current) => removeAcquisitionSelection(current, [rejectedId]));
      setAssetSummary((current) => {
        const statusCounts = { ...current.status_counts };
        statusCounts[assetStatus] = Math.max(0, (statusCounts[assetStatus] ?? 0) - 1);
        statusCounts.rejected = (statusCounts.rejected ?? 0) + 1;
        return { ...current, status_counts: statusCounts };
      });
      reviewReconcileNeededRef.current = true;
      const fillPage = reconcileAssetPageAfterRemoval(remainingAssets, remainingTotal);
      fillPage.catch(() => undefined);
      if (lightboxSnapshotRequestIdRef.current !== closeGeneration) return;
      const nextSnapshotIds = lightboxSnapshotIds.filter((assetId) => assetId !== rejectedId);
      lightboxAssetCacheRef.current.delete(rejectedId);
      unavailableLightboxAssetIdsRef.current.delete(rejectedId);
      setLightboxSnapshotIds(nextSnapshotIds);
      const nextIndex = Math.min(rejectedSnapshotIndex, nextSnapshotIds.length - 1);
      const opened = nextIndex >= 0 && (await selectLightboxSnapshotAsset(nextSnapshotIds, nextIndex, closeGeneration));
      if (lightboxSnapshotRequestIdRef.current !== closeGeneration) return;
      if (!opened) setLightboxSelection(null);
      try {
        await fillPage;
      } catch {
        if (lightboxSnapshotRequestIdRef.current !== closeGeneration) return;
        setNotice("素材已丢弃，但列表补位失败");
        return;
      }
      if (lightboxSnapshotRequestIdRef.current !== closeGeneration) return;
      setNotice("素材已丢弃，临时文件已清除");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "素材丢弃失败");
    } finally {
      setAssetActionBusy(false);
      lightboxRejectPendingRef.current = false;
    }
  }

  function handleFrameCaptured(result: AcquisitionCaptureResult) {
    reviewReconcileNeededRef.current = true;
    void getAcquisitionAssetSummary().then(setAssetSummary).catch(() => {
      setNotice("截图已保存，统计刷新失败，关闭灯箱后可刷新列表");
    });
    if (assetStatus === "pending_review" && mediaFilter !== "video" && assetOffset === 0) {
      void loadAssetPage(assetStatus, 0).catch(() => setNotice("截图已保存，列表刷新失败"));
    }
    if (result.outcome === "created" || result.outcome === "restored") {
      setNotice("截图已添加到待审核·图片最新处");
    }
  }

  function viewCapturedAsset(asset: AcquisitionAsset) {
    setReviewMode("list");
    setAssetStatus("pending_review");
    setMediaFilter("image");
    setAssetOffset(0);
    showLightboxAsset(asset, { status: "pending_review", mediaType: "image" });
  }

  function closeReviewLightbox() {
    lightboxSnapshotRequestIdRef.current += 1;
    setLightboxSelection(null);
    setLightboxSnapshotIds([]);
    setLightboxSnapshotIndex(-1);
    setLightboxNavigationBusy(false);
    lightboxAssetCacheRef.current.clear();
    unavailableLightboxAssetIdsRef.current.clear();
    if (!reviewReconcileNeededRef.current && !assetLoading) {
      void loadAssetPage(assetStatus, assetOffset).catch((error: Error) => setNotice(error.message));
      return;
    }
    reviewReconcileNeededRef.current = false;
    void Promise.all([
      loadAssetPage(assetStatus, assetOffset),
      getAcquisitionAssetSummary()
    ]).then(([, summary]) => {
      setAssetSummary(summary);
    }).catch((error: Error) => {
      reviewReconcileNeededRef.current = true;
      setNotice(error.message);
    });
  }

  function compatibleScripts(source: AcquisitionSource): AcquisitionScript[] {
    return scripts.filter((script) => !source.script_keys.includes(script.key)
      && (!source.page_format_key || source.page_format_key === script.page_format_key));
  }

  const activeScopeOptions = exportScope === "source" ? sources : exportScope === "category" ? categories : runs;

  return <><main className="acquisition-page">
    <header className="acquisition-heading">
      <div><p className="acquisition-eyebrow">媒体采集工作台</p><h1>采集中心</h1></div>
      <div className="acquisition-heading-actions">
        <span className="acquisition-counter">采集资产 {assetSummary.total}</span>
        <button className="icon-button" type="button" onClick={() => void refreshCurrentTab()} title="刷新当前页" aria-label="刷新当前页" disabled={busy || currentTabRefreshing}><LoaderCircle size={17} /></button>
      </div>
    </header>

    <nav className="acquisition-tabs" aria-label="采集中心视图">
      {tabs.map((item) => <button key={item.key} className={tab === item.key ? "active" : ""} onClick={() => setTab(item.key)} type="button">{item.label}</button>)}
    </nav>
    {notice && <p className="acquisition-notice">{notice}</p>}
    <section className="acquisition-funnel" aria-label="采集资产总账">
      <span>待审核 <strong>{assetSummary.status_counts.pending_review ?? 0}</strong></span>
      <span>入库处理中 <strong>{(assetSummary.status_counts.import_queued ?? 0) + (assetSummary.status_counts.importing ?? 0)}</strong></span>
      <span>入库失败 <strong>{assetSummary.status_counts.import_failed ?? 0}</strong></span>
      <span>已入库 <strong>{assetSummary.status_counts.imported ?? 0}</strong></span>
      <span>库内重复 <strong>{assetSummary.status_counts.gallery_duplicate ?? 0}</strong></span>
      <span>已丢弃 <strong>{assetSummary.status_counts.rejected ?? 0}</strong></span>
    </section>

    {tab === "plugins" && <AcquisitionPluginsPanel canAdmin={canAdmin} canManageAccounts={canManageAccounts} onChanged={() => void refreshReferenceData()} refreshRef={pluginsRefreshRef} />}

    {tab === "sources" && <section className="acquisition-grid sources-layout">
      <div className="acquisition-section source-ledger-panel">
        <div className="acquisition-section-title"><span>已维护站点</span><small>{sourcePageTotal} 个</small></div>
        <div className={sourcePageLoading ? "source-ledger loading" : "source-ledger"} aria-busy={sourcePageLoading}>
          {sourcePageItems.map((source) => {
            const bindable = compatibleScripts(source);
            const selectedKey = sourceScriptChoices[source.id] ?? bindable[0]?.key ?? "";
            const selected = selectedSourceId === source.id;
            return <article
              className={`source-card source-select-card${selected ? " selected" : ""}`}
              key={source.id}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              onClick={() => { setSelectedSourceId(source.id); setCategoryPageOffset(0); }}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedSourceId(source.id); setCategoryPageOffset(0); } }}
            >
              <div className="source-card-heading">
                <div><strong>{source.name}</strong><a href={source.base_url} target="_blank" rel="noreferrer" title={source.base_url}>{source.base_url}</a></div>
                <div className="source-command-row">
                  {canEdit && <button type="button" className="icon-button" title="编辑站点" aria-label={`编辑站点 ${source.name}`} onClick={(event) => { event.stopPropagation(); editSource(source); }}><Pencil size={15} /></button>}
                  {canDelete && <button type="button" className="icon-button danger" title="删除站点" aria-label={`删除站点 ${source.name}`} disabled={busy} onClick={(event) => { event.stopPropagation(); void perform(() => deleteAcquisitionSource(source.id), "站点已删除"); }}><Trash2 size={15} /></button>}
                </div>
              </div>
              {source.notes && <p className="source-notes">{source.notes}</p>}
              <div className="script-bindings">
                {source.script_keys.map((key) => <span className="script-chip" key={key} title={scriptByKey.get(key)?.description ?? "插件未安装或未启用"}>
                  {scriptByKey.get(key)?.name ?? key}
                  {canEdit && <button type="button" title="解除绑定" aria-label={`解除绑定 ${key}`} disabled={busy} onClick={(event) => { event.stopPropagation(); void perform(async () => { await unbindAcquisitionScript(source.id, key); }, "脚本绑定已移除"); }}><X size={13} /></button>}
                </span>)}
                {!source.script_keys.length && <small>尚未绑定脚本</small>}
                {source.script_keys.some((key) => !scriptByKey.has(key)) && <small>部分插件未安装或未启用</small>}
              </div>
              {canEdit && bindable.length > 0 && <div className="script-bind-row">
                <select value={selectedKey} onClick={(event) => event.stopPropagation()} onChange={(event) => setSourceScriptChoices((current) => ({ ...current, [source.id]: event.target.value }))} aria-label={`为 ${source.name} 选择脚本`}>
                  {bindable.map((script) => <option key={script.key} value={script.key}>{script.name}</option>)}
                </select>
                <button type="button" className="icon-button" title="绑定脚本" aria-label={`为 ${source.name} 绑定脚本`} disabled={busy || !selectedKey} onClick={(event) => { event.stopPropagation(); void perform(async () => { await bindAcquisitionScript(source.id, selectedKey); }, "脚本已绑定"); }}><Link2 size={16} /></button>
              </div>}
              <small className="source-summary">{categories.filter((category) => category.source_id === source.id).length} 个分类 · {source.enabled ? "启用" : "停用"}</small>
              {source.page_format_key === "telegram-channel-v1" && <div className="telegram-account-panel compact">
                {telegramAccount?.status === "active" ? <div className="telegram-account-line">
                  <small>已连接 {telegramAccount.username ? `@${telegramAccount.username}` : telegramAccount.phone_masked}</small>
                  {canEdit && <button type="button" className="mini-command" title="退出 Telegram 账号" aria-label="退出 Telegram 账号" disabled={busy} onClick={(event) => { event.stopPropagation(); void perform(async () => { setTelegramAccount(await logoutTelegramAccount()); setTelegramCredentialEditing(true); }, "Telegram 账号已退出"); }}><LogOut size={13} />退出</button>}
                </div> : <small>Telegram 未登录，请在上方表单完成登录。</small>}
              </div>}
            </article>;
          })}
          {!sourcePageLoading && !sourcePageItems.length && <p className="acquisition-empty">尚未维护采集站点。</p>}
        </div>
        {sourcePagePagination.totalPages > 1 && <div className="acquisition-pagination compact" aria-label="站点分页">
          <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={sourcePageLoading || sourcePageOffset === 0} onClick={() => void loadSourcePage(sourcePageOffset - managementPageSize)}><ChevronLeft size={18} /></button>
          <span className="pagination-summary">第 {sourcePagePagination.currentPage} / {sourcePagePagination.totalPages} 页 · {sourcePagePagination.rangeStart}-{sourcePagePagination.rangeEnd} / {sourcePageTotal}</span>
          <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={sourcePageLoading || sourcePageOffset + managementPageSize >= sourcePageTotal} onClick={() => void loadSourcePage(sourcePageOffset + managementPageSize)}><ChevronRight size={18} /></button>
        </div>}
      </div>

      {canEdit && <div className="acquisition-section acquisition-forms">
        <form onSubmit={(event) => void submitSource(event)}>
          <div className="acquisition-section-title"><span>{editingSourceId ? "编辑站点" : "新增站点"}</span><Plus size={17} /></div>
          <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="站点名称" required />
          {!editingSourceId && <select value={sourceScriptKey} onChange={(event) => setSourceScriptKey(event.target.value)} required aria-label="选择采集脚本">
            <option value="">选择采集脚本</option>
            {scripts.map((script) => <option key={script.key} value={script.key}>{script.name}</option>)}
          </select>}
          {(editingSourceId || !isTelegramScript(sourceScriptKey)) && <input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="总站或首页 URL" required={!isTelegramScript(sourceScriptKey)} />}
          <textarea value={sourceNotes} onChange={(event) => setSourceNotes(event.target.value)} placeholder="备注（选填）" rows={3} />
          {!editingSourceId && isTelegramScript(sourceScriptKey) && <div className="telegram-account-panel">
            <div className="acquisition-section-title"><span>Telegram 账号</span><Link2 size={17} /></div>
            {telegramAccount?.status === "active" && !telegramCredentialEditing ? <>
              <p className="source-notes">将使用已连接账号 {telegramAccount.username ? `@${telegramAccount.username}` : telegramAccount.phone_masked}</p>
              <button type="button" className="secondary-command" disabled={busy} onClick={() => void perform(async () => { setTelegramAccount(await logoutTelegramAccount()); setTelegramCredentialEditing(true); }, "Telegram 账号已退出")}>退出并更换账号</button>
            </> : telegramAccount?.status === "verification_pending" && !telegramCredentialEditing ? <>
              <div className="telegram-account-summary">
                <small>API ID：{telegramAccount.api_id ?? "—"}</small>
                <small>API Hash：已保存</small>
                <small>手机号：{telegramAccount.phone_masked ?? "—"}</small>
                <small>{telegramDeliveryMessage(telegramAccount.code_delivery)}</small>
              </div>
              <input value={telegramCode} onChange={(event) => setTelegramCode(event.target.value)} placeholder="登录验证码" />
              <input type="password" value={telegramPassword} onChange={(event) => setTelegramPassword(event.target.value)} placeholder="两步验证密码（如有）" />
              <div className="telegram-login-actions">
                <button type="button" disabled={busy || !telegramCode.trim()} onClick={() => void submitTelegramVerify()}>验证登录</button>
                <button type="button" className="secondary-command" disabled={busy} onClick={() => void resendTelegramCode()}>重发验证码</button>
                <button type="button" className="secondary-command" disabled={busy} onClick={() => void cancelPendingTelegramLogin()}>修改凭证</button>
              </div>
            </> : <>
              <input type="number" value={telegramApiId} onChange={(event) => setTelegramApiId(event.target.value)} placeholder="API ID" />
              <input value={telegramApiHash} onChange={(event) => setTelegramApiHash(event.target.value)} placeholder="API Hash" />
              <input value={telegramPhone} onChange={(event) => setTelegramPhone(event.target.value)} onBlur={() => { try { if (telegramPhone.trim()) setTelegramPhone(normalizeTelegramPhone(telegramPhone)); } catch { /* 保持原输入，提交时再校验 */ } }} placeholder="11 位国内手机号，将自动加 +86" />
              <button type="button" disabled={busy || !telegramApiId || !telegramApiHash.trim() || !telegramPhone.trim()} onClick={() => void submitTelegramLogin()}>发送验证码</button>
            </>}
          </div>}
          <div className="form-command-row">
            <button
              type="submit"
              disabled={busy || (!editingSourceId && isTelegramScript(sourceScriptKey) && telegramAccount?.status !== "active")}
            >{editingSourceId ? "保存站点" : "新建站点"}</button>
            {editingSourceId && <button type="button" className="secondary-command" onClick={resetSourceForm}>取消</button>}
          </div>
        </form>
        <form onSubmit={(event) => void submitCategory(event)}>
          <div className="acquisition-section-title"><span>{editingCategoryId ? "编辑分类" : "新增分类"}</span><FolderPlus size={17} /></div>
          <select value={categorySourceId} onChange={(event) => setCategorySourceId(event.target.value)} required disabled={editingCategoryId != null}><option value="">选择站点</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select>
          <input value={categoryName} onChange={(event) => { categoryNameTouchedRef.current = true; setCategoryName(event.target.value); }} placeholder="分类名称" required />
          {sourceById.get(Number(categorySourceId))?.page_format_key !== "telegram-channel-v1" && <input type="url" value={categoryUrl} onChange={(event) => setCategoryUrl(event.target.value)} placeholder="分类分页入口 URL" required />}
          {sourceById.get(Number(categorySourceId))?.page_format_key === "telegram-channel-v1" && <div className="telegram-target-panel">
            <div className="telegram-target-switch" role="tablist" aria-label="Telegram 来源方式">
              <button type="button" className={telegramTargetMode === "dialog" ? "active" : ""} onClick={() => switchTelegramTargetMode("dialog")}>选择已登录会话</button>
              <button type="button" className={telegramTargetMode === "manual" ? "active" : ""} onClick={() => switchTelegramTargetMode("manual")}>手工输入引用</button>
            </div>
            {telegramTargetMode === "dialog" && <>
              <select value={telegramDialogPeerId} onChange={(event) => { setTelegramDialogPeerId(event.target.value); setTelegramTopicId(""); setTelegramTopicTitle(""); }} aria-label="选择 Telegram 会话">
                <option value="">{telegramDialogLoading ? "正在读取会话…" : "选择频道、群组或机器人"}</option>
                {telegramDialogs.map((dialog) => <option key={dialog.peer_id} value={dialog.peer_id}>{dialog.title} · {dialog.entity_type === "bot" ? "机器人" : dialog.entity_type === "group" ? "群组" : "频道"}{dialog.is_forum ? " · 论坛" : ""}</option>)}
              </select>
              {!telegramDialogLoading && telegramDialogError && <small className="telegram-topic-error">读取会话失败：{telegramDialogError}</small>}
              {!telegramDialogLoading && !telegramDialogError && telegramDialogs.length === 0 && <small className="telegram-topic-empty">未读取到已登录会话。</small>}
              <button type="button" className="secondary-command" disabled={busy || telegramDialogLoading || telegramAccount?.status !== "active"} onClick={() => {
                telegramDialogLoadKeyRef.current = null;
                setTelegramDialogRetry((current) => current + 1);
              }}>重新读取会话</button>
            </>}
            {telegramTargetMode === "manual" && <div className="telegram-manual-ref-row">
              <input type="text" value={categoryUrl} onChange={(event) => {
                setCategoryUrl(event.target.value);
                if (telegramManualScan || telegramTopics.length || telegramTopicError) resetTelegramTopicState();
              }} placeholder="频道用户名、频道链接、私有邀请链接或 peer ID" required />
              <button type="button" className="secondary-command" disabled={busy || telegramTopicLoading || !categoryUrl.trim() || telegramAccount?.status !== "active"} onClick={() => void scanManualForumTopics()}>
                <ScanSearch size={15} /> {telegramTopicLoading ? "扫描中…" : "扫描话题"}
              </button>
            </div>}
            {telegramTopics.length > 0 && <select value={telegramTopicId} onChange={(event) => applyTelegramTopicSelection(event.target.value)} aria-label="选择论坛话题"><option value="">采集全部话题</option>{telegramTopics.map((topic) => <option key={topic.topic_id} value={topic.topic_id}>{topic.title}{topic.closed ? " · 已关闭" : ""}</option>)}</select>}
            {telegramTopicLoading && <small>正在读取论坛话题…</small>}
            {!telegramTopicLoading && telegramTopicError && <small className="telegram-topic-error">读取论坛话题失败：{telegramTopicError}</small>}
            {!telegramTopicLoading && !telegramTopicError && telegramTargetMode === "dialog" && telegramDialogPeerId && telegramTopics.length === 0 && <small className="telegram-topic-empty">未读取到论坛话题，可直接手工输入话题 ID。</small>}
            {!telegramTopicLoading && !telegramTopicError && telegramTargetMode === "manual" && telegramManualScan && !telegramManualScan.is_forum && <small className="telegram-topic-empty">该链接不是论坛</small>}
            {!telegramTopicLoading && !telegramTopicError && telegramTargetMode === "manual" && telegramManualScan?.is_forum && telegramTopics.length === 0 && <small className="telegram-topic-empty">未读取到论坛话题，可直接手工输入话题 ID。</small>}
            <input value={telegramTopicId} onChange={(event) => setTelegramTopicId(event.target.value)} placeholder="可选：手工输入话题 ID" inputMode="numeric" />
          </div>}
          <textarea value={categoryNotes} onChange={(event) => setCategoryNotes(event.target.value)} placeholder="备注（选填）" rows={3} />
          <div className="form-command-row"><button type="submit" disabled={busy}>{editingCategoryId ? "保存分类" : sourceById.get(Number(categorySourceId))?.page_format_key === "telegram-channel-v1" ? "添加 Telegram 频道" : "新建分类"}</button>{editingCategoryId && <button type="button" className="secondary-command" onClick={resetCategoryForm}>取消</button>}</div>
        </form>
      </div>}

      <div className="acquisition-section acquisition-category-list">
        <div className="acquisition-section-title"><span>{selectedSourceId == null ? "分类页面" : `${sourceById.get(selectedSourceId)?.name ?? "未知站点"} · 分类`}</span><small>{categoryPageTotal} 条</small></div>
        {categoryPageItems.map((category) => <article key={category.id} className="category-line">
          <ChevronRight size={15} /><div><strong>{telegramCategoryLabel(category)}</strong><small>{sourceById.get(category.source_id)?.name ?? "未知站点"} · {category.crawl_url}</small></div>
          <div className="category-command-row">
            {canEdit && <button type="button" className="icon-button" title="编辑分类" aria-label={`编辑分类 ${category.name}`} onClick={() => editCategory(category)}><Pencil size={15} /></button>}
            {canDelete && <button type="button" className="icon-button danger" title="删除分类" aria-label={`删除分类 ${category.name}`} disabled={busy} onClick={() => void perform(() => deleteAcquisitionCategory(category.id), "分类已删除")}><Trash2 size={15} /></button>}
          </div>
        </article>)}
        {!categoryPageItems.length && <p className="acquisition-empty">{selectedSourceId == null ? "尚未维护采集站点。" : "该站点尚未维护分类页面。"}</p>}
        {categoryPagePagination.totalPages > 1 && <div className="acquisition-pagination compact" aria-label="分类分页">
          <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={categoryPageOffset === 0} onClick={() => setCategoryPageOffset((current) => Math.max(0, current - managementPageSize))}><ChevronLeft size={18} /></button>
          <span className="pagination-summary">第 {categoryPagePagination.currentPage} / {categoryPagePagination.totalPages} 页 · {categoryPagePagination.rangeStart}-{categoryPagePagination.rangeEnd} / {categoryPageTotal}</span>
          <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={categoryPageOffset + managementPageSize >= categoryPageTotal} onClick={() => setCategoryPageOffset((current) => current + managementPageSize)}><ChevronRight size={18} /></button>
        </div>}
      </div>
    </section>}

    {tab === "runs" && <section className="acquisition-grid run-layout">
      <div className="acquisition-section run-launcher" ref={runLauncherRef}>
        <div className="acquisition-section-title"><span>启动采集</span><Play size={17} /></div>
        <label><span>分类页面</span><select value={runCategoryId} onChange={(event) => selectRunCategory(event.target.value)} disabled={!canAdd || runSubmitting}><option value="">选择分类</option>{sources.map((source) => { const sourceCategories = categories.filter((category) => category.source_id === source.id); if (!sourceCategories.length) return null; return <optgroup key={source.id} label={source.name}>{sourceCategories.map((category) => <option key={category.id} value={category.id}>{telegramCategoryLabel(category)}</option>)}</optgroup>; })}</select></label>
        <label><span>爬取脚本</span><select value={runScriptKey} onChange={(event) => selectRunScript(event.target.value)} disabled={!canAdd || runSubmitting || !availableRunScripts.length}><option value="">{runCategoryId && !availableRunScripts.length ? selectedRunSource?.script_keys.length ? "绑定的插件未安装或未启用" : "该站点尚未绑定脚本" : "选择脚本"}</option>{availableRunScripts.map((script) => <option key={script.key} value={script.key}>{script.name} · v{script.version}</option>)}</select></label>
        {!!selectedRunScript?.credentials?.length && <label><span>登录账号</span><select value={runCredentialId} onChange={(event) => setRunCredentialId(event.target.value)} disabled={runSubmitting} required={runRequiresCredential}>
          <option value="">{runRequiresCredential ? "选择已验证账号" : "不使用账号（可选）"}</option>{runCredentials.map((account) => <option key={account.id} value={account.id} disabled={account.status !== "valid"}>{account.name} · {account.status === "valid" ? "已验证" : "请先测试连接"}</option>)}
        </select>{runRequiresCredential && !runCredentials.length && <small>请先在“采集插件”中保存账号并测试连接。</small>}</label>}
        {selectedRunScript?.parameters.map((parameter) => {
          const commentsUnsupported = selectedRunCategory?.telegram_entity_type === "bot"
            || selectedRunCategory?.telegram_entity_type === "group"
            || selectedRunCategory?.telegram_topic_id != null;
          if (parameter.key === "comments_only" && commentsUnsupported) return null;
          return (
            <label key={parameter.key} title={parameter.description ?? undefined}>
              <span>{parameter.label}{parameter.required ? " *" : ""}</span>
              {parameter.key === "media_types"
                ? <div className="telegram-media-options"><span>选择媒体</span><label><input type="checkbox" checked={selectedTelegramMediaTypes(runParameters.media_types).includes("image")} onChange={(event) => setRunParameters((current) => { const values = selectedTelegramMediaTypes(current.media_types); const next = event.target.checked ? [...new Set([...values, "image"])] : values.filter((item) => item !== "image"); return { ...current, media_types: next.join(",") }; })} /> 图片</label><label><input type="checkbox" checked={selectedTelegramMediaTypes(runParameters.media_types).includes("video")} onChange={(event) => setRunParameters((current) => { const values = selectedTelegramMediaTypes(current.media_types); const next = event.target.checked ? [...new Set([...values, "video"])] : values.filter((item) => item !== "video"); return { ...current, media_types: next.join(",") }; })} /> 视频</label></div>
                : parameter.key === "collect_comments" && commentsUnsupported
                  ? <span className="telegram-topic-empty">机器人、群组或论坛话题不支持频道评论区采集</span>
                : parameter.key === "collect_comments" || parameter.key === "comments_only"
                  ? <><input type="checkbox" checked={Boolean(runParameters[parameter.key])} onChange={(event) => setRunParameters((current) => ({
                    ...current,
                    [parameter.key]: event.target.checked,
                    ...(parameter.key === "comments_only" && event.target.checked ? { collect_comments: true } : {}),
                    ...(parameter.key === "collect_comments" && !event.target.checked ? { comments_only: false } : {}),
                  }))} />{parameter.key === "comments_only" && <small>{parameter.description}</small>}</>
                : parameter.type === "boolean"
                  ? <input type="checkbox" checked={Boolean(runParameters[parameter.key])} onChange={(event) => setRunParameters((current) => ({ ...current, [parameter.key]: event.target.checked }))} />
                  : parameter.type === "select"
                    ? <select value={String(runParameters[parameter.key] ?? "")} onChange={(event) => setRunParameters((current) => ({ ...current, [parameter.key]: event.target.value }))}>{parameter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
                    : <input type={parameter.type === "datetime" ? "datetime-local" : parameter.type === "string" || parameter.type === "string_list" ? "text" : "number"} required={parameter.required} min={parameter.minimum ?? undefined} max={parameter.maximum ?? undefined} step={parameter.type === "integer" ? 1 : "any"} placeholder={parameter.type === "string_list" ? "多个值以逗号分隔" : undefined} value={String(runParameters[parameter.key] ?? "")} onChange={(event) => setRunParameters((current) => ({ ...current, [parameter.key]: event.target.value }))} />}
            </label>
          );
        })}
        <div className="mode-switch run-mode-switch" aria-label="采集模式"><button type="button" className={runMode === "incremental" ? "active" : ""} onClick={() => setRunMode("incremental")}>增量</button><button type="button" className={runMode === "full" ? "active" : ""} onClick={() => setRunMode("full")}>全量发现</button><button type="button" className={runMode === "verify" ? "active" : ""} onClick={() => setRunMode("verify")}>核验更新</button></div>
        <button type="button" disabled={!canAdd || !runCategoryId || !availableRunScripts.some((script) => script.key === runScriptKey) || runSubmitting || !runCredentialUsable} onClick={() => void startRun()}><Play size={16} /> 开始采集</button>
        {selectedRunScript?.is_plugin && runScriptKey !== "telegram-channel-mtproto" && <button type="button" className="secondary-command" disabled={!canAdd || !runCategoryId || previewBusy || !runCredentialUsable} onClick={() => void previewRun()}><ScanSearch size={16} /> {previewBusy ? "正在试采…" : "试采前 3 项"}</button>}
        {previewItems.length > 0 && <div className="plugin-preview-results">{previewItems.map((item, index) => <div key={`${item.source_url}-${index}`}><strong>{item.title || item.filename}</strong><small>{item.media_type === "video" ? "视频" : "图片"} · {formatBytes(item.size_bytes)}</small><small title={item.source_url}>{item.source_url}</small></div>)}</div>}
      </div>
      <div className="acquisition-section run-list">
        <div className="acquisition-section-title"><span>最近运行</span><small>{runPageTotal} 条</small></div>
        {runPageItems.map((run) => {
          const configuration = getAcquisitionRunFormConfiguration(run, categories, sources, scripts);
          const isActive = run.status === "pending" || run.status === "running";
          const canLoadConfiguration = canAdd && !runSubmitting && !isActive && Boolean(configuration);
          const loadTitle = isActive
            ? "运行结束后可载入配置"
            : configuration
              ? "载入此运行配置"
              : "原分类或脚本已不可用";
          return <article className="run-line" key={run.id}>
            <div><strong>{run.source_name} / {telegramCategoryLabel(categoryById.get(run.category_id) ?? ({ name: run.category_name } as AcquisitionCategory))}</strong><small>{run.script_name} · v{run.script_version} · {formatDate(run.created_at)} · {run.mode === "verify" ? "核验更新" : run.mode === "full" || run.parameters.force_full_scan === true ? "全量发现" : "增量"}</small>{runStopLabel(run) && <small>{runStopLabel(run)}</small>}{run.error_message && <p className="run-error">{run.error_message}</p>}</div>
            <div className="run-actions">
              <div className="run-metrics"><span className={`acquisition-status status-${run.status}`}>{statusLabel(run.status)}</span><small>扫描 {run.total_count} · 跳过 {run.skipped_count} · 忽略 {run.ignored_count}</small><small>下载成功 {run.download_success_count} · 新候选 {run.candidate_count} · 内容重复 {run.content_duplicate_count} · 清晰度重复 {run.resolution_duplicate_count} · 高清替换 {run.resolution_upgrade_count} · 库内重复 {run.gallery_duplicate_count} · 失败 {run.error_count}</small></div>
              <button type="button" className="icon-button" title={loadTitle} aria-label={`${loadTitle} ${run.category_name}`} disabled={!canLoadConfiguration} onClick={() => loadRunConfiguration(run)}><RotateCcw size={16} /></button>
              {isActive && <button type="button" className="icon-button danger" title="停止采集" aria-label={`停止采集 ${run.category_name}`} disabled={busy} onClick={() => void perform(async () => { await stopAcquisitionRun(run.id); }, "已请求停止采集")}><Square size={16} /></button>}
            </div>
          </article>;
        })}
        {!runPageLoading && !runPageItems.length && <p className="acquisition-empty">尚无运行。</p>}
        {runPagePagination.totalPages > 1 && <div className="acquisition-pagination compact" aria-label="运行分页">
          <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={runPageLoading || runPageOffset === 0} onClick={() => void loadRunPage(runPageOffset - managementPageSize)}><ChevronLeft size={18} /></button>
          <span className="pagination-summary">第 {runPagePagination.currentPage} / {runPagePagination.totalPages} 页 · {runPagePagination.rangeStart}-{runPagePagination.rangeEnd} / {runPageTotal}</span>
          <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={runPageLoading || runPageOffset + managementPageSize >= runPageTotal} onClick={() => void loadRunPage(runPageOffset + managementPageSize)}><ChevronRight size={18} /></button>
        </div>}
      </div>
    </section>}

    {tab === "review" && <section className="acquisition-review">
      <div className="review-toolbar">
        <div className="review-toolbar-leading">
          <div className="mode-switch acquisition-review-mode" aria-label="待审核视图">
            <button type="button" className={reviewMode === "list" ? "active" : ""} onClick={() => changeReviewMode("list")}><Images size={15} /> 素材列表</button>
            <button type="button" className={reviewMode === "similarity" ? "active" : ""} onClick={() => changeReviewMode("similarity")}><ScanSearch size={15} /> 相似整理</button>
          </div>
          {reviewMode === "similarity" && <div className="similarity-scan-options">
            <div className="mode-switch similarity-option-switch" aria-label="相似检查类型">
              <button type="button" className={similarityScanType === "normal" ? "active" : ""} disabled={busy} onClick={() => { setSimilarityScanType("normal"); setSimilarityOffset(0); setSelectedAssets([]); }}>普通相似</button>
              <button type="button" className={similarityScanType === "mirror" ? "active" : ""} disabled={busy} onClick={() => { setSimilarityScanType("mirror"); setSimilarityOffset(0); setSelectedAssets([]); }}>镜像相似</button>
            </div>
            <div className="mode-switch similarity-option-switch" aria-label="相似检查范围">
              <button type="button" className={similarityScope === "pending_only" ? "active" : ""} disabled={busy} onClick={() => { setSimilarityScope("pending_only"); setSimilarityOffset(0); setSelectedAssets([]); }}>审核区内</button>
              <button type="button" className={similarityScope === "pending_to_gallery" ? "active" : ""} disabled={busy} onClick={() => { setSimilarityScope("pending_to_gallery"); setSimilarityOffset(0); setSelectedAssets([]); }}>联查图库</button>
            </div>
          </div>}
          {reviewMode === "list" && <><select value={assetStatus} disabled={busy} onChange={(event) => changeAssetStatus(event.target.value)}><option value="pending_review">待审核</option><option value="import_failed">入库失败</option><option value="import_queued">等待入库</option><option value="importing">正在入库</option><option value="imported">已入库</option><option value="gallery_duplicate">库中已存在</option></select>
            <div className="mode-switch review-media-filter" aria-label="素材类型">
              <button type="button" className={mediaFilter === "all" ? "active" : ""} disabled={busy} onClick={() => changeMediaFilter("all")}>全部 {(assetSummary.status_media_counts?.[assetStatus]?.image ?? 0) + (assetSummary.status_media_counts?.[assetStatus]?.video ?? 0) || ""}</button>
              <button type="button" className={mediaFilter === "image" ? "active" : ""} disabled={busy} onClick={() => changeMediaFilter("image")}>仅图片 {assetSummary.status_media_counts?.[assetStatus]?.image ?? 0}</button>
              <button type="button" className={mediaFilter === "video" ? "active" : ""} disabled={busy} onClick={() => changeMediaFilter("video")}>仅视频 {assetSummary.status_media_counts?.[assetStatus]?.video ?? 0}</button>
            </div>
            <span>{assetsTotal} 项</span></>}
          {reviewMode === "similarity" && <span>{similarity.total} 组</span>}
          {selectedAssets.length > 0 && <span className="review-selection-count">已选 {selectedAssets.length} 项</span>}
        </div>
        <div className="review-actions">
          {canEdit && <button type="button" title={`扫描${similarityScope === "pending_only" ? "审核区内" : "审核区与图库"}的${similarityScanType === "mirror" ? "镜像" : "普通"}相似图片`} disabled={busy || similarity.task?.status === "pending" || similarity.task?.status === "running"} onClick={() => void startSimilarityScan()}><ScanSearch size={16} /> {similarity.generated_at ? "重新扫描" : "扫描相似"}</button>}
          {reviewMode === "list" && <button type="button" title={areCurrentReviewPageSelected ? "取消选择当前页素材" : "选中当前页素材。按住 Shift 点击缩略图或复选框可连选；⌘ 或 Ctrl 点击缩略图可勾选"} disabled={busy || assetActionBusy || assets.length === 0} onClick={toggleCurrentReviewPageSelection}>{areCurrentReviewPageSelected ? "取消本页" : "选中本页"}</button>}
          {reviewMode === "list" && <button type="button" title={areAllReviewAssetsSelected ? "取消选择当前状态下所有素材" : "选中当前状态下所有页面的素材"} disabled={busy || assetActionBusy || assetsTotal === 0} onClick={() => void selectAllReviewAssets()}><CheckCheck size={16} /> {areAllReviewAssetsSelected ? "取消全选" : `全选 ${assetsTotal}`}</button>}
          {reviewMode === "list" && canAdd && (areAllReviewAssetsSelected ? mediaFilter !== "video" : assets.some((asset) => selectedAssets.includes(asset.id) && asset.media_type === "image")) && <div className="mode-switch import-type-switch" aria-label="导入图片类型">
            <button type="button" className={!importAsRichText ? "active" : ""} disabled={busy || assetActionBusy} onClick={() => setImportAsRichText(false)}>普通图片</button>
            <button type="button" className={importAsRichText ? "active" : ""} disabled={busy || assetActionBusy} onClick={() => setImportAsRichText(true)}>图文图片</button>
          </div>}
          {reviewMode === "list" && canAdd && <button type="button" disabled={busy || assetActionBusy || !selectedAssets.length} onClick={() => void performSelectedAssetAction("import", assetStatus === "import_failed" ? "已创建入库重试批次" : "已创建入库批次")}><Check size={16} /> 导入 {selectedAssets.length || ""}</button>}
          {canDelete && <button type="button" className="danger-command" disabled={busy || assetActionBusy || !selectedAssets.length} onClick={() => reviewMode === "similarity" ? void rejectSimilarityAssets(selectedAssets) : void performSelectedAssetAction("reject", "已丢弃临时素材")}><X size={16} /> 丢弃 {selectedAssets.length || ""}</button>}
        </div>
      </div>
      {reviewMode === "list" && <><div className={assetLoading ? "review-grid loading" : "review-grid"} aria-busy={assetLoading}>
          {assets.map((asset) => <article className={selectedAssets.includes(asset.id) ? "review-tile selected" : "review-tile"} key={asset.id}>
          <label className="tile-select" title="按住 Shift 连选当前页"><input type="checkbox" checked={selectedAssets.includes(asset.id)} onChange={(event) => handleReviewListSelect(asset.id, Boolean((event.nativeEvent as globalThis.MouseEvent).shiftKey))} /><span>选择</span></label>
          {asset.media_type === "video" && asset.original_url ? <button className="review-image-button review-video-card" type="button" onClick={(event) => handleReviewMediaClick(asset, event)} aria-label={`查看视频 ${asset.filename}`} title="单击查看；Shift 连选；⌘ 或 Ctrl 勾选">{lightboxAsset ? <span className="review-image-placeholder" aria-hidden="true" /> : <><span className="review-video-fallback" aria-hidden="true" />{asset.preview_url && <img src={getAcquisitionPreviewUrl(asset.preview_url, 480)} alt={asset.filename} loading="lazy" decoding="async" onError={(event) => { event.currentTarget.style.display = "none"; }} />}</>}<span className="review-video-play" aria-hidden="true"><Play size={18} fill="currentColor" /></span>{asset.duration_seconds != null && <span className="review-video-duration">{formatDurationSeconds(asset.duration_seconds)}</span>}</button> : asset.preview_url ? <button className="review-image-button" type="button" onClick={(event) => handleReviewMediaClick(asset, event)} aria-label={`查看大图 ${asset.filename}`} title="单击查看；Shift 连选；⌘ 或 Ctrl 勾选">{lightboxAsset ? <span className="review-image-placeholder" aria-hidden="true" /> : <img src={getAcquisitionPreviewUrl(asset.preview_url, 480)} alt={asset.filename} loading="lazy" decoding="async" />}</button> : <div className="tile-missing">临时文件已清除</div>}
          <div className="tile-meta"><strong title={asset.filename}>{asset.media_type === "video" && <Video size={14} />} {asset.filename}</strong><small>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "尺寸未知"}{asset.duration_seconds != null ? ` · ${formatDurationSeconds(asset.duration_seconds)}` : ""} · {formatBytes(asset.size_bytes)}</small>{asset.source_hashtags.length > 0 && <p className="review-hashtags">{asset.source_hashtags.map((tag) => `#${tag}`).join(" ")}</p>}{asset.quality_warnings.length > 0 && <p>{asset.quality_warnings.join(" / ")}</p>}</div>
        </article>)}
      </div>
      {!assets.length && <p className="acquisition-empty review-empty">此状态下没有素材。</p>}
      {assetPagination.totalPages > 0 && <div className="acquisition-pagination review-pagination" aria-label="审核素材分页">
        <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={assetLoading || assetOffset === 0} onClick={() => void goToAssetOffset(assetOffset - acquisitionAssetPageSize)}><ChevronLeft size={22} /></button>
        <span className="pagination-summary">第 {assetPagination.currentPage} / {assetPagination.totalPages} 页 · {assetPagination.rangeStart}-{assetPagination.rangeEnd} / {assetsTotal}</span>
        <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={assetLoading || assetOffset + acquisitionAssetPageSize >= assetsTotal} onClick={() => void goToAssetOffset(assetOffset + acquisitionAssetPageSize)}><ChevronRight size={22} /></button>
        <form className="pagination-jump" onSubmit={submitAssetPageJump}>
          <label htmlFor="acquisition-page-number">跳至</label>
          <input id="acquisition-page-number" type="number" min={1} max={assetPagination.totalPages} step={1} value={assetJumpPage} onChange={(event) => setAssetJumpPage(event.target.value)} aria-label="审核素材页码" />
          <button type="submit" disabled={assetLoading || !assetJumpPage}>跳转</button>
        </form>
      </div>}</>}
      {reviewMode === "similarity" && <section className="similarity-workspace" aria-label="相似图片整理">
        {similarity.task && <div className={`similarity-task status-${similarity.task.status}`}>
          <div><strong>{statusLabel(similarity.task.status)}</strong><span>{similarity.task.message ?? "正在处理相似图片"}</span></div>
          <progress value={similarity.task.progress} max={1} aria-label="相似扫描进度" />
          <small>{Math.round(similarity.task.progress * 100)}%</small>
        </div>}
        {similarity.is_stale && <div className="similarity-alert">{similarity.scope === "pending_to_gallery" ? "扫描后待审核区或图库有新增图片，当前结果可能不完整，请重新扫描。" : "扫描后又有新的待审核图片进入，当前结果可能不完整，请重新扫描。"}</div>}
        {similarity.task?.status === "failed" && <div className="similarity-alert error">{similarity.task.message ?? "扫描失败，上一次结果已保留。"}</div>}
        <div className={similarityLoading ? "similarity-groups loading" : "similarity-groups"} aria-busy={similarityLoading}>
          {similarity.groups.map((group, groupIndex) => {
            const groupIds = group.members.map((asset) => asset.id);
            const allSelected = groupIds.every((id) => selectedAssets.includes(id));
            return <article className="similarity-group" key={group.id}>
              <header>
                <div><strong>相似组 {similarity.offset + groupIndex + 1}</strong><small>{group.members.length + group.gallery_members.length} 张 · 最高 {Math.round(group.max_score * 100)}% · {group.recommendation_status === "close_quality" ? "质量接近" : group.face_quality_enabled ? "整体 + 人脸" : "仅整体"}</small></div>
                <button type="button" className="secondary-command" onClick={() => setSelectedAssets((current) => allSelected
                  ? current.filter((id) => !groupIds.includes(id))
                  : [...new Set([...current, ...groupIds])]
                )}>{allSelected ? "取消本组" : "选择本组"}</button>
              </header>
              <div className="similarity-members">{group.members.map((asset) => <div className={selectedAssets.includes(asset.id) ? "similarity-member selected" : "similarity-member"} key={asset.id}>
                <button type="button" className="similarity-image-button" onClick={() => setSimilarityLightbox({ groupId: group.id, assetId: asset.id })} aria-label={`查看大图 ${asset.filename}`}>
                  {asset.preview_url ? <img src={getAcquisitionPreviewUrl(asset.preview_url, 480)} alt={asset.filename} loading="lazy" decoding="async" /> : <span>文件已清除</span>}
                </button>
                <label><input type="checkbox" checked={selectedAssets.includes(asset.id)} onChange={() => toggleAsset(asset.id)} /><span title={asset.filename}>{asset.filename}</span></label>
                <small className="similarity-source-label">待审核{asset.recommended_keep ? " · 建议保留" : ""}{asset.similarity_quality_score !== null ? ` · 综合 ${asset.similarity_quality_score.toFixed(1)} · 整体 ${(asset.overall_quality_score ?? 0).toFixed(1)}${asset.face_quality_score !== null ? ` · 人脸 ${asset.face_quality_score.toFixed(1)}` : ""}` : ""}</small>
              </div>)}{group.gallery_members.map((member) => <div className="similarity-member gallery-readonly" key={`gallery-${member.photo.id}`}>
                <a className="similarity-image-button" href={member.photo.original_url} target="_blank" rel="noreferrer" aria-label={`查看图库原图 ${member.photo.filename}`}>
                  <img src={member.photo.thumbnail_url} alt={member.photo.filename} loading="lazy" decoding="async" />
                </a>
                <div className="similarity-gallery-meta"><span title={member.photo.filename}>{member.photo.filename}</span><small>图库 · 相似 {Math.round(member.score * 100)}% · 综合 {member.quality_score.toFixed(1)} · 整体 {member.overall_quality_score.toFixed(1)}{member.face_quality_score !== null ? ` · 人脸 ${member.face_quality_score.toFixed(1)}` : ""}{member.recommended_keep ? " · 建议保留" : ""}</small></div>
              </div>)}</div>
            </article>;
          })}
        </div>
        {!similarityLoading && !similarity.groups.length && <div className="similarity-empty">
          <ScanSearch size={26} />
          <strong>{similarity.generated_at ? "没有发现相似图片" : "尚未扫描待审核图片"}</strong>
          <span>{similarity.generated_at ? (similarityScope === "pending_only" ? "当前待审核图片之间没有达到阈值的相似关系。" : "待审核图片与图库之间没有达到阈值的相似关系。") : "点击“扫描相似”开始整理。"}</span>
        </div>}
        {similarityPagination.totalPages > 1 && <div className="acquisition-pagination" aria-label="相似组分页">
          <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={similarityLoading || similarityOffset === 0} onClick={() => goToSimilarityOffset(similarityOffset - similarityGroupPageSize)}><ChevronLeft size={18} /></button>
          <span className="pagination-summary">第 {similarityPagination.currentPage} / {similarityPagination.totalPages} 页 · {similarity.total} 组</span>
          <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={similarityLoading || similarityOffset + similarityGroupPageSize >= similarity.total} onClick={() => goToSimilarityOffset(similarityOffset + similarityGroupPageSize)}><ChevronRight size={18} /></button>
        </div>}
      </section>}
    </section>}

    {tab === "history" && <section className="acquisition-grid history-layout">
      <div className="acquisition-section import-batch-list">
        <div className="acquisition-section-title">
          <span>入库批次</span>
          <small>{importBatchesTotal} 个批次{unassignedImportedCount > 0 ? ` · ${unassignedImportedCount} 项历史素材未关联批次` : ""}</small>
        </div>
        <div className="import-history-toolbar">
          <label>批次日期</label>
          <input type="date" aria-label="批次开始日期" value={batchDateFrom} onChange={(event) => { setBatchDateFrom(event.target.value); setImportBatchOffset(0); setImportBatchItemOffset(0); }} />
          <span>至</span>
          <input type="date" aria-label="批次结束日期" value={batchDateTo} onChange={(event) => { setBatchDateTo(event.target.value); setImportBatchOffset(0); setImportBatchItemOffset(0); }} />
        </div>
        <div className="import-batch-scroll" aria-busy={importHistoryLoading}>
          {unassignedImportedCount > 0 && <button
            type="button"
            className={`import-batch-line legacy ${selectedImportBatchId === "unassigned" ? "selected" : ""}`}
            aria-pressed={selectedImportBatchId === "unassigned"}
            onClick={() => { setSelectedImportBatchId("unassigned"); setImportBatchItemOffset(0); setExpandedImportAssetId(null); }}
          >
            <div><strong>历史导入（未关联批次）</strong><small>升级前或恢复流程写入的成功溯源</small></div>
            <span className="import-batch-state">
              <span className="acquisition-status status-completed">{unassignedImportedCount} 张</span>
              <span className="import-batch-current" aria-hidden="true"><Check size={16} /></span>
            </span>
          </button>}
          {importBatches.map((batch) => <button
            type="button"
            className={`import-batch-line ${selectedImportBatchId === batch.id ? "selected" : ""}`}
            key={batch.id}
            aria-pressed={selectedImportBatchId === batch.id}
            onClick={() => { setSelectedImportBatchId(batch.id); setImportBatchItemOffset(0); setExpandedImportAssetId(null); }}
          >
            <div><strong>{formatDate(batch.created_at)} · 选择 {batch.total_count} 张</strong><small>已处理 {batch.processed_count} · 成功 {batch.imported_count} · 重复 {batch.duplicate_count} · 失败 {batch.failed_count}</small></div>
            <span className="import-batch-state">
              <span className="import-batch-type">{batch.has_video && batch.has_image ? (batch.is_rich_text ? "图文 + 视频" : "图片 + 视频") : batch.has_video && !batch.has_image ? "视频" : batch.is_rich_text ? "图文图片" : "普通图片"}</span>
              <span className={`acquisition-status status-${batch.status}`}>{statusLabel(batch.status)}</span>
              <span className="import-batch-current" aria-hidden="true"><Check size={16} /></span>
            </span>
          </button>)}
          {!importBatches.length && unassignedImportedCount === 0 && <p className="acquisition-empty">尚无入库批次。</p>}
        </div>
        {importBatchPagination.totalPages > 1 && <div className="acquisition-pagination compact" aria-label="入库批次分页">
          <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={importHistoryLoading || importBatchOffset === 0} onClick={() => setImportBatchOffset(Math.max(0, importBatchOffset - importBatchPageSize))}><ChevronLeft size={17} /></button>
          <span>第 {importBatchPagination.currentPage} / {importBatchPagination.totalPages} 页 · {importBatchPagination.rangeStart}-{importBatchPagination.rangeEnd} / {importBatchesTotal}</span>
          <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={importHistoryLoading || importBatchOffset + importBatchPageSize >= importBatchesTotal} onClick={() => setImportBatchOffset(importBatchOffset + importBatchPageSize)}><ChevronRight size={17} /></button>
        </div>}
      </div>

      <div className="acquisition-section history-list">
        <div className="acquisition-section-title">
          <span>入库溯源</span>
          <small>{selectedImportBatchId ? `${importBatchItemsTotal} 项` : "请先选择批次"}</small>
        </div>
        <div className="import-history-toolbar">
          <label htmlFor="import-result-status">处理结果</label>
          <select id="import-result-status" value={importBatchItemStatus} onChange={(event) => { setImportBatchItemStatus(event.target.value); setImportBatchItemOffset(0); setExpandedImportAssetId(null); }}>
            <option value="all">全部结果</option>
            <option value="imported">成功入库</option>
            <option value="gallery_duplicate">库中已存在</option>
            <option value="failed">导入失败</option>
          </select>
        </div>
        <div className="history-detail-scroll" aria-busy={importHistoryLoading}>
          {importBatchItems.map((item) => {
            const expanded = expandedImportAssetId === item.asset_id;
            const galleryLabel = item.target_type === "video"
              ? (item.video_id ? `视频 #${item.video_id}` : "未生成视频")
              : item.gallery_available
                ? `图库 #${item.gallery_photo_id}`
                : item.gallery_photo_snapshot_id
                  ? `原图库 #${item.gallery_photo_snapshot_id}（文件已删除）`
                  : "未生成图库图片";
            return <article className={`history-detail-row ${expanded ? "expanded" : ""}`} key={item.asset_id}>
              <button type="button" className="history-detail-summary" aria-expanded={expanded} onClick={() => setExpandedImportAssetId(expanded ? null : item.asset_id)}>
                <span className={item.gallery_available ? "history-dot" : "history-dot missing"} />
                <span className="history-detail-name"><strong>{item.filename}</strong><small>{galleryLabel} · {item.origins.length} 个来源</small></span>
                <span className={`acquisition-status status-${item.status}`}>{statusLabel(item.status)}</span>
                <ChevronRight className="history-expand-icon" size={17} />
              </button>
              {expanded && <div className="history-detail-expanded">
                <dl>
                  <div><dt>SHA256</dt><dd>{item.sha256}</dd></div>
                  <div><dt>入库时间</dt><dd>{item.imported_at ? formatDate(item.imported_at) : "未成功入库"}</dd></div>
                  <div><dt>处理次数</dt><dd>{item.attempt_count}</dd></div>
                  {item.error_message && <div><dt>错误</dt><dd>{item.error_message}</dd></div>}
                </dl>
                <div className="history-origins">
                  <strong>采集来源</strong>
                  {item.origins.map((origin) => <p key={origin.run_id}>{origin.source_name} / {origin.category_name} · {formatDate(origin.run_created_at)} · 运行 {origin.run_id}</p>)}
                  {!item.origins.length && <p>未找到关联采集运行。</p>}
                </div>
              </div>}
            </article>;
          })}
          {selectedImportBatchId && !importBatchItems.length && <p className="acquisition-empty">当前筛选下没有素材。</p>}
          {!selectedImportBatchId && <p className="acquisition-empty">从上方选择一个入库批次查看逐图结果。</p>}
        </div>
        {importBatchItemPagination.totalPages > 1 && <div className="acquisition-pagination compact" aria-label="入库溯源分页">
          <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={importHistoryLoading || importBatchItemOffset === 0} onClick={() => setImportBatchItemOffset(Math.max(0, importBatchItemOffset - importBatchItemPageSize))}><ChevronLeft size={17} /></button>
          <span>第 {importBatchItemPagination.currentPage} / {importBatchItemPagination.totalPages} 页 · {importBatchItemPagination.rangeStart}-{importBatchItemPagination.rangeEnd} / {importBatchItemsTotal}</span>
          <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={importHistoryLoading || importBatchItemOffset + importBatchItemPageSize >= importBatchItemsTotal} onClick={() => setImportBatchItemOffset(importBatchItemOffset + importBatchItemPageSize)}><ChevronRight size={17} /></button>
        </div>}
      </div>

      <div className="acquisition-section export-workspace">
        <div className="acquisition-section-title"><span>创建导出与导出任务</span><small>{exports.length} 个任务</small></div>
        <div className="export-create-row">
          <Archive size={17} aria-hidden="true" />
          <select aria-label="导出范围" value={exportScope} onChange={(event) => { setExportScope(event.target.value as typeof exportScope); setExportScopeId(""); }}><option value="all">全部已入图库图片</option><option value="source">按站点</option><option value="category">按分类</option><option value="run">按单次运行</option></select>
          {exportScope !== "all" && <select aria-label="导出具体范围" value={exportScopeId} onChange={(event) => setExportScopeId(event.target.value)}><option value="">选择范围</option>{activeScopeOptions.map((item) => <option key={item.id} value={item.id}>{"mode" in item ? `${item.category_name} · ${formatDate(item.created_at)}` : "source_id" in item ? `${sourceById.get(item.source_id)?.name ?? "站点"} / ${item.name}` : item.name}</option>)}</select>}
          <div className="history-date-range"><input type="date" aria-label="导出开始日期" value={exportDateFrom} onChange={(event) => setExportDateFrom(event.target.value)} /><span>至</span><input type="date" aria-label="导出结束日期" value={exportDateTo} onChange={(event) => setExportDateTo(event.target.value)} /></div>
          <button type="button" disabled={busy || (exportScope !== "all" && !exportScopeId)} onClick={() => void perform(async () => {
            const value = exportScopeId || undefined;
            const dateRange = {
              date_from: exportDateFrom ? toShanghaiDateTimeBoundary(exportDateFrom, "start") : undefined,
              date_to: exportDateTo ? toShanghaiDateTimeBoundary(exportDateTo, "end") : undefined
            };
            await createAcquisitionExport(exportScope === "all" ? dateRange : exportScope === "source" ? { ...dateRange, source_id: Number(value) } : exportScope === "category" ? { ...dateRange, category_id: Number(value) } : { ...dateRange, run_id: value });
          }, "导出任务已创建")}>创建 ZIP</button>
        </div>
        <small className="export-note">仅导出最终入图库且当前仍存在的图片，缺失项会写入 ZIP 元数据。</small>
        <div className="export-task-scroll">
          {exports.map((job) => <article className="export-line" key={job.id}><div><strong>{job.filename ?? "正在生成 ZIP"}</strong><small>{formatDate(job.created_at)} · {job.item_count} 张 · 缺失 {job.missing_count}</small></div><div><span className={`acquisition-status status-${job.status}`}>{statusLabel(job.status)}</span>{job.download_url && <a className="icon-button" href={acquisitionDownloadUrl(job.download_url)} title="下载 ZIP" aria-label="下载 ZIP"><Download size={16} /></a>}</div></article>)}
          {!exports.length && <p className="acquisition-empty">尚无导出任务。</p>}
        </div>
      </div>
    </section>}

  </main>

    {lightboxAsset?.original_url && <AcquisitionReviewLightbox
      asset={lightboxAsset}
      statusLabel={statusLabel(assetStatus)}
      indexLabel={`${lightboxGlobalIndex + 1} / ${lightboxSnapshotIds.length}`}
      selected={selectedAssets.includes(lightboxAsset.id)}
      canDelete={canDelete}
      canCapture={canAdd && assetStatus === "pending_review"}
      onCaptured={handleFrameCaptured}
      onViewCapture={viewCapturedAsset}
      busy={assetActionBusy || lightboxNavigationBusy}
      canGoPrevious={canGoToPreviousAsset}
      canGoNext={canGoToNextAsset}
      onClose={closeReviewLightbox}
      onPrevious={() => navigateLightbox(-1)}
      onNext={() => navigateLightbox(1)}
      onToggleSelect={() => toggleAsset(lightboxAsset.id)}
      onReject={() => void rejectLightboxAsset()}
    />}

    {similarityLightboxAsset?.original_url && similarityLightboxGroup && <PhotoLightbox
      image={{ src: similarityLightboxAsset.original_url, alt: similarityLightboxAsset.filename }}
      backdropClassName="acquisition-review-lightbox-backdrop"
      shellClassName="acquisition-review-lightbox similarity-lightbox"
      busy={busy || similarityLoading}
      canGoPrevious={similarityLightboxIndex > 0}
      canGoNext={similarityLightboxIndex + 1 < similarityLightboxGroup.members.length}
      onClose={() => setSimilarityLightbox(null)}
      onPrevious={() => {
        const asset = similarityLightboxGroup.members[similarityLightboxIndex - 1];
        if (asset) setSimilarityLightbox({ groupId: similarityLightboxGroup.id, assetId: asset.id });
      }}
      onNext={() => {
        const asset = similarityLightboxGroup.members[similarityLightboxIndex + 1];
        if (asset) setSimilarityLightbox({ groupId: similarityLightboxGroup.id, assetId: asset.id });
      }}
      onKeyDown={(event) => {
        handleAcquisitionLightboxShortcut(event, "image", {
          onToggleSelect: () => toggleAsset(similarityLightboxAsset.id),
          onReject: canDelete ? () => void rejectSimilarityAssets([similarityLightboxAsset.id]) : undefined
        });
      }}
      meta={<>
        <div className="acquisition-lightbox-heading">
          <div><p className="acquisition-eyebrow">相似整理</p><h2>{similarityLightboxGroup.members.length} 张相似图片</h2></div>
          <strong>{similarityLightboxIndex + 1} / {similarityLightboxGroup.members.length}</strong>
        </div>
        <div className="similarity-lightbox-strip" aria-label="当前相似组">{similarityLightboxGroup.members.map((asset) => <button
          type="button"
          className={asset.id === similarityLightboxAsset.id ? "active" : ""}
          key={asset.id}
          onClick={() => setSimilarityLightbox({ groupId: similarityLightboxGroup.id, assetId: asset.id })}
          title={asset.filename}
        >{asset.preview_url ? <img src={getAcquisitionPreviewUrl(asset.preview_url, 480)} alt="" loading="lazy" decoding="async" /> : <span>缺失</span>}</button>)}</div>
        <dl className="acquisition-lightbox-facts">
          <div><dt>文件名</dt><dd title={similarityLightboxAsset.filename}>{similarityLightboxAsset.filename}</dd></div>
          <div><dt>尺寸</dt><dd>{similarityLightboxAsset.width && similarityLightboxAsset.height ? `${similarityLightboxAsset.width} × ${similarityLightboxAsset.height}` : "未知"}</dd></div>
          <div><dt>大小</dt><dd>{formatBytes(similarityLightboxAsset.size_bytes)}</dd></div>
          {similarityLightboxAsset.similarity_quality_score !== null && <div><dt>质量评分</dt><dd>综合 {similarityLightboxAsset.similarity_quality_score.toFixed(1)} · 整体 {(similarityLightboxAsset.overall_quality_score ?? 0).toFixed(1)}{similarityLightboxAsset.face_quality_score !== null ? ` · 人脸 ${similarityLightboxAsset.face_quality_score.toFixed(1)}` : ""}</dd></div>}
        </dl>
        <div className="acquisition-lightbox-actions">
          <button type="button" className={selectedAssets.includes(similarityLightboxAsset.id) ? "selected" : ""} onClick={() => toggleAsset(similarityLightboxAsset.id)} disabled={busy}>
            <Check size={17} /> {selectedAssets.includes(similarityLightboxAsset.id) ? "取消选择" : "选中当前"}
          </button>
          {canDelete && <button type="button" className="danger-command" onClick={() => void rejectSimilarityAssets(selectedAssets.length ? selectedAssets : [similarityLightboxAsset.id])} disabled={busy}>
            <Trash2 size={17} /> {selectedAssets.length ? `丢弃选中 ${selectedAssets.length} 张` : "丢弃当前"}
          </button>}
        </div>
      </>}
    />}
  </>;
}
