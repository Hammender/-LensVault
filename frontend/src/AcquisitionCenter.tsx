import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Archive, Check, CheckCheck, ChevronLeft, ChevronRight, Download, FolderPlus, Images, Link2, LoaderCircle, Pencil, Play, Plus, RotateCcw, ScanSearch, Trash2, X } from "lucide-react";

import {
  acquisitionDownloadUrl,
  bindAcquisitionScript,
  changeAcquisitionAssets,
  createAcquisitionCategory,
  createAcquisitionExport,
  createAcquisitionSource,
  deleteAcquisitionCategory,
  deleteAcquisitionSource,
  getAcquisitionAssetSummary,
  listAcquisitionAssetIds,
  listAcquisitionAssets,
  listAcquisitionCategories,
  listAcquisitionExports,
  listAcquisitionImportBatchItems,
  listAcquisitionImportBatches,
  listAcquisitionRuns,
  listAcquisitionScripts,
  listAcquisitionSimilarity,
  listAcquisitionSources,
  startAcquisitionRun,
  startAcquisitionSimilarityScan,
  unbindAcquisitionScript,
  updateAcquisitionCategory,
  updateAcquisitionSource
} from "./api/acquisition";
import {
  acquisitionAssetPageSize,
  clampAcquisitionOffset,
  createAcquisitionStatusReset,
  getAcquisitionPageFill,
  getAcquisitionRejectContinuation,
  getAcquisitionPreviewUrl,
  getAcquisitionLightboxShortcut,
  getAcquisitionPagination,
  hasSelectedAllAcquisitionAssets,
  isAcquisitionPageFillValid,
  isAcquisitionImportBatchActive,
  removeAcquisitionSelection,
  toggleAcquisitionSelection
} from "./acquisitionReview";
import {
  defaultAcquisitionRunParameters,
  getAcquisitionRunFormConfiguration
} from "./acquisitionRunForm";
import { useConfirm } from "./ConfirmDialog";
import PhotoLightbox from "./PhotoLightbox";
import type {
  AcquisitionAsset,
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
} from "./types";
import { formatBytes, formatDate, toShanghaiDateTimeBoundary } from "./utils";
import "./AcquisitionCenter.css";

type Tab = "sources" | "runs" | "review" | "history";

type AcquisitionCenterProps = {
  canEdit: boolean;
  canAdd: boolean;
  canDelete: boolean;
};

const tabs: Array<{ key: Tab; label: string }> = [
  { key: "sources", label: "站点与分类" },
  { key: "runs", label: "运行记录" },
  { key: "review", label: "待审核" },
  { key: "history", label: "入库与导出" }
];

const importBatchPageSize = 15;
const importBatchItemPageSize = 40;
const similarityGroupPageSize = 12;

function statusLabel(status: string): string {
  return ({
    pending: "等待中", running: "运行中", completed: "已完成", interrupted: "已中断", failed: "失败",
    pending_review: "待审核", imported: "已入图库", rejected: "已丢弃",
    import_queued: "等待入库", importing: "正在入库", import_failed: "入库失败",
    gallery_duplicate: "图库已存在", completed_with_errors: "部分失败", ready: "可下载", downloaded: "已下载", expired: "已过期"
  } as Record<string, string>)[status] ?? status;
}

