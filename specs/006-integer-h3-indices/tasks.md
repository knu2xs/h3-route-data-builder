# Tasks: Integer H3 Index Standardization

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contract](contracts/integer-h3-index-contract.md),
and [quickstart.md](quickstart.md).

**Prerequisites**: Read the project constitution and applicable instructions before implementation.
Preserve existing unrelated worktree changes. The active feature is `006-integer-h3-indices`;
Git currently remains on `main`.

**Tests**: Acceptance tests are explicitly required by the specification's scenarios and success
criteria. Write or update them before implementation and establish the expected failing assertions.
Use existing runners and dependencies; this feature does not introduce packages.

**Organization**: Two P1 stories. US1 establishes integer-only processing; US2 integrates durable
state and publication. SQLite remains the ledger engine. A DuckDB backend replacement, migration,
mobile application, and numeric performance target are outside scope.

## Format and Path Conventions

- Each task uses `- [ ] Tnnn [P?] [USn?] Description`.
- `[P]` identifies disjoint work that can run concurrently after the prerequisites below are met.
- Paths are repository-relative and use Windows separators for execution.
- Story labels appear only in story phases. All checkboxes are initially unchecked.
- Exact field/domain constraints are quoted in the tasks that implement them.
- Existing helpers and module layouts are preferred; no parallel identity subsystem is added.

## Phase 1: Setup

**Purpose**: Establish safe, reproducible test inputs and a pre-change behavioral baseline.

- [X] T001 Establish the configured interpreter, targeted baseline results, and fixed pre-change candidate/route expectations using `testing\test_od_candidates.py`, `testing\test_od_solver.py`, `testing\test_real_network_dataset.py`, and the commands in `specs\006-integer-h3-indices\quickstart.md`; record existing failures and unavailable ArcPy/license prerequisites separately from feature failures.
- [X] T002 Add reusable portable valid integer H3 fixtures in `testing\conftest.py` using `h3.api.basic_int`, including resolutions 0-15, pentagon and high-value valid cells above `2^53`, directed reverse pairs, self-pairs, and deliberately invalid values; retain unrelated fixtures and do not weaken production validation to allow symbolic string endpoints.

## Phase 2: Foundational Prerequisites

**Purpose**: Establish the one portable validator used by both stories.

- [X] T003 Add canonicalization, covering, and boundary acceptance tests in `testing\test_eligibility_cells.py` for exact Python integers, numeric ordering/deduplication, valid cells across resolutions 0-15, greatest valid conformance samples, and rejection of hex/decimal strings, booleans, floats, nulls, negative values, invalid cell bits, `0`, `2^64 - 1`, and overflow; test covering's existing resolution argument for invalid range, but leave expected-cell-resolution mismatch tests to configured callers in T005-T006; test without importing ArcPy.
- [X] T004 Update existing helpers in `src\h3_route_data_builder\eligibility\cells.py` to use `h3.api.basic_int` and reuse shared validation; enforce exact integer type, uint64 range, and valid H3 cell identity, reject booleans before H3 calls, and return numerically sorted/deduplicated Python integers with explicit logged validation errors and updated type hints/docstrings; preserve public parameter lists, keep canonicalization resolution-independent, and validate covering's existing resolution argument.

**Checkpoint**: T003 passes against T004 without ArcPy; no textual alias is accepted.

## Phase 3: US1 - Use One Exact H3 Index Representation (Priority: P1)

**Goal**: Carry integers through eligibility, candidate planning, representatives, directed keys,
and solve/preparation boundaries without changing cell membership or solve semantics.

**Independent test**: Exercise in-memory eligibility, candidate and solver-adapter paths with valid
integer fixtures; assert invalid inputs fail before scheduling, permutation invariance, reverse-key
distinction, unchanged representatives/costs/classifications, and exact adapter round-trips.
This checkpoint does not yet claim durable/publication conformance or release readiness.

