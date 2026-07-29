import type { Task } from "./gallery";
import type { VideoSubtitleTrack } from "./videos";

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
