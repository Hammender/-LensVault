import { describe, expect, it } from "vitest";

import { getAcquisitionAssetPageOffset } from "./acquisitionReview";

describe("审核灯箱定位列表页", () => {
  const ids = Array.from({ length: 125 }, (_, index) => `asset-${index}`);

  it("跨过第 60 项时进入第二页，往前翻则回到第一页", () => {
    expect(getAcquisitionAssetPageOffset(ids, "asset-59")).toBe(0);
    expect(getAcquisitionAssetPageOffset(ids, "asset-60")).toBe(60);
    expect(getAcquisitionAssetPageOffset(ids, "asset-59")).toBe(0);
    expect(getAcquisitionAssetPageOffset(ids, "asset-120")).toBe(120);
  });

  it("列表中不能预览的素材也占分页位置，不按灯箱序号定位", () => {
    const allIds = ["missing-file", ...ids];
    expect(getAcquisitionAssetPageOffset(allIds, "asset-59")).toBe(60);
  });

  it("丢弃前面的素材后按最新顺序找到当前页", () => {
    const remainingIds = ids.filter((id) => id !== "asset-0");
    expect(getAcquisitionAssetPageOffset(remainingIds, "asset-60")).toBe(0);
    expect(getAcquisitionAssetPageOffset(remainingIds, "asset-61")).toBe(60);
  });

  it("新增截图插到最前面后仍定位到当前素材所在页", () => {
    const withCapture = ["new-capture", ...ids];
    expect(getAcquisitionAssetPageOffset(withCapture, "asset-59")).toBe(60);
  });

  it("素材已离开当前筛选列表时不跳到无关页面", () => {
    expect(getAcquisitionAssetPageOffset(ids, "absent")).toBeNull();
    expect(getAcquisitionAssetPageOffset([], "asset-0")).toBeNull();
  });
});
