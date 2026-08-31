import type {
  AcquisitionAsset,
  AcquisitionAssetSummary,
  AcquisitionCategory,
  AcquisitionExport,
  AcquisitionHistoryItem,
  AcquisitionImportBatch,
  PaginatedAcquisitionCategories,
  PaginatedAcquisitionImportBatchItems,
  PaginatedAcquisitionImportBatches,
  PaginatedAcquisitionRuns,
  PaginatedAcquisitionSources,
  AcquisitionRun,
  AcquisitionScript,
  AcquisitionSimilarityResult,
  AcquisitionSource,
  PaginatedAcquisitionAssets,
  Task
} from "../types";
import type { TelegramAccount } from "../types/telegram";
import { authFetch, jsonHeaders, parseResponse as parse, withWorkspaceContext } from "../apiClient";
import { toShanghaiDateTimeBoundary } from "../utils";

const fetch = authFetch;

export async function listAcquisitionScripts(): Promise<AcquisitionScript[]> {
  return parse<AcquisitionScript[]>(await fetch("/api/acquisition/scripts"));
}

export async function listAcquisitionSources(): Promise<AcquisitionSource[]> {
  return parse<AcquisitionSource[]>(await fetch("/api/acquisition/sources"));
}

export async function getTelegramAccount(): Promise<TelegramAccount | null> {
  return parse<TelegramAccount | null>(await fetch("/api/acquisition/telegram/account"));
}

export async function startTelegramLogin(payload: { api_id: number; api_hash: string; phone_number: string }): Promise<TelegramAccount> {
  return parse<TelegramAccount>(await fetch("/api/acquisition/telegram/account/login/start", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }));
}

export async function verifyTelegramLogin(payload: { code: string; password?: string }): Promise<TelegramAccount> {
  return parse<TelegramAccount>(await fetch("/api/acquisition/telegram/account/login/verify", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }));
}

export async function logoutTelegramAccount(): Promise<TelegramAccount> {
  return parse<TelegramAccount>(await fetch("/api/acquisition/telegram/account/logout", { method: "POST" }));
}

export async function createTelegramChannel(sourceId: number, payload: { name: string; channel_ref: string; notes?: string | null }): Promise<AcquisitionCategory> {
  return parse<AcquisitionCategory>(await fetch(`/api/acquisition/sources/${sourceId}/telegram-channels`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }));
}

export async function listAcquisitionSourcePage(offset = 0, limit = 10): Promise<PaginatedAcquisitionSources> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return parse<PaginatedAcquisitionSources>(await fetch(`/api/acquisition/sources/page?${params.toString()}`));
}

export async function createAcquisitionSource(payload: { name: string; base_url: string; notes?: string | null }): Promise<AcquisitionSource> {
  return parse<AcquisitionSource>(await fetch("/api/acquisition/sources", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }));
}

export async function updateAcquisitionSource(
  sourceId: number,
  payload: { name: string; base_url: string; notes?: string | null }
): Promise<AcquisitionSource> {
  return parse<AcquisitionSource>(await fetch(`/api/acquisition/sources/${sourceId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }));
}

export async function bindAcquisitionScript(sourceId: number, scriptKey: string): Promise<AcquisitionSource> {
  return parse<AcquisitionSource>(await fetch(`/api/acquisition/sources/${sourceId}/scripts`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ script_key: scriptKey, default_parameters: {} })
  }));
}

export async function unbindAcquisitionScript(sourceId: number, scriptKey: string): Promise<AcquisitionSource> {
  return parse<AcquisitionSource>(await fetch(`/api/acquisition/sources/${sourceId}/scripts/${encodeURIComponent(scriptKey)}`, {
    method: "DELETE"
  }));
}

export async function deleteAcquisitionSource(sourceId: number): Promise<void> {
  await parse<{ status: string }>(await fetch(`/api/acquisition/sources/${sourceId}`, { method: "DELETE" }));
}

export async function listAcquisitionCategories(): Promise<AcquisitionCategory[]> {
  return parse<AcquisitionCategory[]>(await fetch("/api/acquisition/categories"));
}

export async function listAcquisitionCategoryPage(offset = 0, limit = 10): Promise<PaginatedAcquisitionCategories> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return parse<PaginatedAcquisitionCategories>(await fetch(`/api/acquisition/categories/page?${params.toString()}`));
}

export async function createAcquisitionCategory(
  sourceId: number,
  payload: { name: string; crawl_url: string; notes?: string | null }
): Promise<AcquisitionCategory> {
  return parse<AcquisitionCategory>(await fetch(`/api/acquisition/sources/${sourceId}/categories`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }));
}

export async function updateAcquisitionCategory(
  categoryId: number,
  payload: { name: string; crawl_url: string; notes?: string | null }
): Promise<AcquisitionCategory> {
  return parse<AcquisitionCategory>(await fetch(`/api/acquisition/categories/${categoryId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }));
}

export async function deleteAcquisitionCategory(categoryId: number): Promise<void> {
  await parse<{ status: string }>(await fetch(`/api/acquisition/categories/${categoryId}`, { method: "DELETE" }));
}

export async function startAcquisitionRun(
  categoryId: number,
  payload: { script_key: string; mode: "incremental" | "full" | "verify"; parameters: Record<string, unknown> }
): Promise<AcquisitionRun> {
  return parse<AcquisitionRun>(await fetch(`/api/acquisition/categories/${categoryId}/runs`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }));
}

