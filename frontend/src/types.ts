export type UserRead = {
  id: number;
  username: string;
  display_name: string;
  is_admin: boolean;
};

export type WorkspaceRead = {
  id: number;
  name: string;
  kind: string;
  role: string;
  permissions: Record<string, boolean>;
  can_leave: boolean;
};

export type WorkspaceMember = {
  id: number;
  user: UserRead;
  role: string;
  permissions: Record<string, boolean>;
  created_at: string;
};

export type WorkspaceInvitation = {
  id: number;
  workspace_id: number;
  workspace_name: string;
  inviter_username: string;
  invitee_username: string;
  status: string;
  role: string;
  permissions: Record<string, boolean>;
  created_at: string;
};

export type AuthSession = {
  access_token: string;
  token_type: string;
  user: UserRead;
  workspace: WorkspaceRead;
  workspaces: WorkspaceRead[];
};

export type BootstrapStatus = {
  required: boolean;
};

export type Person = {
  id: number;
  name: string;
  display_name: string;
  note: string | null;
  is_unknown: boolean;
  unknown_serial: number | null;
  sample_count: number;
  gallery_photo_count: number;
  created_at: string;
};

export type SamplePhoto = {
  id: number;
  filename: string;
  width: number | null;
  height: number | null;
  taken_at: string | null;
  status: string;
  error_message: string | null;
  quality_status: string | null;
  quality_warnings: string | null;
  source_type: string;
  source_gallery_photo_id: number | null;
  thumbnail_url: string;
  original_url: string;
  created_at: string;
};

export type Tag = {
  id: number;
  name: string;
  is_system: boolean;
  created_at: string;
};

export type GalleryPersonTag = {
  person_id: number;
  person_name: string;
  is_unknown: boolean;
  source: string;
  promoted_sample_id: number | null;
};

export type GalleryTag = {
  id: number;
  name: string;
  is_system: boolean;
};

export type Face = {
  id: number;
  bbox_left: number;
  bbox_top: number;
  bbox_right: number;
  bbox_bottom: number;
  matched_person_id: number | null;
  match_score: number | null;
  second_person_id: number | null;
  second_match_score: number | null;
  match_margin: number | null;
  embedding_version: string | null;
  face_size: number | null;
  blur_score: number | null;
  pose_yaw: number | null;
  needs_review: boolean;
  vector_collection: string | null;
};

export type GalleryPhotoListItem = {
  id: number;
  filename: string;
  width: number | null;
  height: number | null;
  taken_at: string | null;
  is_rich_text: boolean;
  rich_text: string | null;
  ocr_status: string | null;
  persons: GalleryPersonTag[];
  tags: GalleryTag[];
  thumbnail_url: string;
  original_url: string;
};

export type GalleryPhotoDetail = GalleryPhotoListItem & {
  faces: Face[];
  created_at: string;
  content_type: string | null;
  recognition_summary: {
    faces: number;
    known: number;
    unknown: number;
    manual_tags_preserved: number;
  } | null;
};

export type PaginatedGalleryPhotos = {
  items: GalleryPhotoListItem[];
  total: number;
  offset: number;
  limit: number;
};

export type Task = {
  id: string;
  kind: string;
  status: string;
  message: string | null;
  progress: number;
  created_at: string;
  updated_at: string;
};

export type TagStatistics = {
  tag_id: number;
  tag_name: string;
  is_system: boolean;
  photo_count: number;
};

export type PersonStatistics = {
  person_id: number;
  person_name: string;
  display_name: string;
  is_unknown: boolean;
  photo_count: number;
  sample_count: number;
};

export type UploadHistory = {
  id: number;
  upload_type: string;
  total_count: number;
  success_count: number;
  duplicate_count: number;
  created_at: string;
};

export type UploadSummary = {
  total_uploads: number;
  total_photos: number;
  total_success: number;
  total_duplicates: number;
  by_type: {
    gallery: { count: number; photos: number };
    rich: { count: number; photos: number };
  };
};

export type VideoCategoryTag = {
  id: number;
  name: string;
  created_at: string;
};

export type VideoPerson = {
  id: number;
  name: string;
  note: string | null;
  avatar_url: string | null;
  created_at: string;
  updated_at: string;
};

export type VideoSubtitleTrack = {
  id: number;
  video_id: number;
  language: string;
  label: string;
  source_language: string | null;
  provider: string;
  status: string;
  error_message: string | null;
  task_id: string | null;
  generated_at: string | null;
  created_at: string;
  updated_at: string;
  vtt_url: string | null;
  srt_url: string | null;
};

export type SubtitleAsrStatus = {
  status: string;
  loaded: boolean;
  model_path: string;
  device: string;
  compute_type: string;
  current_video_id: number | null;
  current_task_id: string | null;
  message: string | null;
  last_duration_seconds: number | null;
  last_language: string | null;
  last_segment_count: number | null;
  last_error: string | null;
};

export type SubtitleServiceStatus = {
  status: string;
  healthy: boolean;
  managed: boolean;
  pid: number | null;
  endpoint: string;
  model: string;
  model_path: string;
  server_path: string | null;
  log_path: string | null;
  message: string | null;
  asr: SubtitleAsrStatus;
};

export type SubtitleServiceLogs = {
  log_path: string | null;
  exists: boolean;
  content: string;
};

export type SubtitleJob = {
  video_id: number;
  video_title: string;
  video_filename: string;
  track: VideoSubtitleTrack;
  task: Task | null;
};

export type VideoItem = {
  id: number;
  title: string;
  description: string | null;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  status: string;
  category_tags: VideoCategoryTag[];
  people: VideoPerson[];
  stream_url: string;
  play_url: string;
  cover_url: string | null;
  faststart_applied: boolean;
  seek_optimized: boolean;
  seek_optimized_at: string | null;
  seek_keyframe_interval_seconds: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  original_video_codec: string | null;
  original_audio_codec: string | null;
  video_codec: string | null;
  audio_codec: string | null;
  processed_at: string | null;
  processing_error: string | null;
  subtitle_tracks: VideoSubtitleTrack[];
  created_at: string;
  updated_at: string;
};

export type VideoDetail = VideoItem & {
  sha256: string | null;
};

export type VideoPlaybackDiagnostics = {
  video_id: number;
  status: string;
  content_type: string | null;
  size_bytes: number;
  play_url: string;
  stream_url: string;
  presigned_enabled: boolean;
  minio_endpoint: string;
  minio_public_endpoint: string;
  minio_public_secure: boolean;
  expected_mode: string;
  presigned_url_scheme?: string;
  presigned_url_host?: string;
  presigned_url_path_prefix?: string;
  presigned_url_ok?: boolean;
  presigned_url_error?: string;
  object_probe_ok?: boolean;
  object_probe_error?: string;
  object?: {
    object_key: string;
    object_size_bytes: number;
    object_content_type: string | null;
    duration_seconds: number | null;
    width: number | null;
    height: number | null;
    video_codec: string | null;
    audio_codec: string | null;
    bitrate: number | null;
    faststart: boolean | null;
    estimated_keyframe_interval_seconds: number | null;
  };
};

export type PaginatedVideos = {
  items: VideoItem[];
  total: number;
  offset: number;
  limit: number;
};

export type VideoUploadSession = {
  id: string;
  filename: string;
  title: string;
  description: string | null;
  content_type: string | null;
  size_bytes: number;
  part_size: number;
  total_parts: number;
  uploaded_parts: number[];
  status: string;
  created_at: string;
  updated_at: string;
};
