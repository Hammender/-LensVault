import { afterEach, describe, expect, it, vi } from "vitest";

import {
  listAcquisitionAssetIds,
  listAcquisitionAssets,
  listAcquisitionImportBatches,
  listAcquisitionImportBatchItems,
  listAcquisitionSimilarity,
  startAcquisitionSimilarityScan
} from "../src/api/acquisition";
import { getConfirmDialogKeyboardDecision } from "../src/components/ConfirmDialog";
import {
  acquisitionAssetPageSize,
  clampAcquisitionOffset,
  createAcquisitionStatusReset,
  findClosestPreviewableIndex,
  getAcquisitionPageFill,
  getAcquisitionRejectContinuation,
  getAcquisitionPreviewUrl,
  getAcquisitionLightboxShortcut,
  getAcquisitionPagination,
  getNextAcquisitionSnapshotIndex,
  hasSelectedAllAcquisitionAssets,
  isAcquisitionPageFillValid,
  isAcquisitionImportBatchActive,
  removeAcquisitionSelection,
  toggleAcquisitionSelection
} from "../src/lib/acquisitionReview";

function installWindow() {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
    items: [],
    total: 377,
    offset: 120,
    limit: 60
  }), { status: 200 }));
  Object.assign(globalThis, {
    window: {
      location: { origin: "http://localhost:5173" },
      localStorage: {
        getItem: () => null,
        setItem: () => undefined,
        removeItem: () => undefined
      },
      fetch
    }
  });
  return fetch;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

describe("acquisition review pagination", () => {
  it("sends status, offset and the fixed page size", async () => {
    const fetch = installWindow();

    const page = await listAcquisitionAssets("pending_review", 120, acquisitionAssetPageSize);

    expect(page.total).toBe(377);
    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/assets?status=pending_review&offset=120&limit=60");
  });

  it("can request a single media type", async () => {
    const fetch = installWindow();

    await listAcquisitionAssets("pending_review", 0, 60, "video");

    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/assets?status=pending_review&offset=0&limit=60&media_type=video");
  });

  it("requests fill rows with the active media filter", async () => {
    const fetch = installWindow();

    await listAcquisitionAssets("pending_review", 59, 1, "image");

    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/assets?status=pending_review&offset=59&limit=1&media_type=image");
  });

  it("can request only the metadata row needed to refill a page", async () => {
    const fetch = installWindow();

    await listAcquisitionAssets("pending_review", 59, 1);

    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/assets?status=pending_review&offset=59&limit=1");
  });

  it("requests every ID for the current review status without loading every image page", async () => {
    const fetch = installWindow();

    await listAcquisitionAssetIds("pending_review");

    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/assets/ids?status=pending_review");
  });

  it("requests only previewable assets when opening a stable large-preview session", async () => {
    const fetch = installWindow();

    await listAcquisitionAssetIds("pending_review", true, "video");

    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/assets/ids?status=pending_review&previewable=true&media_type=video");
  });

  it("calculates seven pages and the final range for 377 assets", () => {
    expect(getAcquisitionPagination(377, 0, 60)).toEqual({
      currentPage: 1,
      totalPages: 7,
      rangeStart: 1,
      rangeEnd: 60
    });
    expect(getAcquisitionPagination(377, 360, 17)).toEqual({
      currentPage: 7,
      totalPages: 7,
      rangeStart: 361,
      rangeEnd: 377
    });
  });

  it("moves an out-of-range page back to the last valid page", () => {
    expect(clampAcquisitionOffset(377, 420)).toBe(360);
    expect(clampAcquisitionOffset(360, 360)).toBe(300);
    expect(clampAcquisitionOffset(1, 60)).toBe(0);
    expect(clampAcquisitionOffset(0, 60)).toBe(0);
  });
});

