import { describe, expect, it } from "vitest";

import { findPreviewAfterCurrentDelete, getSimilarityLightboxShortcut } from "../src/similarityReviewKeyboard";

describe("similarity review lightbox keyboard", () => {
  it("maps Space and Delete to current-image actions", () => {
    expect(getSimilarityLightboxShortcut(" ")).toBe("toggle_selection");
    expect(getSimilarityLightboxShortcut("Spacebar")).toBe("toggle_selection");
    expect(getSimilarityLightboxShortcut("Delete")).toBe("delete_current");
    expect(getSimilarityLightboxShortcut("ArrowUp")).toBe("previous_group");
    expect(getSimilarityLightboxShortcut("ArrowDown")).toBe("next_group");
    expect(getSimilarityLightboxShortcut("P")).toBe("dismiss_group");
    expect(getSimilarityLightboxShortcut("p")).toBe("dismiss_group");
    expect(getSimilarityLightboxShortcut("Enter")).toBeNull();
  });

  it("moves to the next photo after deletion and falls back to the previous one", () => {
    expect(findPreviewAfterCurrentDelete([11, 12, 13], 12)).toBe(13);
    expect(findPreviewAfterCurrentDelete([11, 12, 13], 13)).toBe(12);
    expect(findPreviewAfterCurrentDelete([11], 11)).toBeNull();
    expect(findPreviewAfterCurrentDelete([11, 12], 99)).toBeNull();
  });
});
