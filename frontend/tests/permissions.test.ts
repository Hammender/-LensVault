import { describe, expect, it } from "vitest";

import { hasPermission } from "../src/lib/permissions";
import type { AuthSession } from "../src/types";

function session(role: string, permissions: AuthSession["workspace"]["permissions"] = {}): AuthSession {
  return {
    access_token: "token",
    token_type: "bearer",
    user: { id: 1, username: "u", display_name: "U", is_admin: false },
    workspace: {
      id: 1,
      name: "空间",
      kind: "shared",
      role,
      permissions,
      can_leave: role !== "owner"
    },
    workspaces: []
  };
}

describe("hasPermission", () => {
  it("allows every action for workspace owners", () => {
    const owner = session("owner", {});
    expect(hasPermission(owner, "can_delete_videos")).toBe(true);
    expect(hasPermission(owner, "can_edit_gallery")).toBe(true);
  });

  it("reads member permission flags", () => {
    const member = session("member", { can_delete_videos: true, can_edit_gallery: false });
    expect(hasPermission(member, "can_delete_videos")).toBe(true);
    expect(hasPermission(member, "can_edit_gallery")).toBe(false);
    expect(hasPermission(member, "can_add_videos")).toBe(false);
  });
});
