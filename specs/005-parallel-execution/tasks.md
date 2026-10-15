# Tasks: Parallel Execution

**Input**: Design documents from `specs/005-parallel-execution/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/parallel-execution.md`, and `quickstart.md`

**Tests**: Test tasks are included because the specification requires serial/parallel equivalence,
isolation, lifecycle, probe, fallback, and non-ArcPy validation acceptance coverage.

**Organization**: Tasks are grouped by user story. Feature 003 owns durable lifecycle actions;
Feature 005 work must use its coordinator/ledger contracts without adding a parallel state machine.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different files and no dependency on incomplete tasks
- **[Story]**: User story traceability label (`US1` through `US4`)
- Every task names the source, test, configuration, or documentation file it changes.

## Phase 1: Setup

**Purpose**: Add the execution settings surface without changing candidate, ledger, or publication
configuration.

- [X] T001 Add the `parallel_solving` settings section to `config/config.yml` with `enabled: null`, a positive bounded `max_workers` default of 2, and positive bounded probe-timeout and graceful-shutdown settings; document that only explicit `false` disables parallel network solving, not eligible non-ArcPy preparation.

## Phase 2: Foundational

**Purpose**: Provide validated, portable execution policy and transient record types used by the
stories. Complete this phase before user-story implementation.

- [X] T002 Add ArcPy-free tests for absent, null, true, and false enablement; valid and invalid limits; configured worker ceilings below and above CPU count; and unavailable CPU count resolving to one in `testing/test_od_execution_config.py`.
- [X] T003 Implement validated parallel execution configuration loading and policy records in `src/h3_route_data_builder/od/execution.py`; treat absent or null `parallel_solving.enabled` as enabled, explicit `false` as disabled, reject invalid worker/time limits, and resolve ArcPy processes to `min(max_workers, os.cpu_count() or 1)`.
- [X] T004 Define serializable coordinator assignment, worker result, probe attempt/report, and execution summary records in `src/h3_route_data_builder/od/execution.py`; include Feature 003 work identity, compatibility, attempt, lease/fencing evidence, expected keys, effective mode, fallback reason, and reconciled counts without creating new durable ledger states.
- [X] T005 Verify the shared assignment/result records can be serialized and that importing `h3_route_data_builder.od.execution` does not import ArcPy in `testing/test_od_execution_config.py`.
- [X] T006 Add tests using existing Feature 003 bounded work items and Feature 001 representative inputs to verify immutable serializable payload normalization, preserved identities/keys/order, no ledger mutation or candidate selection, at most two active preparation units, at most two prepared payloads waiting for lease/dispatch, streaming/backpressure without full-plan materialization, and explicit failure reporting in `testing/test_od_execution_preparation.py`.
- [X] T007 Implement streamed deterministic non-ArcPy normalization of existing work items and representative inputs into immutable serializable solve payloads in `src/h3_route_data_builder/od/preparation.py`; preserve identities, expected keys, batch membership, and canonical order; run at most two preparation units concurrently and buffer at most two completed payloads awaiting lease/dispatch; apply backpressure instead of materializing the full plan; perform no candidate selection or ledger mutation; and report failures explicitly to the coordinator.

**Checkpoint**: Configuration and CPU-resolved worker ceilings, portable execution records, and
parallel non-ArcPy preparation for serial-solve modes are validated; Feature 001–004 ownership
remains unchanged.

## Phase 3: User Story 1 - Preserve a Serial Reference Run (Priority: P1)

**Goal**: Make serial execution an independently testable correctness reference using the same
bounded work items and Feature 003 acceptance lifecycle that parallel execution will use.

**Independent Test**: Run a bounded fixture through serial mode and verify expected logical keys,
per-key classifications and costs, ledger dispositions, and authoritative published logical rows
against fixture expectations.

### Tests for User Story 1

- [X] T008 [US1] Add serial reference tests for bounded work, expected directed keys, solve classifications, canonical costs, Feature 003 committed outcomes, and the authoritative Feature 004 publication handoff in `testing/test_od_execution.py`.
- [X] T009 [US1] Add zero-work, explicit serial-mode, and `parallel_solving.enabled: false` tests in `testing/test_od_execution.py`; verify zero work starts no probe or solve worker, explicit serial/disabled modes start no probe or concurrent ArcPy workers, and preparation runs concurrently for at least two eligible units while respecting T007's active and buffered-payload bounds.

### Implementation for User Story 1