describe("acquisition similarity scan", () => {
  it("starts a persisted task and requests paginated groups", async () => {
    const fetch = installWindow();
    fetch
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "scan-task",
        kind: "acquisition_similarity_scan",
        status: "pending",
        progress: 0,
        message: "相似扫描已进入队列",
        result: null,
        workspace_id: null,
        created_at: "2026-07-27T10:00:00",
        updated_at: "2026-07-27T10:00:00"
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        task: null,
        generated_at: null,
        is_stale: false,
        groups: [],
        total: 0,
        offset: 12,
        limit: 12
      }), { status: 200 }));

    const task = await startAcquisitionSimilarityScan();
    const result = await listAcquisitionSimilarity(12, 12);

    expect(task.kind).toBe("acquisition_similarity_scan");
    expect(result.groups).toEqual([]);
    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/similarity/scan");
    expect(fetch.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST" }));
    expect(fetch.mock.calls[1][0]).toBe("/api/acquisition/similarity?offset=12&limit=12");
  });
});

describe("acquisition review selection and rejection", () => {
  it("treats the all-selection command as a toggle", () => {
    expect(hasSelectedAllAcquisitionAssets([], 0)).toBe(false);
    expect(hasSelectedAllAcquisitionAssets(["one"], 2)).toBe(false);
    expect(hasSelectedAllAcquisitionAssets(["one", "two"], 2)).toBe(true);
  });

  it("keeps selections from other pages and removes only processed assets", () => {
    const firstPageSelection = toggleAcquisitionSelection([], "page-1-asset");
    const crossPageSelection = toggleAcquisitionSelection(firstPageSelection, "page-2-asset");

    expect(crossPageSelection).toEqual(["page-1-asset", "page-2-asset"]);
    expect(removeAcquisitionSelection(crossPageSelection, ["page-2-asset"])).toEqual(["page-1-asset"]);
    expect(createAcquisitionStatusReset("imported")).toEqual({
      status: "imported",
      offset: 0,
      selectedIds: [],
      jumpPage: "",
      lightboxAssetId: null
    });
  });

  it("prefers the next item after rejection and otherwise uses the previous one", () => {
    const previewable = (count: number) => Array.from({ length: count }, () => ({ preview_url: "/image" }));

    expect(findClosestPreviewableIndex(previewable(3), 1)).toBe(1);
    expect(findClosestPreviewableIndex(previewable(2), 2)).toBe(1);
    expect(findClosestPreviewableIndex(previewable(60), 60)).toBe(59);
    expect(findClosestPreviewableIndex(previewable(1), 1)).toBe(0);
    expect(findClosestPreviewableIndex([], 0)).toBe(-1);
  });

  it("skips metadata-only records when choosing the next large preview", () => {
    expect(findClosestPreviewableIndex([
      { preview_url: null },
      { preview_url: null },
      { preview_url: "/next" }
    ], 0)).toBe(2);
    expect(findClosestPreviewableIndex([
      { preview_url: "/previous" },
      { preview_url: null }
    ], 1)).toBe(0);
  });

  it("keeps navigation on the opening snapshot when live list entries change", () => {
    const snapshot = ["asset-3", "asset-2", "asset-1"];
    const unavailable = new Set<string>(["asset-2"]);

    expect(getNextAcquisitionSnapshotIndex(snapshot, 0, 1, unavailable)).toBe(2);
    expect(getNextAcquisitionSnapshotIndex(snapshot, 2, -1, unavailable)).toBe(0);
    expect(getNextAcquisitionSnapshotIndex(snapshot, 0, -1, unavailable)).toBe(-1);
  });

  it("keeps the next item selected when rejecting inside the current page", () => {
    expect(getAcquisitionRejectContinuation([true, true, true], 1, 0, 3)).toEqual({
      kind: "local",
      index: 1
    });
  });

  it("keeps a full logical page while repeatedly rejecting assets", () => {
    let remaining = Array.from({ length: 125 }, (_, index) => `asset-${index}`);
    let page = remaining.slice(0, acquisitionAssetPageSize);

    for (let deletion = 0; deletion < 8; deletion += 1) {
      const rejectedId = page[10];
      remaining = remaining.filter((id) => id !== rejectedId);
      page = page.filter((id) => id !== rejectedId);
      const fill = getAcquisitionPageFill(page.length, 0, remaining.length);
      expect(fill).toEqual({ offset: 59, limit: 1 });
      if (fill) page.push(...remaining.slice(fill.offset, fill.offset + fill.limit));
      expect(page).toEqual(remaining.slice(0, acquisitionAssetPageSize));
    }

    expect(page[59]).toBe(remaining[59]);
    expect(remaining.slice(60, 120)[0]).toBe(remaining[60]);
    expect(remaining.slice(0, 60)[59]).toBe(page[59]);
  });

  it("does not request a fill beyond the remaining tail", () => {
    expect(getAcquisitionPageFill(5, 120, 125)).toBeNull();
  });

  it("fills a later page from the remaining tail so the next page start does not move", () => {
    expect(getAcquisitionPageFill(55, 60, 175)).toEqual({ offset: 115, limit: 5 });
  });

  it("rejects inconsistent page fills so the caller can reload the full page", () => {
    const fill = { offset: 59, limit: 1 };
    expect(isAcquisitionPageFillValid(["asset-1"], 119, fill, {
      offset: 59,
      total: 119,
      items: [{ id: "asset-60" }]
    })).toBe(true);
    expect(isAcquisitionPageFillValid(["asset-1"], 118, fill, {
      offset: 59,
      total: 119,
      items: [{ id: "asset-60" }]
    })).toBe(false);
    expect(isAcquisitionPageFillValid(["asset-1"], 119, fill, {
      offset: 59,
      total: 119,
      items: [{ id: "asset-1" }]
    })).toBe(false);
  });

  it("reloads the current offset to continue with the old next page after rejecting a page tail", () => {
    expect(getAcquisitionRejectContinuation(Array.from({ length: 59 }, () => true), 59, 0, 119)).toEqual({
      kind: "reload",
      offset: 0,
      preferredIndex: 59,
      direction: 1
    });
  });

  it("falls back to the global previous item only when no following item remains", () => {
    expect(getAcquisitionRejectContinuation([true, true], 2, 0, 2)).toEqual({
      kind: "local",
      index: 1
    });
    expect(getAcquisitionRejectContinuation([], 0, 60, 60)).toEqual({
      kind: "reload",
      offset: 0,
      preferredIndex: 59,
      direction: -1
    });
    expect(getAcquisitionRejectContinuation([], 0, 0, 0)).toEqual({ kind: "close" });
  });
});

