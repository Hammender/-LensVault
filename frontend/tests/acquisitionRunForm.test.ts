import { describe, expect, it } from "vitest";

import {
  defaultAcquisitionRunParameters,
  getAcquisitionRunFormConfiguration,
  restoreAcquisitionRunParameters
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
  ignored_count: 0,
  invalid_count: 0,
  error_count: 0,
  imported_count: 0,
  error_message: null,
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
});
