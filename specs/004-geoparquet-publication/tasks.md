---

description: "Implementation tasks for GeoParquet Publication"
---

# Tasks: GeoParquet Publication

**Input**: Design documents from `specs/004-geoparquet-publication/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, and
`contracts/publication-contract.md`

**Tests**: Acceptance criteria and Constitution Principle X require tests for reader
interoperability, schema and manifest validation, atomicity, pruning, and compaction equivalence.

**Organization**: Tasks are grouped by the three prioritized user stories in `spec.md`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other marked tasks because they use separate files and have no
  dependency on unfinished work.
- **[Story]**: Maps a task to a user story in `spec.md`.
- Every task names the exact repository file path to change or validate.

## Phase 1: Setup

**Purpose**: Establish the ArcPy-free publication package boundary.

- [X] T001 Create `src/h3_route_data_builder/publication/__init__.py` and ensure package imports do not load ArcPy or GeoPandas.

## Phase 2: Foundational

**Purpose**: Verify the portable reader and writer capabilities before story implementation.

- [X] T002 Verify PyArrow, DuckDB, and DuckDB Spatial availability in the configured environment; if required capabilities are missing, justify any proposed dependency-manifest change in `pyproject.toml` or `environment.yml` before adding it.

**Checkpoint**: Required Arrow/Parquet and independent-reader capabilities are known before
user-story implementation begins.

## Phase 3: User Story 1 - Produce and Read GeoParquet Tables (Priority: P1) - MVP

**Goal**: Convert Feature 001/002/003 inputs to canonical Arrow tables, write the solvable-cell
dimension and OD facts as GeoParquet, and validate schema, metadata, and readable logical rows.
These files are not exposed as a complete dataset version and do not receive a valid `_SUCCESS`
marker in this story.

**Independent Test**: Write a small fixture as dimension and fact GeoParquet files. Use PyArrow to
validate schemas and GeoParquet metadata, read both files with PyArrow and DuckDB Spatial, and
compare identifiers, units, geometries, eligibility evidence, and logical rows with independent
expected values. Include an in-scope solvable cell whose candidate pairs were all prefilter-pruned.
Confirm US1 output is not presented as an atomically published complete dataset.

### Tests for User Story 1

- [X] T003 [P] [US1] Test exact Arrow field types, nullability, canonical identifiers, geometry-free OD facts, and direction-sensitive logical keys in `testing/test_publication_schema.py`.
- [X] T004 [P] [US1] Test conversion of Feature 001/002/003 fixtures, including solvable eligibility and representative evidence, exact selected-scope dimension membership, and retention of a cell whose candidate pairs are all prefilter-pruned in `testing/test_publication_conversion.py`.
- [X] T005 [P] [US1] Test GeoParquet 1.1.0 output metadata, WKB geometry types, complete EPSG:4326 PROJJSON, usable extent/covering metadata, PyArrow metadata inspection, PyArrow and DuckDB Spatial reads, and absence of a valid completion marker in `testing/test_publication_interoperability.py`.

### Implementation for User Story 1

- [X] T006 [US1] Define typed schema, conversion, and table-output records with explicit schema versions in `src/h3_route_data_builder/publication/models.py`.
- [X] T007 [US1] Implement Arrow schemas for `solvable_cells` and `od_facts` in `src/h3_route_data_builder/publication/schema.py`; match every canonical field type and nullability, and exclude geometry from OD facts.
- [X] T008 [US1] Convert Feature 001 solvable records, Feature 003 qualifying outcomes, and Feature 002 self-pairs to canonical Arrow tables in `src/h3_route_data_builder/publication/convert.py`; require lowercase H3 identifiers, one directed row per key, actual network costs only, and zero-cost self-pairs with null `work_item_id`.
- [X] T009 [US1] Write bounded `solvable_cells` and `od_facts` GeoParquet table files with the required GeoParquet 1.1.0 metadata in `src/h3_route_data_builder/publication/write.py`; keep outputs outside the successful-publication visibility path and do not create a valid `_SUCCESS` marker.
- [X] T010 [US1] Export supported schemas, conversion functions, and GeoParquet table-writing entry points from `src/h3_route_data_builder/publication/__init__.py` without importing ArcPy or GeoPandas.

**Checkpoint**: The fixture produces two readable GeoParquet table files whose schemas,
metadata, eligibility evidence, and logical rows validate independently; no complete dataset
version is claimed.

## Phase 4: User Story 2 - Publish Only a Complete Valid Snapshot (Priority: P1)

**Goal**: Reconcile expected keys and manifests, reject invalid or unresolved output, and expose
only a complete immutable dataset version atomically.

**Independent Test**: Inject interruptions after staging, validation, manifest creation, and
publication exposure; corrupt or omit files and keys; verify recovery leaves either the previous
complete version or a fully validated new version, never partial success or duplicate logical
keys.

### Tests for User Story 2

- [X] T011 [P] [US2] Test required dataset/partition manifest fields, schema versions, fingerprints, checksums, row counts, extents, referenced parts, and reconciled totals in `testing/test_publication_manifest.py`.
- [X] T012 [P] [US2] Test rejection and diagnostics for missing, duplicate, unexpected, incompatible, corrupt, or unresolved keys/files and verify invalid output has no valid completion marker in `testing/test_publication_validation.py`.
- [X] T013 [P] [US2] Test restart/fault injection after staging, data validation, manifest creation, and atomic exposure, proving recovery neither loses results nor commits duplicate logical OD keys in `testing/test_publication_publish.py`.

### Implementation for User Story 2

- [X] T014 [US2] Define deterministic dataset and partition manifest records in `src/h3_route_data_builder/publication/manifest.py`, including publication state, version/fingerprints, Feature 001-003 provenance, expected/published key counts, outcome counts, schemas, geometry conventions, partition/order policies, checksums, row counts, extents, and manifest references.
- [X] T015 [US2] Validate schemas, GeoParquet metadata, CRS/extents, part checksums and row counts, manifest totals/references, endpoint membership, logical-key uniqueness, and exact expected-key accounting in `src/h3_route_data_builder/publication/validation.py`.
- [X] T016 [US2] Reconcile Feature 002 retained non-self keys and self-pairs with Feature 003 authoritative compatible outcomes in `src/h3_route_data_builder/publication/validation.py`; count `unlocated`, `unreachable`, and `cutoff-excluded` as non-route outcomes and reject unresolved, retryable, terminal system-failure, missing, duplicate, or unexpected keys.
- [X] T017 [US2] Stage immutable parts and manifests as undiscoverable output, expose the validated version through one atomic publication reference, and write `_SUCCESS` only after every required validation passes in `src/h3_route_data_builder/publication/publish.py`.
- [X] T018 [US2] Surface publication and validation failures with explicit diagnostics and structured logging, and ensure staged, incomplete, or corrupt versions cannot be read as successful in `src/h3_route_data_builder/publication/publish.py`.

**Checkpoint**: Invalid or interrupted versions remain incomplete; a valid version becomes
visible atomically with matching complete manifests and marker.

## Phase 5: User Story 3 - Prune and Compact Published Data (Priority: P2)

**Goal**: Let origin-filtered reads skip unrelated facts and compact physical parts into a new
immutable version without changing logical dataset contents.

**Independent Test**: Query a multi-origin version for one origin and demonstrate unrelated
files/row groups are skipped. Compact it and compare all logical dimension and fact records while
confirming the prior version remains unchanged.

### Tests for User Story 3

- [X] T019 [P] [US3] Test that a single-origin query skips unrelated fact files or row groups using recorded origin metadata before and after compaction in `testing/test_publication_pruning.py`.
- [X] T020 [P] [US3] Test compaction's exact logical equivalence, refreshed manifests/checksums/extents, zero duplicate keys, and immutability of the source version in `testing/test_publication_compaction.py`.

### Implementation for User Story 3

- [X] T021 [US3] Write bounded fact parts with canonical origin identifiers retained as typed rows and partition metadata, record file/row-group origin statistics for pruning, and preserve deterministic locality-aware cell ordering in `src/h3_route_data_builder/publication/partition.py`.
- [X] T022 [US3] Implement compaction as a new immutable physical version with regenerated parts, extents, checksums, row counts, and manifests while preserving all logical rows, identifiers, and source-version immutability in `src/h3_route_data_builder/publication/compact.py`.

**Checkpoint**: Origin pruning is measurable after compaction, and the prior published version
remains unchanged.

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T023 [P] Update validation commands and expected outcomes for US1 GeoParquet writing, US2 atomic publication, and US3 pruning/compaction in `specs/004-geoparquet-publication/quickstart.md`.
- [X] T024 Run the focused Feature 004 tests and verify PyArrow/DuckDB reader behavior, manifest/checksum/count consistency, atomic publication, origin pruning, compaction equivalence, and absence of GeoPandas dependencies/imports/usages in `testing/` and `src/h3_route_data_builder/publication/`.
- [X] T025 Run the repository's relevant test suite and `git diff --check`; record any environment limitation or missing runtime dependency in `specs/004-geoparquet-publication/plan.md` without silently adding unrelated packages.

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Creates the ArcPy-free publication package boundary.
- **Foundational (Phase 2)**: Verifies reader/writer capabilities; resolve any dependency gap
  before story implementation.
- **User Story 1 (Phase 3)**: Depends on Setup and Foundation; produces and validates GeoParquet
  table files but does not expose a complete dataset version.
- **User Story 2 (Phase 4)**: Depends on US1's schemas, conversion, and table-writing capability;
  adds reconciliation, manifests, and atomic exposure.
- **User Story 3 (Phase 5)**: Depends on US2's complete immutable versions; adds pruning and
  compaction.
- **Polish (Phase 6)**: Depends on all selected stories.

### Within Each User Story

- Write and run acceptance tests before implementation.
- In US1, implement models and schemas before conversion and GeoParquet writing.
- In US2, build manifests and validation before reconciliation and atomic exposure.
- In US3, implement origin metadata before compaction.

### Parallel Opportunities

- **US1**: T003, T004, and T005 use separate test files and may be developed in parallel.
  Implementation follows the models → schemas → conversion → writing sequence.
- **US2**: T011, T012, and T013 use separate test files and may be developed in parallel.
  Manifest, validation, reconciliation, and publication implementation follow the data flow.
- **US3**: T019 and T020 use separate test files and may be developed in parallel; T021 must
  precede T022.
- **Across stories**: US2 consumes US1's GeoParquet files, and US3 consumes US2's complete
  immutable versions, so story execution is sequential.

## Parallel Examples

```text
User Story 1:
T003 - test Arrow schemas in testing/test_publication_schema.py
T004 - test conversion in testing/test_publication_conversion.py
T005 - test GeoParquet interoperability in testing/test_publication_interoperability.py

