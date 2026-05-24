## ADDED Requirements

### Requirement: Local Translation Service Management

The system SHALL expose the configured local subtitle translation service status and controls from the video library.

#### Scenario: View service status

- **GIVEN** the user opens the video library
- **WHEN** the local translation service is running or stopped
- **THEN** the page SHALL show the current service status, configured model, endpoint, log path, and process id when available.

#### Scenario: Start and stop service

- **GIVEN** the user is on the video library page
- **WHEN** the user starts or stops the translation service
- **THEN** the backend SHALL start or terminate the configured `llama-server` process and return the refreshed service status.

#### Scenario: Stop service with running subtitle jobs

- **GIVEN** subtitle generation jobs are running
- **WHEN** the user confirms a forced translation service stop
- **THEN** the backend SHALL stop the service and mark running subtitle jobs as canceled.

### Requirement: Subtitle Job Visibility And Cancellation

The system SHALL show subtitle generation jobs in the video library and allow users to cancel an individual video subtitle job.

#### Scenario: View subtitle generation progress

- **GIVEN** one or more videos are generating subtitles
- **WHEN** the user opens the video library
- **THEN** the page SHALL show each job's video title, status, task message, progress, and error message when present.

#### Scenario: Cancel one subtitle job

- **GIVEN** a video subtitle job is pending or running
- **WHEN** the user cancels that job
- **THEN** the task and subtitle track SHALL be marked `canceled`
- **AND** the user SHALL be able to request subtitle generation again later.
