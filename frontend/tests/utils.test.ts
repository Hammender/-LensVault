import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatDate,
  formatDurationSeconds,
  formatPhotoDate,
  getFileExtension,
  isSupportedVideoFile,
  splitCommaList,
  toShanghaiDateTimeBoundary,
  toShanghaiDateTimeLocalValue,
  toShanghaiDateTimeOffset,
  toWorkspacePermissions
} from "../src/utils";

describe("frontend utilities", () => {
  it("formats byte and duration values", () => {
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatDurationSeconds(65)).toBe("1:05");
    expect(formatDurationSeconds(3661)).toBe("1:01:01");
  });

  it("normalizes file extensions and supported video formats", () => {
    expect(getFileExtension("DEMO.MP4")).toBe(".mp4");
    expect(isSupportedVideoFile("demo.mkv")).toBe(true);
    expect(isSupportedVideoFile("demo.avi")).toBe(false);
  });

  it("deduplicates comma separated values", () => {
    expect(splitCommaList("甲, 乙，甲")).toEqual(["甲", "乙"]);
  });

  it("fills all workspace permission flags", () => {
    const permissions = toWorkspacePermissions({ can_add_gallery: true });
    expect(permissions.can_add_gallery).toBe(true);
    expect(permissions.can_edit_videos).toBe(false);
  });

  it("always formats system timestamps in Shanghai time", () => {
    expect(formatDate("2026-07-29T15:30:00+08:00")).toContain("15:30");
    expect(formatDate("2026-07-29T07:30:00Z")).toContain("15:30");
    expect(formatDate("2026-07-29 15:30:00")).toContain("15:30");
  });

  it("keeps EXIF wall-clock time and sends explicit Shanghai date boundaries", () => {
    expect(formatPhotoDate("2020-01-02 09:15:00", "2026-07-29T15:30:00+08:00")).toContain("09:15");
    expect(toShanghaiDateTimeBoundary("2026-07-29", "start")).toBe("2026-07-29T00:00:00+08:00");
    expect(toShanghaiDateTimeBoundary("2026-07-29", "end")).toBe("2026-07-29T23:59:59.999999+08:00");
  });

  it("round-trips datetime-local values through Shanghai offsets", () => {
    expect(toShanghaiDateTimeOffset("2026-09-02T00:00")).toBe("2026-09-02T00:00:00+08:00");
    expect(toShanghaiDateTimeOffset("2026-09-02T00:00:00+08:00")).toBe("2026-09-02T00:00:00+08:00");
    expect(toShanghaiDateTimeLocalValue("2026-09-02T00:00:00+08:00")).toBe("2026-09-02T00:00");
    expect(toShanghaiDateTimeLocalValue("2026-09-01T16:00:00Z")).toBe("2026-09-02T00:00");
  });
});