User Story 2:
T011 - test manifests in testing/test_publication_manifest.py
T012 - test validation in testing/test_publication_validation.py
T013 - test publication recovery in testing/test_publication_publish.py

User Story 3:
T019 - test origin pruning in testing/test_publication_pruning.py
T020 - test compaction in testing/test_publication_compaction.py
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundation.
2. Produce canonical, readable GeoParquet dimension and fact files and validate them with PyArrow
   and DuckDB Spatial, including eligibility evidence and the prefilter-pruned-cell case.
3. Do not claim atomic publication or expose a valid `_SUCCESS` until US2 is complete.

### Incremental Delivery

1. Complete US1 for canonical GeoParquet table files and independent reader validation.
2. Complete US2 for reconciliation, manifests, atomic visibility, and completion markers.
3. Complete US3 for origin pruning and immutable compaction.
4. Run the Feature 004 quickstart and relevant repository tests.

## Notes

- `[P]` tasks use separate files and have no unfinished prerequisites.
- User-story labels map directly to the Feature 004 stories in `spec.md`.
- No GeoPandas dependency, import, or usage may be introduced.
- Candidate generation, solve lifecycle, eligibility geometry, and worker scheduling remain
  within Features 002, 003, 001, and 005 respectively.
- Record any required dependency-manifest change for review; do not silently add packages.
