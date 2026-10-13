---

description: "Implementation tasks for Sparse OD Candidates"
---

# Tasks: Sparse OD Candidates

**Input**: Design documents from `specs/002-sparse-od-candidates/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/candidate-planning.md`

**Tests**: Acceptance tests are required by the feature success criteria and Constitution Principle X.
Write each story's tests before its implementation tasks.

**Organization**: Tasks are grouped by user story. All three stories are P1; implementation order
reflects shared candidate-module dependencies, not priority.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with tasks touching different files and having no incomplete dependencies.
- **[Story]**: User-story label for story-phase tasks.
- Every task names the file or files to change or validate.

## Phase 1: Setup

**Purpose**: Establish the import-safe OD package used by the planned portable candidate code.

- [X] T001 Create the import-safe package initializer in `src/h3_route_data_builder/od/__init__.py`.

## Phase 2: Foundational

**Purpose**: Define shared typed records and validation invariants before story-specific behavior.

- [X] T002 Define solvable-cell, candidate-scope, directed-pair, ledger-reference, and summary records with a module logger in `src/h3_route_data_builder/od/models.py`; preserve these data-model validations:
  `h3_id_hex` is a canonical lowercase hexadecimal H3 cell identifier, valid at the build
  resolution and unique after canonicalization; `resolution` matches the build's configured
  resolution; `eligibility_status` must be `solvable`; `cell_geometry` is valid geometry in a
  declared spatial reference; `representative` is present, finite, in WGS 84 / EPSG:4326;
  `mode` is a required supported mode (`aoi_only` or `aoi_to_surrounding`); `aoi_geometry` is
  non-empty, valid, WGS 84 / EPSG:4326; `origin_ids` are unique canonical IDs and each cell
  polygon intersects AOI under the configured policy; AOI-only `destination_ids` equal
  `origin_ids`, while surrounding destinations intersect expanded AOI; `reach_distance` and
  `maximum_origin_offset` are finite, nonnegative geodesic meters, and origin offset is zero
  within AOI; `expanded_aoi` includes the original AOI; origin and destination endpoints
  reference solvable IDs in their respective scope sets; `logical_od_key` is deterministic
  and unique with endpoint order significant; lower-bound units are meters and missing/invalid
  values cannot prune; ledger fingerprint matches compatible evidence, work-unit origin matches
  each expected pair origin, destination batches are deterministic, and expected keys contain no
  duplicates or self/pruned pairs.

**Checkpoint**: Shared OD records are defined; user-story work can begin.

## Phase 3: User Story 1 - Generate AOI-Only Candidates (Priority: P1)

**Goal**: Build the complete directed AOI-only pair universe from in-AOI solvable cells, resolve
self-pairs without route work, and conservatively prefilter non-self pairs.

**Independent Test**: Compare an AOI-only result with an independently enumerated directed product;
verify no invalid endpoints or false-negative prunes, self-pairs incur zero solver calls, actual
network costs determine cutoff inclusion, and reported counts and pruning ratio match their formulas.

### Tests for User Story 1

- [X] T003 [US1] Add AOI-only tests in `testing/test_od_candidates.py` for scope, missing/non-solvable endpoint rejection with reason counts,
  deterministic ordered-key, reverse-direction, duplicate-input, and exactly-one-self-pair/no-solver behavior.
- [X] T004 [US1] Add exhaustive synthetic-route tests in `testing/test_od_candidates.py` for distance and time cutoff reach derivation, zero
  false-negative prefiltering (including route cost equal to cutoff and injected measurement
  errors up to the configured bound), no pruning when the error bound is absent, missing time-speed
  bound and invalid cutoff/configuration rejection, retention when an individual distance
  measurement is unavailable, actual-cost inclusion/equality/exclusion after solve, and
  independently calculated pruning/count metrics with zero-denominator behavior.

### Implementation for User Story 1

