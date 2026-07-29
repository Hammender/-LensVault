import { useEffect, useState } from "react";

import PermissionEditor from "./PermissionEditor";
import {
  acceptWorkspaceInvitation,
  clearSelectedWorkspaceId,
  createWorkspace,
  createWorkspaceUser,
  declineWorkspaceInvitation,
  getCurrentSession,
  inviteWorkspaceMember,
  leaveWorkspace,
  listWorkspaceInvitations,
  listWorkspaceMembers,
  removeWorkspaceMember,
  setSelectedWorkspaceId,
  updateWorkspaceMember,
  type WorkspacePermissionsPayload
} from "../api/index";
import type { AuthSession, WorkspaceInvitation, WorkspaceMember } from "../types";
import { emptyWorkspacePermissions, toWorkspacePermissions } from "../utils";

type WorkspacePanelProps = {
  session: AuthSession;
  onSessionChange: (session: AuthSession) => void;
  onClose: () => void;
};

export default function WorkspacePanel({ session, onSessionChange, onClose }: WorkspacePanelProps) {
  const [workspaceName, setWorkspaceName] = useState("");
  const [inviteUsername, setInviteUsername] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [invitePermissions, setInvitePermissions] = useState<WorkspacePermissionsPayload>({ ...emptyWorkspacePermissions });
  const [newUserPermissions, setNewUserPermissions] = useState<WorkspacePermissionsPayload>({ ...emptyWorkspacePermissions });
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isSharedOwner = session.workspace.kind === "shared" && session.workspace.role === "owner";

  const reloadSession = async () => {
    const next = await getCurrentSession();
    onSessionChange(next);
  };

  const reloadPanel = async () => {
    const [nextInvitations, nextMembers] = await Promise.all([
      listWorkspaceInvitations(),
      isSharedOwner ? listWorkspaceMembers(session.workspace.id) : Promise.resolve([])
    ]);
    setInvitations(nextInvitations);
    setMembers(nextMembers);
  };

  useEffect(() => {
    void reloadPanel().catch((error) => setMessage(error instanceof Error ? error.message : "加载工作区信息失败"));
  }, [session.workspace.id, isSharedOwner]);

  const run = async (action: () => Promise<void>, success: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage(success);
      await reloadPanel();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="export-modal workspace-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-heading">
          <p className="eyebrow">Workspace</p>
          <h2>内容空间</h2>
        </div>
        {message && <p className="inline-error">{message}</p>}
        <div className="workspace-section">
          <h3>我的空间</h3>
          <div className="workspace-list">
            {session.workspaces.map((workspace) => (
              <button
                key={workspace.id}
                type="button"
                className={workspace.id === session.workspace.id ? "workspace-row active" : "workspace-row"}
                onClick={async () => {
                  setSelectedWorkspaceId(workspace.id);
                  await reloadSession();
                }}
              >
                <span>{workspace.name}</span>
                <small>{workspace.kind === "private" ? "私人" : workspace.role === "owner" ? "共享 owner" : "共享成员"}</small>
              </button>
            ))}
          </div>
          <div className="workspace-inline-form">
            <input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} placeholder="新共享空间名称" />
            <button
              disabled={busy || !workspaceName.trim()}
              onClick={() => run(async () => {
                const workspace = await createWorkspace(workspaceName.trim());
                setSelectedWorkspaceId(workspace.id);
                setWorkspaceName("");
                await reloadSession();
              }, "已创建共享空间")}
            >
              新建共享空间
            </button>
            {session.workspace.can_leave && (
              <button
                disabled={busy}
                onClick={() => run(async () => {
                  await leaveWorkspace(session.workspace.id);
                  clearSelectedWorkspaceId();
                  await reloadSession();
                }, "已退出共享空间")}
              >
                退出当前空间
              </button>
            )}
          </div>
        </div>
        <div className="workspace-section">
          <h3>收到的邀请</h3>
          {invitations.length === 0 ? <p className="muted-text">暂无邀请</p> : invitations.map((invitation) => (
            <div key={invitation.id} className="workspace-member-row">
              <div>
                <strong>{invitation.workspace_name}</strong>
                <small>来自 {invitation.inviter_username}</small>
              </div>
              <div className="micro-row">
                <button disabled={busy} onClick={() => run(async () => {
                  const workspace = await acceptWorkspaceInvitation(invitation.id);
                  setSelectedWorkspaceId(workspace.id);
                  await reloadSession();
                }, "已加入内容空间")}>接受</button>
                <button disabled={busy} onClick={() => run(async () => {
                  await declineWorkspaceInvitation(invitation.id);
                  await reloadSession();
                }, "已拒绝邀请")}>拒绝</button>
              </div>
            </div>
          ))}
        </div>
        {isSharedOwner && (
          <>
            <div className="workspace-section">
              <h3>邀请现有账号</h3>
              <div className="workspace-inline-form">
                <input value={inviteUsername} onChange={(event) => setInviteUsername(event.target.value)} placeholder="用户名" />
                <button disabled={busy || !inviteUsername.trim()} onClick={() => run(async () => {
                  await inviteWorkspaceMember(session.workspace.id, inviteUsername.trim(), invitePermissions);
                  setInviteUsername("");
                }, "已发送邀请")}>发送邀请</button>
              </div>
              <PermissionEditor value={invitePermissions} onChange={setInvitePermissions} />
            </div>
            <div className="workspace-section">
              <h3>创建成员账号</h3>
              <div className="workspace-inline-form">
                <input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} placeholder="用户名" />
                <input value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} placeholder="显示名" />
                <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="初始密码" />
                <button disabled={busy || !newUsername.trim() || newPassword.length < 8} onClick={() => run(async () => {
                  await createWorkspaceUser(session.workspace.id, {
                    username: newUsername.trim(),
                    password: newPassword,
                    display_name: newDisplayName.trim() || null,
                    ...newUserPermissions
                  });
                  setNewUsername("");
                  setNewDisplayName("");
                  setNewPassword("");
                }, "已创建账号并加入当前空间")}>创建并加入</button>
              </div>
              <PermissionEditor value={newUserPermissions} onChange={setNewUserPermissions} />
            </div>
            <div className="workspace-section">
              <h3>成员权限</h3>
              {members.map((member) => (
                <div key={member.id} className="workspace-member-row">
                  <div>
                    <strong>{member.user.display_name || member.user.username}</strong>
                    <small>{member.role === "owner" ? "owner" : member.user.username}</small>
                  </div>
                  <PermissionEditor
                    value={toWorkspacePermissions(member.permissions)}
                    disabled={member.role === "owner" || busy}
                    onChange={(permissions) => {
                      void run(async () => {
                        await updateWorkspaceMember(session.workspace.id, member.id, permissions);
                      }, "已更新成员权限");
                    }}
                  />
                  {member.role !== "owner" && (
                    <button disabled={busy} onClick={() => run(async () => {
                      await removeWorkspaceMember(session.workspace.id, member.id);
                    }, "已移除成员")}>移除</button>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
        <div className="modal-actions">
          <button type="button" onClick={onClose}>关闭</button>
        </div>
      </section>
    </div>
  );
}
