## Context

The active Qdrant collection contains 310 points, but 256 migrated sample points have no payload metadata. Current searches require `workspace_id`, `source_type`, and `embedding_version`, so only 37 samples and 17 centroids are searchable even though SQLite contains 293 ready samples for 164 people. Face preprocessing also opens image pixels without applying EXIF orientation.

## Goals / Non-Goals

**Goals:**
- Generate sample and gallery embeddings from the same orientation-normalized image pipeline.
- Build a complete sample-only index without overwriting the active collection.
- Make index coverage and payload problems observable.
- Provide a direct, read-only comparison path that separates model/preprocessing problems from vector-store problems.

**Non-Goals:**
- Automatically activate a new collection, restart services, or rewrite gallery labels.
- Lower the recognition threshold or replace InsightFace before measuring the repaired index.
- Add another frontend batch-recognition action.

## Decisions

- Apply `ImageOps.exif_transpose` before RGB/BGR conversion in the shared face service. This keeps sample uploads, rebuilds, gallery imports, and re-recognition in one embedding space.
- Bump the default embedding version to `buffalo_l-v2-exif`. Changing preprocessing without changing the version could mix incompatible points.
- Rebuild into a versioned target collection and refuse to overwrite the configured active collection. In-place payload backfilling is rejected because the provenance of migrated vectors cannot be proven.
- Validate distance, dimension, normalized vectors, required payload fields, indexed sample count, and covered person count before suggesting activation.
- Report health through the existing health endpoint while leaving startup non-blocking; an incomplete index is an operational fault but must not prevent unrelated application functions.
- Implement exact pair diagnostics as a maintenance CLI. It recomputes current embeddings, compares locally, and optionally checks Qdrant results without changing data.

## Risks / Trade-offs

- [Some ready samples may fail under current detection rules] → Report every skip reason and covered person IDs; never silently activate an incomplete collection.
- [EXIF normalization changes existing embeddings] → Use a new embedding version and full rebuild.
- [A new collection consumes extra storage] → Retain the old collection for rollback, then remove it manually after validation.
- [Health counting can be expensive] → Use Qdrant count queries and database aggregate counts rather than loading vectors.

## Migration Plan

1. Deploy the code without changing the active collection.
2. Run the rebuild command manually after explicit authorization.
3. Review indexed/skipped sample counts and person coverage.
4. Set the reported collection and embedding version in local configuration, then restart services manually.
5. Use the existing unknown-person re-recognition button.
6. Keep the old collection until results are accepted; rollback by restoring the previous configuration.

## Open Questions

None.
