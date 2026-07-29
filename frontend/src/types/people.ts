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
