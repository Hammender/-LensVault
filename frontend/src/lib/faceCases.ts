import type { CaseAnswerType, CaseIssueType, FaceCase, FaceCaseCreate } from "../types/faceCases";
import type { Face } from "../types/gallery";

export const caseIssueLabels: Record<CaseIssueType, string> = { unknown: "被判为未知", wrong_person: "认成其他人物", other: "其他异常" };
export const caseAnswerLabels: Record<CaseAnswerType, string> = {
  known_person: "是库中某个人物", out_of_library: "确定是库外人物", not_person: "只确定不是某人",
};
export function caseAnswerSummary(item: Pick<FaceCase, "answer_type" | "correct_person_name" | "excluded_person_name">): string {
  if (item.answer_type === "out_of_library") return "非样本库人物";
  if (item.answer_type === "not_person") return `不是${item.excluded_person_name ?? "指定人物"}`;
  return item.correct_person_name;
}
export function caseCreatePayload(photoId: number, face: Face, draft: {
  answerType: CaseAnswerType; personId: string; excludedPersonId: string; issue: CaseIssueType; notes: string; bind: boolean;
}): FaceCaseCreate {
  return { photo_id: photoId, face_id: face.id, face_revision: face.face_revision, answer_type: draft.answerType,
    correct_person_id: draft.answerType === "known_person" && draft.personId ? Number(draft.personId) : null,
    excluded_person_id: draft.answerType === "not_person" && draft.excludedPersonId ? Number(draft.excludedPersonId) : null,
    issue_type: draft.answerType !== "known_person" && draft.issue === "unknown" ? "wrong_person" : draft.issue,
    notes: draft.notes, bind_person: draft.answerType === "known_person" && draft.bind };
}
export function casePath(id?: string): string {
  return `/face-recognition-cases${id ? `?case=${encodeURIComponent(id)}` : ""}`;
}
export function faceBoxStyle(face: { bbox_left?: number; bbox_top?: number; bbox_right?: number; bbox_bottom?: number }, width: number, height: number) {
  if (width <= 0 || height <= 0 || [face.bbox_left, face.bbox_top, face.bbox_right, face.bbox_bottom].some((v) => v == null || !Number.isFinite(v))) return null;
  const left = Math.max(0, Math.min(width, face.bbox_left!));
  const top = Math.max(0, Math.min(height, face.bbox_top!));
  const right = Math.max(left, Math.min(width, face.bbox_right!));
  const bottom = Math.max(top, Math.min(height, face.bbox_bottom!));
  return { left: `${left / width * 100}%`, top: `${top / height * 100}%`, width: `${(right - left) / width * 100}%`, height: `${(bottom - top) / height * 100}%` };
}
