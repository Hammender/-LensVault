import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatDurationSeconds,
  getFileExtension,
  isSupportedVideoFile,
  splitCommaList,
  toWorkspacePermissions
} from "./utils";

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
});
