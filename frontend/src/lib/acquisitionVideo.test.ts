import { describe, expect, it } from "vitest";
import { formatVideoTime, parseVideoTime } from "./acquisitionVideo";

describe("视频精确定位时间", () => {
  it("支持秒数、分秒和跨小时定位", () => {
    expect(parseVideoTime("1.234")).toBe(1.234);
    expect(parseVideoTime("01:23.456")).toBe(83.456);
    expect(parseVideoTime("01:02:03.456")).toBe(3723.456);
    expect(formatVideoTime(3723.456, true)).toBe("01:02:03.456");
  });
  it("拒绝无效或非有限时间", () => {
    for (const value of ["", "-1", "Infinity", "1:60", "1:2:70", "1.2345", "1:2:3:4"]) {
      expect(parseVideoTime(value)).toBeNull();
    }
    expect(formatVideoTime(Number.NaN, true)).toBe("00:00.000");
    expect(formatVideoTime(59.999, true)).toBe("00:59.999");
  });
});
