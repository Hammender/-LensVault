import type { GalleryPhotoListItem, Task } from "./gallery";

export type AcquisitionSource = {
  id: number;
  name: string;
  base_url: string;
  notes: string | null;
  page_format_key: string | null;
  script_keys: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type PaginatedAcquisitionSources = {
  items: AcquisitionSource[];
  total: number;
  offset: number;
  limit: number;
};

export type AcquisitionScriptParameterOption = {
  value: string;
  label: string;
};

export type AcquisitionScriptParameter = {
  key: string;
  label: string;
  type: "string" | "integer" | "number" | "boolean" | "select" | "datetime" | "string_list";
  required: boolean;
  default: unknown;
  description: string | null;
  minimum: number | null;
  maximum: number | null;
  options: AcquisitionScriptParameterOption[];
};

export type AcquisitionScript = {
  key: string;
  name: string;
  version: string;
  page_format_key: string;
  description: string;
  parameters: AcquisitionScriptParameter[];
  credentials?: Array<{ key: string; label: string; required?: boolean; description?: string; secret?: boolean }>;
  is_plugin?: boolean;
};

export type AcquisitionCategory = {
  id: number;
  source_id: number;
  name: string;
  crawl_url: string;
  notes: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  telegram_peer_id?: string | null;
  telegram_entity_type?: "channel" | "group" | "bot" | null;
  telegram_username?: string | null;
  telegram_topic_id?: number | null;
  telegram_topic_title?: string | null;
  telegram_source_mode?: "manual" | "dialog";
};

export type PaginatedAcquisitionCategories = {
  items: AcquisitionCategory[];
  total: number;
  offset: number;
  limit: number;
};

export type AcquisitionRun = {
  id: string;
  source_id: number;
  category_id: number;
  script_key: string | null;
  credential_id?: number | null;
  script_name: string;
  script_version: string;
  source_name: string;
  category_name: string;
  category_url: string;
  parameters: Record<string, unknown>;
  mode: string;
  status: string;
  total_count: number;
  downloaded_count: number;
  skipped_count: number;
  download_success_count: number;
  candidate_count: number;
  content_duplicate_count: number;
  gallery_duplicate_count: number;
  resolution_duplicate_count: number;
  resolution_upgrade_count: number;
  ignored_count: number;
  invalid_count: number;
  error_count: number;
  imported_count: number;
  error_message: string | null;
  scan_start_page: number | null;
  scan_end_page: number | null;
  reached_collection_end: boolean;
  stop_reason: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PaginatedAcquisitionRuns = {
  items: AcquisitionRun[];
  total: number;
  offset: number;
  limit: number;
};

export type AcquisitionCaptureMetadata = {
  video_asset_id: string;
  video_filename: string;
  video_sha256: string;
  frame_index: number;
  time_seconds: number;
  source_caption: string | null;
  source_hashtags: string[];
  source_published_at: string | null;
  source_message_url: string | null;
  source_channel_title: string | null;
};

export type AcquisitionFrame = {
  frame_index: number;
  time_seconds: number;
  total_frames: number;
  source_sha256: string;
  image_url: string;
};

export type AcquisitionCaptureResult = {
  asset: AcquisitionAsset;
  outcome: "created" | "existing" | "restored" | "imported";
};

export type AcquisitionAsset = {
  id: string;
  filename: string;
  content_type: string | null;
  media_type: "image" | "video";
  sha256: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  blur_score: number | null;
  overall_quality_score: number | null;
  face_quality_score: number | null;
  similarity_quality_score: number | null;
  recommended_keep: boolean;
  quality_warnings: string[];
  status: string;
  created_at: string;
  preview_url: string | null;
  original_url: string | null;
  source_caption: string | null;
  source_hashtags: string[];
  source_published_at: string | null;
  source_message_url: string | null;
  source_channel_title: string | null;
  capture_metadata?: AcquisitionCaptureMetadata | null;
};

export type PaginatedAcquisitionAssets = {
  items: AcquisitionAsset[];
  total: number;
  offset: number;
  limit: number;
};

export type AcquisitionAssetSummary = {
  total: number;
  status_counts: Record<string, number>;
  media_counts?: Record<string, number>;
  status_media_counts?: Record<string, Record<string, number>>;
};

export type AcquisitionImportBatchItem = {
  id: number;
  asset_id: string;
  ordinal: number;
  status: string;
  gallery_photo_id: number | null;
  video_id: number | null;
  target_type: "image" | "video";
  attempt_count: number;
  error_message: string | null;
};

export type AcquisitionImportBatch = {
  id: string;
  status: string;
  is_rich_text: boolean;
  has_video?: boolean;
  has_image?: boolean;
  total_count: number;
  processed_count: number;
  imported_count: number;
  duplicate_count: number;
  failed_count: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  items: AcquisitionImportBatchItem[];
};

export type PaginatedAcquisitionImportBatches = {
  items: AcquisitionImportBatch[];
  total: number;
  offset: number;
  limit: number;
  unassigned_imported_count: number;
};

export type AcquisitionImportOrigin = {
  run_id: string;
  source_name: string;
  category_name: string;
  run_created_at: string;
};

export type AcquisitionImportBatchItemDetail = {
  id: number | null;
  asset_id: string;
  ordinal: number;
  status: string;
  gallery_photo_id: number | null;
  video_id?: number | null;
  target_type?: "image" | "video";
  gallery_photo_snapshot_id: number | null;
  gallery_available: boolean;
  attempt_count: number;
  error_message: string | null;
  filename: string;
  sha256: string;
  imported_at: string | null;
  origins: AcquisitionImportOrigin[];
};

export type PaginatedAcquisitionImportBatchItems = {
  items: AcquisitionImportBatchItemDetail[];
  total: number;
  offset: number;
  limit: number;
};

export type AcquisitionSimilarityGroup = {
  id: string;
  max_score: number;
  average_score: number;
  face_quality_enabled: boolean;
  recommendation_status: "recommended" | "close_quality" | "unavailable";
  members: AcquisitionAsset[];
  gallery_members: Array<{
    photo: GalleryPhotoListItem;
    score: number;
    overall_quality_score: number;
    face_quality_score: number | null;
    quality_score: number;
    recommended_keep: boolean;
  }>;
};

export type AcquisitionSimilarityResult = {
  scan_type: "normal" | "mirror";
  scope: "pending_only" | "pending_to_gallery";
  task: Task | null;
  generated_at: string | null;
  is_stale: boolean;
  groups: AcquisitionSimilarityGroup[];
  total: number;
  offset: number;
  limit: number;
};

export type AcquisitionHistoryItem = {
  id: number;
  run_id: string;
  category_path: string;
  gallery_photo_id: number | null;
  gallery_photo_snapshot_id: number | null;
  filename: string;
  sha256: string;
  available: boolean;
  created_at: string;
};

export type AcquisitionExport = {
  id: string;
  status: string;
  filename: string | null;
  item_count: number;
  missing_count: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
  download_url: string | null;
};
