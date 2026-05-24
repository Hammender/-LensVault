# Tasks

- [x] Add subtitle track database model, relationship, SQLite legacy-table creation, and cascade cleanup.
- [x] Add subtitle Pydantic schemas and include lightweight subtitle track metadata in video detail responses.
- [x] Add subtitle list, WebVTT read, generate/retry, edit, and delete APIs.
- [x] Add subtitle generation service with ffmpeg audio extraction, `faster-whisper medium` CPU int8 ASR adapter, `local_hymt2` translation adapter through local `llama-server`, WebVTT rendering, and task status updates.
- [x] Add subtitle-related local `.env` settings and dependency notes.
- [x] Extend upload completion payload with `generate_zh_subtitles`.
- [x] Extend frontend API helper with `generate_zh_subtitles`.
- [x] Add upload modal checkbox and playback/detail subtitle controls.
- [x] Extend `BiliVideoPlayer` to load WebVTT tracks and toggle subtitles without modifying the video source.
- [x] Validate backend syntax checks and app/service imports.
- [x] Validate frontend `cmd /c npm.cmd run build` after frontend integration.
