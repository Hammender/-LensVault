import { describe, expect, it } from "vitest";

import { galleryFaceStatusLabel, personTagSourceLabel } from "../src/lib/galleryFaceStatus";

describe("galleryFaceStatusLabel", () => {
  it("labels faces waiting for review", () => {
    expect(galleryFaceStatusLabel({ needs_review: true, matched_person_id: 1, matched_person_is_unknown: true })).toBe("待人工确认");
  });

  it("labels confirmed faces that match the top candidate", () => {
    expect(galleryFaceStatusLabel({
      needs_review: false,
      matched_person_id: 1,
      matched_person_is_unknown: false,
      predicted_person_id: 1
    })).toBe("已确认");
  });

  it("labels unassigned reviewed faces as ignored", () => {
    expect(galleryFaceStatusLabel({ needs_review: false, matched_person_id: null })).toBe("已忽略");
  });

  it("does not call a mismatched candidate 已确认", () => {
    expect(galleryFaceStatusLabel({
      needs_review: false,
      matched_person_id: 16,
      matched_person_is_unknown: false,
      predicted_person_id: 58
    })).toBe("人工指定");
  });
});

describe("personTagSourceLabel", () => {
  it("labels photo-level and face-derived sources", () => {
    expect(personTagSourceLabel("manual")).toBe("图片标签");
    expect(personTagSourceLabel("debug")).toBe("待审");
    expect(personTagSourceLabel("face_manual")).toBe("人工确认");
    expect(personTagSourceLabel("auto")).toBe("自动");
  });
});
