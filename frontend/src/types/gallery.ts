import type { SourceSummary } from "./provenance";
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
  face_revision: string;
  recognition_case_id: string | null;
  face_index: number;
  bbox_left: number;
  bbox_top: number;
  bbox_right: number;
  bbox_bottom: number;
  matched_person_id: number | null;
  matched_person_name: string | null;
  matched_person_is_unknown: boolean;
  binding_source: "auto" | "manual" | "unknown";
  predicted_person_id: number | null;
  predicted_person_name: string | null;
  match_score: number | null;
  predicted_match_source: "sample" | "centroid" | null;
  predicted_sample_photo_id: number | null;
  second_person_id: number | null;
  second_person_name: string | null;
  second_match_score: number | null;
  second_match_source: "sample" | "centroid" | null;
  second_sample_photo_id: number | null;
  match_margin: number | null;
  rejection_reason: string | null;
  recognition_adapter_id: string | null;
  decision_threshold: number | null;
  decision_min_margin: number | null;
  embedding_version: string | null;
  face_size: number | null;
  blur_score: number | null;
  pose_yaw: number | null;
  needs_review: boolean;
  vector_collection: string | null;
  promoted_sample_id: number | null;
};

export type GalleryPhotoListItem = {
  source_summary?: SourceSummary;
  id: number;
  filename: string;
  size_bytes: number | null;
  width: number | null;
  height: number | null;
  taken_at: string | null;
  is_rich_text: boolean;
  rich_text: string | null;
  ocr_status: string | null;
  persons: GalleryPersonTag[];
  tags: GalleryTag[];
  thumbnail_url: string;
  animated_thumbnail_url: string;
  original_url: string;
};

export type GalleryPhotoDetail = GalleryPhotoListItem & {
  faces: Face[];
  display_width: number | null;
  display_height: number | null;
  created_at: string;
  content_type: string | null;
  recognition_summary: {
    faces: number;
    known: number;
    unknown: number;
    manual_tags_preserved: number;
    import_tags_preserved?: number;
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

export type StatisticsOverview = {
  gallery_total: number;
  gallery_photo_count: number;
  rich_photo_count: number;
  source_counts: Record<string, number>;
  person_covered_count: number;
  tag_covered_count: number;
  acquisition_status_counts: Record<string, number>;
};

export type ImageIntakeActivity = {
  id: string;
  source: "gallery" | "rich" | "gallery_zip" | "acquisition";
  status: string;
  total_count: number;
  imported_count: number;
  updated_count: number;
  skipped_count: number;
  failed_count: number;
  completed_at: string;
};

export type PaginatedImageIntakeActivities = {
  items: ImageIntakeActivity[];
  total: number;
  offset: number;
  limit: number;
};
