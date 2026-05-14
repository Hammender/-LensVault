## ADDED Requirements

### Requirement: Video Upload Sessions

The system SHALL allow users to create a video upload session with title, description, filename, content type, size, and chunk size.

#### Scenario: Chunked upload completes

- **GIVEN** a valid MP4 video upload session
- **WHEN** all required chunks are uploaded and completion is requested
- **THEN** the system SHALL compose the chunks into one final MinIO object
- **AND** create one video library record
- **AND** remove temporary chunk objects.

#### Scenario: Upload resumes

- **GIVEN** a session with some uploaded chunks
- **WHEN** the client queries the session
- **THEN** the system SHALL return uploaded part indexes so the client can skip them.

### Requirement: Video Streaming

The system SHALL provide playable video URLs backed by MinIO and retain an HTTP byte range fallback endpoint.

#### Scenario: Browser seeks in a video

- **GIVEN** a stored video
- **WHEN** the browser requests `Range: bytes=start-end` from the backend stream fallback
- **THEN** the system SHALL return status `206`
- **AND** include `Accept-Ranges`, `Content-Range`, and `Content-Length` headers
- **AND** stream only the requested byte range from MinIO.

#### Scenario: Browser plays through MinIO

- **GIVEN** a stored video
- **WHEN** the frontend requests video list or detail data
- **THEN** the response SHALL include a MinIO presigned play URL
- **AND** also include a backend stream URL for fallback playback.

### Requirement: Video Faststart Processing

The system SHALL run ffmpeg faststart processing after upload completion to optimize MP4 metadata placement.

#### Scenario: Faststart succeeds

- **GIVEN** all video chunks have been composed into a final MinIO object
- **WHEN** post-upload processing runs
- **THEN** the system SHALL remux the MP4 with `-c copy -movflags +faststart`
- **AND** replace the final MinIO object with the optimized object
- **AND** mark the video as ready with faststart applied.

#### Scenario: Faststart fails

- **GIVEN** a composed video object
- **WHEN** ffmpeg processing fails
- **THEN** the system SHALL keep the original MinIO object
- **AND** mark the video with a processing failure status and error message.

### Requirement: Independent Video Tags

The system SHALL maintain video category tags and video people independently from image tags and image people.

#### Scenario: Tag video

- **GIVEN** an uploaded video
- **WHEN** a user assigns category tags and video people
- **THEN** the system SHALL return them in video list/detail responses
- **AND** image gallery tags SHALL NOT be modified.

### Requirement: Video People Avatars

The system SHALL allow each video person to have one optional uploaded avatar photo for display.

#### Scenario: Display video person

- **GIVEN** a video person with an avatar object
- **WHEN** the frontend renders filters or video details
- **THEN** the response SHALL include an avatar URL that loads the stored photo.
