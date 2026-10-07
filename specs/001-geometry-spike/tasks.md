# Tasks: H3 Geometry Eligibility Spike

**Input**: Design documents from `specs/001-geometry-spike/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/eligibility-output.md`, and `quickstart.md`

**Tests**: Required by the acceptance scenarios and constitution. ArcPy geometry/network tests run in ArcGIS Pro; portable H3 and non-spatial state tests run without ArcPy. The StreetMap Premium smoke test is read-only and skipped when its ArcPy environment or configured path is unavailable.

**Organization**: Tasks are grouped by the two P1 user stories. The complete solvable-cell handoff requires both stories because cells cannot be marked `solvable` until representative and Network Analyst location validation succeeds.

## Phase 1: Setup

**Purpose**: Establish feature configuration, package boundaries, and test-environment gates.

- [X] T001 [P] Add explicit spatial, network, and eligibility configuration keys in `config/config.yml`, including working/storage CRS, snap tolerance, H3 resolution, travel mode/restrictions, inclusive intersection policy, batch size, per-part row limit, and required total solvable-cell hard cap; reject missing required values instead of adding implicit code defaults.
- [X] T002 [P] Add ArcPy-test skip helpers and a `H3_RDB_TEST_NETWORK` environment-variable fixture that checks dataset availability with `arcpy.Exists` in `testing/conftest.py`.
- [X] T003 [P] Create the package initializers `src/h3_route_data_builder/eligibility/__init__.py` and `src/h3_route_data_builder/network/__init__.py`.

---

## Phase 2: Foundational

**Purpose**: Define shared eligibility/run records and deterministic run metadata before either story implements behavior.

- [X] T004 Define typed AOI, edge-evidence, cell-result, representative, partition, and run-state models in `src/h3_route_data_builder/eligibility/models.py`, preserving the required `solvable`/`ineligible` status semantics and nullable representative fields for ineligible rows.
- [X] T005 [P] Add deterministic fingerprint tests in `testing/test_eligibility_fingerprint.py` and implement fingerprint construction in `src/h3_route_data_builder/eligibility/fingerprint.py`, including network/travel mode/restrictions, CRS, H3 resolution, policy values, schema version, and Python/ArcGIS Pro/H3/package versions.
- [X] T006 [P] Add run-state transition/persistence tests in `testing/test_eligibility_run_state.py` and implement persisted run and expected-partition state transitions in `src/h3_route_data_builder/eligibility/run_state.py`; a run must remain incomplete until all required reconciliation and representative checks succeed.
- [X] T007 Add atomic staging tests in `testing/test_eligibility_staging.py` and implement GeoParquet staged-part writing with per-part row-count/checksum metadata in `src/h3_route_data_builder/eligibility/staging.py`, using the existing solvable-cell spatial schema and keeping run metadata outside worker scratch workspaces.

**Checkpoint**: Configuration, shared models, fingerprints, run state, and atomic staging primitives are ready.

---

## Phase 3: User Story 1 - Identify Network-Eligible Cells (Priority: P1)

**Goal**: Validate the AOI, determine eligible edges, and identify the unique H3 cells with inclusive intersections while preserving edge evidence.

**Independent Test**: With synthetic ArcPy AOI/edge fixtures and portable H3 fixtures, verify every qualifying H3 ID and reject nearby, restricted-only, and unknown-eligibility cases. Crossing, point-touch, coincident-boundary, multipart, and pentagon-adjacent cases must match fixed expected IDs.

### Tests for User Story 1

- [X] T008 [P] [US1] Add ArcPy AOI and topology acceptance tests for valid/invalid CRS, crossing, point-touch, coincident boundary, nearby non-intersection, multipart edges, and pentagon-adjacent H3 cells in `testing/test_eligibility_geometry.py`.
- [X] T009 [P] [US1] Add edge eligibility tests for restrictions, one-way direction, and unknown eligibility failing closed in `testing/test_network_eligibility.py`.
- [X] T010 [P] [US1] Add portable H3-ID ordering and non-spatial eligibility-rule tests, including that an edge-less cell is never admitted to a solvable handoff, in `testing/test_eligibility_rules.py`.

### Implementation for User Story 1

