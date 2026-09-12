export type GalleryFaceStatusKind = "review" | "ignored" | "override" | "confirmed";

type FaceStatusFields = {
  needs_review: boolean;
  matched_person_id: number | null;
  matched_person_is_unknown?: boolean;
  predicted_person_id?: number | null;
};

export function galleryFaceStatusKind(face: FaceStatusFields): GalleryFaceStatusKind {
  if (face.matched_person_id === null) {
    return "ignored";
  }
  if (face.needs_review || face.matched_person_is_unknown) {
    return "review";
  }
  if (face.predicted_person_id != null && face.predicted_person_id !== face.matched_person_id) {
    return "override";
  }
  return "confirmed";
}

export function galleryFaceStatusLabel(face: FaceStatusFields): string {
  switch (galleryFaceStatusKind(face)) {
    case "ignored":
      return "已忽略";
    case "review":
      return "待人工确认";
    case "override":
      return "人工指定";
    default:
      return "已确认";
  }
}

export function personTagSourceLabel(source: string): string {
  switch (source) {
    case "auto":
      return "自动";
    case "face_manual":
      return "人工确认";
    case "manual":
      return "图片标签";
    case "import":
    case "import_unknown":
      return "导入";
    case "debug":
      return "待审";
    case "unknown":
      return "未知";
    default:
      return "";
  }
}

export function faceBindingSourceLabel(source: "auto" | "manual" | "unknown"): string {
  if (source === "manual") {
    return "人工确认";
  }
  if (source === "unknown") {
    return "未知人物";
  }
  return "自动识别";
}
