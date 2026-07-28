import type { WorkspaceInvitation, WorkspaceMember, WorkspaceRead } from "../types";
import { authFetch, jsonHeaders, parseResponse as parse } from "../apiClient";

export type WorkspacePermissionsPayload = {
  can_add_gallery?: boolean;
  can_delete_gallery?: boolean;
  can_edit_gallery?: boolean;
  can_add_samples?: boolean;
  can_delete_samples?: boolean;
  can_edit_samples?: boolean;
  can_add_videos?: boolean;
  can_delete_videos?: boolean;
  can_edit_videos?: boolean;
};

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