export async function listAcquisitionRuns(): Promise<AcquisitionRun[]> {
  return parse<AcquisitionRun[]>(await fetch("/api/acquisition/runs"));
}

export async function stopAcquisitionRun(runId: string): Promise<AcquisitionRun> {
  return parse<AcquisitionRun>(await fetch(`/api/acquisition/runs/${runId}/stop`, {
    method: "POST"
  }));
}

export async function listAcquisitionRunPage(offset = 0, limit = 10): Promise<PaginatedAcquisitionRuns> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return parse<PaginatedAcquisitionRuns>(await fetch(`/api/acquisition/runs/page?${params.toString()}`));
}

export async function listAcquisitionAssets(status = "pending_review", offset = 0, limit = 60): Promise<PaginatedAcquisitionAssets> {
  const params = new URLSearchParams({ status, offset: String(offset), limit: String(limit) });
  return parse<PaginatedAcquisitionAssets>(await fetch(`/api/acquisition/assets?${params.toString()}`));
}

export async function getAcquisitionAsset(assetId: string): Promise<AcquisitionAsset> {
  return parse<AcquisitionAsset>(await fetch(`/api/acquisition/assets/${encodeURIComponent(assetId)}`));
}

export async function listAcquisitionAssetIds(status: string, previewable = false): Promise<string[]> {
  const params = new URLSearchParams({ status });
  if (previewable) params.set("previewable", "true");
  return parse<string[]>(await fetch(`/api/acquisition/assets/ids?${params.toString()}`));
}

export async function changeAcquisitionAssets(
  action: "import" | "reject",
  assetIds: string[],
  isRichText = false
): Promise<AcquisitionImportBatch | void> {
  return parse<AcquisitionImportBatch | { rejected?: number }>(await fetch(`/api/acquisition/assets/${action}`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(action === "import"
      ? { asset_ids: assetIds, is_rich_text: isRichText }
      : { asset_ids: assetIds })
  })) as Promise<AcquisitionImportBatch | void>;
}

export async function getAcquisitionAssetSummary(): Promise<AcquisitionAssetSummary> {
  return parse<AcquisitionAssetSummary>(await fetch("/api/acquisition/assets/summary"));
}

export async function listAcquisitionImportBatches(
  offset = 0,
  limit = 20,
  dateFrom?: string,
  dateTo?: string
): Promise<PaginatedAcquisitionImportBatches> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (dateFrom) params.set("date_from", toShanghaiDateTimeBoundary(dateFrom, "start"));
  if (dateTo) params.set("date_to", toShanghaiDateTimeBoundary(dateTo, "end"));
  return parse<PaginatedAcquisitionImportBatches>(await fetch(`/api/acquisition/import-batches?${params}`));
}

export async function listAcquisitionImportBatchItems(
  batchId: string,
  status = "all",
  offset = 0,
  limit = 40,
  dateFrom?: string,
  dateTo?: string
): Promise<PaginatedAcquisitionImportBatchItems> {
  const params = new URLSearchParams({ status, offset: String(offset), limit: String(limit) });
  if (batchId === "unassigned" && dateFrom) params.set("date_from", toShanghaiDateTimeBoundary(dateFrom, "start"));
  if (batchId === "unassigned" && dateTo) params.set("date_to", toShanghaiDateTimeBoundary(dateTo, "end"));
  return parse<PaginatedAcquisitionImportBatchItems>(
    await fetch(`/api/acquisition/import-batches/${encodeURIComponent(batchId)}/items?${params}`)
  );
}

export async function startAcquisitionSimilarityScan(
  scanType: "normal" | "mirror" = "normal",
  scope: "pending_only" | "pending_to_gallery" = "pending_only"
): Promise<Task> {
  return parse<Task>(await fetch("/api/acquisition/similarity/scan", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ scan_type: scanType, scope })
  }));
}

export async function listAcquisitionSimilarity(
  offset = 0,
  limit = 12,
  scanType: "normal" | "mirror" = "normal",
  scope: "pending_only" | "pending_to_gallery" = "pending_only"
): Promise<AcquisitionSimilarityResult> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (scanType !== "normal") params.set("scan_type", scanType);
  if (scope !== "pending_only") params.set("scope", scope);
  return parse<AcquisitionSimilarityResult>(await fetch(`/api/acquisition/similarity?${params}`));
}

export async function listAcquisitionHistory(dateFrom?: string, dateTo?: string): Promise<AcquisitionHistoryItem[]> {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", toShanghaiDateTimeBoundary(dateFrom, "start"));
  if (dateTo) params.set("date_to", toShanghaiDateTimeBoundary(dateTo, "end"));
  return parse<AcquisitionHistoryItem[]>(await fetch(`/api/acquisition/history${params.size ? `?${params}` : ""}`));
}

export async function createAcquisitionExport(payload: { run_id?: string; source_id?: number; category_id?: number; date_from?: string; date_to?: string }): Promise<AcquisitionExport> {
  return parse<AcquisitionExport>(await fetch("/api/acquisition/exports", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }));
}

export async function listAcquisitionExports(): Promise<AcquisitionExport[]> {
  return parse<AcquisitionExport[]>(await fetch("/api/acquisition/exports"));
}

export function acquisitionDownloadUrl(url: string): string {
  return withWorkspaceContext(url);
}
