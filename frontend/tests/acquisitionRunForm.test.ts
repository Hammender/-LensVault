import { describe, expect, it } from "vitest";

import {
  defaultAcquisitionRunParameters,
  getAcquisitionRunFormConfiguration,
  restoreAcquisitionRunParameters,
  serializeAcquisitionRunParameters
} from "../src/acquisitionRunForm";
import type { AcquisitionCategory, AcquisitionRun, AcquisitionScript, AcquisitionSource } from "../src/types";

const script: AcquisitionScript = {
  key: "raindrop",
  name: "Raindrop",
  version: "1",
  page_format_key: "raindrop-v1",
  description: "",
  parameters: [
    { key: "max_pages", label: "最大扫描页数", type: "integer", required: false, default: null, description: null, minimum: 1, maximum: null, options: [] },
    { key: "include_video", label: "包含视频", type: "boolean", required: false, default: true, description: null, minimum: null, maximum: null, options: [] },
    { key: "order", label: "排序", type: "select", required: false, default: "newest", description: null, minimum: null, maximum: null, options: [{ value: "newest", label: "最新" }] }
  ]
};

const pageScript: AcquisitionScript = {
  key: "shfwzwz-raindrop-page",
  name: "shfwzwz-raindrop-page",
  version: "1.2.0",
  page_format_key: "raindrop-public-page-v1",
  description: "",
  parameters: [
    { key: "start_page", label: "起始页", type: "integer", required: false, default: 1, description: null, minimum: 1, maximum: 1001, options: [] },
    { key: "end_page", label: "结束页", type: "integer", required: false, default: null, description: null, minimum: 1, maximum: 1001, options: [] }
  ]
};

const source: AcquisitionSource = {
  id: 1,
  name: "站点",
  base_url: "https://example.test",
  notes: null,
  page_format_key: "raindrop-v1",
  script_keys: [script.key],
  enabled: true,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00"
};

const category: AcquisitionCategory = {
  id: 2,
  source_id: source.id,
  name: "分类",
  crawl_url: "https://example.test/category",
  notes: null,
  enabled: true,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00"
};

const run: AcquisitionRun = {
  id: "run-1",
  source_id: source.id,
  category_id: category.id,
  script_key: script.key,
  script_name: script.name,
  script_version: script.version,
  source_name: source.name,
  category_name: category.name,
  category_url: category.crawl_url,
  parameters: { max_pages: 10, include_video: false },
  mode: "incremental",
  status: "interrupted",
  total_count: 44,
  downloaded_count: 44,
  skipped_count: 0,
  download_success_count: 44,
  candidate_count: 44,
  content_duplicate_count: 0,
  gallery_duplicate_count: 0,
  resolution_duplicate_count: 0,
  resolution_upgrade_count: 0,
  ignored_count: 0,
  invalid_count: 0,
  error_count: 0,
  imported_count: 0,
  error_message: null,
  scan_start_page: 1,
  scan_end_page: 10,
  reached_collection_end: false,
  stop_reason: "requested_end",
  started_at: null,
  completed_at: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00"
};

describe("acquisition run form configuration", () => {
  it("keeps an omitted page limit blank and restores typed snapshot values", () => {
    expect(defaultAcquisitionRunParameters(script)).toEqual({ max_pages: "", include_video: true, order: "newest" });
    expect(restoreAcquisitionRunParameters(script, { include_video: false, order: "oldest" })).toEqual({
      max_pages: "",
      include_video: false,
      order: "oldest"
    });
  });

  it("loads the original category, script, mode and parameters when they are still available", () => {
    expect(getAcquisitionRunFormConfiguration(run, [category], [source], [script])).toEqual({
      categoryId: "2",
      scriptKey: "raindrop",
      mode: "incremental",
      parameters: { max_pages: "10", include_video: false, order: "newest" }
    });
  });

  it("rejects a historical configuration after its script binding is removed", () => {
    expect(getAcquisitionRunFormConfiguration(run, [category], [{ ...source, script_keys: [] }], [script])).toBeNull();
  });

  it("maps the historical max page snapshot to the new inclusive page fields", () => {
    expect(restoreAcquisitionRunParameters(pageScript, { max_pages: 5 })).toEqual({
      start_page: "1",
      end_page: "5"
    });
  });

  it("maps a historical forced scan to full mode and removes the retired parameter", () => {
    const historicalRun = {
      ...run,
      script_key: pageScript.key,
      script_name: pageScript.name,
      script_version: "1.1.0",
      parameters: { start_page: 1, end_page: 8, force_full_scan: true }
    };
    const historicalSource = {
      ...source,
      page_format_key: pageScript.page_format_key,
      script_keys: [pageScript.key]
    };
    expect(getAcquisitionRunFormConfiguration(historicalRun, [category], [historicalSource], [pageScript])).toEqual({
      categoryId: "2",
      scriptKey: pageScript.key,
      mode: "full",
      parameters: { start_page: "1", end_page: "8" }
    });
  });

  it("serializes datetime parameters as Shanghai offsets and restores local values", () => {
    const telegramScript: AcquisitionScript = {
      key: "telegram-channel-mtproto",
      name: "Telegram 频道",
      version: "1.1.0",
      page_format_key: "telegram-channel-v1",
      description: "",
      parameters: [
        { key: "date_from", label: "起始时间（上海时间）", type: "datetime", required: false, default: null, description: null, minimum: null, maximum: null, options: [] },
        { key: "date_to", label: "结束时间（上海时间）", type: "datetime", required: false, default: null, description: null, minimum: null, maximum: null, options: [] },
        { key: "scan_order", label: "扫描顺序", type: "select", required: false, default: "newest", description: null, minimum: null, maximum: null, options: [{ value: "newest", label: "从新到旧" }, { value: "oldest", label: "从旧到新" }] },
        { key: "max_messages", label: "最大扫描消息数", type: "integer", required: false, default: 1000, description: null, minimum: 1, maximum: 10000, options: [] }
      ]
    };
    expect(serializeAcquisitionRunParameters(telegramScript, {
      date_from: "2026-09-02T00:00",
      date_to: "2026-09-02T15:30",
      scan_order: "oldest",
      max_messages: "10"
    })).toEqual({
      date_from: "2026-09-02T00:00:00+08:00",
      date_to: "2026-09-02T15:30:00+08:00",
      scan_order: "oldest",
      max_messages: 10
    });
    expect(restoreAcquisitionRunParameters(telegramScript, {
      date_from: "2026-09-01T16:00:00Z",
      scan_order: "oldest",
      max_messages: 10
    })).toEqual({
      date_from: "2026-09-02T00:00",
      date_to: "",
      scan_order: "oldest",
      max_messages: "10"
    });
  });
});