describe("acquisition import batch state", () => {
  it("polls only batches that can still make progress", () => {
    expect(isAcquisitionImportBatchActive("queued")).toBe(true);
    expect(isAcquisitionImportBatchActive("running")).toBe(true);
    expect(isAcquisitionImportBatchActive("completed")).toBe(false);
    expect(isAcquisitionImportBatchActive("completed_with_errors")).toBe(false);
    expect(isAcquisitionImportBatchActive("failed")).toBe(false);
  });

  it("sends independent pagination and date filters for batches and details", async () => {
    const fetch = installWindow();
    await listAcquisitionImportBatches(15, 15, "2026-07-01", "2026-07-26");
    await listAcquisitionImportBatchItems("batch-id", "imported", 40, 40);

    expect(fetch.mock.calls[0][0]).toBe("/api/acquisition/import-batches?offset=15&limit=15&date_from=2026-07-01T00%3A00%3A00%2B08%3A00&date_to=2026-07-26T23%3A59%3A59.999999%2B08%3A00");
    expect(fetch.mock.calls[1][0]).toBe("/api/acquisition/import-batches/batch-id/items?status=imported&offset=40&limit=40");
  });
});

describe("acquisition lightbox keyboard review", () => {
  it("maps Space and Delete to review actions", () => {
    expect(getAcquisitionLightboxShortcut(" ")).toBe("toggle_selection");
    expect(getAcquisitionLightboxShortcut(" ", "video")).toBeNull();
    expect(getAcquisitionLightboxShortcut("Enter")).toBe("toggle_selection");
    expect(getAcquisitionLightboxShortcut("Delete")).toBe("reject");
  });

  it("maps Enter and Escape to confirmation decisions", () => {
    expect(getConfirmDialogKeyboardDecision("Enter")).toBe(true);
    expect(getConfirmDialogKeyboardDecision("Escape")).toBe(false);
    expect(getConfirmDialogKeyboardDecision("Delete")).toBeNull();
  });
});

describe("acquisition preview URLs", () => {
  it("preserves the content version when sizing a list preview", () => {
    expect(getAcquisitionPreviewUrl("/api/acquisition/assets/a/preview?v=sha", 480))
      .toBe("/api/acquisition/assets/a/preview?v=sha&max_edge=480");
  });
});
