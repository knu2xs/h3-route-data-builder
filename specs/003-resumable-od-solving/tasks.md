# Tasks: Resumable OD Solving

**Input**: Design documents from `/specs/003-resumable-od-solving/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/solver-ledger.md,
quickstart.md

**Tests**: Required by the specification for restart boundaries, lease expiry/reclaim,
stale-worker rejection, invalid staged output, and compatible AOI-expansion reuse.

**Organization**: Tasks are grouped by the three P1 user stories in `spec.md`.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work in separate files.
- **[Story]** maps to a user story in `spec.md`.
- Every task is a single checklist line and includes its target file path.

## Phase 1: Setup

**Purpose**: Preserve the feature's storage-engine-neutral contract while capturing implementation
constraints for a durable ledger.

- [X] T001 Document the backend-neutral atomic commit, key-claim, and durability requirements and any ArcGIS Pro compatibility constraints in `specs/003-resumable-od-solving/research.md`; leave the storage engine unselected unless implementation evidence shows a choice is necessary, and justify any dependency before changing `pyproject.toml` or `environment.yml`.

---

## Phase 2: Foundational

**Purpose**: Establish portable records and result compatibility identity for all user stories.

- [X] T002 [P] Define `WorkState`, `WorkItem`, `Lease`, and failure-evidence records in `src/h3_route_data_builder/od/ledger.py`; validate unique expected keys, matching work origin, non-empty lease owner, and finite lease expiry.
- [X] T003 [P] Implement a versioned result-compatibility fingerprint in `src/h3_route_data_builder/od/results.py`; include result-affecting inputs and exclude AOI coverage, batch boundaries, execution limits, and candidate-planning provenance.

**Checkpoint**: Portable lifecycle records and compatibility identity are available before user-story implementation.

---

## Phase 3: User Story 1 - Resume Interrupted Route Work (Priority: P1) 🎯 MVP

**Goal**: Durable work resumes at every lifecycle boundary without losing committed outcomes,
creating duplicate active keys, or accepting stale worker output.

**Independent Test**: Interrupt a known expected-key set after every durable boundary, restart,
and compare reconciled outcomes with an uninterrupted reference run.

### Tests for User Story 1

- [X] T004 [US1] Add portable lifecycle and fault-injection tests in `testing/test_od_ledger.py` for legal transitions and restart after planned, leased, solving, staged, validated, immutable-part write, and commit acknowledgement; on restart revalidate staged artifacts against fingerprint, accepted fencing evidence, expected keys, and outcome validity, committing valid stages once and returning invalid stages to retry without authority.
- [X] T005 [US1] Add lease and stage-validation tests in `testing/test_od_ledger.py` for expiry/reclaim, stale fencing, missing/duplicate/unexpected/invalid staged outcomes, and idempotent commit recovery.

### Implementation for User Story 1

- [X] T006 [US1] Implement durable work persistence, legal transitions, attempt/provenance recording, and deterministic work IDs in `src/h3_route_data_builder/od/ledger.py`; derive IDs from compatibility fingerprint, origin, and canonical bounded destination batch.
- [X] T007 [US1] Implement lease acquisition, renewal, expiry, and reclaim in `src/h3_route_data_builder/od/ledger.py`; advance the fencing value on reclaim, reject stale mutations, and route expired work through retryable or terminal failure under the bounded retry policy.
- [X] T008 [US1] Implement coordinator-only stage validation and atomic commit in `src/h3_route_data_builder/od/ledger.py`; require exact expected-key equality, reject invalid staged outcomes, keep parts immutable, and make identical commits idempotent.
- [X] T009 [US1] Run and fix `testing/test_od_ledger.py`; verify every injected restart yields zero lost results and zero duplicate authoritative logical keys.

**Checkpoint**: The serial ledger lifecycle can plan, lease, recover, validate, and commit work.

---

## Phase 4: User Story 2 - Account for Every Solve Outcome (Priority: P1)

**Goal**: Each expected key receives a durable route, unroutable, cutoff, or system-failure
disposition; only qualifying actual network costs become route facts.

**Independent Test**: Exercise success, unlocated, unreachable, over-cutoff, transient failure, and
exhausted-retry cases with a bounded synthetic batch; reconcile every expected key.

### Tests for User Story 2

- [X] T010 [P] [US2] Add portable outcome and coordinator tests in `testing/test_od_solver.py` for actual-cost cutoff classification, unroutable diagnostics, retryable/terminal failures, invalid cost/units, representative handoff, and isolated scratch; mark only ArcPy-dependent cases.

### Implementation for User Story 2

- [X] T011 [P] [US2] Implement outcome classification and validation in `src/h3_route_data_builder/od/results.py`; require finite nonnegative actual costs in configured units, exclude unlocated/unreachable/cutoff-excluded cases from qualifying facts, and keep system failures as work failures.
- [X] T012 [P] [US2] Implement the ArcPy/Network Analyst solve adapter in `src/h3_route_data_builder/network/solver.py`; solve directed expected keys using Feature 001 deterministic representatives and isolated temporary output, without writing to source network data or shared final output.
- [X] T013 [US2] Implement serial solve coordination in `src/h3_route_data_builder/od/solving.py`; connect Feature 002 batches, the ledger, and solver, and have the coordinator validate and commit actual-cost-classified results.
- [X] T014 [US2] Run and fix `testing/test_od_solver.py`; verify portable and mocked adapter tests, and run its real Network Analyst smoke test when `H3_RDB_TEST_NETWORK` is configured.

**Checkpoint**: Every expected key has an explicit solve classification or durable failure evidence.

---

## Phase 5: User Story 3 - Expand Coverage Without Repeating Compatible Work (Priority: P1)

**Goal**: AOI expansion reuses compatible committed keys and schedules only new or explicitly
invalidated expected keys, independent of prior work-item or batch identity.

**Independent Test**: Compare expected dispositions for an original and expanded AOI with compatible
commits, changed batch/provenance, new keys, invalidations, and incompatible result fingerprints.

### Tests for User Story 3

- [X] T015 [P] [US3] Add AOI-expansion and reconciliation tests in `testing/test_od_candidate_ledger.py` for compatible logical-key reuse across changed AOI/batches/limits, one-time scheduling of missing or invalidated keys, terminal-failure retention, and incompatible-fingerprint rejection; independently enumerate expected keys and assert each is counted exactly once, zero-candidate plans reconcile successfully, and reconciled-with-failures differs from all-success completion.

### Implementation for User Story 3

- [X] T016 [P] [US3] Update reconciliation in `src/h3_route_data_builder/od/candidates.py` to reuse compatible committed evidence by logical key across prior work IDs/batches, schedule each missing expected key once, account for every expected key exactly once, and distinguish reconciled-with-failures from all-success completion without changing Feature 002 candidate selection or batching.
- [X] T017 [P] [US3] Implement explicit invalidation and rescheduling in `src/h3_route_data_builder/od/ledger.py`; withdraw outcomes from authority without editing immutable parts, fence in-flight leases, and schedule still-expected invalidated work exactly once.
- [X] T018 [US3] Run and fix `testing/test_od_candidate_ledger.py`; verify compatible overlap reuse, new/invalidated key scheduling, terminal failures, and incompatible-result rejection.

**Checkpoint**: AOI expansion reuses compatible route outcomes by logical key, not by filename or batch.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Keep acceptance guidance executable and verify the cross-feature handoff.

- [X] T019 Update `specs/003-resumable-od-solving/quickstart.md` with implemented portable and ArcGIS Pro test paths, prerequisites, restart boundaries, and expected reconciliation assertions.
- [X] T020 Run the acceptance commands in `specs/003-resumable-od-solving/quickstart.md` and `testing/test_od_candidate_ledger.py`; verify portable tests pass, the real-network smoke test runs when configured (otherwise reports its prerequisite skip), and Features 002/004 ownership contracts remain unchanged.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 selects and documents an implementation with durable atomic key
  claims; no ledger implementation begins before that decision.
- **Foundational (Phase 2)**: T002 and T003 depend on T001 and are independent because they edit
  separate files. Both block user stories.
- **User Stories (Phases 3-5)**: US1 depends on Phase 2. US2 and US3 depend on US1's ledger and
  commit behavior; after US1, they can proceed in parallel.
- **Polish (Phase 6)**: Depends on all selected user stories.

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2; independent of other stories and is the MVP.
- **US2 (P1)**: Depends on US1's durable ledger, stage validation, and commit path.
- **US3 (P1)**: Depends on US1's durable ledger and commit path; can run alongside US2 after US1.

### Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- After US1, US2 and US3 can proceed in parallel; their acceptance tests and main implementation
  files are separate.
- Within US2, T011 and T012 can run in parallel after T010; T013 integrates both.
- Within US3, T016 and T017 can run in parallel after T015 because they update separate modules.
- T019 may be prepared alongside story implementation; T020 waits for completed implementation
  and the quickstart update.

### Parallel Example: User Stories 2 and 3

```text
After Phase 3 (US1) is complete:

Developer A: T010 -> T011 + T012 -> T013 -> T014
Developer B: T015 -> T016 + T017 -> T018
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete setup and foundational identity/state records.
2. Implement the durable lifecycle, leases/fencing, stage validation, and atomic idempotent
   commit.
3. Run `pytest testing/test_od_ledger.py -q` and verify restart recovery at every durable
   boundary.
4. Stop and validate the ledger contract before adding network solve orchestration.

### Incremental Delivery

1. Deliver US1 as the durable lifecycle MVP.
2. Add US2 for solve outcome classification and serial network solving.
3. Add US3 for compatible reuse during AOI expansion and explicit invalidation.
4. Run the focused Feature 003 and Feature 002 acceptance commands in `quickstart.md`.

### Parallel Team Strategy

Complete setup, foundational records, and US1 first. Then implement US2's result/solver path and
US3's candidate-reconciliation/invalidation path in parallel, integrating through the
solver-ledger contract before the final acceptance suite.
