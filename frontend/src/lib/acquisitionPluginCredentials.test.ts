import { describe, expect, it } from "vitest";
import { canUsePluginCredential, requiresPluginCredential } from "./acquisitionRunForm";

const optional = [{ key: "header", label: "请求头", required: false }];
const required = [{ key: "cookie", label: "Cookie", required: true }];

describe("采集插件账号选择", () => {
  it("没有凭据或只有可选字段时允许不选择账号", () => {
    expect(requiresPluginCredential(undefined)).toBe(false);
    expect(canUsePluginCredential(optional, "", [])).toBe(true);
    expect(canUsePluginCredential(required, "", [])).toBe(false);
  });

  it("主动选择的可选账号仍需通过验证", () => {
    expect(canUsePluginCredential(optional, "1", [{ id: 1, status: "untested" }])).toBe(false);
    expect(canUsePluginCredential(optional, "1", [{ id: 1, status: "valid" }])).toBe(true);
    expect(canUsePluginCredential(required, "2", [{ id: 1, status: "valid" }])).toBe(false);
  });
});
