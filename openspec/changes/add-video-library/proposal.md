# Add Video Library

## Why

PictureShow currently manages still images, people samples, gallery tags, and imports. Users also need a first-class video area where they can upload videos to the existing MinIO bucket, browse all videos, tag them independently from image tags, and play long videos smoothly in the browser.

## What Changes

- Add a video library page with video upload, video list, metadata, filters, and native browser playback.
- Store video objects in the existing MinIO bucket under a dedicated namespace.
- Support HTTP byte range streaming for smooth seeking through short and long MP4 videos.
- Add an independent video tag model:
  - category tags for classification.
  - video people tags for named people shown with a single avatar photo.
- Add resumable chunk upload sessions. Chunks are stored temporarily, composed into the final MinIO object without quality loss, and removed after completion.
- Run ffmpeg faststart remux after upload completion to move MP4 metadata to the front without re-encoding.
- Return MinIO presigned play URLs for browser playback, while keeping the backend range stream endpoint as a fallback.

## Scope

- First version supports MP4/H.264/AAC-style browser playback through the native `<video>` element.
- No video transcoding, HLS generation, cover generation, duration probing, or face recognition is included in this change.
- ffmpeg is expected to be installed and available on PATH unless configured otherwise.
- Video tags do not reuse image gallery tags or image person entities.

## Risks

- Browser seeking quality still depends on codec, keyframe interval, bitrate, and network quality. Faststart improves MP4 metadata access but does not replace transcoding or HLS.
- MinIO compose requires non-final parts to be at least 5 MiB. The client uses 16 MiB chunks to satisfy that constraint.
