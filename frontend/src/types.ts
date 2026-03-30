export type Person = {
  id: number;
  name: string;
  note: string | null;
  photo_count: number;
  created_at: string;
};

export type PhotoTag = {
  person_id: number;
  person_name: string;
  source: string;
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
  cluster_key: string | null;
};

export type PhotoListItem = {
  id: number;
  filename: string;
  width: number | null;
  height: number | null;
  taken_at: string | null;
  tags: PhotoTag[];
  thumbnail_url: string;
  original_url: string;
};

export type PhotoDetail = PhotoListItem & {
  faces: Face[];
  object_key: string;
  content_type: string | null;
  created_at: string;
};

export type PaginatedPhotos = {
  items: PhotoListItem[];
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

export type Cluster = {
  cluster_key: string;
  count: number;
  sample: {
    cluster_key: string;
    face_ids: number[];
    photo_id: number;
    thumbnail_url: string;
  };
};
