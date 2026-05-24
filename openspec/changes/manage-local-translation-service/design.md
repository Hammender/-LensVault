# Design

The first version keeps the existing local `local_hymt2` provider and wraps its current `llama-server` lifecycle in explicit management APIs. The backend remains the process owner when it starts the server, but on Windows it may also locate a process listening on the configured port for force-stop after confirmation.

Subtitle cancellation is cooperative. The API sets an in-memory cancellation flag and immediately marks the task and subtitle track as `canceled`; the background generation loop checks that flag between major stages and translation batches. An in-flight ASR, ffmpeg, or HTTP call may finish before the loop exits, but the finished task must not publish a ready subtitle after cancellation.

The video library page owns the UI because this is where users manage uploaded videos and subtitle generation. The panel polls service status and subtitle jobs while the page is open, shows the configured model/port/PID, exposes service logs from `SUBTITLE_LLAMA_SERVER_LOG_PATH`, and lists currently active or recently interrupted/failed subtitle jobs.
