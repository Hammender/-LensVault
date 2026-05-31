## ADDED Requirements

### Requirement: Private Workspace Ownership
Every account SHALL have one private workspace owned by that account. A private workspace SHALL NOT allow any other account to become a member, and the owner SHALL NOT be allowed to leave it.

#### Scenario: New account gets private workspace
- **WHEN** an account is created
- **THEN** the system creates a private workspace owned by that account

#### Scenario: Private workspace cannot be shared
- **WHEN** an owner tries to invite or add another account to a private workspace
- **THEN** the system rejects the operation

#### Scenario: Private workspace cannot be left
- **WHEN** a user tries to leave their private workspace
- **THEN** the system rejects the operation

### Requirement: Self-Service Account Registration
After system bootstrap, unauthenticated users SHALL be able to register a normal account from the auth screen. A self-registered account SHALL receive exactly one private workspace owned by that account and SHALL NOT be added to any shared workspace.

#### Scenario: User registers after bootstrap
- **WHEN** an unauthenticated user submits a unique username and valid password after system bootstrap
- **THEN** the system creates the account, creates its private workspace, and returns an authenticated session for that private workspace

#### Scenario: Registration before bootstrap
- **WHEN** no administrator account exists and a user tries to register
- **THEN** the system rejects registration and requires the bootstrap flow

### Requirement: Shared Workspace Creation
Any authenticated account SHALL be able to create a shared workspace and SHALL become its owner.

#### Scenario: User creates shared workspace
- **WHEN** an authenticated user creates a workspace with a valid name
- **THEN** the system creates a shared workspace and adds the user as owner

### Requirement: Invitation Based Membership
Shared workspace owners SHALL be able to invite existing accounts into the shared workspace. Invited accounts SHALL become members only after accepting the invitation.

#### Scenario: Owner invites existing account
- **WHEN** a shared workspace owner invites an account that is not already a member
- **THEN** the system records a pending invitation for that account

#### Scenario: Invitee accepts invitation
- **WHEN** the invited account accepts a pending invitation
- **THEN** the system creates a workspace membership using the invitation permissions

#### Scenario: Invitee declines invitation
- **WHEN** the invited account declines a pending invitation
- **THEN** the system marks the invitation declined and does not create membership

### Requirement: Direct Account Creation Into Shared Workspace
Shared workspace owners SHALL be able to create a new account directly inside the current shared workspace. The new account SHALL also receive its own private workspace.

#### Scenario: Owner creates member account
- **WHEN** a shared workspace owner creates a new account
- **THEN** the system creates the account, creates its private workspace, and adds it to the shared workspace immediately

### Requirement: Member Exit
Members SHALL be able to leave shared workspaces. The system MUST prevent leaving private workspaces and MUST prevent a shared workspace from losing its last owner.

#### Scenario: Member leaves shared workspace
- **WHEN** a non-owner member leaves a shared workspace
- **THEN** the system removes that membership

#### Scenario: Last owner cannot leave
- **WHEN** the only owner of a shared workspace tries to leave
- **THEN** the system rejects the operation

### Requirement: Owner Managed Write Permissions
Shared workspace owners SHALL be able to configure each ordinary member's add, delete, and edit permissions separately for gallery pictures, person sample-library pictures, and videos. Owners SHALL always have all permissions.

#### Scenario: Owner updates member permissions
- **WHEN** a shared workspace owner updates a member's write permissions
- **THEN** the system persists those permission settings for that member

#### Scenario: Owner has all permissions
- **WHEN** the workspace owner performs any workspace write operation
- **THEN** the system allows the operation regardless of stored permission booleans

### Requirement: Mandatory Read Access
All workspace members SHALL be able to read all pictures, videos, metadata, and member-visible workspace content in that workspace. Read access SHALL NOT be configurable per member.

#### Scenario: Member reads workspace media
- **WHEN** any workspace member requests pictures or videos in the workspace
- **THEN** the system returns the workspace content allowed by membership

### Requirement: Legacy media migration
When upgrading an existing single-workspace installation, legacy media rows without `workspace_id` SHALL be assigned to workspace `id=1`. Legacy MinIO objects referenced by those rows SHALL be copied into workspace-scoped object keys before the database reference is updated, and the original object SHALL be retained.

#### Scenario: Upgrade legacy local media
- **GIVEN** an existing media row has no workspace assignment or references a non-workspace MinIO key
- **WHEN** the application startup migration runs
- **THEN** the row is assigned to workspace `id=1`
- **AND** the referenced object is copied under `workspaces/1/`
- **AND** the database key is updated only after the copied object is verified