### Acceptance Tests

- [X] T005 [P] [US1] Update `testing\test_eligibility_rules.py` to assert integer-only eligibility results and reconciliation identities, unchanged solvable membership/reasons/tie-breaking, rejection of invalid types/resolutions, and canonical field name `h3_id` without alternate fields.
- [X] T006 [P] [US1] Update `testing\test_od_candidates.py` to assert integer scopes/directed endpoints, input permutation/deduplication invariance, distinct reverse keys, zero-cost self-pairs, unchanged pruning and batching, and rejection before planning for invalid cell identity or resolution.
- [X] T007 [P] [US1] Update `testing\test_eligibility_geometry.py`, `testing\test_network_eligibility.py`, and `testing\test_od_candidate_geometry.py` to compare integer-indexed covers, polygons, centroids, and representatives with the fixed baseline; keep spatial checks ArcPy-marked and isolated from portable tests.
- [X] T008 [P] [US1] Add adapter tests in `testing\test_od_solver.py` for opaque Network Analyst labels mapping back to integer route and location-status endpoints, exact values above `2^53`, missing/unknown/duplicate label rejection, and unchanged unlocated/unreachable/cutoff/system outcome classification; add portable `test_integer_payload_*` tests in `testing\test_od_execution_preparation.py` and `testing\test_od_execution_workers.py` for prepared assignments, integer representative maps/expected keys, and spawn serialization round-trips above `2^53`, without opening a ledger or invoking ArcPy.

### Models and Implementation

- [X] T009 [P] [US1] Replace representation-specific H3 fields with integer `h3_id` in `src\h3_route_data_builder\eligibility\models.py`, and update `src\h3_route_data_builder\eligibility\engine.py` and `src\h3_route_data_builder\eligibility\reconcile.py`; validate cells at existing input boundaries, explicitly compare cell resolution to configured eligibility resolution before use, and preserve all statuses, evidence, geometry references, and representative policy.
- [X] T010 [P] [US1] Update `src\h3_route_data_builder\od\models.py` and `src\h3_route_data_builder\od\candidates.py` to enforce "Canonical integer referencing an eligible solvable cell" for both endpoints and "Ordered integer pair; direction is significant" for keys; compare cell resolution to configured candidate resolution before scheduling, use `h3_id`, `origin_h3_id`, and `destination_h3_id`, numeric ordering, and unchanged candidate modes, pruning, self-pairs, batch policy, and counters.
- [X] T011 [US1] Update H3 calls and cell-keyed geometry/location maps in `src\h3_route_data_builder\network\geometry.py`, `src\h3_route_data_builder\network\eligibility.py`, `src\h3_route_data_builder\network\representatives.py`, and `src\h3_route_data_builder\network\locations.py` to integer identity; retain ArcPy geometry operations, CRS handling, representative selection, and source/OID tie-breaking.
- [X] T012 [US1] Update solve outcome/key models and strict dictionary deserialization in `src\h3_route_data_builder\od\results.py` to integer directed keys, rejecting textual/coerced endpoints instead of `str(endpoint)` reconstruction; preserve non-H3 opaque identifiers, costs, outcome fields, and classifications.
- [X] T013 [US1] Implement assignment-local opaque text label maps in `src\h3_route_data_builder\network\solver.py` for point creation, location-status reads, and route result reads; resolve/validate labels to integer keys immediately, fail explicitly for invalid mappings, and never transport H3 identity through floating-point geodatabase fields.
- [X] T014 [US1] Update prepared assignments, representative lookups, expected keys, and spawn payload types in `src\h3_route_data_builder\od\preparation.py`, `src\h3_route_data_builder\od\execution.py`, and `src\h3_route_data_builder\od\solving.py`; retain coordinator ownership, isolated scratch, bounded execution, serial reference/probe/fallback, and non-H3 IDs.
- [X] T015 [US1] Wire integer candidate/result/representative maps and numeric H3 diagnostics through `src\h3_route_data_builder\network\workflow.py`; use the integer H3 API where needed while retaining top-level package version reporting, and preserve input, limit, eligibility, and toolbox behavior.
- [X] T016 [US1] Run T003 and the in-memory/adapter acceptance selections from T005-T008 using `specs\006-integer-h3-indices\quickstart.md`; verify the fixed candidate/representative/route expectations, integer-only model and spawn payload round-trips, and ArcPy-free imports, while deferring ledger/publication integration assertions to US2.

