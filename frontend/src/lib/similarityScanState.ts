import type { GallerySimilarityScan } from "../types";

export function scanScopeKey(personId: number | null, includeCrossType: boolean, scanType: "normal" | "mirror" = "normal"): string {
  return `${personId ?? "all"}:${includeCrossType ? "cross" : "separate"}:${scanType}`;
}

export function findScanForScope(
  scans: GallerySimilarityScan[],
  personId: number | null,
  includeCrossType: boolean,
  scanType: "normal" | "mirror" = "normal"
): GallerySimilarityScan | null {
  const targetKey = scanScopeKey(personId, includeCrossType, scanType);
  return scans.find((scan) => scanScopeKey(scan.person_id, scan.include_cross_type, scan.scan_type) === targetKey) ?? null;
}

export function chooseRecoveredScan(
  scans: GallerySimilarityScan[],
  preferredScanId?: string | null
): GallerySimilarityScan | null {
  if (preferredScanId) {
    const preferred = scans.find((scan) => scan.id === preferredScanId);
    if (preferred) return preferred;
  }
  return scans[0] ?? null;
}
