export const GALLERY_ZIP_PERSON_TAG_MODES = ["all", "known_only", "none"] as const;
export type GalleryZipPersonTagMode = (typeof GALLERY_ZIP_PERSON_TAG_MODES)[number];

export const GALLERY_ZIP_UNKNOWN_TAG_SOURCES = ["import_unknown", "unknown"] as const;
export type GalleryZipUnknownTagSource = (typeof GALLERY_ZIP_UNKNOWN_TAG_SOURCES)[number];

export type GalleryZipImportOptions = {
  personTags: GalleryZipPersonTagMode;
  unknownTagSource: GalleryZipUnknownTagSource;
  recognize: boolean;
};

export const DEFAULT_GALLERY_ZIP_IMPORT_OPTIONS: GalleryZipImportOptions = {
  personTags: "all",
  unknownTagSource: "import_unknown",
  recognize: false
};

export function galleryZipPersonTagControlsEnabled(options: Pick<GalleryZipImportOptions, "recognize">): boolean {
  return !options.recognize;
}

export function galleryZipUnknownSourceEnabled(options: GalleryZipImportOptions): boolean {
  return !options.recognize && options.personTags === "all";
}

export function toGalleryZipImportFormFields(options: GalleryZipImportOptions): Record<string, string> {
  return {
    person_tags: options.personTags,
    unknown_tag_source: options.unknownTagSource,
    recognize: options.recognize ? "true" : "false"
  };
}