- [X] T011 [US1] Inspect ArcPy network-source/edge evaluator behavior for configured travel modes and restrictions; add synthetic tests for allowed, restricted, one-way, and unknown evaluator cases in `testing/test_network_eligibility.py`, and record the supported evaluator mapping and limitations in `specs/001-geometry-spike/research.md`.
- [X] T012 [P] [US1] Implement AOI validation, explicit ArcPy projection to the configured working CRS, datum transformation handling, AOI clipping, multipart traversal, and exact point/line intersection checks in `src/h3_route_data_builder/network/geometry.py`; use ArcPy intersection dimensions 1 and 2 so point touches and line overlaps both qualify.
- [X] T013 [US1] Implement network edge-source extraction and eligibility using the supported evaluator mapping established in T011 in `src/h3_route_data_builder/network/eligibility.py`; exclude prohibited or indeterminate edges with a recorded reason.
- [X] T014 [US1] Implement sorted/deduplicated H3 v4 AOI candidate coverage in `src/h3_route_data_builder/eligibility/cells.py` and construct/project canonical H3 cell polygons through `src/h3_route_data_builder/network/geometry.py`; use exact ArcPy topology as the eligibility predicate, not the candidate cover.
- [X] T015 [US1] Implement per-cell intersection classification and edge evidence assembly in `src/h3_route_data_builder/eligibility/engine.py`; do not mark a row `solvable` until Story 2 validates its representative and Network Analyst fields.
- [X] T016 [US1] Add deterministic batch split/retry, staging-part row-limit, and no-truncation tests in `testing/test_eligibility_staging.py`.
- [X] T017 [US1] Implement deterministic bounded input partitioning and batch subdivision/retry in `src/h3_route_data_builder/eligibility/staging.py`; write each batch to its own atomic part and never drop rows at the per-part limit.
- [X] T018 [US1] Add cross-part duplicate-H3, missing-partition, and checksum-reconciliation tests in `testing/test_eligibility_staging.py`.
- [X] T019 [US1] Implement cross-part H3/edge-evidence reconciliation in `src/h3_route_data_builder/eligibility/reconcile.py`; deduplicate canonical H3 IDs and edge identities while leaving the run incomplete until representatives and final handoff validation finish.
- [X] T020 [US1] Add an ArcGIS Pro toolbox entry point that validates required AOI/network/configuration inputs and delegates to the package in `arcgis/h3_route_data_builder.pyt`; do not add candidate generation or OD solve parameters.

**Checkpoint**: The system identifies and reconciles exactly the cells intersecting eligible edges, but exposes no row as solvable until Story 2 validates its representative.

---

## Phase 4: User Story 2 - Audit Cell Representatives and Eligibility (Priority: P1)

**Goal**: Select one deterministic on-network representative per eligible cell, populate valid Network Analyst location fields, record evidence, and expose only validated solvable rows.

**Independent Test**: Given synthetic eligible edge/cell results, repeat representative selection under reordered inputs and verify the same point, edge identity, measure, snap tolerance, location fields, eligibility evidence, and handoff rows. Separately run the path-gated StreetMap Premium smoke test when ArcPy and the dataset are available.

### Tests for User Story 2

- [X] T021 [P] [US2] Add representative tie-break, zero-snap-tolerance, source/OID mismatch, invalid-location, and solvable-only handoff tests in `testing/test_network_eligibility.py`.
- [X] T022 [P] [US2] Add the read-only StreetMap Premium integration test in `testing/test_real_network_dataset.py`; use `arcpy.Exists` on `H3_RDB_TEST_NETWORK`, verify `Driving Time`, run `arcpy.na.CalculateLocations` on the fixed in-memory point (longitude -73.9857, latitude 40.7484), and assert valid location fields without modifying the source dataset.
- [X] T023 [P] [US2] Add required-total-hard-cap, unique-solvable-count, incomplete-on-overflow, and complete-only-after-reconciliation tests in `testing/test_eligibility_staging.py` using fixtures with validated representatives.

### Implementation for User Story 2

- [X] T024 [US2] Implement nearest-point representative selection on eligible in-AOI edge portions in `src/h3_route_data_builder/network/representatives.py`; rank by centroid distance, then source ID, source OID, and edge measure, independent of input order.
- [X] T025 [US2] Implement `arcpy.na.CalculateLocations` integration and validate `SourceID`, `SourceOID`, `PosAlong`, and `SideOfEdge` against the intended eligible edge in `src/h3_route_data_builder/network/locations.py`; reject a mismatched location and try the next deterministically ranked edge candidate.
- [X] T026 [US2] Persist representative geometry, snap distance, location fields, eligibility reason, CRS/travel-mode/restriction policy, and fingerprint evidence in `src/h3_route_data_builder/eligibility/engine.py`; rows without a valid representative remain `ineligible`.
- [X] T027 [US2] Enforce the required total hard cap against distinct validated solvable H3 IDs and implement the final `eligibility_status=solvable` handoff/completion gate in `src/h3_route_data_builder/eligibility/reconcile.py`; fail explicitly and keep the run incomplete on cap overflow or unreconciled partitions.

