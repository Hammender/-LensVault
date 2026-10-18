import { afterEach, expect, it, vi } from "vitest";
import { exportFaceCases } from "../src/api/faceCases";

afterEach(() => vi.unstubAllGlobals());

it("导出勾选跨页案例时，不叠加当前列表筛选导致遗漏", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(["zip"]), {
    status: 200, headers: { "Content-Disposition": 'attachment; filename="cases.zip"' },
  }));
  vi.stubGlobal("window", { fetch: fetchMock, localStorage: { getItem: () => null } });
  const result = await exportFaceCases({ correct_person_name: "甲", issue_type: "unknown", embedding_version: "v1", answer_type: "not_person" }, ["case-a", "case-b"]);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ case_ids: ["case-a", "case-b"] });
  expect(result.filename).toBe("cases.zip");
});

it("按筛选导出保留人工结论条件", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(["zip"]), { status: 200 }));
  vi.stubGlobal("window", { fetch: fetchMock, localStorage: { getItem: () => null } });
  await exportFaceCases({ correct_person_name: "甲", issue_type: "", embedding_version: "", answer_type: "not_person" });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ correct_person_name: "甲", answer_type: "not_person" });
});
