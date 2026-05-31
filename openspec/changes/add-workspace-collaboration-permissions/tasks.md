## 1. Data Model And Migration

- [x] 1.1 Add workspace kind/owner fields, member permission fields, and invitation model.
- [x] 1.2 Extend SQLite startup migration to add/backfill new workspace collaboration fields without deleting existing data.
- [x] 1.3 Add helpers that ensure every account has a private workspace.

## 2. Backend Workspace APIs

- [x] 2.1 Extend auth/session schemas to include workspace kind, permissions, and leave capability.
- [x] 2.2 Add shared workspace creation, rename, listing, member listing, member permission update, member removal, and leave endpoints.
- [x] 2.3 Add invitation endpoints for owner invite, invitee list, accept, decline, and owner revoke.
- [x] 2.4 Add owner-created-account endpoint that creates an account, its private workspace, and direct shared-workspace membership.

## 3. Backend Authorization

- [x] 3.1 Replace global-admin checks for workspace administration with workspace-owner checks.
- [x] 3.2 Gate gallery write operations with gallery add/delete/edit permissions.
- [x] 3.3 Gate person sample-library write operations with sample add/delete/edit permissions.
- [x] 3.4 Gate video write operations with video add/delete/edit permissions while keeping reads open to workspace members.

## 4. Frontend Workspace Experience

- [x] 4.1 Persist selected workspace id and send it with authenticated API requests.
- [x] 4.2 Add workspace switcher and shared workspace creation flow.
- [x] 4.3 Add invitation inbox with accept/decline actions.
- [x] 4.4 Add owner member-management UI for invitations, direct account creation, permission updates, member removal, and leave action.

## 5. Verification

- [x] 5.1 Run backend compile check.
- [x] 5.2 Run frontend TypeScript/build check.

## 6. Self-Service Registration

- [x] 6.1 Add OpenSpec coverage for self-service registration after bootstrap.
- [x] 6.2 Add backend registration schema and `/api/auth/register` endpoint.
- [x] 6.3 Add frontend auth API and login/register screen toggle.
- [x] 6.4 Run backend compile check.
- [x] 6.5 Run frontend TypeScript/build check.

## 7. Startup Migration Fix

- [x] 7.1 Migrate legacy global `tags.name` uniqueness to workspace-scoped uniqueness.
- [x] 7.2 Add non-destructive legacy workspace data and MinIO object migration.
- [x] 7.3 Run backend compile check.
