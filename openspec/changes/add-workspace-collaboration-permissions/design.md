## Context

The current codebase has a FastAPI backend, SQLite local state, MinIO object storage, and a React client. A first-pass tenant model already exists around `User`, `Workspace`, and `WorkspaceMember`, and content rows already carry `workspace_id`. That model still treats administration as global and does not express private workspaces, invitation flows, member exit, or per-member write permissions.

## Goals / Non-Goals

**Goals:**

- Make workspace ownership local to each workspace.
- Guarantee every account has a private workspace owned only by that account.
- Support user-created shared workspaces.
- Support owner invitation of existing accounts and owner creation of new accounts directly into a shared workspace.
- Gate write operations by member permissions while keeping read access available to all members.
- Preserve existing local data during SQLite migration.

**Non-Goals:**

- Active request-to-join workflows.
- Public workspaces.
- Cross-workspace sharing of a single media row.
- Fine-grained per-item ACLs inside a workspace.
- Removing legacy columns immediately.

## Decisions

### Workspace kinds

Use a `kind` column on `workspaces` with `private` and `shared` values, plus `owner_user_id` for the owner account. This keeps private and shared workspaces in the same authorization path and avoids creating a separate tenant table.

Alternative considered: model private storage as user-owned records without a workspace. That would duplicate most content filtering logic and make switching between private and shared spaces harder.

### Self-service registration

After the first administrator bootstrap is complete, the login screen allows open account registration. A self-registered account is a normal active account, receives its own private workspace, and is not added to any shared workspace. When no administrator exists yet, registration remains blocked so the bootstrap flow creates the first administrator and initial private workspace.

### Membership permissions

Store permissions on `workspace_members` as booleans:

- `can_add_gallery`, `can_delete_gallery`, `can_edit_gallery`
- `can_add_samples`, `can_delete_samples`, `can_edit_samples`
- `can_add_videos`, `can_delete_videos`, `can_edit_videos`

Owners bypass these booleans and always have all permissions. Every member has read access by membership alone.

Alternative considered: role templates such as admin/editor/viewer. The requested behavior requires owner-configurable individual options, so explicit booleans are clearer and easier to evolve.

### Invitations

Add `workspace_invitations` for existing-account invitations. Invitations are pending until accepted or declined. The invitation stores the intended permission booleans so acceptance creates the membership exactly as configured by the owner.

Creating a brand-new account from a shared workspace is not modeled as an invitation; the account is created, receives its own private workspace, and is immediately added to the current shared workspace.

### SQLite migration

Use additive migrations for new columns and tables, then backfill missing workspace kind and owner metadata. Existing content rows already assigned to a workspace stay in place. Existing content rows without a workspace are assigned to the legacy workspace `id=1`. Existing MinIO objects referenced by legacy rows are copied into workspace-scoped object keys and the database reference is updated only after the copy is verified; the old MinIO object is retained. Existing workspaces with one owner become private by default; multi-member workspaces become shared.

Dropping or rebuilding existing tables is avoided for this change because additive columns preserve local data with lower risk.

## Risks / Trade-offs

- [Risk] Existing local databases may have partially migrated rows from earlier development states. -> Backfill helper functions must tolerate missing owners and create private workspaces when a user logs in.
- [Risk] Frontend controls may miss some edge-case buttons. -> Backend permission checks are authoritative.
- [Risk] Owners leaving or being removed could orphan a shared workspace. -> Owner leave/removal is blocked when it would leave no owner.

## Migration Plan

1. Add new columns and tables through startup compatibility migration.
2. Backfill workspaces with `kind`, `owner_user_id`, and member permission defaults.
3. Ensure every user has a private workspace on bootstrap, login, session fetch, and user creation.
4. Preserve legacy content associations by leaving existing `workspace_id` values unchanged.

Rollback is limited because SQLite schema changes are additive. A rollback can leave the new columns/tables unused while older content rows remain readable by previous code paths that ignore them.

## Open Questions

- Whether future request-to-join workflows should reuse `workspace_invitations` or introduce a separate `workspace_join_requests` table.
- Whether role templates should be added later for easier bulk permission management.
