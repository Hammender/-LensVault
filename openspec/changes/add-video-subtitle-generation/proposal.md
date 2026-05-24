# Add Video Subtitle Generation

## Why

PictureShow already supports uploading MP4, MKV, MOV, and WEBM videos, then processing them into browser-playable video. Users also need YouTube-style optional subtitles that are displayed by the platform during playback without modifying or burning text into the video file.

## What Changes

- Add platform-managed subtitle tracks for videos, starting with Simplified Chinese subtitles.
- Let users choose whether to generate Chinese subtitles during video upload.
- Let users generate, retry, edit, replace, show, hide, and delete subtitle tracks from the video detail/playback flow.
- Generate subtitles asynchronously after upload or on demand using local audio extraction, speech recognition, and translation providers.
- Serve subtitles as WebVTT so the frontend player can overlay them separately from the video asset.

## Out of Scope

- Burning subtitles into video pixels.
- Replacing the original uploaded media with a subtitle-muxed file.
- Full multi-language subtitle management beyond the initial Chinese subtitle track.
- Human-level translation quality guarantees; generated subtitles are editable because automatic results need review.

## Impact

- Adds video subtitle persistence and API surface.
- Adds optional local AI dependencies and settings for speech recognition and translation providers.
- Extends the video upload completion payload and frontend upload modal.
- Extends the custom video player to load and toggle subtitle tracks.
