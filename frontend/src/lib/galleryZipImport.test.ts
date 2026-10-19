import { describe, expect, it } from "vitest";

import {
  DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS,
  galleryZipPersonTagControlsEnabled,
  galleryZipUnknownSourceEnabled,
  toGalleryZipImportFormFields
} from "./galleryZipImport";

describe("galleryZipImport", () => {
  it("keeps current defaults", () => {
    expect(DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS).toEqual({
      personTags: "all",
      unknownTagSource: "import_unknown",
      recognize: false
    });
  });

  it("disables person and unknown controls when recognizing", () => {
    const recognizing = { ...DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS, recognize: true };
    expect(galleryZipPersonTagControlsEnabled(recognizing)).toBe(false);
    expect(galleryZipUnknownSourceEnabled(recognizing)).toBe(false);
  });

  it("enables unknown source only when importing all person tags", () => {
    expect(galleryZipUnknownSourceEnabled(DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS)).toBe(true);
    expect(galleryZipUnknownSourceEnabled({ ...DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS, personTags: "known_only" })).toBe(false);
    expect(galleryZipUnknownSourceEnabled({ ...DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS, personTags: "none" })).toBe(false);
  });

  it("serializes form fields for the import API", () => {
    expect(toGalleryZipImportFormFields({
      personTags: "none",
      unknownTagSource: "unknown",
      recognize: true
    })).toEqual({
      person_tags: "none",
      unknown_tag_source: "unknown",
      recognize: "true"
    });
  });
});
