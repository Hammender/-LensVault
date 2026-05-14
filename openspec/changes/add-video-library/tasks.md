## 1. Backend

- [x] Add video, video category tag, video person, and upload session database models.
- [x] Add MinIO helpers for streamed range reads, temporary chunk storage, object composition, and cleanup.
- [x] Add video upload session, chunk upload, completion, cancellation, list/detail, metadata, tag, person, avatar, delete, and stream endpoints.
- [x] Validate MP4 uploads and serve `Accept-Ranges` / `Content-Range` responses for playback.
- [x] Add ffmpeg faststart processing after upload completion.
- [x] Add MinIO presigned play URLs with backend stream fallback.

## 2. Frontend

- [x] Add video API client types and request helpers.
- [x] Add a video page to the app navigation.
- [x] Add upload form with title, description, category tags, video people tags, resumable chunk upload, and progress.
- [x] Add video filters, list view, detail view, and native browser playback.
- [x] Add independent video category/person tag management.
- [x] Display video processing status and use presigned play URLs for playback.

## 3. Verification

- [x] Run backend syntax validation.
- [x] Run frontend production build.
