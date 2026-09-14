import type { WorkspaceInvitation, WorkspaceMember, WorkspacePermissionsPayload, WorkspaceRead } from "../types";
import { authFetch, jsonHeaders, parseResponse as parse } from "../lib/apiClient";

export type { WorkspacePermissionsPayload };

export async function createWorkspace(name: string): Promise<WorkspaceRead> {
  return parse<WorkspaceRead>(
    await authFetch("/api/workspaces", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function listWorkspaceMembers(workspaceId: number): Promise<WorkspaceMember[]> {
  return parse<WorkspaceMember[]>(await authFetch(`/api/workspaces/${workspaceId}/members`));
}

export async function updateWorkspaceMember(
  workspaceId: number,
  memberId: number,
  permissions: WorkspacePermissionsPayload
): Promise<WorkspaceMember> {
  return parse<WorkspaceMember>(
    await authFetch(`/api/workspaces/${workspaceId}/members/${memberId}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify(permissions)
    })
  );
}

export async function removeWorkspaceMember(workspaceId: number, memberId: number): Promise<void> {
  await parse<{ status: string }>(
    await authFetch(`/api/workspaces/${workspaceId}/members/${memberId}`, { method: "DELETE" })
  );
}

export async function leaveWorkspace(workspaceId: number): Promise<void> {
  await parse<{ status: string }>(await authFetch(`/api/workspaces/${workspaceId}/leave`, { method: "POST" }));
}

export async function inviteWorkspaceMember(
  workspaceId: number,
  username: string,
  permissions: WorkspacePermissionsPayload
): Promise<WorkspaceInvitation> {
  return parse<WorkspaceInvitation>(
    await authFetch(`/api/workspaces/${workspaceId}/invitations`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ username, ...permissions })
    })
  );
}

export async function createWorkspaceUser(
  workspaceId: number,
  payload: { username: string; password: string; display_name?: string | null } & WorkspacePermissionsPayload
): Promise<void> {
  await parse<{ id: number }>(
    await authFetch(`/api/workspaces/${workspaceId}/users`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function listWorkspaceInvitations(): Promise<WorkspaceInvitation[]> {
  return parse<WorkspaceInvitation[]>(await authFetch("/api/workspace-invitations"));
}

export async function acceptWorkspaceInvitation(invitationId: number): Promise<WorkspaceRead> {
  return parse<WorkspaceRead>(
    await authFetch(`/api/workspace-invitations/${invitationId}/accept`, { method: "POST" })
  );
}

export async function declineWorkspaceInvitation(invitationId: number): Promise<void> {
  await parse<{ status: string }>(
    await authFetch(`/api/workspace-invitations/${invitationId}/decline`, { method: "POST" })
  );
}
