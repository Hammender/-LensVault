import type { Face } from "./gallery";

export type CaseIssueType = "unknown" | "wrong_person" | "other";
export type CaseAnswerType = "known_person" | "out_of_library" | "not_person";
export type FaceCase = {
  id: string;
  source_photo_id: number | null;
  source_face_id: number;
  correct_person_id: number | null;
  correct_person_name: string;
  answer_type: CaseAnswerType;
  excluded_person_id: number | null;
  excluded_person_name: string | null;
  issue_type: CaseIssueType;
  notes: string;
  embedding_version: string | null;
  actor_name: string;
  status: string;
  cleanup_error: string | null;
  created_at: string;
  updated_at: string;
  original_url: string;
  thumbnail_url: string;
};
export type FaceCaseDetail = FaceCase & {
  snapshot: {
    schema_version: number;
    ground_truth?: {
      answer_type: CaseAnswerType;
      correct_person: { id: number; name: string } | null;
      excluded_person: { id: number; name: string } | null;
    };
    captured_at: string;
    photo: { id: number; filename: string; sha256: string; content_type: string | null; display_width: number; display_height: number; exif_orientation: number };
    recognition: Partial<Face> & { created_at: string; detection_score: number | null };
    binding_at_capture: { person_id: number | null; person_name: string | null; source: string | null; needs_review: boolean };
    reference_samples_at_capture: {
      role?: "correct_person" | "excluded_person" | "recognized_person" | null;
      person_name?: string | null;
      captured_at: string;
      ready_count: number;
      samples: { id: number; filename: string; sha256: string; status: string; quality_status: string | null; source_type: string; source_gallery_photo_id: number | null }[];
    };
    same_photo_sample_ids_at_capture: number[];
    configuration_at_capture: Record<string, unknown>;
    bind_person_requested: boolean;
  };
};
export type CaseFilters = { correct_person_name: string; issue_type: CaseIssueType | ""; embedding_version: string; answer_type?: CaseAnswerType | "" };
export type FaceCaseCreate = {
  photo_id: number;
  face_id: number;
  face_revision: string;
  answer_type: CaseAnswerType;
  correct_person_id: number | null;
  excluded_person_id: number | null;
  issue_type: CaseIssueType;
  notes: string;
  bind_person: boolean;
};
export type PaginatedFaceCases = { items: FaceCase[]; total: number; offset: number; limit: number };
