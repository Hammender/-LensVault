## Why

PictureShow already stores user-owned media, but the current workspace model is not sufficient for real multi-tenant collaboration. Accounts need private content by default while still being able to create shared content spaces with explicit membership and owner-managed write permissions.

## What Changes

- Add private and shared workspace types.
- Allow self-service account registration after system bootstrap, with each new account receiving only its own private workspace.
- Give every account exactly one default private workspace where the account is owner and no other account can join.
- Allow signed-in users to create shared workspaces and become the owner of those workspaces.
- Allow shared workspace owners to invite existing accounts or create new accounts directly into the current shared workspace.
- Allow users to accept or decline invitations, and to leave shared workspaces.
- Prevent users from leaving their private workspace.
- Add owner-managed member permissions for adding, deleting, and editing:
  - gallery/display pictures,
  - person sample-library pictures,
  - videos.
- Keep read access mandatory for every workspace member.
- Replace global-admin workspace administration with workspace-owner administration.

## Capabilities

### New Capabilities

- `workspace-collaboration`: Account private workspaces, shared workspace creation, invitation-based membership, member exit, and owner-configured write permissions.

### Modified Capabilities

- `video-library`: Video write operations become workspace-permission gated while read operations remain available to all workspace members.

## Impact

- Backend models, SQLite schema compatibility migration, auth/session payloads, workspace/member/invitation APIs, and write-operation authorization.
- Frontend auth state, selected workspace handling, workspace switcher, invitation inbox, shared workspace creation, and owner member-management UI.
- Existing local data remains in the current workspace and is migrated in place without deleting media rows or object-storage files.