- [X] T010 [US1] Implement the serial execution entry point in `src/h3_route_data_builder/od/execution.py`; consume normalized work inputs from T007 through an internal solver adapter, then invoke the existing `solve_work_item` lifecycle in `src/h3_route_data_builder/od/solving.py` without changing its public signature or serial outcome behavior.
- [X] T011 [US1] Return a serial execution summary from `src/h3_route_data_builder/od/execution.py` with requested/effective mode, assignment counts, fallback status, and Feature 003 reconciliation counts without treating process status or filenames as completion.

**Checkpoint**: Serial reference mode passes independently and leaves existing Feature 003 durable state and Feature 004 publication semantics intact.

## Phase 4: User Story 2 - Execute Network Solves in Isolated Processes (Priority: P1)

**Goal**: Run bounded ArcPy solve work in spawned processes while leaving lease authority,
acceptance, and commit with the coordinator.

**Independent Test**: Dispatch multiple small work units and verify distinct worker scratch,
serializable assignments with current Feature 003 fencing evidence, exact-key result acceptance,
and no worker writes to the ledger or final partitions; compare logical results with serial mode.

### Tests for User Story 2

- [X] T012 [P] [US2] Add serial-versus-parallel logical equivalence tests comparing directed key sets, endpoint identities, outcome classifications, units, and canonical costs in `testing/test_od_execution.py`.
- [X] T013 [P] [US2] Add spawned-worker tests for bounded assignments, unique per-attempt scratch directories/geodatabases, coordinator-only lease/commit actions, and rejection of missing, duplicate, unexpected, and stale-fenced keys in `testing/test_od_execution_workers.py`.

### Implementation for User Story 2

- [X] T014 [P] [US2] Add an importable module-level worker entry point in `src/h3_route_data_builder/network/solver.py` that initializes ArcPy/Network Analyst in the child process, accepts only serializable bounded solve inputs, and writes only to its unique supplied scratch directory.
- [X] T015 [P] [US2] Extract or add a coordinator-side result acceptance helper in `src/h3_route_data_builder/od/solving.py` that stages, validates, and commits worker outcomes through the current Feature 003 lease and fencing evidence while preserving `solve_work_item`'s public signature.
- [X] T016 [US2] Implement bounded spawned-process dispatch in `src/h3_route_data_builder/od/execution.py`; consume normalized work inputs from T007, then have the coordinator acquire/renew Feature 003 leases, bind current fencing evidence, bound in-flight assignments by effective worker capacity, accept results through T015, and keep workers away from ledger and publication writes.

**Checkpoint**: Worker processes are isolated and bounded; only coordinator-accepted Feature 003 commits count as results.

## Phase 5: User Story 3 - Probe Capability and Fall Back Safely (Priority: P1)

**Goal**: Authorize parallel solves only after bounded evidence from the configured network and
license environment, then visibly recover through serial execution when parallel execution fails.

**Independent Test**: Inject success and each specified probe/runtime failure; verify descending
probe levels choose the highest passing concurrency or serial fallback, and that no failed,
stale, or unresolved logical key is reported successful.

### Tests for User Story 3

- [X] T017 [US3] Add capability-probe tests for successful requested concurrency, CPU-resolved worker ceilings, a ceiling below two with probe skipped and observable serial reason, step-down to a lower passing count, failure at every count of at least two, missing safe probe inputs, and structured failure reasons in `testing/test_od_execution_probe.py`; verify that exhausting probe levels falls back to serial solving while preparation remains concurrent for at least two eligible units and respects its active/buffer bounds.
- [X] T018 [US3] Add runtime tests for initialization, license, lock, crash, timeout, cancellation, and serial-retry outcomes; assert dispatch stops, incomplete work is fenced or expires, stale output is rejected, non-ArcPy preparation remains parallel during runtime serial fallback, prepared-payload buffering remains bounded, and summary counts reconcile in `testing/test_od_execution_probe.py`.
- [X] T019 [P] [US3] Add ArcPy-marked integration coverage for actual configured network access, per-child Network Analyst license access, bounded probe solving, and non-authoritative temporary probe output in `testing/test_real_network_dataset.py`.

### Implementation for User Story 3

