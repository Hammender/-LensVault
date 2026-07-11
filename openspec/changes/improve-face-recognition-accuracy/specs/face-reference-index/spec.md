## ADDED Requirements

### Requirement: Workspace-isolated reference index
The system SHALL store and query face reference vectors with workspace and embedding-version isolation.

#### Scenario: Search current workspace
- **WHEN** a gallery face is recognized in a workspace
- **THEN** only sample and centroid vectors belonging to that workspace and active embedding version are eligible

#### Scenario: No gallery vectors
- **WHEN** a gallery photo is imported or re-recognized
- **THEN** no vector from that gallery photo is inserted into the reference collection

### Requirement: Versioned index rebuild
The system SHALL rebuild reference vectors from valid sample records into a versioned collection without modifying gallery records.

#### Scenario: Successful rebuild
- **WHEN** an administrator runs the rebuild command
- **THEN** the new collection contains valid sample points and person centroid points with counts reported for validation

#### Scenario: Failed rebuild
- **WHEN** rebuilding or validation fails
- **THEN** the active collection remains unchanged and usable

### Requirement: Centroid maintenance
The system SHALL recompute a person's normalized centroid whenever that person's indexed samples change.

#### Scenario: Sample added or removed
- **WHEN** a valid sample is added to or removed from a person
- **THEN** the person's centroid point is updated or removed when no samples remain
## ADDED Requirements

### Requirement: Gallery-derived samples retain provenance
The system SHALL store the source gallery photo for a promoted face crop, SHALL allow at most one promoted sample for the same person and gallery photo, and SHALL preserve the sample if the source gallery photo is later deleted.

#### Scenario: Promote an existing person tag
- **WHEN** a gallery photo has exactly one detected face and already has a formal person tag
- **THEN** the user can explicitly promote the padded face crop into that person's sample library
- **AND** the resulting sample exposes its gallery source while that source still exists

#### Scenario: Duplicate promotion
- **WHEN** the same gallery photo has already been promoted for the same person
- **THEN** the system rejects or disables another promotion without creating a second sample or vector

#### Scenario: Promotion fails validation
- **WHEN** the cropped face cannot become a valid ready sample
- **THEN** no sample record, stored crop, or reference vector remains from the failed attempt

#### Scenario: Undo a gallery-derived sample
- **WHEN** a user confirms undo for an existing gallery-derived sample
- **THEN** the derived sample record, stored crop, sample vector, and centroid contribution are removed
- **AND** the source gallery photo and its person tag remain unchanged
