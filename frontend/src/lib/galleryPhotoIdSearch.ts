export const GALLERY_PHOTO_ID_MAX = 2_147_483_647;

export type GalleryPhotoIdQuery =
  | { kind: "empty" }
  | { kind: "valid"; photoId: number }
  | { kind: "invalid"; message: string };

export function parseGalleryPhotoIdQuery(raw: string): GalleryPhotoIdQuery {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { kind: "empty" };
  }
  const digits = trimmed.startsWith("#") ? trimmed.slice(1).trim() : trimmed;
  if (!/^\d+$/.test(digits)) {
    return { kind: "invalid", message: "请输入数字编号，例如 123 或 #123" };
  }
  const photoId = Number(digits);
  if (photoId < 1 || photoId > GALLERY_PHOTO_ID_MAX) {
    return { kind: "invalid", message: "图片编号需为大于 0 的整数" };
  }
  return { kind: "valid", photoId };
}