**Checkpoint**: US1's independent integer-processing tests pass. US2 is still required for
complete persisted state and publication; do not expose mixed-format output as conformant.

## Phase 4: US2 - Exchange and Resume Integer-Keyed Data (Priority: P1)

**Goal**: Store and recover integer work exactly, reject old working state without mutation,
publish versioned uint64 tables, and establish explicit shared-consumer release evidence.

**Independent test**: From a fresh temporary ledger, solve/restart/reconcile a fixture and publish
it. Inspect SQLite integer storage, numeric JSON, required uint64 columns and schema versions;
reject old ledgers/stages before reuse, preserve legacy bytes and publications, and prove exact
Arrow/DuckDB reads, pruning, compaction, and logical-key uniqueness.

### Acceptance Tests

- [X] T017 [P] [US2] Update `testing\test_od_ledger.py` with actual integer endpoints and tests for SQLite `typeof='integer'`, strict JSON reload, stable version-2 work IDs, incompatibility with old encodings, read-only rejection of TEXT/missing-version/inconsistent schemas before WAL/schema changes, and interruption recovery at plan, lease, solve, stage, validate, and commit boundaries; verify lease reclaim/fencing, stale-worker rejection, invalid staged keys, and no duplicate/missing logical results.
- [X] T018 [P] [US2] Update `testing\test_od_candidate_ledger.py` to prove fresh integer-ledger rebuilding does not count abandoned hex work as reused, compatible new-format AOI expansion reuses completed logical pairs and schedules only new/invalidated pairs, and input permutation preserves work identity and reconciliation.
- [X] T019 [P] [US2] Update `testing\test_eligibility_fingerprint.py`, `testing\test_eligibility_run_state.py`, `testing\test_eligibility_staging.py`, and `testing\test_eligibility_output.py` to assert schema-2 fingerprints, exact uint64 staged/output cells, numeric JSON record arrays, and rejection/non-adoption of old stages and completed summaries during restart; author fresh-build/restart/rebuild tests in `testing\test_network_eligibility.py` and integer-output assertions in `testing\test_real_network_dataset.py` before storage/workflow changes, proving no legacy work reuse or mutation and baseline real-network parity when prerequisites exist.
- [X] T020 [P] [US2] Update `testing\test_publication_schema.py` and `testing\test_publication_conversion.py` to require non-null uint64 `h3_id`, `origin_h3_id`, and `destination_h3_id`, no `_hex`/`_uint64` aliases, dataset/cell/fact `2.0.0`, unchanged GeoParquet `1.1.0`/geometry/CRS/non-index fields, and invalid endpoint/type rejection; author the shared conformance fixture/reader tests in `testing\test_publication_interoperability.py` before publication changes, covering exact Arrow/DuckDB values above `2^53`, reverse/self keys, numeric manifest origins, unchanged geometry/costs, and historical schema distinction.
- [X] T021 [P] [US2] Update `testing\test_publication_manifest.py`, `testing\test_publication_validation.py`, and `testing\test_publication_publish.py` for exact integer manifest origins, endpoint membership/uniqueness, compatibility/version checks, invalid/partial output rejection, atomic success publication, and historical artifact immutability.
- [X] T022 [P] [US2] Update `testing\test_publication_pruning.py` and `testing\test_publication_compaction.py` for integer-origin pruning, precise keys above `2^53`, compacted integer origin arrays, unchanged row/key sets, and typed identity independent of decimal partition directory labels or Hive inference.
- [X] T023 [P] [US2] Update remaining ledger-backed execution assertions in `testing\test_od_execution.py`, `testing\test_od_execution_config.py`, `testing\test_od_execution_preparation.py`, `testing\test_od_execution_workers.py`, and `testing\test_od_execution_probe.py` to replace symbolic string cells with valid integer fixtures and assert serial/parallel logical parity, coordinator fencing, fallback, and unchanged configured limits; preserve the portable payload tests already authored and passed in US1 T008/T016.

