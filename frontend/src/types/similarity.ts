import type { GalleryPhotoListItem, Task } from "./gallery";
import type { Person } from "./people";

export type GallerySimilarityScan = {
  id: string;
  task_id: string | null;
  person_id: number | null;
  include_cross_type: boolean;
  scan_type: "normal" | "mirror";
  auto_delete_exact_mirror: boolean;
  auto_deleted_count: number;
  status: string;
  is_stale: boolean;
  feature_version: string;
  photo_count: number;
  candidate_pair_count: number;
  group_count: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  task: Task | null;
};

export type GallerySimilarityScanOverview = {
  active: GallerySimilarityScan | null;
  results: GallerySimilarityScan[];
};

export type GallerySimilarityMember = {
  photo: GalleryPhotoListItem;
  score_to_representative: number;
  overall_quality_score: number;
  face_quality_score: number | null;
  quality_score: number;
  recommended_keep: boolean;
};

export type GallerySimilarityGroup = {
  id: number;
  ordinal: number;
  tier: "near_duplicate" | "same_scene";
  review_status: "pending" | "dismissed";
  min_score: number;
  average_score: number;
  face_quality_enabled: boolean;
  recommendation_status: "recommended" | "close_quality" | "unavailable";
  people: Person[];
  members: GallerySimilarityMember[];
};

export type PaginatedGallerySimilarityGroups = {
  items: GallerySimilarityGroup[];
  total: number;
  offset: number;
  limit: number;
};
