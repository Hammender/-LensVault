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
