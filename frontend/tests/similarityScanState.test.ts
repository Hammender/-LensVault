import { describe, expect, it } from "vitest";

import { chooseRecoveredScan, findScanForScope, scanScopeKey } from "../src/similarityScanState";
import type { GallerySimilarityScan } from "../src/types";

function scan(
  id: string,
  personId: number | null,
  includeCrossType: boolean,
  scanType: "normal" | "mirror" = "normal"
): GallerySimilarityScan {
  return {
    id,
    task_id: null,
    person_id: personId,
    include_cross_type: includeCrossType,
    scan_type: scanType,
    auto_delete_exact_mirror: false,
    auto_deleted_count: 0,
    status: "completed",
    is_stale: false,
    feature_version: "dinov2-v1",
    photo_count: 20,
    candidate_pair_count: 10,
    group_count: 3,
    error_message: null,
    created_at: "2026-07-14T10:00:00",
    completed_at: "2026-07-14T10:01:00",
    task: null
  };
}

describe("相似扫描结果恢复", () => {
  const scans = [scan("latest", null, true), scan("person", 7, false)];

  it("默认恢复列表中的最近成功结果", () => {
    expect(chooseRecoveredScan(scans)?.id).toBe("latest");
  });

  it("刷新或新扫描失败后仍优先保留原来查看的成功结果", () => {
    expect(chooseRecoveredScan(scans, "person")?.id).toBe("person");
  });

  it("指定结果已不存在时回退到最近成功结果", () => {
    expect(chooseRecoveredScan(scans, "missing")?.id).toBe("latest");
  });

  it("按人物和跨类型选项精确匹配扫描范围", () => {
    expect(findScanForScope(scans, 7, false)?.id).toBe("person");
    expect(findScanForScope(scans, 7, true)).toBeNull();
    expect(scanScopeKey(null, true)).not.toBe(scanScopeKey(null, false));
  });

  it("普通与镜像扫描结果彼此隔离", () => {
    const scoped = [scan("normal", 7, false), scan("mirror", 7, false, "mirror")];
    expect(findScanForScope(scoped, 7, false, "normal")?.id).toBe("normal");
    expect(findScanForScope(scoped, 7, false, "mirror")?.id).toBe("mirror");
  });

  it("没有成功结果时返回空", () => {
    expect(chooseRecoveredScan([])).toBeNull();
  });
});
