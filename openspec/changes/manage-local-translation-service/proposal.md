# Manage Local Translation Service

## Why

Subtitle generation now depends on a resident local Hy-MT2 service through `llama-server`. Users need visibility and control for that service from the video library instead of relying on backend console output.

## What Changes

- Add a video-library service panel for local translation service status, manual start/stop, log viewing, and subtitle job progress.
- Expose backend APIs for translation service health, process control, log tailing, subtitle job listing, and per-video subtitle cancellation.
- Add a `canceled` subtitle/task state so manual interruption is not mixed with real failures.

## Out of Scope

- Multi-model selection.
- Remote translation providers.
- Persisted historical log/event storage beyond existing task and subtitle-track records.
