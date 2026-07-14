import type { GallerySimilarityScan } from "./types";

export function scanScopeKey(personId: number | null, includeCrossType: boolean): string {
  return `${personId ?? "all"}:${includeCrossType ? "cross" : "separate"}`;
}

export function findScanForScope(
  scans: GallerySimilarityScan[],
  personId: number | null,
  includeCrossType: boolean
): GallerySimilarityScan | null {
  const targetKey = scanScopeKey(personId, includeCrossType);
  return scans.find((scan) => scanScopeKey(scan.person_id, scan.include_cross_type) === targetKey) ?? null;
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
