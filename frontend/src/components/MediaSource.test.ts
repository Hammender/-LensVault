import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import MediaSource from "./MediaSource";

vi.mock("../lib/apiClient", () => ({
  getAuthToken: () => "test-token",
  getSelectedWorkspaceId: () => 1,
  authFetch: vi.fn(),
  parseResponse: vi.fn()
}));

describe("MediaSource", () => {
  it("显示站点和分类摘要，详细来源默认收起", () => {
    const html = renderToStaticMarkup(createElement(MediaSource, {
      mediaType: "photo", mediaId: 1,
      summary: { source_type: "acquisition", text: "站点 · 甲/乙", has_details: true }
    }));
    expect(html).toContain("站点 · 甲/乙");
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("media-source-detail");
  });

  it.each(["手动上传", "导入"])("显示%s的操作人", (label) => {
    const html = renderToStaticMarkup(createElement(MediaSource, {
      mediaType: "video", mediaId: 2,
      summary: {
        source_type: label === "导入" ? "import" : "manual_upload",
        text: `${label} · 操作人`, actor_name: "操作人", has_details: true
      }
    }));
    expect(html).toContain(`${label} · 操作人`);
  });

  it("缺少来源摘要时显示历史来源未知", () => {
    const html = renderToStaticMarkup(createElement(MediaSource, { mediaType: "photo", mediaId: 3 }));
    expect(html).toContain("历史来源未知");
  });
});
