## ADDED Requirements

### Requirement: Person-level candidate matching
The system SHALL retrieve multiple sample candidates, group them by person, and determine the best and second-best person candidates.

#### Scenario: Familiar face matched
- **WHEN** at least one eligible sample for a person exceeds the active threshold
- **THEN** the face is assigned to the highest-scoring person and candidate diagnostics are recorded

#### Scenario: No candidate passes threshold
- **WHEN** no eligible person reaches the active threshold
- **THEN** the face is marked for review as unknown

### Requirement: Explicit sample promotion
The system SHALL only add a manually assigned gallery face to the reference library when the user explicitly requests promotion.

#### Scenario: Tag without promotion
- **WHEN** a user assigns a person to a gallery photo
- **THEN** the photo tag changes and the reference index is unchanged

#### Scenario: Promote a single face
- **WHEN** a tagged gallery photo has exactly one valid face and the user separately requests promotion
- **THEN** a cropped sample is created, quality checked, indexed, and included in the person's centroid

#### Scenario: Reject ambiguous promotion
- **WHEN** promotion is requested for a photo containing zero or multiple faces
- **THEN** no sample is created and a clear validation error is returned without changing the existing tag

### Requirement: Safe re-recognition
The system SHALL preserve existing recognition data until a complete replacement result is ready.

#### Scenario: Successful re-recognition
- **WHEN** image loading, detection and matching complete successfully
- **THEN** automatic face records and automatic person tags are replaced while manual tags remain

#### Scenario: Failed re-recognition
- **WHEN** image loading, detection or matching raises an error
- **THEN** all previous recognition records and tags remain unchanged

### Requirement: Sample quality assessment
The system SHALL calculate face size, detection confidence, blur and pose indicators for sample candidates.

#### Scenario: Severely invalid sample
- **WHEN** a candidate has no single usable face or falls below the hard minimum face size
- **THEN** it is not inserted into the reference index and the reason is reported

#### Scenario: Marginal sample
- **WHEN** a sample is usable but has quality warnings
- **THEN** its warnings are persisted and shown without silently discarding the sample
### Requirement: Adaptive gallery face crop
The system SHALL crop a gallery-derived sample in the coordinate system used during detection, preserve the image's display orientation, and retry with additional context when the first crop contains no detectable face.

#### Scenario: Initial crop succeeds
- **WHEN** the square crop at roughly twice the detected face's longest side contains one usable face
- **THEN** that crop is stored and the already computed detection result is reused for sample creation

#### Scenario: Initial crop misses the face
- **WHEN** the initial crop contains no detectable face
- **THEN** the system retries once with a square crop at roughly three times the detected face's longest side

#### Scenario: Adaptive crop still fails
- **WHEN** neither crop contains exactly one usable face
- **THEN** no stored sample or reference vector remains and a clear validation error is returned