- [X] T005 [US1] Implement canonical endpoint validation and deterministic directed AOI-only enumeration in `src/h3_route_data_builder/od/candidates.py`, using ordered `(origin_h3_id, destination_h3_id)` keys.
- [X] T006 [US1] Define optional `network.prefilter_distance_error_bound_m` in `config/config.yml` and validate it in `src/h3_route_data_builder/od/candidates.py`.
  A present negative or non-finite value fails before scheduling; absent bound or invalid
  individual distance retains the pair. Resolve distance cutoffs to meters; derive time reach
  from a documented maximum permitted network speed or reject if no proven bound exists. Compute
  `max(0, measured_distance_m - prefilter_distance_error_bound_m)` and prune only when that is
  strictly greater than reach; retain equality. Classify cutoff after solve using actual cost.
- [X] T007 [US1] Implement candidate/solve summary reconciliation and explicit incomplete outcomes in `src/h3_route_data_builder/od/candidates.py` when resolved build limits are exceeded, reusing the existing resource-limit policy.

**Checkpoint**: AOI-only candidate generation and its prefilter/cutoff behavior pass independently.

## Phase 4: User Story 2 - Include Bounded Surrounding Destinations (Priority: P1)

**Goal**: Use in-AOI solvable cells as origins and include all solvable destination cells whose
polygons intersect the conservatively expanded AOI.

**Independent Test**: With synthetic WGS 84 geometry, verify AOI membership, the expansion by
conservative reach plus maximum nearest-AOI origin offset, inclusive destination polygon
intersection, reach-boundary retention, and clear failure before scheduling when no valid reach
bound exists.

### Tests for User Story 2

- [X] T008 [P] [US2] Add ArcPy geometry tests in `testing/test_od_candidate_geometry.py` for inclusive AOI intersection, geodesic-meter
  nearest-point origin offsets (zero inside, not centroid distance), expanded-AOI destination
  polygon intersection, boundary inclusion, invalid reach rejection, and no self-pairs for
  destination-only cells.

### Implementation for User Story 2

- [X] T009 [US2] Implement AOI validation, solvable-cell selection, nearest-geometry offsets, and geodesic expansion by cutoff reach plus maximum origin offset in `src/h3_route_data_builder/network/geometry.py`, using Feature 001's WGS 84 / EPSG:4326 contract and meters.
- [X] T010 [US2] Implement surrounding destination selection by canonical H3 polygon intersection and directed-pair construction in `src/h3_route_data_builder/od/candidates.py`; include origin-only self-pairs.

**Checkpoint**: AOI-to-surrounding scope is bounded and independently validated before any
candidate is scheduled.

## Phase 5: User Story 3 - Reconcile Candidates with Resumable Work (Priority: P1)

**Goal**: Reconcile retained non-self pair keys with Feature 003 so only absent or invalidated
keys are newly scheduled.

**Independent Test**: Seed compatible committed, absent, invalidated, recoverable, and terminal
ledger entries; assert each retained key is reused, resumed, planned once, or left terminal as
specified, with no duplicate work and exact ledger metrics.

### Tests for User Story 3

- [X] T011 [P] [US3] Add ledger reconciliation tests in `testing/test_od_candidate_ledger.py` for compatible committed reuse, missing and
  invalidated keys, existing recoverable work, terminal failures, changed batch assignment,
  duplicate candidates, and exclusion of self/pruned pairs from route work.

### Implementation for User Story 3

- [X] T012 [US3] Implement the Feature 003 expected-key handoff in `src/h3_route_data_builder/od/candidates.py`: reconcile by ordered pair key independently of
  fingerprint and batch, reuse compatible committed work, resume recoverable work, schedule only
  absent or invalidated retained non-self keys, and leave terminal failures unscheduled unless
  invalidated.
- [X] T013 [US3] Add synthetic Feature 003 solver/ledger handoff and resume tests in `testing/test_od_candidate_ledger.py`: supply actual solved costs below, equal to, and above cutoff; verify over-cutoff results cannot be validated, committed, or published as qualifying facts and estimates are never used as solved costs. Verify resume restores limits/sources, policy version, cutoff/reach, and error bound without recalculation; changed explicit overrides identify a distinct run or fail clearly.
- [X] T014 [US3] Implement post-solve classification and candidate-policy handoff in `src/h3_route_data_builder/od/candidates.py`, reusing saved-limit handling from `src/h3_route_data_builder/eligibility/limits.py`. Provide Feature 003 with cutoff value/units, error bound, resolved limits/sources, and inference-policy version. Classify actual solved costs before validation or commit; ensure candidate policy participates in the behavior fingerprint and Feature 003 manifest/resume interface.

