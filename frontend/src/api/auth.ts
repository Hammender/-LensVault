import type { AuthSession, BootstrapStatus } from "../types";
import { authFetch, jsonHeaders, parseResponse as parse } from "../lib/apiClient";

export async function getBootstrapStatus(): Promise<BootstrapStatus> {
  return parse<BootstrapStatus>(await authFetch("/api/auth/bootstrap-status"));
}

export async function bootstrapAdmin(payload: {
  username: string;
  password: string;
  display_name?: string | null;
  workspace_name?: string | null;
}): Promise<AuthSession> {
  return parse<AuthSession>(
    await authFetch("/api/auth/bootstrap", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function login(username: string, password: string): Promise<AuthSession> {
  return parse<AuthSession>(
    await authFetch("/api/auth/login", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ username, password })
    })
  );
}

export async function registerAccount(payload: {
  username: string;
  password: string;
  display_name?: string | null;
}): Promise<AuthSession> {
  return parse<AuthSession>(
    await authFetch("/api/auth/register", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function getCurrentSession(): Promise<AuthSession> {
  return parse<AuthSession>(await authFetch("/api/auth/me"));
}

export async function logout(): Promise<void> {
  await parse<{ status: string }>(await authFetch("/api/auth/logout", { method: "POST" }));
}
