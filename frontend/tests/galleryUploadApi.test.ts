import { afterEach, describe, expect, it, vi } from "vitest";

import { importGalleryPhotos } from "../src/api";

describe("展示图上传请求", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("发送多人物 ID 而不是人物名称", async () => {
    const captured: { body: FormData | null } = { body: null };
    const fetchMock = vi.fn().mockImplementation(async (_input: RequestInfo | URL, init?: RequestInit) => {
      captured.body = init?.body as FormData;
      return { ok: true, json: async () => ({ id: "task-1" }) };
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", { fetch: fetchMock, localStorage: { getItem: () => null } });

    await importGalleryPhotos(
      [new File(["image"], "photo.jpg", { type: "image/jpeg" })],
      [{ person_ids: [3, 5], tag_names: ["活动"] }]
    );

    const metadata = JSON.parse(String(captured.body?.get("metadata_json")));
    expect(metadata).toEqual([{ person_ids: [3, 5], tag_names: ["活动"] }]);
    expect(metadata[0]).not.toHaveProperty("person_names");
  });
});
