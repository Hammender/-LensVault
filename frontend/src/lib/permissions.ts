import type { AuthSession, WorkspacePermissionsPayload } from "../types";

export function hasPermission(session: AuthSession, key: keyof WorkspacePermissionsPayload): boolean {
  if (session.workspace.role === "owner") {
    return true;
  }
  return Boolean(session.workspace.permissions[key]);
}
