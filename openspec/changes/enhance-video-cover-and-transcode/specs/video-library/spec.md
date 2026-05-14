## ADDED Requirements

### Requirement: Video Covers

The system SHALL generate a cover image for each uploaded video and allow the user to replace that cover.

#### Scenario: Cover generated during processing

- **GIVEN** a video upload has completed
- **WHEN** post-upload processing runs
- **THEN** the system SHALL extract a representative JPEG frame
- **AND** store it in MinIO
- **AND** return a `cover_url` in video list and detail responses.

#### Scenario: User replaces cover

- **GIVEN** an existing video
- **WHEN** the user uploads an image as the cover
- **THEN** the system SHALL replace the old cover object
- **AND** future video list and detail responses SHALL reference the new cover.

### Requirement: Original and Playback Codec Metadata

The system SHALL record the original uploaded codecs separately from the final playback codecs.

#### Scenario: Browser-friendly upload

- **GIVEN** an uploaded MP4 with browser-friendly video and audio codecs
- **WHEN** post-upload processing completes
- **THEN** the original codec fields SHALL match the uploaded file
- **AND** the playback codec fields SHALL match the final faststart file
- **AND** the video SHALL be marked ready.

#### Scenario: Browser-unfriendly upload

- **GIVEN** an uploaded MP4 with browser-unfriendly codecs
- **WHEN** post-upload processing completes
- **THEN** the original codec fields SHALL preserve the uploaded codecs
- **AND** the playback codec fields SHALL describe the transcoded H.264 + AAC file.

### Requirement: Conditional Browser-Friendly Processing

The system SHALL transcode only videos that are not browser-friendly and otherwise perform lossless faststart remuxing.

#### Scenario: Browser-friendly video is remuxed

- **GIVEN** a stored MP4 using H.264 video and AAC, MP3, or no audio
- **WHEN** post-upload processing runs
- **THEN** the system SHALL use stream copy with faststart
- **AND** preserve visual quality.

#### Scenario: Browser-unfriendly video is transcoded

- **GIVEN** a stored MP4 using codecs unsuitable for browser playback
- **WHEN** post-upload processing runs
- **THEN** the system SHALL produce an H.264 + AAC MP4 playback file with faststart
- **AND** replace the stored video object with the playback file.
