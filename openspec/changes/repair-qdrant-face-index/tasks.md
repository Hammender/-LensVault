## 1. Embedding Consistency

- [x] 1.1 Apply EXIF orientation normalization in the shared face detection pipeline
- [x] 1.2 Introduce a new default embedding version for the changed preprocessing

## 2. Index Integrity

- [x] 2.1 Add Qdrant schema, payload, vector, and coverage inspection helpers
- [x] 2.2 Make the rebuild tool safe, versioned, reason-reporting, and self-validating
- [x] 2.3 Add face-index coverage to backend health information

## 3. Diagnostics

- [x] 3.1 Add a read-only gallery-photo/person direct match diagnostic command

## 4. Verification

- [x] 4.1 Add focused tests for EXIF normalization and index health calculations
- [x] 4.2 Run Python compilation and relevant backend tests without starting services
- [x] 4.3 Document the manual rebuild, activation, rollback, and existing re-recognition flow