**Checkpoint**: Only cells with an eligible intersecting edge, one deterministic representative, valid location fields, and reconciled run evidence are exposed as solvable.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T028 Add structured progress, exclusion-reason, partition-reconciliation, and run-completion logging with `get_logger` in `src/h3_route_data_builder/eligibility/` and `src/h3_route_data_builder/network/` modules.
- [X] T029 Run the portable checks, ArcPy synthetic suites, path-gated real-data test, and `make test` following `specs/001-geometry-spike/quickstart.md`; update the guide only if the implemented commands or expected outcomes differ.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001-T003 have no prerequisites and can run in parallel.
- **Foundational (Phase 2)**: T004 follows package setup; T005 and T006 depend on T004 and can run in parallel; T007 depends on the run/partition model in T004/T006.
- **User Story 1 (Phase 3)**: Begins after foundational tasks. T008-T010 can be written in parallel because they target different test files. T011 establishes the evaluator method and must finish before T013; T012 geometry work can proceed independently. Staging and reconciliation tests precede their implementations.
- **User Story 2 (Phase 4)**: Begins after the Story 1 eligible-cell/edge-evidence contract exists. T020-T022 can be written in parallel in separate test files. Representative selection, Network Analyst location validation, evidence, and final completion follow in order.
- **Polish (Phase 5)**: Depends on both P1 stories.

### User Story Dependencies

- **User Story 1 (P1)**: Starts after Phase 2; independently tests AOI, network-edge, H3 intersection, and staged partition eligibility.
- **User Story 2 (P1)**: Uses Story 1 eligible-cell and edge evidence; representative behavior is independently tested with synthetic fixtures. The complete solvable-cell MVP requires both stories.

### Parallel Opportunities

- Setup tasks T001-T003 touch separate configuration, test-fixture, and package-init files.
- Synthetic geometry tests T008, edge eligibility tests T009, and portable rule tests T010 target separate files.
- Evaluator discovery T011 and ArcPy geometry implementation T012 can proceed in parallel after the T009 fixture cases are defined.
- Story 2 representative tests T021, real-data smoke test T022, and cap/finalization tests T023 target separate test files.
- Fingerprint construction T005 and run-state models T006 can proceed in parallel after T004.

### Parallel Example: Story 1 Tests

```text
T008: ArcPy geometry cases in testing/test_eligibility_geometry.py
T009: Travel-mode edge cases in testing/test_network_eligibility.py
T010: H3/status rules in testing/test_eligibility_rules.py
After T008-T010 complete, T011 evaluator-method tests/research and T012 geometry implementation can proceed in parallel.
```

### Parallel Example: Story 2 Tests

```text
T021: Synthetic representative/location tests in testing/test_network_eligibility.py
T022: Real StreetMap Premium smoke test in testing/test_real_network_dataset.py
T023: Cap and run-completion tests in testing/test_eligibility_staging.py
```

## Implementation Strategy

### MVP First

Both P1 stories are required for an end-to-end MVP. Story 1 alone can demonstrate eligible edge/cell evidence, but cannot emit `eligibility_status=solvable` without Story 2's validated representative and Network Analyst fields.

1. Complete setup and foundational run/configuration models.
2. Implement and validate Story 1's AOI, edge eligibility, H3 intersections, and staged partition results.
3. Implement and validate Story 2's deterministic representatives, Network Analyst fields, audit evidence, and solvable-only handoff.
4. Run the required synthetic acceptance suite; run the real-data smoke test when the ArcPy environment and configured dataset are available.
5. Run `make test` and verify no partial run is marked complete.

### Incremental Delivery

- Deliver Story 1's eligible-cell evidence and reconciled partitions first, with no solvable handoff before representative validation.
- Deliver Story 2 to turn validated eligible cells into deterministic solvable-cell rows.
- Keep real-data smoke validation supplemental to the synthetic topology oracle.