**Checkpoint**: Repeated reconciliation schedules no duplicate logical pair and preserves
Feature 003 lifecycle ownership.

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Keep the acceptance guide aligned with runnable tests and validate all feature paths.

- [X] T015 Add a `get_logger` module logger and structured reconciliation events in `src/h3_route_data_builder/od/candidates.py` for scope, prefilter input/pruned/retained/unbounded-retained counts, ledger reuse/resume/planning/terminal counts, solved results, cutoff exclusions, and every limit's value/source; assert required events and count reconciliation in `testing/test_od_candidates.py` and `testing/test_od_candidate_ledger.py`.
- [X] T016 Update `specs/002-sparse-od-candidates/quickstart.md` with the implemented portable,
  ArcPy geometry, and ledger test commands and expected acceptance outcomes.
- [X] T017 Run the portable candidate and ledger tests in `testing/test_od_candidates.py` and
  `testing/test_od_candidate_ledger.py`, then run the ArcPy geometry tests in
  `testing/test_od_candidate_geometry.py` in the ArcGIS Pro environment; resolve failures without
  changing the specified candidate, cutoff, or ledger contracts. Verify a resumed fixture reuses
  manifest-saved execution limits, sources, inference-policy version, cutoff/reach, and error bound
  without reprobe or recalculation; verify changed explicit overrides select a distinct run or
  fail clearly.

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user-story implementation.
- **User Story 1 (Phase 3)**: Depends on Foundational; establishes shared candidate behavior.
- **User Story 2 (Phase 4)**: Depends on Foundational and the candidate core from User Story 1.
- **User Story 3 (Phase 5)**: Depends on the retained-key and candidate interfaces from User Stories
  1 and 2.
- **Polish (Phase 6)**: Depends on the desired user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Starts after Foundational; no dependency on another story.
- **User Story 2 (P1)**: Uses the pair and summary records from Foundational and integrates with
  User Story 1's candidate planner.
- **User Story 3 (P1)**: Reconciles candidates produced by User Stories 1 and 2; Feature 003
  retains ownership of solving, cutoff-result handoff, manifests, durable states, leases, and
  commits.

### Parallel Opportunities

- T008 and T011 may be authored in parallel after Foundational because they modify separate test
  files and exercise distinct contracts.
- T013 follows the ledger reconciliation coverage in T011 and can be authored independently of
  the ArcPy geometry test T008; it uses a synthetic solver/ledger adapter.
- Within User Story 1, T003 and T004 touch the same test file and should be authored sequentially;
  implementation starts after both tests are in place.
- User Story implementations are sequenced because they extend the shared
  `src/h3_route_data_builder/od/candidates.py` module.

## Parallel Example: User Story 2 and User Story 3 Tests

```text
Task: T008 Add surrounding-scope geometry acceptance tests in testing/test_od_candidate_geometry.py
Task: T011 Add resumable-ledger acceptance tests in testing/test_od_candidate_ledger.py
```

## Implementation Strategy

### MVP First (User Story 1)

1. Complete Setup and Foundational phases.
2. Complete User Story 1, including tests before implementation.
3. Validate AOI-only directed pairs, self-pairs, conservative pruning, actual cutoff handling, and
   reconciled metrics independently.
4. Treat User Story 1 as the first usable increment; do not claim surrounding or resumable behavior
   until those stories pass.

### Incremental Delivery

1. Add User Story 2 to expand destination scope without weakening the conservative reach contract.
2. Add User Story 3 to reconcile all retained candidates with Feature 003's durable work lifecycle.
3. Run the full quickstart acceptance path after all desired stories are complete.
