# Enhance Video Cover and Transcode

## Why

The video library currently shows MP4 placeholders instead of video covers and only applies faststart remuxing after upload. Users need to see a useful cover, know the uploaded video's original codecs, and get a browser-friendly playback file when the uploaded encoding is not suitable for web playback.

## What Changes

- Generate a video cover image automatically after upload.
- Allow users to replace a video's cover manually.
- Record both original uploaded codecs and final playback codecs.
- Keep faststart-only remuxing for browser-friendly MP4 files.
- Transcode only browser-unfriendly MP4 files to H.264 + AAC and replace the stored playback object.

## Impact

- Adds video metadata columns and response fields.
- Adds a cover upload endpoint and cover image endpoint.
- Expands ffmpeg processing from faststart-only to probe, cover extraction, conditional transcode, and faststart.