### Durable State and Eligibility

- [X] T024 [US2] Add read-only preflight to `src\h3_route_data_builder\od\ledger.py` before WAL/metadata/schema initialization for existing databases; require ledger format `2`, reject legacy and inconsistent layouts explicitly, and initialize fresh endpoint columns as "INTEGER NOT NULL, with storage-type checks", retaining bound parameters, transactions, and unique logical-key claims without migration, deletion, or overwriting.
- [X] T025 [US2] Complete integer work/expected-key/outcome persistence, strict restoration, numeric batches, canonical work-ID encoding `2`, and reconciliation in `src\h3_route_data_builder\od\ledger.py`; update result compatibility encoding to `2` in `src\h3_route_data_builder\od\results.py`, preserving all lifecycle transitions, attempts, leases, fencing, and immutable part commit semantics.
- [X] T026 [P] [US2] Version eligibility schema/fingerprints as `2` and carry integer references through `src\h3_route_data_builder\eligibility\fingerprint.py`, `src\h3_route_data_builder\eligibility\run_state.py`, `src\h3_route_data_builder\eligibility\staging.py`, and `src\h3_route_data_builder\eligibility\output.py`; persist required uint64 `h3_id`, use sorted record arrays for any serialized cell-indexed maps, and validate restored indices without string coercion.
- [X] T027 [US2] Integrate schema-2 eligibility fingerprinting, old-stage/completed-run refusal, and exact numeric run-manifest serialization in `src\h3_route_data_builder\network\workflow.py`; ensure `default=str` cannot stringify index scalars, log incompatible-state/fresh-rebuild guidance, preserve prior files, and prevent adoption based on counts or filenames.

### Publication and Interfaces

