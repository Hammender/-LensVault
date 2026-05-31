## ADDED Requirements

### Requirement: Video Write Permission Enforcement
The system SHALL require workspace video write permissions for video upload, delete, and metadata update operations. Video read operations SHALL remain available to every workspace member.

#### Scenario: Member uploads video with permission
- **WHEN** a workspace member with `can_add_videos` starts or completes a video upload
- **THEN** the system allows the upload operation

#### Scenario: Member uploads video without permission
- **WHEN** a workspace member without `can_add_videos` starts or completes a video upload
- **THEN** the system rejects the upload operation

#### Scenario: Member edits video metadata with permission
- **WHEN** a workspace member with `can_edit_videos` modifies video metadata, tags, people, cover, or subtitle content
- **THEN** the system allows the edit operation

#### Scenario: Member deletes video with permission
- **WHEN** a workspace member with `can_delete_videos` deletes a video
- **THEN** the system allows the delete operation
