import type { UserRead } from "./users";

export type WorkspaceRead = {
  id: number;
  name: string;
  kind: string;
  role: string;
  permissions: Record<string, boolean>;
  can_leave: boolean;
};

export type WorkspaceMember = {
  id: number;
  user: UserRead;
  role: string;
  permissions: Record<string, boolean>;
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
  permissions: Record<string, boolean>;
  created_at: string;
};
