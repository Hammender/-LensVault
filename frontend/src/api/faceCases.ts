import { authFetch, jsonHeaders, parseBlobResponse, parseResponse } from "../lib/apiClient";
import type { CaseFilters, FaceCaseCreate, FaceCaseDetail, PaginatedFaceCases } from "../types/faceCases";

const prefix = "/api/face-recognition-cases";

export async function createFaceCase(payload: FaceCaseCreate): Promise<FaceCaseDetail> {
  return parseResponse(await authFetch(prefix, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }));
}
export async function listFaceCases(filters: CaseFilters, offset: number): Promise<PaginatedFaceCases> {
  const query = new URLSearchParams({ offset: String(offset), limit: "24" });
  Object.entries(filters).forEach(([key, value]) => { if (value.trim()) query.set(key, value.trim()); });
  return parseResponse(await authFetch(`${prefix}?${query}`));
}
export async function getFaceCase(id: string): Promise<FaceCaseDetail> {
  return parseResponse(await authFetch(`${prefix}/${id}`));
}
export async function updateFaceCaseNotes(id: string, notes: string): Promise<FaceCaseDetail> {
  return parseResponse(await authFetch(`${prefix}/${id}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ notes }) }));
}
export async function deleteFaceCase(id: string): Promise<void> {
  await parseResponse(await authFetch(`${prefix}/${id}`, { method: "DELETE" }));
}
export async function exportFaceCases(filters: CaseFilters, ids?: string[]): Promise<{ blob: Blob; filename: string }> {
  const payload: Record<string, unknown> = ids ? { case_ids: ids } : Object.fromEntries(Object.entries(filters).filter(([, value]) => value.trim()));
  return parseBlobResponse(await authFetch(`${prefix}/export`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }), "识别异常案例.zip");
}
