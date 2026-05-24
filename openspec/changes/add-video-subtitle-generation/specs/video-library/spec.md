# Video Library Subtitle Generation

## ADDED Requirements

### Requirement: Platform subtitle tracks

The system SHALL store video subtitles as platform-managed subtitle tracks separate from the video media object.

#### Scenario: Play video with subtitles

- **GIVEN** a video has a ready Simplified Chinese subtitle track
- **WHEN** the frontend renders the video player
- **THEN** the user SHALL be able to show or hide the subtitle overlay
- **AND** the video media file SHALL NOT be modified.

### Requirement: Optional Chinese subtitle generation

The system SHALL allow users to request automatic Simplified Chinese subtitle generation during video upload and from an existing video detail page.

#### Scenario: Upload requests subtitles

- **GIVEN** a user uploads a supported video format
- **WHEN** upload completion includes a subtitle generation request
- **THEN** the system SHALL create a subtitle generation task for that video
- **AND** video playback processing SHALL remain independent from subtitle generation status.

#### Scenario: Existing video requests subtitles

- **GIVEN** an existing video without a ready Chinese subtitle track
- **WHEN** the user requests subtitle generation
- **THEN** the system SHALL generate or retry the Chinese subtitle track asynchronously.

### Requirement: Editable generated subtitles

The system SHALL allow users to edit and save generated subtitle text.

#### Scenario: Save corrected subtitles

- **GIVEN** a video has a generated WebVTT subtitle track
- **WHEN** the user saves valid edited WebVTT content
- **THEN** future playback SHALL use the edited subtitle content.

#### Scenario: Reject invalid subtitle text

- **GIVEN** a user edits subtitle content
- **WHEN** the submitted text is not valid WebVTT
- **THEN** the system SHALL reject the update with a validation error
- **AND** preserve the previous subtitle content.

### Requirement: Subtitle generation failures are visible

The system SHALL expose subtitle generation status and failure messages without blocking video playback.

#### Scenario: Subtitle generation fails

- **GIVEN** subtitle generation cannot complete because audio, ASR, or translation is unavailable
- **WHEN** the user views the video detail page
- **THEN** the system SHALL show the failed subtitle status and a retry action
- **AND** the video SHALL remain playable if video processing succeeded.
