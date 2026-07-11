## ADDED Requirements

### Requirement: Orientation-consistent face embeddings
The system SHALL apply embedded image orientation before detecting faces and generating embeddings for both sample and gallery images.

#### Scenario: EXIF-rotated image is processed
- **WHEN** an image contains an EXIF orientation that rotates or mirrors its stored pixels
- **THEN** face detection and embedding generation use the visually oriented pixels

### Requirement: Safe versioned sample-index rebuild
The system SHALL rebuild ready sample photos into a separate versioned Qdrant collection with complete workspace, person, sample, source, and embedding-version metadata.

#### Scenario: Legacy collection is active
- **WHEN** an operator rebuilds the sample index while a legacy collection is configured
- **THEN** the system creates or recreates a distinct target collection and leaves the active collection unchanged

#### Scenario: Sample cannot be indexed
- **WHEN** a ready sample has no single usable face
- **THEN** the rebuild report records the sample and a specific skip reason

### Requirement: Index validation and health reporting
The system SHALL validate the configured collection's vector schema and report searchable sample and person coverage relative to ready database samples.

#### Scenario: Migrated points lack required payload
- **WHEN** Qdrant contains points that do not satisfy the active workspace, source, and embedding-version filters
- **THEN** health information reports that those points are not searchable and shows the resulting coverage gap

#### Scenario: Rebuilt collection is complete
- **WHEN** all usable ready samples have been indexed with normalized vectors and complete payloads
- **THEN** validation reports the sample and person coverage and marks the index ready for manual activation

### Requirement: Read-only direct match diagnostics
The system SHALL provide a command that compares a selected gallery photo face with current embeddings recomputed from every ready sample of a selected person without modifying application data.

#### Scenario: Diagnose a low recognition score
- **WHEN** an operator supplies a gallery photo ID and person ID
- **THEN** the command reports per-sample local cosine scores, the best local match, current Qdrant candidates, and whether the Qdrant score agrees with direct cosine comparison

### Requirement: Manual gallery re-recognition remains explicit
The system SHALL NOT automatically re-recognize gallery photos after building or validating a new sample index.

#### Scenario: Rebuild completes
- **WHEN** a new sample index passes validation
- **THEN** gallery records remain unchanged until the operator uses the existing re-recognition workflow