- [X] T028 [P] [US2] Update `src\h3_route_data_builder\publication\models.py` and `src\h3_route_data_builder\publication\schema.py` to dataset/cell/fact `2.0.0`, retaining GeoParquet `1.1.0`; enforce "one required unsigned 64-bit `h3_id` field" and "required unsigned 64-bit `origin_h3_id` and `destination_h3_id` fields", integer `PublishedPart.origin_ids`, no alternate columns, and unchanged non-index nullability/geometry/CRS.
- [X] T029 [US2] Update `src\h3_route_data_builder\publication\convert.py` to consume integer eligibility and committed solve records directly, validate values/resolutions and logical membership, and produce the new fields without string-to-integer adoption, float conversion, duplicate aliases, or changed cost/classification semantics.
- [X] T030 [US2] Update `src\h3_route_data_builder\publication\write.py` and `src\h3_route_data_builder\publication\partition.py` together for integer-origin grouping, typed row filtering and manifest pruning; allow `origin_h3_id=<decimal>` location labels only as syntax, reject string-origin API input, and never reconstruct identity from paths or inferred partition types.
- [X] T031 [US2] Preserve integer references through `src\h3_route_data_builder\publication\compact.py`, `src\h3_route_data_builder\publication\manifest.py`, and `src\h3_route_data_builder\publication\publish.py`; serialize numeric origin arrays and representation-aware compatibility, preserve immutable compaction/publication, and distinguish old versions without adding an old-data reader or rewriting history.
- [X] T032 [US2] Update aggregate/schema/endpoint validation in `src\h3_route_data_builder\publication\validation.py` for uint64 integer IDs, strict type/value/resolution validation, integer expected-key comparison, duplicate/missing key detection, version identity, and unchanged validation-worker policy and atomic publication gates.
- [X] T033 [US2] Integrate integer candidate-to-ledger handoff and committed-result acceptance in `src\h3_route_data_builder\od\candidates.py`, `src\h3_route_data_builder\od\solving.py`, `src\h3_route_data_builder\od\execution.py`, and `src\h3_route_data_builder\od\preparation.py`; close any gaps revealed by T017-T023 without changing batches, concurrency, coordinator fencing, expected-key reconciliation, or outcome policy.
- [X] T034 [P] [US2] Update the proposed shared contract in `docsrc\mkdocs\design\03-data-contract.md` to canonical integer field names, uint64 columns, integer JSON values/arrays rather than H3 object keys, exact parsing above `2^53`, versions `2.0.0`, and explicit coordinated-adoption status; preserve all non-index semantics and do not claim the existing solver is compatible.
- [X] T035 [US2] Run the shared conformance fixture and reader assertions authored in T020 in `testing\test_publication_interoperability.py` using the portable fixtures from `testing\conftest.py`; verify exact Arrow and DuckDB values above `2^53`, reverse/self keys, unchanged geometry/cost outcomes, numeric manifest origins, and historical schema distinction against the proposed contract from T034.
- [X] T036 [US2] Run the fresh-build/restart/rebuild integration coverage authored in T019 in `testing\test_network_eligibility.py` and `testing\test_real_network_dataset.py`; prove old eligibility state is not adopted, legacy ledger/publication contents remain unchanged, fresh work completes without claiming legacy reuse, and real-network behavior matches the baseline when prerequisites exist.
- [X] T037 [US2] Run the focused persistence/publication/execution commands in `specs\006-integer-h3-indices\quickstart.md`; verify T017-T023 and T035-T036 pass, review lifecycle boundary evidence and exact schema/output shapes, and identify missing integration prerequisites rather than treating skips as successful evidence.
- [ ] T038 [US2] Coordinate the proposed `2.0.0` contract and matching consumer fixture with the `knu2xs/h3-route-solver` maintainer using `specs\006-integer-h3-indices\contracts\integer-h3-index-contract.md` and `testing\test_publication_interoperability.py`; record agreement and both projects' fixture results in `specs\006-integer-h3-indices\quickstart.md`, or leave this release gate explicitly blocked if approval/consumer access is unavailable; do not modify the external repository without authorization.

**Checkpoint**: Local US2 acceptance passes only after T037. Shared consumability remains blocked
until T038 supplies consumer evidence; local completion does not imply external adoption.

## Phase 5: Polish and Cross-Cutting Validation

**Purpose**: Finish directly related documentation and verify the complete representation cutover.

