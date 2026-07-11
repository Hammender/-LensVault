## ADDED Requirements

### Requirement: Correction-derived labels
The system SHALL record recognition predictions as evaluation labels when a user explicitly corrects or promotes a face.

#### Scenario: Unknown corrected to known
- **WHEN** a user assigns a known person to an automatically unknown single face
- **THEN** the previous candidate diagnostics and corrected person are stored as a labeled evaluation event

#### Scenario: Unchanged prediction
- **WHEN** a user does not modify an automatic prediction
- **THEN** the prediction is not treated as verified ground truth

### Requirement: Offline recognition benchmark
The system SHALL provide an offline command that compares detection sizes, flip augmentation, matching strategies, thresholds and ambiguity margins without modifying production records.

#### Scenario: Benchmark completes
- **WHEN** the evaluator runs against available samples and correction events
- **THEN** it writes Markdown, JSON and CSV reports containing accuracy, recall, error and performance metrics

#### Scenario: Insufficient labels
- **WHEN** fewer than 100 labeled faces or fewer than 20 identities are available
- **THEN** the report is marked insufficient and does not provide a production parameter recommendation

### Requirement: Conservative recommendation
The evaluator SHALL recommend a candidate only when it improves familiar-person recall without increasing wrong-person rate beyond the baseline.

#### Scenario: Algorithm recommendation
- **WHEN** a candidate improves familiar-person recall by at least two percentage points and does not worsen wrong-person rate
- **THEN** it may be reported as the recommended algorithm configuration

#### Scenario: Model recommendation
- **WHEN** a candidate model improves familiar-person recall by at least three percentage points, does not worsen wrong-person rate, runs within twice the baseline time, and is approved for use
- **THEN** it may be reported as a model replacement candidate using a separate embedding version
