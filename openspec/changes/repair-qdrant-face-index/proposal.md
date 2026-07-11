## Why

The Qdrant migration left most sample vectors without the metadata required by the current search filters. As a result, only 37 of 293 ready samples participate in recognition and visually obvious matches can appear as low-scoring unknown faces.

## What Changes

- Normalize image EXIF orientation before face detection and embedding generation.
- Rebuild all ready sample embeddings into a new versioned Qdrant collection with complete payload metadata and person centroids.
- Validate collection configuration, vector integrity, sample coverage, and person coverage before activation.
- Expose face-index health information without starting a rebuild automatically.
- Add a read-only diagnostic command for comparing a gallery face directly with every sample for a selected person.
- Keep the existing “一键重新识别所有未知人物” workflow; do not add another batch-recognition UI action.

## Capabilities

### New Capabilities
- `face-index-integrity`: Versioned sample-only face indexes can be rebuilt, validated, monitored, and diagnosed safely.

### Modified Capabilities

## Impact

- Backend face preprocessing, Qdrant integration, health response, and maintenance tools.
- A new embedding version and a manually activated versioned Qdrant collection.
- No frontend behavior change and no automatic mutation of gallery recognition results.