- [X] T020 [P] [US3] Implement the descending capability-probe policy in `src/h3_route_data_builder/od/execution.py`; skip probing and select serial mode with a structured reason when the CPU-resolved ceiling is below two, otherwise probe from that ceiling down to two and select the highest passing count or serial mode with a structured failure reason.
- [X] T021 [P] [US3] Implement probe child execution in `src/h3_route_data_builder/network/solver.py` using isolated temporary scratch, actual configured network/Network Analyst access, bounded representative solves, and no Feature 003 or Feature 004 writes.
- [X] T022 [US3] Implement runtime failure and cancellation handling in `src/h3_route_data_builder/od/execution.py`; stop dispatch, request bounded shutdown, fence or expire incomplete leases, retry eligible assignments serially using the parallel preparation helper from T007, accept completed output only under current fencing checks, and report serial recovery failure visibly.
- [X] T023 [US3] Record requested/effective mode, configured and CPU-resolved worker ceilings, probe attempts, selected concurrency, fallback reason, assignment outcomes, preparation outcomes, and Feature 003 reconciled counts in `src/h3_route_data_builder/od/execution.py` and emit the report through the module logger.

**Checkpoint**: Probe and runtime instability lead to explicit tested fallback, and Feature 003 remains the only durable completion authority.

## Phase 6: User Story 4 - Parallelize Safe Non-Spatial Work (Priority: P2)

**Goal**: Concurrently perform independent checks over immutable publication artifacts, while
keeping candidate planning, reconciliation, and publication coordinator-owned. Bounded
non-ArcPy preparation is implemented as a shared foundational capability for serial-solve modes.

**Independent Test**: Compare serial and concurrent per-artifact validation results and diagnostics;
verify aggregate key reconciliation and Feature 004 atomic publication still reject incomplete or
inconsistent output.

### Tests for User Story 4

- [X] T024 [US4] Add tests comparing serial and bounded concurrent per-part integrity, schema, and row-count validation results and surfaced failures in `testing/test_publication_validation.py`.

### Implementation for User Story 4

- [X] T025 [US4] Parallelize only independent immutable-part checks in `src/h3_route_data_builder/publication/validation.py`; retain deterministic result ordering and keep aggregate logical-key reconciliation, manifest decisions, and atomic publication coordinator-owned.
- [X] T026 [US4] Ensure a failed concurrent per-part validation is explicitly returned to the publication owner and blocks successful aggregate validation in `src/h3_route_data_builder/publication/validation.py`.

**Checkpoint**: Independent artifact checks may complete out of order without changing canonical validation results or publication visibility.

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verify boundaries, docs, quickstart commands, and regression behavior.

- [X] T027 [P] Update `specs/005-parallel-execution/quickstart.md` with final focused test names, runtime prerequisites, and expected outcomes as implemented.
- [X] T028 [P] Verify portable execution/configuration/preparation modules remain ArcPy-free and Feature 005 adds no GeoPandas import or dependency in `testing/test_od_execution_config.py`, `testing/test_od_execution_preparation.py`, and the project dependency manifests `pyproject.toml` and `environment.yml`.
- [X] T029 Run the focused Feature 005 commands in `specs/005-parallel-execution/quickstart.md`, then run `pytest`; record failures explicitly and do not treat unavailable ArcPy/network/license integration prerequisites as passing probe evidence.

  - Validation: focused suite passed (91 tests); the full suite ran 237 tests (236 passed, 1 failed). The failure is `testing/test_real_network_dataset.py::test_streetmap_network_builds_reconciled_small_aoi_without_source_edits`, where `caplog.text` is empty although the expected execution-limit message appears in captured stdout.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; adds the configuration section.
- **Foundational (Phase 2)**: Depends on setup; blocks all user-story phases.
- **User Story 1 (Phase 3)**: Depends on the foundational policy and portable records.
- **User Story 2 (Phase 4)**: Depends on US1's serial reference and shared coordinator acceptance lifecycle.
- **User Story 3 (Phase 5)**: Depends on US2's process dispatch and result-return path.
- **User Story 4 (Phase 6)**: Depends on the foundational bounded execution policy; its per-artifact
  checks do not take over candidate, reconciliation, or publication ownership. Its deterministic
  preparation capability is foundational because serial network-solve fallback depends on it.
- **Polish (Phase 7)**: Depends on all desired stories being implemented.

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2; establishes serial execution using the foundational
  preparation helper.
- **US2 (P1)**: Starts after US1; adds isolated execution and serial/parallel equivalence.
- **US3 (P1)**: Starts after US2; probes and recovers the implemented parallel process path.
- **US4 (P2)**: Its shared preparation prerequisite is completed in Phase 2; the remaining
  publication-validation tasks may proceed after Phase 2 independently of US1–US3 because they
  edit `publication/validation.py`, not `od/execution.py`. Final cross-story regression waits for
  all stories.

