import type { WorkspaceRead } from "./workspace";
import type { UserRead } from "./users";

export type AuthSession = {
  access_token: string;
  token_type: string;
  user: UserRead;
  workspace: WorkspaceRead;
  workspaces: WorkspaceRead[];
};

export type BootstrapStatus = {
  required: boolean;
};
