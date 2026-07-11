## 1. Data model and configuration

- [x] 1.1 Add recognition candidate, correction-event, sample-quality, and embedding-version persistence
- [x] 1.2 Add configurable model, detection size, search limit, flip augmentation, and quality thresholds

## 2. Reference index

- [x] 2.1 Add workspace/version/source payloads and filtered multi-candidate Qdrant search
- [x] 2.2 Add sample centroid creation and maintenance on sample add/delete
- [x] 2.3 Add a safe versioned reference-index rebuild and validation command

## 3. Recognition behavior

- [x] 3.1 Implement person-level candidate aggregation and candidate diagnostics
- [x] 3.2 Add sample quality assessment and enforce the hard validity gate
- [x] 3.3 Refactor re-recognition to compute before replace, preserve manual tags, and roll back failures

## 4. Manual promotion and frontend

- [x] 4.1 Extend the manual person-tag API with explicit single-face sample promotion
- [x] 4.2 Add the default-off promotion checkbox, validation messaging, and re-recognition summary to image details

## 5. Evaluation tooling

- [x] 5.1 Record correction-derived evaluation labels without treating unchanged predictions as verified
- [x] 5.2 Add an offline benchmark command and Markdown/JSON/CSV reports with recommendation gates

## 6. Verification

- [x] 6.1 Add backend tests for workspace isolation, aggregation, promotion, centroid maintenance, and safe re-recognition
- [x] 6.2 Add frontend tests for promotion controls and run the production frontend build
- [x] 6.3 Update configuration documentation and verify no normal gallery operation writes reference vectors

## 7. Gallery sample promotion follow-up

- [x] 7.1 Persist gallery-source provenance for promoted samples and prevent duplicate promotion per person/photo
- [x] 7.2 Add independent promotion for existing gallery person tags with atomic failure cleanup
- [x] 7.3 Reset the promotion checkbox per photo, make the submit label explicit, and show promotion status/actions on existing tags
- [x] 7.4 Show promoted-sample source links in the sample library and verify backend/frontend contracts and builds

## 8. Simplify and harden gallery sample promotion

- [x] 8.1 Remove the combined tag-and-promotion checkbox/API path and keep person tagging as a separate operation
- [x] 8.2 Add symmetric promotion undo that removes only the derived sample, stored crop, vectors, and centroid contribution
- [x] 8.3 Use EXIF-safe adaptive square crops at roughly 2x and 3x face size without duplicate face detection
- [x] 8.4 Update backend/frontend tests and API contracts, then run the production frontend build