function runStopLabel(run: AcquisitionRun): string | null {
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

export default function AcquisitionCenter({ canEdit, canAdd, canDelete }: AcquisitionCenterProps) {
  const confirm = useConfirm();
  const [tab, setTab] = useState<Tab>("sources");
  const [sources, setSources] = useState<AcquisitionSource[]>([]);
  const [categories, setCategories] = useState<AcquisitionCategory[]>([]);
  const [scripts, setScripts] = useState<AcquisitionScript[]>([]);
  const [runs, setRuns] = useState<AcquisitionRun[]>([]);
  const [assets, setAssets] = useState<AcquisitionAsset[]>([]);
  const [assetsTotal, setAssetsTotal] = useState(0);
  const [assetOffset, setAssetOffset] = useState(0);
  const [assetJumpPage, setAssetJumpPage] = useState("");
  const [assetLoading, setAssetLoading] = useState(false);
  const [lightboxSelection, setLightboxSelection] = useState<{ asset: AcquisitionAsset; globalIndex: number } | null>(null);
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
  const [similarity, setSimilarity] = useState<AcquisitionSimilarityResult>({
    task: null, generated_at: null, is_stale: false, groups: [], total: 0, offset: 0, limit: similarityGroupPageSize
  });
  const [similarityOffset, setSimilarityOffset] = useState(0);
  const [similarityLoading, setSimilarityLoading] = useState(false);
  const [similarityLightbox, setSimilarityLightbox] = useState<{ groupId: string; assetId: string } | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceNotes, setSourceNotes] = useState("");
  const [editingSourceId, setEditingSourceId] = useState<number | null>(null);
  const [sourceScriptChoices, setSourceScriptChoices] = useState<Record<number, string>>({});
  const [categorySourceId, setCategorySourceId] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [categoryUrl, setCategoryUrl] = useState("");
  const [categoryNotes, setCategoryNotes] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [runCategoryId, setRunCategoryId] = useState("");
  const [runScriptKey, setRunScriptKey] = useState("");
  const [runParameters, setRunParameters] = useState<Record<string, string | boolean>>({});
  const [runMode, setRunMode] = useState<"incremental" | "full" | "verify">("incremental");
  const [assetStatus, setAssetStatus] = useState("pending_review");
  const [exportScope, setExportScope] = useState<"all" | "source" | "category" | "run">("all");
  const [exportScopeId, setExportScopeId] = useState("");
  const [batchDateFrom, setBatchDateFrom] = useState("");
  const [batchDateTo, setBatchDateTo] = useState("");
  const [exportDateFrom, setExportDateFrom] = useState("");
  const [exportDateTo, setExportDateTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const assetRequestIdRef = useRef(0);
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
  const assetPagination = getAcquisitionPagination(assetsTotal, assetOffset, assets.length, acquisitionAssetPageSize);
  const areAllReviewAssetsSelected = hasSelectedAllAcquisitionAssets(selectedAssets, assetsTotal);
  const lightboxAsset = lightboxSelection?.asset ?? null;
  const lightboxAssetIndex = lightboxAsset ? assets.findIndex((asset) => asset.id === lightboxAsset.id) : -1;
  const lightboxGlobalIndex = lightboxAssetIndex >= 0
    ? assetOffset + lightboxAssetIndex
    : lightboxSelection?.globalIndex ?? -1;
  const previousPreviewIndex = lightboxAssetIndex >= 0
    ? findPreviewableIndexInDirection(assets, lightboxAssetIndex - 1, -1)
    : -1;
  const nextPreviewIndex = lightboxAssetIndex >= 0
    ? findPreviewableIndexInDirection(assets, lightboxAssetIndex + 1, 1)
    : -1;
  const canGoToPreviousAsset = lightboxAssetIndex >= 0 && (previousPreviewIndex >= 0 || assetOffset > 0);
  const canGoToNextAsset = lightboxAssetIndex >= 0
    && (nextPreviewIndex >= 0 || assetOffset + assets.length < assetsTotal);
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
    const [scriptsResult, sourcesResult, categoriesResult, runsResult, exportsResult, summaryResult] = await Promise.all([
      settleRequest(listAcquisitionScripts()), settleRequest(listAcquisitionSources()),
      settleRequest(listAcquisitionCategories()), settleRequest(listAcquisitionRuns()),
      settleRequest(listAcquisitionExports()), settleRequest(getAcquisitionAssetSummary())
    ]);
    if (scriptsResult.data) setScripts(scriptsResult.data);
    if (sourcesResult.data) {
      setSources(sourcesResult.data);
      setCategorySourceId((current) => current || (sourcesResult.data?.[0] ? String(sourcesResult.data[0].id) : ""));
    }
    if (categoriesResult.data) {
      setCategories(categoriesResult.data);
      setRunCategoryId((current) => categoriesResult.data?.some((category) => String(category.id) === current) ? current : "");
    }
    if (runsResult.data) setRuns(runsResult.data);
    if (exportsResult.data) setExports(exportsResult.data);
    if (summaryResult.data) setAssetSummary(summaryResult.data);
    const failed = [scriptsResult, sourcesResult, categoriesResult, runsResult, exportsResult, summaryResult]
      .find((result) => result.error);
    if (failed?.error) throw failed.error;
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

  const loadAssetPage = useCallback(async (status: string, requestedOffset: number): Promise<PaginatedAcquisitionAssets | null> => {
    const requestId = assetRequestIdRef.current + 1;
    assetRequestIdRef.current = requestId;
    setAssetLoading(true);
    try {
      let page = await listAcquisitionAssets(status, Math.max(0, requestedOffset), acquisitionAssetPageSize);
      const validOffset = clampAcquisitionOffset(page.total, requestedOffset, acquisitionAssetPageSize);
      if (validOffset !== page.offset) {
        page = await listAcquisitionAssets(status, validOffset, acquisitionAssetPageSize);
      }
      if (requestId !== assetRequestIdRef.current) return null;
      setAssets(page.items);
      setAssetsTotal(page.total);
      setAssetOffset(page.offset);
      return page;
    } finally {
      if (requestId === assetRequestIdRef.current) setAssetLoading(false);
    }
  }, []);

  const loadSimilarityPage = useCallback(async (requestedOffset: number): Promise<AcquisitionSimilarityResult> => {
    setSimilarityLoading(true);
    try {
      let result = await listAcquisitionSimilarity(Math.max(0, requestedOffset), similarityGroupPageSize);
      const validOffset = clampAcquisitionOffset(result.total, requestedOffset, similarityGroupPageSize);
      if (validOffset !== result.offset) {
        result = await listAcquisitionSimilarity(validOffset, similarityGroupPageSize);
      }
      setSimilarity(result);
      setSimilarityOffset(result.offset);
      setSimilarityLightbox((current) => current && result.groups.some((group) =>
        group.id === current.groupId && group.members.some((asset) => asset.id === current.assetId)
      ) ? current : null);
      return result;
    } finally {
      setSimilarityLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    const requests: Promise<unknown>[] = [
      refreshReferenceData(),
      loadAssetPage(assetStatus, assetOffset),
      loadSimilarityPage(similarityOffset),
      loadImportBatchPage(importBatchOffset)
    ];
    if (selectedImportBatchId) {
      requests.push(loadImportBatchItemPage(selectedImportBatchId, importBatchItemOffset));
    }
    await Promise.all(requests);
  }, [assetOffset, assetStatus, importBatchItemOffset, importBatchOffset, loadAssetPage, loadImportBatchItemPage, loadImportBatchPage, loadSimilarityPage, refreshReferenceData, selectedImportBatchId, similarityOffset]);

  useEffect(() => { void refreshReferenceData().catch((error: Error) => setNotice(error.message)); }, [refreshReferenceData]);

  useEffect(() => {
    void loadSimilarityPage(similarityOffset).catch((error: Error) => setNotice(error.message));
  }, [loadSimilarityPage, similarityOffset]);

  useEffect(() => {
    void loadAssetPage(assetStatus, 0).catch((error: Error) => setNotice(error.message));
  }, [assetStatus, loadAssetPage]);

  useEffect(() => {
    void loadImportBatchPage(importBatchOffset).catch((error: Error) => setNotice(error.message));
  }, [importBatchOffset, loadImportBatchPage]);

  useEffect(() => {
    if (!selectedImportBatchId) {
      setImportBatchItems([]);
      setImportBatchItemsTotal(0);
      return;
    }
    void loadImportBatchItemPage(selectedImportBatchId, importBatchItemOffset)
      .catch((error: Error) => setNotice(error.message));
  }, [importBatchItemOffset, loadImportBatchItemPage, selectedImportBatchId]);

  useEffect(() => {
    if (!runs.some((run) => run.status === "pending" || run.status === "running")) return;
    const timer = window.setInterval(() => {
      void listAcquisitionRuns().then(setRuns).catch((error: Error) => setNotice(error.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runs]);

  useEffect(() => {
    if (!importBatches.some((batch) => isAcquisitionImportBatchActive(batch.status))) return;
    const timer = window.setInterval(() => {
      void refresh().catch((error: Error) => setNotice(error.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [importBatches, refresh]);

  useEffect(() => {
    if (!similarity.task || !["pending", "running"].includes(similarity.task.status)) return;
    const timer = window.setInterval(() => {
      void loadSimilarityPage(similarityOffset).catch((error: Error) => setNotice(error.message));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [loadSimilarityPage, similarity.task, similarityOffset]);

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
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作未完成");
    } finally {
      setBusy(false);
    }
  }

  async function performSelectedAssetAction(action: "import" | "reject", message: string) {
    const assetIds = [...selectedAssets];
    if (!assetIds.length) return;
    await perform(async () => {
      await changeAcquisitionAssets(action, assetIds);
      setSelectedAssets((current) => removeAcquisitionSelection(current, assetIds));
      if (lightboxAsset && assetIds.includes(lightboxAsset.id)) setLightboxSelection(null);
    }, message);
  }

  async function startSimilarityScan() {
    setBusy(true);
    setNotice(null);
    try {
      const task = await startAcquisitionSimilarityScan();
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
      title: `丢弃选中的 ${uniqueIds.length} 张图片？`,
      message: "将立即删除这些临时文件并保留拒绝状态和来源记录，此操作无法撤销。",
      confirmLabel: "确认丢弃",
      tone: "danger"
    });
    if (!confirmed) return;
    setBusy(true);
    setNotice(null);
    try {
      await changeAcquisitionAssets("reject", uniqueIds);
      setSelectedAssets((current) => removeAcquisitionSelection(current, uniqueIds));
      setSimilarityLightbox(null);
      await Promise.all([
        loadSimilarityPage(similarityOffset),
        loadAssetPage(assetStatus, assetOffset),
        refreshReferenceData()
      ]);
      setNotice(`已丢弃 ${uniqueIds.length} 张临时图片`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "图片丢弃失败");
    } finally {
      setBusy(false);
    }
  }

  function goToSimilarityOffset(nextOffset: number) {
    setSelectedAssets([]);
    setSimilarityLightbox(null);
    setSimilarityOffset(Math.max(0, nextOffset));
  }

  function resetSourceForm() {
    setEditingSourceId(null);
    setSourceName("");
    setSourceUrl("");
    setSourceNotes("");
  }

  function editSource(source: AcquisitionSource) {
    setEditingSourceId(source.id);
    setSourceName(source.name);
    setSourceUrl(source.base_url);
    setSourceNotes(source.notes ?? "");
  }

  async function submitSource(event: FormEvent) {
    event.preventDefault();
    if (!sourceName.trim() || !sourceUrl.trim()) return;
    await perform(async () => {
      const payload = { name: sourceName.trim(), base_url: sourceUrl.trim(), notes: sourceNotes.trim() || null };
      if (editingSourceId) await updateAcquisitionSource(editingSourceId, payload);
      else await createAcquisitionSource(payload);
      resetSourceForm();
    }, editingSourceId ? "站点信息已更新" : "站点已创建");
  }

  function resetCategoryForm() {
    setEditingCategoryId(null);
    setCategoryName("");
    setCategoryUrl("");
    setCategoryNotes("");
  }

  function editCategory(category: AcquisitionCategory) {
    setEditingCategoryId(category.id);
    setCategorySourceId(String(category.source_id));
    setCategoryName(category.name);
    setCategoryUrl(category.crawl_url);
    setCategoryNotes(category.notes ?? "");
  }

  async function submitCategory(event: FormEvent) {
    event.preventDefault();
    if (!categorySourceId || !categoryName.trim() || !categoryUrl.trim()) return;
    await perform(async () => {
      const payload = { name: categoryName.trim(), crawl_url: categoryUrl.trim(), notes: categoryNotes.trim() || null };
      if (editingCategoryId) await updateAcquisitionCategory(editingCategoryId, payload);
      else await createAcquisitionCategory(Number(categorySourceId), payload);
      resetCategoryForm();
    }, editingCategoryId ? "分类信息已更新" : "分类已创建");
  }

  function selectRunCategory(categoryId: string) {
    setRunCategoryId(categoryId);
    const category = categoryById.get(Number(categoryId));
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
    setNotice(`已载入“${run.category_name}”的运行配置，请确认后开始采集`);
    window.requestAnimationFrame(() => runLauncherRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function runPayloadParameters(): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const parameter of selectedRunScript?.parameters ?? []) {
      const value = runParameters[parameter.key];
      if (value === "" && !parameter.required) continue;
      if (parameter.type === "integer" || parameter.type === "number") result[parameter.key] = Number(value);
      else result[parameter.key] = value;
    }
    const startPage = Number(result.start_page ?? 1);
    const endPage = result.end_page == null ? null : Number(result.end_page);
    if (endPage != null && endPage < startPage) throw new Error("结束页不能小于起始页");
    return result;
  }

  function toggleAsset(id: string) {
    setSelectedAssets((items) => toggleAcquisitionSelection(items, id));
  }

  function showLightboxAsset(asset: AcquisitionAsset, index: number, offset = assetOffset) {
    setLightboxSelection({ asset, globalIndex: offset + index });
  }

  function changeReviewMode(nextMode: "list" | "similarity") {
    setReviewMode(nextMode);
    setSelectedAssets([]);
    setLightboxSelection(null);
    setSimilarityLightbox(null);
  }

  async function selectAllReviewAssets() {
    if (busy || assetsTotal === 0) return;
    if (areAllReviewAssetsSelected) {
      setSelectedAssets([]);
      setNotice("已取消选择全部图片");
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const assetIds = await listAcquisitionAssetIds(assetStatus);
      setSelectedAssets(assetIds);
      setNotice(`已选中当前状态下的全部 ${assetIds.length} 张图片`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "全选图片失败");
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
    setLightboxSelection(null);
    setAssetOffset(reset.offset);
    setAssetJumpPage(reset.jumpPage);
    setAssetStatus(reset.status);
  }

  async function goToAssetOffset(nextOffset: number) {
    setNotice(null);
    try {
      await loadAssetPage(assetStatus, nextOffset);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "图片列表加载失败");
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

  async function navigateLightbox(direction: -1 | 1) {
    if (lightboxAssetIndex < 0) return;
    const localIndex = direction < 0 ? previousPreviewIndex : nextPreviewIndex;
    if (localIndex >= 0) {
      showLightboxAsset(assets[localIndex], localIndex);
      return;
    }

    let nextOffset = assetOffset + direction * acquisitionAssetPageSize;
    while (nextOffset >= 0 && nextOffset < assetsTotal) {
      const page = await loadAssetPage(assetStatus, nextOffset);
      if (!page) return;
      const startIndex = direction < 0 ? page.items.length - 1 : 0;
      const index = findPreviewableIndexInDirection(page.items, startIndex, direction);
      if (index >= 0) {
        showLightboxAsset(page.items[index], index, page.offset);
        return;
      }
      nextOffset += direction * acquisitionAssetPageSize;
    }
    setLightboxSelection(null);
  }

  async function focusPreviewAfterRemoval(
    page: PaginatedAcquisitionAssets,
    preferredIndex: number,
    direction: -1 | 1
  ) {
    let loadedForwardPage = false;
    if (direction > 0) {
      const localNextIndex = findPreviewableIndexInDirection(page.items, Math.max(0, preferredIndex), 1);
      if (localNextIndex >= 0) {
        showLightboxAsset(page.items[localNextIndex], localNextIndex, page.offset);
        return;
      }
      for (let nextOffset = page.offset + acquisitionAssetPageSize; nextOffset < page.total; nextOffset += acquisitionAssetPageSize) {
        const nextPage = await loadAssetPage(assetStatus, nextOffset);
        if (!nextPage) return;
        loadedForwardPage = true;
        const nextIndex = findPreviewableIndexInDirection(nextPage.items, 0, 1);
        if (nextIndex >= 0) {
          showLightboxAsset(nextPage.items[nextIndex], nextIndex, nextPage.offset);
          return;
        }
      }
    }

    let previousPage = page;
    let previousPreferredIndex = preferredIndex;
    if (loadedForwardPage) {
      const restoredPage = await loadAssetPage(assetStatus, page.offset);
      if (!restoredPage) return;
      previousPage = restoredPage;
      previousPreferredIndex = page.offset + preferredIndex - restoredPage.offset;
    }
    const localPreviousStart = direction > 0 ? previousPreferredIndex - 1 : previousPreferredIndex;
    const localPreviousIndex = findPreviewableIndexInDirection(
      previousPage.items,
      Math.min(localPreviousStart, previousPage.items.length - 1),
      -1
    );
    if (localPreviousIndex >= 0) {
      showLightboxAsset(previousPage.items[localPreviousIndex], localPreviousIndex, previousPage.offset);
      return;
    }
    for (let previousOffset = previousPage.offset - acquisitionAssetPageSize; previousOffset >= 0; previousOffset -= acquisitionAssetPageSize) {
      const earlierPage = await loadAssetPage(assetStatus, previousOffset);
      if (!earlierPage) return;
      const previousIndex = findPreviewableIndexInDirection(earlierPage.items, earlierPage.items.length - 1, -1);
      if (previousIndex >= 0) {
        showLightboxAsset(earlierPage.items[previousIndex], previousIndex, earlierPage.offset);
        return;
      }
    }
    setLightboxSelection(null);
  }

  async function reconcileAssetPageAfterRemoval(
    remainingAssets: AcquisitionAsset[],
    remainingTotal: number
  ): Promise<PaginatedAcquisitionAssets> {
    const localPage: PaginatedAcquisitionAssets = {
      items: remainingAssets,
      total: remainingTotal,
      offset: assetOffset,
      limit: acquisitionAssetPageSize
    };
    const fill = getAcquisitionPageFill(
      remainingAssets.length,
      assetOffset,
      remainingTotal
    );
    if (!fill) return localPage;

    try {
      const fillPage = await listAcquisitionAssets(assetStatus, fill.offset, fill.limit);
      if (!isAcquisitionPageFillValid(
        remainingAssets.map((asset) => asset.id),
        remainingTotal,
        fill,
        fillPage
      )) throw new Error("审核图片列表已发生变化");

      const page = { ...localPage, items: [...remainingAssets, ...fillPage.items] };
      setAssets(page.items);
      setAssetsTotal(page.total);
      return page;
    } catch {
      const page = await loadAssetPage(assetStatus, assetOffset);
      if (!page) throw new Error("审核图片列表刷新失败");
      return page;
    }
  }

  async function rejectLightboxAsset() {
    if (!lightboxAsset || !canDelete || lightboxRejectPendingRef.current) return;
    lightboxRejectPendingRef.current = true;
    try {
      const confirmed = await confirm({
        title: "丢弃这张采集图片？",
        message: `将立即删除临时文件“${lightboxAsset.filename}”，同时保留拒绝状态和来源记录。`,
        confirmLabel: "确认丢弃",
        tone: "danger",
        backdrop: "transparent"
      });
      if (!confirmed) return;

      const rejectedId = lightboxAsset.id;
      const preferredIndex = lightboxAssetIndex;
      const removedGlobalIndex = assetOffset + preferredIndex;
      const remainingAssets = assets.filter((asset) => asset.id !== rejectedId);
      const remainingTotal = Math.max(0, assetsTotal - 1);
      setBusy(true);
      setNotice(null);
      await changeAcquisitionAssets("reject", [rejectedId]);
      setSelectedAssets((current) => removeAcquisitionSelection(current, [rejectedId]));
      setAssets(remainingAssets);
      setAssetsTotal(remainingTotal);
      setAssetSummary((current) => {
        const statusCounts = { ...current.status_counts };
        statusCounts[assetStatus] = Math.max(0, (statusCounts[assetStatus] ?? 0) - 1);
        statusCounts.rejected = (statusCounts.rejected ?? 0) + 1;
        return { ...current, status_counts: statusCounts };
      });
      reviewReconcileNeededRef.current = true;

      const immediateContinuation = getAcquisitionRejectContinuation(
        remainingAssets.map((asset) => Boolean(asset.preview_url)),
        preferredIndex,
        assetOffset,
        remainingTotal
      );
      if (immediateContinuation.kind === "local") {
        showLightboxAsset(remainingAssets[immediateContinuation.index], immediateContinuation.index);
      }

      let page: PaginatedAcquisitionAssets;
      try {
        page = await reconcileAssetPageAfterRemoval(remainingAssets, remainingTotal);
      } catch (error) {
        setLightboxSelection(null);
        setNotice(error instanceof Error ? `图片已丢弃，但列表刷新失败：${error.message}` : "图片已丢弃，但列表刷新失败");
        return;
      }

      const reconciledPreferredIndex = removedGlobalIndex - page.offset;
      const continuation = getAcquisitionRejectContinuation(
        page.items.map((asset) => Boolean(asset.preview_url)),
        reconciledPreferredIndex,
        page.offset,
        page.total
      );
      if (continuation.kind === "local") {
        showLightboxAsset(page.items[continuation.index], continuation.index, page.offset);
      } else if (continuation.kind === "reload") {
        setLightboxSelection((current) => current
          ? { ...current, globalIndex: continuation.offset + continuation.preferredIndex }
          : current);
        try {
          const page = await loadAssetPage(assetStatus, continuation.offset);
          if (page) {
            const targetGlobalIndex = continuation.offset + continuation.preferredIndex;
            await focusPreviewAfterRemoval(
              page,
              targetGlobalIndex - page.offset,
              continuation.direction
            );
          }
        } catch (error) {
          setLightboxSelection(null);
          setNotice(error instanceof Error ? `图片已丢弃，但下一页加载失败：${error.message}` : "图片已丢弃，但下一页加载失败");
          return;
        }
      } else {
        setLightboxSelection(null);
      }
      setNotice("图片已丢弃，临时文件已清除");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "图片丢弃失败");
    } finally {
      setBusy(false);
      lightboxRejectPendingRef.current = false;
    }
  }

  function closeReviewLightbox() {
    if (lightboxRejectPendingRef.current) return;
    setLightboxSelection(null);
    if (!reviewReconcileNeededRef.current) return;
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
      <div><p className="acquisition-eyebrow">图片采集工作台</p><h1>图片采集中心</h1></div>
      <div className="acquisition-heading-actions">
        <span className="acquisition-counter">采集资产 {assetSummary.total}</span>
        <button className="icon-button" type="button" onClick={() => void refresh()} title="刷新数据" aria-label="刷新数据" disabled={busy || assetLoading}><LoaderCircle size={17} /></button>
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
      <span>已入图库 <strong>{assetSummary.status_counts.imported ?? 0}</strong></span>
      <span>图库重复 <strong>{assetSummary.status_counts.gallery_duplicate ?? 0}</strong></span>
      <span>已丢弃 <strong>{assetSummary.status_counts.rejected ?? 0}</strong></span>
    </section>

    {tab === "sources" && <section className="acquisition-grid sources-layout">
      <div className="acquisition-section source-ledger-panel">
        <div className="acquisition-section-title"><span>已维护站点</span><small>{sources.length} 个</small></div>
        <div className="source-ledger">
          {sources.map((source) => {
            const bindable = compatibleScripts(source);
            const selectedKey = sourceScriptChoices[source.id] ?? bindable[0]?.key ?? "";
            return <article className="source-card" key={source.id}>
              <div className="source-card-heading">
                <div><strong>{source.name}</strong><a href={source.base_url} target="_blank" rel="noreferrer" title={source.base_url}>{source.base_url}</a></div>
                <div className="source-command-row">
                  {canEdit && <button type="button" className="icon-button" title="编辑站点" aria-label={`编辑站点 ${source.name}`} onClick={() => editSource(source)}><Pencil size={15} /></button>}
                  {canDelete && <button type="button" className="icon-button danger" title="删除站点" aria-label={`删除站点 ${source.name}`} disabled={busy} onClick={() => void perform(() => deleteAcquisitionSource(source.id), "站点已删除")}><Trash2 size={15} /></button>}
                </div>
              </div>
              {source.notes && <p className="source-notes">{source.notes}</p>}
              <div className="script-bindings">
                {source.script_keys.map((key) => <span className="script-chip" key={key} title={scriptByKey.get(key)?.description}>
                  {scriptByKey.get(key)?.name ?? key}
                  {canEdit && <button type="button" title="解除绑定" aria-label={`解除绑定 ${key}`} disabled={busy} onClick={() => void perform(async () => { await unbindAcquisitionScript(source.id, key); }, "脚本绑定已移除")}><X size={13} /></button>}
                </span>)}
                {!source.script_keys.length && <small>尚未绑定脚本</small>}
              </div>
              {canEdit && bindable.length > 0 && <div className="script-bind-row">
                <select value={selectedKey} onChange={(event) => setSourceScriptChoices((current) => ({ ...current, [source.id]: event.target.value }))} aria-label={`为 ${source.name} 选择脚本`}>
                  {bindable.map((script) => <option key={script.key} value={script.key}>{script.name}</option>)}
                </select>
                <button type="button" className="icon-button" title="绑定脚本" aria-label={`为 ${source.name} 绑定脚本`} disabled={busy || !selectedKey} onClick={() => void perform(async () => { await bindAcquisitionScript(source.id, selectedKey); }, "脚本已绑定")}><Link2 size={16} /></button>
              </div>}
              <small className="source-summary">{categories.filter((category) => category.source_id === source.id).length} 个分类 · {source.enabled ? "启用" : "停用"}</small>
            </article>;
          })}
          {!sources.length && <p className="acquisition-empty">尚未维护采集站点。</p>}
        </div>
      </div>

      {canEdit && <div className="acquisition-section acquisition-forms">
        <form onSubmit={(event) => void submitSource(event)}>
          <div className="acquisition-section-title"><span>{editingSourceId ? "编辑站点" : "新增站点"}</span><Plus size={17} /></div>
          <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="站点名称" required />
          <input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="总站或首页 URL" required />
          <textarea value={sourceNotes} onChange={(event) => setSourceNotes(event.target.value)} placeholder="备注（选填）" rows={3} />
          <div className="form-command-row"><button type="submit" disabled={busy}>{editingSourceId ? "保存站点" : "新建站点"}</button>{editingSourceId && <button type="button" className="secondary-command" onClick={resetSourceForm}>取消</button>}</div>
        </form>
        <form onSubmit={(event) => void submitCategory(event)}>
          <div className="acquisition-section-title"><span>{editingCategoryId ? "编辑分类" : "新增分类"}</span><FolderPlus size={17} /></div>
          <select value={categorySourceId} onChange={(event) => setCategorySourceId(event.target.value)} required disabled={editingCategoryId != null}><option value="">选择站点</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select>
          <input value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="分类名称" required />
          <input type="url" value={categoryUrl} onChange={(event) => setCategoryUrl(event.target.value)} placeholder="分类分页入口 URL" required />
          <textarea value={categoryNotes} onChange={(event) => setCategoryNotes(event.target.value)} placeholder="备注（选填）" rows={3} />
          <div className="form-command-row"><button type="submit" disabled={busy}>{editingCategoryId ? "保存分类" : "新建分类"}</button>{editingCategoryId && <button type="button" className="secondary-command" onClick={resetCategoryForm}>取消</button>}</div>
        </form>
      </div>}

      <div className="acquisition-section acquisition-category-list">
        <div className="acquisition-section-title"><span>分类页面</span><small>{categories.length} 条</small></div>
        {categories.map((category) => <article key={category.id} className="category-line">
          <ChevronRight size={15} /><div><strong>{category.name}</strong><small>{sourceById.get(category.source_id)?.name ?? "未知站点"} · {category.crawl_url}</small></div>
          <div className="category-command-row">
            {canEdit && <button type="button" className="icon-button" title="编辑分类" aria-label={`编辑分类 ${category.name}`} onClick={() => editCategory(category)}><Pencil size={15} /></button>}
            {canDelete && <button type="button" className="icon-button danger" title="删除分类" aria-label={`删除分类 ${category.name}`} disabled={busy} onClick={() => void perform(() => deleteAcquisitionCategory(category.id), "分类已删除")}><Trash2 size={15} /></button>}
          </div>
        </article>)}
      </div>
    </section>}

    {tab === "runs" && <section className="acquisition-grid run-layout">
      <div className="acquisition-section run-launcher" ref={runLauncherRef}>
        <div className="acquisition-section-title"><span>启动采集</span><Play size={17} /></div>
        <label><span>分类页面</span><select value={runCategoryId} onChange={(event) => selectRunCategory(event.target.value)} disabled={!canAdd || busy}><option value="">选择分类</option>{categories.map((category) => <option key={category.id} value={category.id}>{sourceById.get(category.source_id)?.name ?? "未知站点"} / {category.name}</option>)}</select></label>
        <label><span>爬取脚本</span><select value={runScriptKey} onChange={(event) => selectRunScript(event.target.value)} disabled={!canAdd || busy || !availableRunScripts.length}><option value="">{runCategoryId && !availableRunScripts.length ? "该站点尚未绑定脚本" : "选择脚本"}</option>{availableRunScripts.map((script) => <option key={script.key} value={script.key}>{script.name} · v{script.version}</option>)}</select></label>
        {selectedRunScript?.parameters.map((parameter) => <label key={parameter.key} title={parameter.description ?? undefined}>
          <span>{parameter.label}{parameter.required ? " *" : ""}</span>
          {parameter.type === "boolean"
            ? <input type="checkbox" checked={Boolean(runParameters[parameter.key])} onChange={(event) => setRunParameters((current) => ({ ...current, [parameter.key]: event.target.checked }))} />
            : parameter.type === "select"
              ? <select value={String(runParameters[parameter.key] ?? "")} onChange={(event) => setRunParameters((current) => ({ ...current, [parameter.key]: event.target.value }))}>{parameter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
              : <input type={parameter.type === "string" ? "text" : "number"} required={parameter.required} min={parameter.minimum ?? undefined} max={parameter.maximum ?? undefined} step={parameter.type === "integer" ? 1 : "any"} value={String(runParameters[parameter.key] ?? "")} onChange={(event) => setRunParameters((current) => ({ ...current, [parameter.key]: event.target.value }))} />}
        </label>)}
        <div className="mode-switch run-mode-switch" aria-label="采集模式"><button type="button" className={runMode === "incremental" ? "active" : ""} onClick={() => setRunMode("incremental")}>增量</button><button type="button" className={runMode === "full" ? "active" : ""} onClick={() => setRunMode("full")}>全量发现</button><button type="button" className={runMode === "verify" ? "active" : ""} onClick={() => setRunMode("verify")}>核验更新</button></div>
        <button type="button" disabled={!canAdd || !runCategoryId || !runScriptKey || busy} onClick={() => void perform(async () => {
          await startAcquisitionRun(Number(runCategoryId), { script_key: runScriptKey, mode: runMode, parameters: runPayloadParameters() });
        }, "采集任务已进入队列")}><Play size={16} /> 开始采集</button>
      </div>
      <div className="acquisition-section run-list">
        <div className="acquisition-section-title"><span>最近运行</span><small>{runs.length} 条</small></div>
        {runs.map((run) => {
          const configuration = getAcquisitionRunFormConfiguration(run, categories, sources, scripts);
          const isActive = run.status === "pending" || run.status === "running";
          const canLoadConfiguration = canAdd && !busy && !isActive && Boolean(configuration);
          const loadTitle = isActive
            ? "运行结束后可载入配置"
            : configuration
              ? "载入此运行配置"
              : "原分类或脚本已不可用";
          return <article className="run-line" key={run.id}>
            <div><strong>{run.source_name} / {run.category_name}</strong><small>{run.script_name} · v{run.script_version} · {formatDate(run.created_at)} · {run.mode === "verify" ? "核验更新" : run.mode === "full" || run.parameters.force_full_scan === true ? "全量发现" : "增量"}</small>{runStopLabel(run) && <small>{runStopLabel(run)}</small>}{run.error_message && <p className="run-error">{run.error_message}</p>}</div>
            <div className="run-actions">
              <div className="run-metrics"><span className={`acquisition-status status-${run.status}`}>{statusLabel(run.status)}</span><small>扫描 {run.total_count} · 跳过 {run.skipped_count} · 忽略 {run.ignored_count}</small><small>下载成功 {run.download_success_count} · 新候选 {run.candidate_count} · 内容重复 {run.content_duplicate_count} · 清晰度重复 {run.resolution_duplicate_count} · 高清替换 {run.resolution_upgrade_count} · 图库重复 {run.gallery_duplicate_count} · 失败 {run.error_count}</small></div>
              <button type="button" className="icon-button" title={loadTitle} aria-label={`${loadTitle} ${run.category_name}`} disabled={!canLoadConfiguration} onClick={() => loadRunConfiguration(run)}><RotateCcw size={16} /></button>
            </div>
          </article>;
        })}
        {!runs.length && <p className="acquisition-empty">尚无运行记录。</p>}
      </div>
    </section>}

    {tab === "review" && <section className="acquisition-review">
      <div className="review-toolbar">
        <div className="review-toolbar-leading">
          <div className="mode-switch acquisition-review-mode" aria-label="待审核视图">
            <button type="button" className={reviewMode === "list" ? "active" : ""} onClick={() => changeReviewMode("list")}><Images size={15} /> 图片列表</button>
            <button type="button" className={reviewMode === "similarity" ? "active" : ""} onClick={() => changeReviewMode("similarity")}><ScanSearch size={15} /> 相似整理</button>
          </div>
          {reviewMode === "list" && <><select value={assetStatus} disabled={busy} onChange={(event) => changeAssetStatus(event.target.value)}><option value="pending_review">待审核</option><option value="import_failed">入库失败</option><option value="import_queued">等待入库</option><option value="importing">正在入库</option><option value="imported">已入图库</option><option value="gallery_duplicate">图库已存在</option></select><span>{assetsTotal} 张</span></>}
          {reviewMode === "similarity" && <span>{similarity.total} 组</span>}
          {selectedAssets.length > 0 && <span className="review-selection-count">已选 {selectedAssets.length} 张</span>}
        </div>
        <div className="review-actions">
          {canEdit && <button type="button" title="重新扫描全部待审核图片" disabled={busy || similarity.task?.status === "pending" || similarity.task?.status === "running"} onClick={() => void startSimilarityScan()}><ScanSearch size={16} /> {similarity.generated_at ? "重新扫描" : "扫描相似"}</button>}
          {reviewMode === "list" && <button type="button" title={areAllReviewAssetsSelected ? "取消选择当前状态下所有图片" : "选中当前状态下所有页面的图片"} disabled={busy || assetsTotal === 0} onClick={() => void selectAllReviewAssets()}><CheckCheck size={16} /> {areAllReviewAssetsSelected ? "取消全选" : `全选 ${assetsTotal}`}</button>}
          {reviewMode === "list" && canAdd && <button type="button" disabled={busy || !selectedAssets.length} onClick={() => void performSelectedAssetAction("import", assetStatus === "import_failed" ? "已创建重试批次" : "已创建入库批次")}><Check size={16} /> {assetStatus === "import_failed" ? "重试" : "导入"} {selectedAssets.length || ""}</button>}
          {canDelete && <button type="button" className="danger-command" disabled={busy || !selectedAssets.length} onClick={() => reviewMode === "similarity" ? void rejectSimilarityAssets(selectedAssets) : void performSelectedAssetAction("reject", "已丢弃临时图片")}><X size={16} /> 丢弃 {selectedAssets.length || ""}</button>}
        </div>
      </div>
      {reviewMode === "list" && <><div className={assetLoading ? "review-grid loading" : "review-grid"} aria-busy={assetLoading}>
        {assets.map((asset, index) => <article className={selectedAssets.includes(asset.id) ? "review-tile selected" : "review-tile"} key={asset.id}>
          <label className="tile-select"><input type="checkbox" checked={selectedAssets.includes(asset.id)} onChange={() => toggleAsset(asset.id)} /><span>选择</span></label>
          {asset.preview_url ? <button className="review-image-button" type="button" onClick={() => showLightboxAsset(asset, index)} aria-label={`查看大图 ${asset.filename}`}>{lightboxAsset ? <span className="review-image-placeholder" aria-hidden="true" /> : <img src={getAcquisitionPreviewUrl(asset.preview_url, 480)} alt={asset.filename} loading="lazy" decoding="async" />}</button> : <div className="tile-missing">临时文件已清除</div>}
          <div className="tile-meta"><strong title={asset.filename}>{asset.filename}</strong><small>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "尺寸未知"} · {formatBytes(asset.size_bytes)}</small>{asset.quality_warnings.length > 0 && <p>{asset.quality_warnings.join(" / ")}</p>}</div>
        </article>)}
      </div>
      {!assets.length && <p className="acquisition-empty review-empty">此状态下没有图片。</p>}
      {assetPagination.totalPages > 0 && <div className="acquisition-pagination" aria-label="审核图片分页">
        <button className="icon-button" type="button" title="上一页" aria-label="上一页" disabled={assetLoading || assetOffset === 0} onClick={() => void goToAssetOffset(assetOffset - acquisitionAssetPageSize)}><ChevronLeft size={18} /></button>
        <span className="pagination-summary">第 {assetPagination.currentPage} / {assetPagination.totalPages} 页 · {assetPagination.rangeStart}-{assetPagination.rangeEnd} / {assetsTotal}</span>
        <button className="icon-button" type="button" title="下一页" aria-label="下一页" disabled={assetLoading || assetOffset + acquisitionAssetPageSize >= assetsTotal} onClick={() => void goToAssetOffset(assetOffset + acquisitionAssetPageSize)}><ChevronRight size={18} /></button>
        <form className="pagination-jump" onSubmit={submitAssetPageJump}>
          <label htmlFor="acquisition-page-number">跳至</label>
          <input id="acquisition-page-number" type="number" min={1} max={assetPagination.totalPages} step={1} value={assetJumpPage} onChange={(event) => setAssetJumpPage(event.target.value)} aria-label="审核图片页码" />
          <button type="submit" disabled={assetLoading || !assetJumpPage}>跳转</button>
        </form>
      </div>}</>}
      {reviewMode === "similarity" && <section className="similarity-workspace" aria-label="相似图片整理">
        {similarity.task && <div className={`similarity-task status-${similarity.task.status}`}>
          <div><strong>{statusLabel(similarity.task.status)}</strong><span>{similarity.task.message ?? "正在处理相似图片"}</span></div>
          <progress value={similarity.task.progress} max={1} aria-label="相似扫描进度" />
          <small>{Math.round(similarity.task.progress * 100)}%</small>
        </div>}
        {similarity.is_stale && <div className="similarity-alert">扫描后又有新的待审核图片进入，当前结果可能不完整，请重新扫描。</div>}
        {similarity.task?.status === "failed" && <div className="similarity-alert error">{similarity.task.message ?? "扫描失败，上一次结果已保留。"}</div>}
        <div className={similarityLoading ? "similarity-groups loading" : "similarity-groups"} aria-busy={similarityLoading}>
          {similarity.groups.map((group, groupIndex) => {
            const groupIds = group.members.map((asset) => asset.id);
            const allSelected = groupIds.every((id) => selectedAssets.includes(id));
            return <article className="similarity-group" key={group.id}>
              <header>
                <div><strong>相似组 {similarity.offset + groupIndex + 1}</strong><small>{group.members.length} 张 · 最高 {Math.round(group.max_score * 100)}%</small></div>
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
              </div>)}</div>
            </article>;
          })}
        </div>
        {!similarityLoading && !similarity.groups.length && <div className="similarity-empty">
          <ScanSearch size={26} />
          <strong>{similarity.generated_at ? "没有发现相似图片" : "尚未扫描待审核图片"}</strong>
          <span>{similarity.generated_at ? "当前待审核图片之间没有达到阈值的相似关系。" : "点击“扫描相似”开始整理。"}</span>
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
          <small>{importBatchesTotal} 个批次{unassignedImportedCount > 0 ? ` · ${unassignedImportedCount} 张历史图片未关联批次` : ""}</small>
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
          <small>{selectedImportBatchId ? `${importBatchItemsTotal} 张` : "请先选择批次"}</small>
        </div>
        <div className="import-history-toolbar">
          <label htmlFor="import-result-status">处理结果</label>
          <select id="import-result-status" value={importBatchItemStatus} onChange={(event) => { setImportBatchItemStatus(event.target.value); setImportBatchItemOffset(0); setExpandedImportAssetId(null); }}>
            <option value="all">全部结果</option>
            <option value="imported">成功入图库</option>
            <option value="gallery_duplicate">图库已存在</option>
            <option value="failed">导入失败</option>
          </select>
        </div>
        <div className="history-detail-scroll" aria-busy={importHistoryLoading}>
          {importBatchItems.map((item) => {
            const expanded = expandedImportAssetId === item.asset_id;
            const galleryLabel = item.gallery_available
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
          {selectedImportBatchId && !importBatchItems.length && <p className="acquisition-empty">当前筛选下没有图片。</p>}
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

    {lightboxAsset?.original_url && <PhotoLightbox
      backdropClassName="acquisition-review-lightbox-backdrop"
      shellClassName="acquisition-review-lightbox"
      busy={busy || assetLoading}
      canGoPrevious={canGoToPreviousAsset}
      canGoNext={canGoToNextAsset}
      previousLabel={previousPreviewIndex < 0 && assetOffset > 0 ? "上一页" : undefined}
      nextLabel={nextPreviewIndex < 0 && assetOffset + assets.length < assetsTotal ? "下一页" : undefined}
      onClose={closeReviewLightbox}
      onPrevious={() => navigateLightbox(-1)}
      onNext={() => navigateLightbox(1)}
      onKeyDown={(event) => {
        const shortcut = getAcquisitionLightboxShortcut(event.key);
        if (shortcut === "toggle_selection") {
          event.preventDefault();
          toggleAsset(lightboxAsset.id);
        } else if (shortcut === "reject" && canDelete) {
          event.preventDefault();
          void rejectLightboxAsset();
        }
      }}
      meta={<>
        <div className="acquisition-lightbox-heading">
          <div><p className="acquisition-eyebrow">采集审核</p><h2>{statusLabel(assetStatus)}</h2></div>
          <strong>{lightboxGlobalIndex + 1} / {assetsTotal}</strong>
        </div>
        <dl className="acquisition-lightbox-facts">
          <div><dt>文件名</dt><dd title={lightboxAsset.filename}>{lightboxAsset.filename}</dd></div>
          <div><dt>尺寸</dt><dd>{lightboxAsset.width && lightboxAsset.height ? `${lightboxAsset.width} × ${lightboxAsset.height}` : "未知"}</dd></div>
          <div><dt>大小</dt><dd>{formatBytes(lightboxAsset.size_bytes)}</dd></div>
        </dl>
        <section className={lightboxAsset.quality_warnings.length ? "acquisition-quality-notes has-warning" : "acquisition-quality-notes"}>
          <strong>质量提示</strong>
          <p>{lightboxAsset.quality_warnings.length ? lightboxAsset.quality_warnings.join(" / ") : "未发现自动质量提示"}</p>
        </section>
        <div className="acquisition-lightbox-actions">
          <button type="button" className={selectedAssets.includes(lightboxAsset.id) ? "selected" : ""} onClick={() => toggleAsset(lightboxAsset.id)} disabled={busy}>
            <Check size={17} /> {selectedAssets.includes(lightboxAsset.id) ? "取消选择" : "选中当前"}
          </button>
          {canDelete && <button type="button" className="danger-command" onClick={() => void rejectLightboxAsset()} disabled={busy}>
            <Trash2 size={17} /> 丢弃当前
          </button>}
        </div>
      </>}
    >
      <img className="lightbox-image" src={lightboxAsset.original_url} alt={lightboxAsset.filename} />
    </PhotoLightbox>}

    {similarityLightboxAsset?.original_url && similarityLightboxGroup && <PhotoLightbox
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
        const shortcut = getAcquisitionLightboxShortcut(event.key);
        if (shortcut === "toggle_selection") {
          event.preventDefault();
          toggleAsset(similarityLightboxAsset.id);
        } else if (shortcut === "reject" && canDelete) {
          event.preventDefault();
          void rejectSimilarityAssets([similarityLightboxAsset.id]);
        }
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
    >
      <img className="lightbox-image" src={similarityLightboxAsset.original_url} alt={similarityLightboxAsset.filename} />
    </PhotoLightbox>}
  </>;
}
