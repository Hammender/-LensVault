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

import {
  listAcquisitionCategoryPage,
  listAcquisitionRunPage,
  listAcquisitionSourcePage
} from "../src/api/acquisition";

describe("采集管理分页接口", () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.authFetch.mockResolvedValue({ json: async () => ({ items: [], total: 0, offset: 0, limit: 20 }) });
  });

  it("请求站点、分类和运行记录的指定页", async () => {
    await Promise.all([
      listAcquisitionSourcePage(20, 10),
      listAcquisitionCategoryPage(30, 15),
      listAcquisitionRunPage(40, 20)
    ]);

    expect(mocks.authFetch).toHaveBeenCalledWith("/api/acquisition/sources/page?offset=20&limit=10");
    expect(mocks.authFetch).toHaveBeenCalledWith("/api/acquisition/categories/page?offset=30&limit=15");
    expect(mocks.authFetch).toHaveBeenCalledWith("/api/acquisition/runs/page?offset=40&limit=20");
  });
});
