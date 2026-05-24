# Design: Video Subtitle Generation

## Current System Context

The current video library accepts `.mp4`, `.mkv`, `.mov`, and `.webm` uploads. Uploads are chunked, composed into MinIO, then processed by `VideoService.process_video_for_playback`. The post-upload step probes metadata, extracts a cover, and writes a browser-playable MP4 playback object when needed. The frontend uses a custom `BiliVideoPlayer` around the native `<video>` element.

Subtitle generation should attach to the platform playback layer, not to a specific source container. The generated subtitles are separate records and WebVTT text served by the API.

## Data Model

Add `VideoSubtitleTrack` with:

- `id`
- `video_id`
- `language`, default `zh-CN`
- `label`, default `中文字幕`
- `source_language`
- `provider`
- `status`: `pending`, `running`, `ready`, `failed`
- `content_vtt`
- `error_message`
- `generated_at`
- `created_at`
- `updated_at`

Each video may have at most one generated `zh-CN` track in the first implementation. Deleting a video cascades subtitle deletion.

## Backend Flow

Upload completion accepts `generate_zh_subtitles: bool = false`. When true, the backend creates a subtitle track in `pending` status and schedules a `video_subtitle_generation` background task after video upload completion.

On-demand generation uses the same task path and should replace/retry the existing generated Chinese track instead of creating duplicates.

Generation steps:

1. Wait until the video is playable or fail with a retryable message if playback processing failed.
2. Download the current video object from MinIO to a temporary file.
3. Use `ffmpeg` to extract audio to a normalized WAV file.
4. Run local ASR with `faster-whisper medium` from `E:\AI-MODELS\ASR\faster-whisper-medium`, using CPU `int8` and automatic source-language detection.
5. Translate segment text to Simplified Chinese using the configured translation provider.
6. Preserve ASR segment start/end timestamps and write translated text as WebVTT.
7. Mark the subtitle track `ready`, or `failed` with an error message.

The task status should be independent from `VideoItem.status` so video playback remains available even if subtitle generation fails.

## Translation Provider Strategy

Use a provider interface so translation can evolve without changing API contracts. The first implementation exposes only one configured mode in the UI and task runner:

- `local_hymt2`: default and only v1 mode, backed by `llama-server` on `http://127.0.0.1:8081/v1` with `E:\AI-MODELS\translate\HY-MT2-1-1.88GGUF\Hy-MT2-1.8B-Q4_K_M.gguf`.
- `none`, `local_nllb`, and `external` remain internal extension points only; do not expose provider selection in v1.

For v1 implementation, keep provider configuration explicit in `.env`. If local translation dependencies or model files are missing, generation fails with a clear setup error.

Default local settings:

- `SUBTITLE_ASR_MODEL_PATH=E:/AI-MODELS/ASR/faster-whisper-medium`
- `SUBTITLE_ASR_DEVICE=cpu`
- `SUBTITLE_ASR_COMPUTE_TYPE=int8`
- `SUBTITLE_TRANSLATION_PROVIDER=local_hymt2`
- `SUBTITLE_TRANSLATION_BASE_URL=http://127.0.0.1:8081/v1`
- `SUBTITLE_TRANSLATION_MODEL=Hy-MT2-1.8B-Q4_K_M`

## API And Frontend

Add subtitle APIs:

- `GET /api/videos/{video_id}/subtitles`
- `GET /api/videos/{video_id}/subtitles/{track_id}.vtt`
- `POST /api/videos/{video_id}/subtitles/generate`
- `PATCH /api/videos/{video_id}/subtitles/{track_id}`
- `DELETE /api/videos/{video_id}/subtitles/{track_id}`

Video detail responses may include a lightweight `subtitle_tracks` list so playback can render immediately without a second fetch.

Frontend changes:

- Add an upload checkbox: `自动生成中文字幕`.
- Add subtitle status controls in the video playback/sidebar area.
- Pass ready subtitle track URLs to `BiliVideoPlayer`.
- Add a subtitle toggle in the player controls.
- Add a text editor for WebVTT correction and save.

## Failure Modes

- No audio stream: mark subtitle failed with `未检测到音轨`.
- Video processing failed: subtitle task fails without blocking video status.
- ASR model missing or unsupported device: failed setup message.
- Translation provider unavailable: failed setup message.
- Malformed edited WebVTT: reject save with validation error.
