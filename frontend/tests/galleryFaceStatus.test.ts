import { describe, expect, it } from "vitest";

import { galleryFaceStatusLabel } from "../src/galleryFaceStatus";

describe("galleryFaceStatusLabel", () => {
  it("labels faces waiting for review", () => {
    expect(galleryFaceStatusLabel(true, 1)).toBe("待人工确认");
  });

  it("labels confirmed faces", () => {
    expect(galleryFaceStatusLabel(false, 1)).toBe("已确认");
  });

  it("labels unassigned reviewed faces as ignored", () => {
    expect(galleryFaceStatusLabel(false, null)).toBe("已忽略");
  });
});
