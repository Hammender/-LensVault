import { authFetch, jsonHeaders, parseResponse } from "../lib/apiClient";

const base = "/api/acquisition/plugins";

export type PluginCredentialField = { key: string; label: string; required?: boolean; description?: string; secret?: boolean };
export type AcquisitionPluginVersion = {
  key: string; name: string; version: string; description: string;
  status: "uploaded" | "preparing" | "ready" | "active" | "failed";
  last_error: string | null;
  requirements: string[]; credentials: PluginCredentialField[]; created_at: string;
};
export type AcquisitionPluginCredential = { id: number; name: string; status: string; last_tested_at: string | null; reason?: string | null };

export async function listPlugins(): Promise<AcquisitionPluginVersion[]> {
  return parseResponse(await authFetch(base));
}

export async function uploadPlugin(file: File): Promise<AcquisitionPluginVersion> {
  const form = new FormData();
  form.append("file", file);
  return parseResponse(await authFetch(base, { method: "POST", body: form }));
}

export async function changePlugin(key: string, version: string, action: "prepare" | "activate" | "disable"): Promise<void> {
  await parseResponse(await authFetch(`${base}/${encodeURIComponent(key)}/versions/${encodeURIComponent(version)}/${action}`, { method: "POST" }));
}

export async function uninstallPlugin(key: string, version: string): Promise<void> {
  await parseResponse(await authFetch(`${base}/${encodeURIComponent(key)}/versions/${encodeURIComponent(version)}`, { method: "DELETE" }));
}

export async function getPluginGuide(key: string): Promise<string> {
  const result = await parseResponse<{ text: string }>(await authFetch(`${base}/${encodeURIComponent(key)}/guide`));
  return result.text;
}

export async function listPluginCredentials(key: string): Promise<AcquisitionPluginCredential[]> {
  return parseResponse(await authFetch(`${base}/${encodeURIComponent(key)}/credentials`));
}

export async function savePluginCredential(key: string, name: string, values: Record<string, string>): Promise<AcquisitionPluginCredential> {
  return parseResponse(await authFetch(`${base}/${encodeURIComponent(key)}/credentials`, {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({ name, values })
  }));
}

export async function testPluginCredential(id: number): Promise<AcquisitionPluginCredential> {
  return parseResponse(await authFetch(`${base}/credentials/${id}/test`, { method: "POST" }));
}

export async function deletePluginCredential(id: number): Promise<void> {
  await parseResponse(await authFetch(`${base}/credentials/${id}`, { method: "DELETE" }));
}

export type PluginPreviewItem = { title: string | null; source_url: string; media_type: "image" | "video"; filename: string; size_bytes: number };

export async function previewPlugin(key: string, payload: {
  category_id: number; credential_id: number | null; parameters: Record<string, unknown>; limit?: number
}): Promise<{ items: PluginPreviewItem[] }> {
  return parseResponse(await authFetch(`${base}/${encodeURIComponent(key)}/preview`, {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(payload)
  }));
}
