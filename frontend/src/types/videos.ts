import type { SourceSummary } from "./provenance";
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

export type VideoItem = {
  source_summary?: SourceSummary;
  id: number;
  title: string;
  description: string | null;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  status: string;
  video_type: "short" | "long";
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