- [X] T039 [P] Update representation descriptions in `docsrc\mkdocs\design\builder\001-aoi-cell-generation-and-snapping.md`, `docsrc\mkdocs\design\builder\002-candidate-generation.md`, `docsrc\mkdocs\design\builder\003-resumable-od-solving.md`, `docsrc\mkdocs\design\builder\004-geoparquet-publication.md`, and `docsrc\mkdocs\design\builder\005-parallel-execution.md` with the Feature 006 versioned cutover, preserving their behavioral ownership and historical context.
- [X] T040 [P] Update affected examples and operator rebuild guidance in `docsrc\mkdocs\api.md`, `docsrc\mkdocs\configuration.md`, and `arcgis\README.md`; synchronize any changed H3 output/help description in `arcgis\h3_route_data_builder.pyt` and `arcgis\h3_route_data_builder.GeometryEligibilityTool.pyt.xml`, verify sidecar tests and Pro help if changed, and leave unchanged parameters/defaults alone.
- [X] T041 Audit H3-bearing inputs, models, logs, serialization and exports in `src\h3_route_data_builder\eligibility\__init__.py`, `src\h3_route_data_builder\od\__init__.py`, `src\h3_route_data_builder\network\__init__.py`, `src\h3_route_data_builder\publication\__init__.py`, and their modules for remaining new-data `_hex`/`_uint64` aliases, string keys or precision loss; update callers surgically while retaining opaque non-H3 strings and legitimate negative/historical tests.
- [ ] T042 Run existing Black checks on changed Python files and editor/type diagnostics for `src\h3_route_data_builder` and `testing`; resolve feature-caused errors without unrelated refactors, then run whitespace checks on `specs\006-integer-h3-indices\tasks.md` and other changed files.
- [X] T043 Run the complete regression and geometry/network commands in `specs\006-integer-h3-indices\quickstart.md`; verify no candidate/route/outcome changes, portable modules import without ArcPy, integer restart/lease/atomic-publication guarantees hold, and report baseline failures and missing ArcPy/Network Analyst prerequisites distinctly.
- [X] T044 Record final FR-001 through FR-012 and SC-001 through SC-005 acceptance evidence and remaining external/prerequisite blockers in `specs\006-integer-h3-indices\quickstart.md`, and update completed checkboxes in `specs\006-integer-h3-indices\tasks.md` truthfully; include edge-device efficiency only as motivation, not an unmeasured performance claim.

### Final Execution Status