### Parallel Opportunities

- **Foundational**: T006 must precede T007; preparation behavior is available before serial fallback
  is implemented.
- **US1**: No story tasks are safely parallelizable: T008/T009 share a test file and T010/T011
  share the execution module.
- **US2**: T012 and T013 can be authored in parallel because they target separate test files.
  Worker entry-point work T014 and shared acceptance helper T015 can be developed in parallel
  because they target separate modules; coordinator integration T016 follows T015.
- **US3**: T017/T018 target the same probe test file and are sequential; T019 targets a separate
  ArcPy-marked test file and can be authored in parallel. Probe policy T020 and child probe
  execution T021 target separate modules and can proceed in parallel against the documented
  contract. Runtime integration T022 and reporting T023 follow.
- **US4**: T024 precedes T025 and T026; all three target the same validation test or module and
  should be completed sequentially.
- **Polish**: T027 can be performed independently of the source-boundary audit T028; T029 follows
  implementation and doc updates.

## Parallel Examples by User Story

### User Story 1

No story tasks are safely parallelizable: tests share `testing/test_od_execution.py`, and the
entry point and summary share `src/h3_route_data_builder/od/execution.py`.

### User Story 2

```text
After the US1 serial path is complete, author these independent test files in parallel:
Task: T012 - Add serial/parallel equivalence tests in testing/test_od_execution.py
Task: T013 - Add worker isolation/fencing tests in testing/test_od_execution_workers.py

After the assignment/result contract is fixed, worker and shared acceptance implementation can be split:
Task: T014 - Add child-process worker entry point in src/h3_route_data_builder/network/solver.py
Task: T015 - Add shared result acceptance in src/h3_route_data_builder/od/solving.py
Then integrate bounded coordinator dispatch through T016.
```

### User Story 3

```text
Author portable probe tests and ArcPy-marked integration coverage in parallel:
Task: T017 - Add probe policy tests in testing/test_od_execution_probe.py
Task: T019 - Add configured network/license integration coverage in testing/test_real_network_dataset.py

After the probe contract is fixed, implement coordinator policy and child probe execution in parallel:
Task: T020 - Implement descending probe policy in src/h3_route_data_builder/od/execution.py
Task: T021 - Implement child probe execution in src/h3_route_data_builder/network/solver.py
```

### User Story 4

```text
The deterministic non-ArcPy preparation helper is delivered in Phase 2 for serial-solve fallback.
The remaining artifact-validation tasks share one module and therefore run sequentially:
Task: T024 - Add per-part validation tests in testing/test_publication_validation.py
Task: T025 - Parallelize immutable-part checks in src/h3_route_data_builder/publication/validation.py
Task: T026 - Ensure failed parallel checks block aggregate validation in src/h3_route_data_builder/publication/validation.py
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 configuration setup and Phase 2 portable execution foundations, including
   CPU-resolved worker limits and parallel non-ArcPy preparation for serial-solve modes.
2. Complete US1 serial reference mode using the existing Feature 003 solve lifecycle.
3. Validate bounded work, expected keys, ledger outcomes, zero-work behavior, and serial reporting.
4. Stop and review serial correctness before adding concurrent ArcPy processes.

### Incremental Delivery

1. Add US2 spawned worker isolation and coordinator-only result acceptance; prove serial/parallel
   logical equivalence.
2. Add US3 real capability probing, bounded step-down, observable fallback, cancellation, and
   recovery; verify against injected failures and configured ArcPy integration.
3. Add US4 independent immutable-artifact checks without changing aggregate publication behavior.
4. Complete Phase 7 boundary audits and regression tests.

### Story Completion Criteria

- **US1**: Independent bounded serial fixture agrees with expected keys, costs, classifications,
  and Feature 003 durable dispositions.
- **US2**: Serial and parallel logical outputs are equivalent; scratch is unique; workers cannot
  lease, reconcile, validate, commit, or publish.
- **US3**: Probe step-down and every specified failure category are tested; fallback is visible;
  no unresolved or stale result is counted as success.
- **US4**: Concurrent per-artifact checks match serial diagnostics, while coordinator candidate
  planning, aggregate validation, and atomic publication retain ownership and reject
  invalid/incomplete artifacts. Preparation equivalence and fallback behavior are covered by
  foundational tasks T006–T007 and runtime task T018.
