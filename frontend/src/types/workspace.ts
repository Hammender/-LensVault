import type { UserRead } from "./users";

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

export type WorkspaceRead = {
  id: number;
  name: string;
  kind: string;
  role: string;
  permissions: WorkspacePermissionsPayload;
  can_leave: boolean;
};

export type WorkspaceMember = {
  id: number;
  user: UserRead;
  role: string;
  permissions: WorkspacePermissionsPayload;
  created_at: string;
};

export type WorkspaceInvitation = {
  id: number;
  workspace_id: number;
  workspace_name: string;
  inviter_username: string;
  invitee_username: string;
  status: string;
  role: string;
  permissions: WorkspacePermissionsPayload;
  created_at: string;
};