- **42 of 44 tasks complete.** Acceptance evidence and validation limitations are recorded in
  [quickstart.md](quickstart.md#implementation-evidence-2026-10-15).
- **T038 blocked:** external solver maintainer agreement and solver-side fixture execution
  are unavailable. Builder-only Arrow/DuckDB conformance does not complete this release gate.
- **T042 partially verified:** feature-relevant Black checks, Python compilation and whitespace
  checks pass. No static type checker is configured, and editor diagnostics are unavailable
  through the current tools; that portion remains unchecked.
- **T043 completed with a baseline failure reported:** full suite has 331 passes and the known
  real-network logging-capture assertion failure. The isolated configured-network selection
  passed. No unrelated logging or pre-existing formatting changes were made to force green.
- Requirements checklists remain reviewer-owned and were not edited.

## Dependencies and Execution Order

### Story Dependency Graph

```text
Setup (T001-T002)
    -> Foundation (T003-T004)
        -> US1 (T005-T016): independently tested internal milestone
            -> US2 local (T017-T037): durable/publication cutover
                -> Release coordination (T038): external evidence
                -> Polish/local validation (T039-T044)

Release readiness requires local validation AND T038.
```

Both stories are P1. US2 intentionally depends on US1's identity/model changes rather than
pretending the two stories can be implemented independently. Its acceptance scenario is
independently runnable on a fresh fixture once those prerequisites exist.

### Explicit Task Prerequisites

All tasks in a phase require the preceding local phase checkpoint unless stated otherwise.
Within each phase the following are the actual prerequisites; list order alone is not a dependency.

| Tasks | Prerequisites |
|---|---|
| T001 | None |
| T002 | T001 |
| T003 | T002 |
| T004 | T003; observe intended failing tests before implementation |
| T005-T008 | T004 |
| T009 | T005 |
| T010 | T006 |
| T011 | T007, T009, T010 |
| T012 | T008, T010 |
| T013 | T011, T012 |
| T014 | T008, T012, T013 |
| T015 | T009, T011 |
| T016 | T005-T015 |
| T017-T023, T034 | T016 |
| T024 | T017 |
| T025 | T018, T024 |
| T026 | T019 |
| T027 | T026 |
| T028 | T020 |
| T029 | T020, T028 |
| T030 | T022, T029 |
| T031 | T021, T030 |
| T032 | T031 |
| T033 | T023, T025, T027, T032 |
| T035 | T020, T032, T034 |
| T036 | T019, T033, T035 |
| T037 | T017-T036 |
| T038 | T037 plus external maintainer approval and consumer fixture execution |
| T039-T041 | T037; do not wait for T038 to finish local work |
| T042 | T039-T041 |
| T043 | T042 |
| T044 | T043; report T038 as complete only with evidence, otherwise blocked |

Tests precede implementation; convert remaining existing fixtures in the corresponding test
task rather than weakening validation to keep symbolic `"origin"`/`"destination"` values.
T019 and T020 author integration/reader tests and establish their expected failing assertions;
T035 and T036 execute those existing tests after integration, not author them for the first time.
Keep repeated edits to the same file sequential. No cross-story concurrent implementation
is proposed, since models, workflow, result and execution modules are shared.

## Parallel Execution Examples

### US1

After T004, T005-T008 can run concurrently: they edit different test files.
Once their respective tests exist, T009 and T010 can run concurrently on eligibility and OD
models/logic. After T010, T012 may run alongside T011 because result models and network geometry
adapters are disjoint. Join both before T013; then integrate serially.

```text
After T004:
    T005: eligibility rule tests
    T006: candidate identity tests
    T007: spatial invariance tests
    T008: Network Analyst label tests and portable integer payload round-trips

After T005 and T006:
    T009: eligibility models/rules
    T010: candidate models/planning
```

### US2

After T016, T017-T023 and T034 can run concurrently in disjoint test/document files.
When those tests are written, the ledger chain T024-T025, eligibility chain T026-T027,
and publication chain T028-T032 can progress concurrently. T033 joins them.
Do not parallelize publication writer/pruning work with dependent compaction/validation edits.

```text
After US2 acceptance tests are established:
    T024 -> T025: ledger format and integer persistence
    T026 -> T027: eligibility storage and workflow recovery
    T028 -> T029 -> T030 -> T031 -> T032: publication cutover

Join all three chains at T033.
```

T039 and T040 are also disjoint documentation tasks after local US2 completion.
All `[P]` markings are conditional on the prerequisites above, not permission to ignore them.

## Requirement Coverage

| Requirements | Primary tasks |
|---|---|
| FR-001, FR-002; SC-002 | T002-T004, T005-T008, T017, T020, T035 |
| FR-003, FR-004; SC-001 | T009-T015, T024-T033, T041 |
| FR-005; SC-003 | T003, T006, T010, T017-T018, T025 |
| FR-006 | T007-T008, T011-T014 |
| FR-007; SC-005 | T019-T022, T026-T032, T035 |
| FR-008 | T034-T035, T038 |
| FR-009 | T017-T019, T025-T028, T031, T034 |
| FR-010; SC-004 | T017-T018, T024-T027, T036, T040 |
| FR-011 | T021, T031, T035-T036 |
| FR-012 | T001, T005-T008, T017-T018, T021-T023, T033, T036-T037, T043 |

## Implementation Strategy

### MVP First

1. Complete setup and the portable foundation.
2. Complete US1 and validate its in-memory/adapter milestone at T016.
3. Stop to inspect integer identity and unchanged candidate/route expectations.
4. Do not release from this checkpoint: the full standard requires US2's persisted cutover.

### Incremental Delivery

1. Add new-format ledger support with explicit legacy refusal.
2. Version eligibility storage/recovery and publish uint64 tables.
3. Join execution and validate interruption/reclaim/fencing and immutable publication.
4. Finish builder documentation and local regression independently of external coordination.
5. Claim shared consumption only after the coordinated solver contract/fixture evidence exists.

### Completion Rules

- No automatic legacy migration, destructive reset, old-publication rewriting, or dual aliases.
- Keep states, lease ownership, batching, outcome policy, and concurrency behavior unchanged.
- Use only temporary test outputs; never rewrite source data or historical published fixtures.
- Missing external approval or integration prerequisites are blockers, not passing tests.
- Task generation does not implement code, modify the solver, commit, or push changes.
