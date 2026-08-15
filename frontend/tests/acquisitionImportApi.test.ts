import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn()
}));

vi.mock("../src/apiClient", () => ({
  authFetch: mocks.authFetch,
  jsonHeaders: { "Content-Type": "application/json" },
  parseResponse: async (response: { json: () => Promise<unknown> }) => response.json(),
  withWorkspaceContext: (path: string) => path
}));

import { changeAcquisitionAssets } from "../src/api/acquisition";

describe("changeAcquisitionAssets", () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.authFetch.mockResolvedValue({ json: async () => ({ id: "batch" }) });
  });

  it("提交图文图片导入类型", async () => {
    await changeAcquisitionAssets("import", ["asset-1"], true);

    expect(mocks.authFetch).toHaveBeenCalledWith("/api/acquisition/assets/import", expect.objectContaining({
      body: JSON.stringify({ asset_ids: ["asset-1"], is_rich_text: true })
    }));
  });

  it("默认提交普通图片导入类型", async () => {
    await changeAcquisitionAssets("import", ["asset-1"]);

    expect(mocks.authFetch).toHaveBeenCalledWith("/api/acquisition/assets/import", expect.objectContaining({
      body: JSON.stringify({ asset_ids: ["asset-1"], is_rich_text: false })
    }));
  });

  it("丢弃图片时不发送导入类型", async () => {
    await changeAcquisitionAssets("reject", ["asset-1"], true);

    expect(mocks.authFetch).toHaveBeenCalledWith("/api/acquisition/assets/reject", expect.objectContaining({
      body: JSON.stringify({ asset_ids: ["asset-1"] })
    }));
  });
});
