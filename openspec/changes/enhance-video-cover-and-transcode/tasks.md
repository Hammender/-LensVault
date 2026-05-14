# Tasks

- [x] Add video cover and codec metadata columns with legacy SQLite column backfill.
- [x] Add ffprobe-based metadata extraction and browser-friendly codec detection.
- [x] Generate automatic JPEG covers during post-upload processing.
- [x] Conditionally transcode non-browser-friendly uploads to H.264 + AAC and faststart the final playback file.
- [x] Add video cover read and replacement APIs.
- [x] Return cover URL, media dimensions, duration, original codecs, and final playback codecs in video list/detail APIs.
- [x] Update the frontend video list, playback page, types, and API helper for covers and codec display.
- [x] Validate with backend compile checks and frontend production build without starting services.
