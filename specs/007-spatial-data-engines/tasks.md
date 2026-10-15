# Tasks: Spatial Data Engine Standardization

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [engine contract](contracts/spatial-data-engines.md),
[amendment proposal](contracts/constitution-amendment.md), and [quickstart.md](quickstart.md).

**Prerequisites**: Read the constitution and applicable instructions before changes. Preserve
unrelated worktree changes. Feature directory is `specs/007-spatial-data-engines`; Git remains
on `main`. No commit, push, external solver change, or PR creation is authorized by these tasks.

**Tests**: Required by FR-016 and the acceptance scenarios. Author the tests before the code they
exercise, observe the expected failures, and preserve fixed pre-change semantic expectations.
Do not treat skipped spatial/resource/Pro UI validation as passing evidence.

**Organization**: Four user-story increments, with governance and shared policy prerequisites.
US3 is an independent P1 workstream and may run before US1/US2, matching the plan's recommended
delivery order. US2 depends on the US1 reference adapter. US4 completes operator cutover and
integration; its mandatory constitution prerequisite is deliberately pulled forward into Setup.

## Format and Path Conventions

- Every task uses `- [ ] Tnnn [P?] [USn?] Description`.
- `[P]` permits parallel work only in the explicitly identified dependency wave and disjoint files.
- Story labels apply only to user-story phases. All tasks begin unchecked.
- Paths are repository-relative; use Windows separators for execution.
- Shared model constraints quoted below are binding; details remain in the linked design documents.

## Phase 1: Setup

**Purpose**: Establish the baseline, enact the prerequisite governance change, and declare approved
dependencies before any conflicting runtime changes.

- [X] T001 Capture the configured interpreter/dependency/extension versions and run the baseline selection in `specs\007-spatial-data-engines\quickstart.md` against `testing\test_eligibility_geometry.py`, `testing\test_network_eligibility.py`, `testing\test_od_candidate_geometry.py`, `testing\test_od_candidates.py`, `testing\test_od_ledger.py`, and `testing\test_od_solver.py`; record actual results and the separately known real-network logging-order failure without changing production code or source data.
- [ ] T002 Complete the separate, explicit constitution-update workflow for `.specify\memory\constitution.md` using `specs\007-spatial-data-engines\contracts\constitution-amendment.md`: prepare the 2.0.1-to-3.0.0 amendment redefining Principle II and aligning VIII/Technology Constraints, Sync Impact Report, actual amendment date and rationale/fresh-state impact while preserving shared principles and Principle XVII formulas; complete the pull-request governance required by the current constitution and record the amendment PR and enacted version before marking this task complete. Local text preparation alone does not release the gate; if PR authorization/governance is outstanding, leave this task blocked rather than creating a PR without authorization or inferring approval.
- [ ] T003 Synchronize canonical spatial/DataFrame/SQL guidance in `AGENTS.md` with T002, inspect `.specify\templates\plan-template.md`, `.specify\templates\spec-template.md`, and `.specify\templates\tasks-template.md` for actual conflicts, and update only conflicts; use existing regeneration tooling for derived instructions if available, otherwise report its absence in `specs\007-spatial-data-engines\quickstart.md` rather than hand-edit generated instruction copies.
- [ ] T004 Declare the reviewed `spatial` extra with `pandas>=2.0` and `arcgis>=2.4.3.1` in `pyproject.toml` and explicit `pandas>=2.0` in `environment.yml`; retain existing versions/backends until their story tasks, flag dependency additions in `specs\007-spatial-data-engines\quickstart.md`, and restore/install only if validation proves a declared dependency missing; no unrelated upgrades or GeoPandas/Shapely/pyproj application dependencies.

**Gate**: T002 must complete through the separate constitution workflow and required PR governance
before conflicting spatial implementation begins. Local amendment preparation alone is insufficient;
do not invent approval rules beyond current Governance. T003 must use the applicable customization
workflow when editing agent guidance.

## Phase 2: Foundational Prerequisites

**Purpose**: Shared deterministic configuration, estimates, saved metadata, and reusable fixtures.

- [ ] T005 Add reusable synthetic geometry/reference, typed all-resolution H3, source-iterator, and controlled resource-snapshot fixtures in `testing\conftest.py` using the unchanged expectations captured by T001; retain greatest-valid/pentagon/above-`2^53` cases, reverse/self keys, restrictions/direction/ties, and temporary-only source/output isolation.
- [ ] T006 Add portable policy/serialization tests in `testing\test_data_engines.py` for `policy_version` and `estimator_version` "Literal `\"1\"`; unknown versions rejected", `source` "`inferred` or `set` for each resolved field", exact non-negative counts or unknown, and `selected_path` "`geoaccessor` or `duckdb`"; test below/equal/above-budget/unknown estimates before materialization, cross-field bounds, strict invalid-value rejection, saved-policy restoration, and blocked ArcGIS/ArcPy/Spatial imports.
- [ ] T007 Implement portable `EnginePolicy`, `WorkloadEstimate`, and `EngineDecision` validation/resolution in `src\h3_route_data_builder\eligibility\data_engines.py`, reusing `ResourceSnapshot` from `src\h3_route_data_builder\eligibility\limits.py` without changing existing formulas: memory "Positive exact integer; default `min(1 GiB, available_memory_bytes // 4)`; minimum 64 MiB", batch "Positive exact integer; default `min(64 MiB, memory_budget_bytes // 8)`; must not exceed budget/8", DuckDB memory "Default budget/2; positive, no greater than budget/2", and scratch cap "Default `min(8 GiB, free_scratch_bytes // 4)`; minimum 128 MiB; explicit value must fit free space".
- [ ] T008 Complete estimator/decision serialization in `src\h3_route_data_builder\eligibility\data_engines.py` and add `data_engines` defaults under `environments.default` in `config\config.yml`: use `8 * (geometry_wkb_bytes + attribute_bytes + 512 * input_row_count) + 64 * pair_upper_bound`, unknown estimates select DuckDB, stage keys are stable, reasons are `fits_budget`/`exceeds_budget`/`unknown_estimate`, scratch is a unique run child under configured default `data/interim/engine-scratch`, and comparison tolerances are "Coordinate tolerance `1e-9` degrees; distance `1e-6` m; source measure `1e-12`"; reject invalid settings with logged context.
- [ ] T009 Add saved engine-envelope/fingerprint acceptance tests in `testing\test_eligibility_fingerprint.py` and `testing\test_network_eligibility.py` for `engine_metadata_version = "1"`, exact decisions/version/delegation summaries, restore-before-fingerprint behavior, resource changes without engine switching, incompatible explicit overrides, absent/unknown metadata requiring fresh working output, and unchanged eligibility table/state schema 2; production integration follows T019/T030.
- [ ] T010 Run the foundational policy/fixture tests from `testing\test_data_engines.py` and existing limit tests in `testing\test_eligibility_limits.py`; verify blocked spatial imports, exact settings/error shapes, deterministic estimates and unchanged Principle XVII behavior, then record the checkpoint in `specs\007-spatial-data-engines\quickstart.md`; T009 integration tests may remain explicitly red until their assigned story implementation.

**Checkpoint**: Shared policy is portable and validated; metadata tests identify integration work,
not a claim that the spatial or storage cutover is complete.

## Phase 3: US1 - Process Small Spatial Inputs Consistently (Priority: P1)

**Goal**: Deliver the approved small-data reference path with exact identities and unchanged geometry,
representative, candidate and solve semantics.

**Independent test**: Synthetic small fixtures invoke actual GeoAccessor operations with fallback
blocked and match fixed pre-change discrete results and declared numerical tolerances.

### Acceptance Tests

- [ ] T011 [US1] Add small-path adapter tests in `testing\test_spatial_engines.py` proving actual GeoAccessor/GeoSeries operations execute with ArcPy capability present and Shapely fallback blocked; valid empty datasets/zero planned work reconcile successfully without unnecessary spatial execution, while missing dependencies/CRS and empty/invalid individual geometry fail explicitly unless an existing rule defines otherwise. Valid antimeridian geometry must preserve reference semantics through conservative filtering/bounded exact checks; unsupported operations use recorded bounded delegation under policy or fail actionably. Neither a wrapped unchanged pipeline nor a success-shaped empty table on failure is acceptance.
- [ ] T012 [P] [US1] Extend `testing\test_eligibility_geometry.py` and `testing\test_od_candidate_geometry.py` with fixed-baseline eligibility, dimensional boundary touch, restriction/direction, representative tie, candidate AOI membership, geodesic-offset and expansion expectations; require exact membership/choices and comparisons <=`1e-9` degrees, <=`1e-6` m, <=`1e-12` measure without changing production snap/tie policy.
- [ ] T013 [US1] Extend `testing\test_spatial_engines.py` with all-resolution Pandas/GeoAccessor/Arrow round-trips: "GeoAccessor H3 dtype `uint64`; Arrow H3 type non-null `uint64`; DuckDB H3 type `UBIGINT`"; reject identity null/bool/float/text and verify nullable ancillary integer columns, joins/overlays and opaque transport labels cannot coerce or reconstruct H3 identities.

### Implementation and Integration

- [ ] T014 [US1] Implement lazy dependency/capability checks, typed spatial-table construction and bounded GeoAccessor/GeoSeries operations in `src\h3_route_data_builder\network\spatial.py`; validate ArcGIS geometry execution rather than relying only on private flags or `ARCGIS_IO_ENGINE`, preserve exact non-null integer identities and CRS, avoid remote GIS calls, and surface missing capabilities explicitly.
- [ ] T015 [US1] Wire small-path AOI validation/projection/union and H3 polygon/centroid/candidate geometry operations through the adapter in `src\h3_route_data_builder\network\geometry.py`; retain existing public argument lists, fixed WGS84/geodesic semantics, configured comparison tolerances and necessary ArcPy geoprocessing boundaries.
- [ ] T016 [US1] Replace small cell-edge pair processing with the GeoAccessor adapter in `src\h3_route_data_builder\eligibility\engine.py`, preserving source ID/OID/name order, inclusive point/line intersection evidence, deferred traversability classification, exact cell membership and portable imports; do not change non-spatial eligibility result construction.
- [ ] T017 [US1] Integrate bounded ArcGIS representative geometry/ranking and location transport in `src\h3_route_data_builder\network\representatives.py` and `src\h3_route_data_builder\network\locations.py`, preserving centroid-distance/source-ID/OID/measure ordering, source-relative measure, snap behavior, opaque labels and exact integer lookup; do not replace Network Analyst.
- [ ] T018 [US1] Add versioned operation-capability/delegation summaries to `src\h3_route_data_builder\network\spatial.py` and strict `EngineDecision` record support in `src\h3_route_data_builder\eligibility\data_engines.py`: reasons are `unsupported` or `semantic_equivalence`, records carry capability/version/settings/counts/status, selection is reproducible, and missing delegated capabilities fail explicitly.
- [ ] T019 [US1] Integrate initial/saved policy and stage decisions in `src\h3_route_data_builder\network\workflow.py` and semantic fingerprint payloads in `src\h3_route_data_builder\eligibility\fingerprint.py`; discover saved settings before materializing inputs or deriving behavior fingerprints, persist envelope version 1 and engine evidence before execution, require fresh output for old envelopes, and keep small-path resource/provenance failures explicit.
- [ ] T020 [US1] Run the US1 spatial/reference/identity and T009 integration selections in `testing\test_spatial_engines.py`, `testing\test_eligibility_geometry.py`, `testing\test_od_candidate_geometry.py`, `testing\test_network_eligibility.py`, and `testing\test_od_solver.py`; record actual GeoAccessor execution and unchanged outputs in `specs\007-spatial-data-engines\quickstart.md`, listing unavailable spatial prerequisites rather than treating skips as passes.

**Checkpoint**: Small-data correctness reference is usable independently; large-data memory
acceptance and DuckDB persistence are separate increments and are not implied by US1 completion.

## Phase 4: US2 - Process Large Data Without Full Materialization (Priority: P1)

**Goal**: Execute above-budget/unknown workloads with DuckDB, bounded exact delegation and verifiable
resource accounting, without changing logical output.

**Independent test**: Compare both paths to frozen reference expectations and complete a >=256 MiB
encoded fixture under the contract's 128 MiB stage budget without full-input client materialization.

### Acceptance Tests

- [ ] T021 [US2] Add large-path/delegation/offline acceptance tests in `testing\test_spatial_engines.py` for unknown sizes, high fan-out, explicit DuckDB filtering/query execution, forced unsupported and semantic-equivalence delegation, exact reference outcomes and stable H3/source ordering; trap full-input `list`/DataFrame/query-result materialization and all runtime extension downloads/`INSTALL` attempts.
- [ ] T022 [P] [US2] Extend `testing\test_network_eligibility.py` and `testing\test_od_candidate_geometry.py` with large AOI ingestion/union, bounded H3 generation/sorting, source cursor batching, per-cell high-degree reduction, stage-before-load decision and saved-policy resume tests; exceed the shared budget with candidate IDs alone, trap complete-cover allocation before batching and downstream full scope/endpoint reconstruction, test partition-boundary duplicates and antimeridian handling, and compare exact candidate sets with tractable reference covers. Ensure large-path integration reaches every geometry entry point, not just cell-edge joins.
- [ ] T023 [US2] Add `resource_`, `offline_`, and `delegation_` cases to `testing\test_spatial_engines.py` using isolated warmed child processes: >=256 MiB encoded input, 128 MiB shared budget, 4 GiB scratch allocation, 20 ms Windows working-set sampling, internal accounted peak <=128 MiB, process delta <=320 MiB and zero whole-input client tables; include oversized-record, fan-out/allocation, spill/disk failure and missing capability fixtures with incomplete/no-`_SUCCESS` assertions.

### Implementation and Integration

- [ ] T024 [US2] Implement conservative metadata/bounded-scan estimates and incremental WKB/Arrow transfer in `src\h3_route_data_builder\network\spatial.py`, using T008's estimator and simultaneous decoded/input/result/reducer accounting; enforce byte and existing row limits before conversion, reject a single oversized record, serialize shared spatial stages, and never treat a sample mean as an upper bound.
- [ ] T025 [P] [US2] Add bound-parameter spatial filtering/pair and candidate-scope queries in `src\h3_route_data_builder\sql\spatial_cell_edge_pairs.sql` and `src\h3_route_data_builder\sql\spatial_scope_membership.sql` through existing `src\h3_route_data_builder\sql\__init__.py`; use installed DuckDB 1.3.2 capabilities, conservative prefilters for unproved topology/antimeridian semantics, typed `UBIGINT` endpoints and stable ordered batch results, with no user-interpolated identifiers or assumed newer spatial functions.
- [ ] T026 [US2] Implement configured DuckDB spatial connections and streamed query consumption in `src\h3_route_data_builder\network\spatial.py`: disable auto-install/autoload, load only installed Spatial for spatial work, apply buffer memory <=budget/2 and scratch cap, stream record batches without `.fetchall()`/`.df()` full results, and include non-buffer allocations in accounting/error context.
- [ ] T027 [US2] Remove full source-edge and per-cell fan-out materialization from the large path in `src\h3_route_data_builder\network\eligibility.py` and `src\h3_route_data_builder\eligibility\engine.py`; stream stable source records and SQL pairs, spill evidence and incrementally reduce matches while preserving all expected cell counts, classifications and sparse-correctness semantics.
- [ ] T028 [US2] Before implementation, document conservative partition-coverage and allocation-bound reasoning in `specs\007-spatial-data-engines\contracts\spatial-data-engines.md`, including boundary/antimeridian completeness. Implement bounded AOI preparation, pre-allocation-bounded H3 partition covers, DuckDB ID persistence/deduplication/external ordering and candidate membership/offset/expansion in `src\h3_route_data_builder\network\geometry.py` and `src\h3_route_data_builder\network\spatial.py`; account for cover results and all retained scope IDs, retain small public list helpers but use internal disk-backed large-path processing without rebuilding complete endpoint tuples, use bounded ArcGIS scratch geoprocessing where needed, and fail explicitly when safe bounds or final geometry cannot be satisfied.
- [ ] T029 [US2] Integrate large-path exact representative/geodesic/dimensional-topology delegation in `src\h3_route_data_builder\network\representatives.py` and `src\h3_route_data_builder\network\spatial.py`, retaining DuckDB-led filtering/orchestration, incrementally applying existing ranking, recording delegated reasons/counts/settings and failing when capability, budget or exact semantics cannot be satisfied.
- [ ] T030 [US2] Complete large-path orchestration and durable engine decision/delegation/failure summaries in `src\h3_route_data_builder\network\workflow.py`, including saved-policy safety checks against current resources without reselecting an engine; clean only owned named scratch paths, retain recoverable completed work and keep failed runs visibly incomplete.
- [ ] T031 [US2] Disable automatic extension installation/loading in existing non-spatial DuckDB connections in `src\h3_route_data_builder\publication\write.py` and `src\h3_route_data_builder\publication\validation.py`; extend `testing\test_publication_interoperability.py` and `testing\test_publication_validation.py` to prove non-spatial operations do not load Spatial or download extensions and preserve current schemas/exact identities.
- [ ] T032 [US2] Run and, if needed, correct the exact `resource_`/`offline_`/`delegation_` thresholds in `testing\test_spatial_engines.py` without weakening the contract; record input size, sampling baseline/peak delta, accounted peak, row/byte batch sizes, DuckDB settings and error-path evidence in `specs\007-spatial-data-engines\quickstart.md`; do not substitute a buffer-limit setting for measured acceptance.
- [ ] T033 [US2] Run combined small/large reference geometry and configured-network selections in `testing\test_spatial_engines.py`, `testing\test_network_eligibility.py`, `testing\test_od_candidate_geometry.py`, and `testing\test_real_network_dataset.py`; prove unchanged membership/representatives/directed outcomes, explicit delegation and read-only source access, and record the integrated checkpoint in `specs\007-spatial-data-engines\quickstart.md`.

**Checkpoint**: Both spatial paths and the exact resource/offline contracts pass independently of
ledger backend integration. Do not claim a whole-build persistence cutover before US3/US4.

## Phase 5: US3 - Resume Work from a Durable Database (Priority: P1)

**Goal**: Replace SQLite end-to-end with a lifetime-owned native DuckDB ledger preserving lifecycle,
exact identities, transaction atomicity and restart safety.

**Independent test**: Temporary native DuckDB fixtures survive killed-process recovery at every
lifecycle/transaction boundary with exact logical-key reconciliation and competing-owner rejection.

### Acceptance Tests

- [ ] T034 [US3] Port/add backend contract tests in `testing\test_od_ledger.py` for metadata `engine = duckdb`, `format_version = "3"`, `h3_identity_encoding = "2"`, `work_id_encoding = "2"`, positive matching `max_attempts`, required `UBIGINT` endpoints, exact restored JSON keys/work IDs and `work_events` "Sequence gaps are allowed; event order uses event ID"; retain strict all-resolution identity and immutable-part assertions.
- [ ] T035 [US3] Add same-process canonical-path conflict, spawned competing coordinator, different-PID handle use, live-handle serialization rejection, idempotent `close()`, closed-handle failure, exception cleanup and unlocked-leftover-lock-file tests in `testing\test_od_ledger.py`; verify ownership spans preflight/open/lifetime and no process deletes another owner's lock based on timestamps.
- [ ] T036 [US3] Add real child-process termination tests in `testing\test_od_ledger.py` for planned/leased/solving/staged/validated/committed boundaries and before/after transaction commit, including pending WAL replay, duplicate active claims, multi-row invalidation/recommit, rollback/disk-write failure, retry limits, lease renewal/reclaim, stale rejection and invalid stage digests/keys; graceful-close tests are not crash evidence.
- [ ] T037 [P] [US3] Extend `testing\test_od_execution.py`, `testing\test_od_execution_preparation.py`, and `testing\test_od_execution_workers.py` to prove only the coordinator owns the live database, worker payloads contain neither handles nor database paths, serial/parallel/fallback retain exact logical outcomes, and coordinator/error exit releases ownership before reopen; preserve existing spawn isolation and worker ceilings.

### Implementation and Integration

- [ ] T038 [US3] Add `src\h3_route_data_builder\sql\ledger_schema.sql` with format-3 `work_items`, `ledger_metadata`, `committed_parts`, `active_outcomes`, `work_events` and sequence definitions; enforce required `UBIGINT` endpoints, work/metadata/part primary keys and active composite key `(compatibility_fingerprint, origin_h3_id, destination_h3_id)`, retaining existing payload/failure/lease fields without introducing unnecessary foreign keys or external part files.
- [ ] T039 [US3] Implement DuckDB connection lifetime/ownership and explicit `close()`/context-manager support in `src\h3_route_data_builder\od\ledger.py` while preserving `ODLedger(database_path, max_attempts=3)`: canonical-path same-process guard, creator PID/serialization checks, OS sibling ownership-file lock before preflight held to close, native DuckDB locking and serialized coordinator connection, with rollback/release on failures and no Spatial load.
- [ ] T040 [US3] Replace SQLite lifecycle SQL/row factories/PRAGMAs with explicit DuckDB transactions, typed row mapping and bound external SQL assets in `src\h3_route_data_builder\od\ledger.py` and `src\h3_route_data_builder\sql`; preserve `_ALLOWED_TRANSITIONS`, attempts/retries/leases/fencing/history and strict restored identity validation, and atomically insert immutable part/checksum plus active claims plus committed state/event without replace-shaped conflict suppression.
- [ ] T041 [US3] Implement header-first SQLite refusal and ownership-protected isolated DuckDB database+WAL snapshot preflight in `src\h3_route_data_builder\od\ledger.py`; verify stable source size/mtime and WAL presence, engine/format/policy/schema/types/keys and restored domain values before authoritative read-write open, reject corrupt/incompatible/unstable originals without mutation, and never create an ownership file for a header-rejected SQLite input.
- [ ] T042 [US3] Update coordinator/open/reopen sites in `src\h3_route_data_builder\od\execution.py`, `src\h3_route_data_builder\od\solving.py`, and test fixtures/callers in `testing\conftest.py`, `testing\test_od_ledger.py`, `testing\test_od_execution.py`, `testing\test_od_execution_probe.py`, `testing\test_od_candidate_ledger.py`, and `testing\test_real_network_dataset.py` to close owned ledgers deterministically before reopen or error exit; do not close caller-owned ledgers prematurely or add a destructor-dependent release policy.
- [ ] T043 [US3] Preserve committed-result, evidence and publication handoff semantics in `src\h3_route_data_builder\od\ledger.py`, `src\h3_route_data_builder\od\results.py`, and `src\h3_route_data_builder\publication\publish.py`; retain work-ID encoding 2 and immutable JSON parts inside transactions, exact directed keys and outcome classifications, no schema bump for external tables and no new file/database dual commit.
- [ ] T044 [US3] Run T034-T037 lifecycle/ownership/crash tests plus existing `testing\test_od_candidate_ledger.py` and `testing\test_od_solver.py` selections; verify actual WAL recovery and resource/transaction failures against DuckDB 1.3.2, fix feature-caused constraint differences without weakening unique claims, and record actual results in `specs\007-spatial-data-engines\quickstart.md`.
- [ ] T045 [US3] Audit persistent database opens/imports in `src\h3_route_data_builder\od\ledger.py`, `src\h3_route_data_builder\od\execution.py`, and `src\h3_route_data_builder\publication`, verifying no SQLite runtime persistence/fallback remains, no worker owns the authoritative path and portable ledger execution works with ArcGIS/ArcPy/Spatial blocked; keep test-only SQLite legacy fixture construction and legitimate JSON/Parquet storage.

**Checkpoint**: Native persistent storage is independently validated. The fresh-legacy/reuse and
publication provenance integration remains the explicit US4 acceptance increment.

## Phase 6: US4 - Adopt the Policy Without Rewriting History (Priority: P2)

**Goal**: Make governance, operator guidance, fresh-state rebuilding, compatible new-state reuse and
external publication provenance consistent across the completed engine/storage paths.

**Independent test**: Refuse legacy files byte-for-byte, complete a fresh build, restart/expand it
with precisely compatible reuse, and preserve historical publications and current reader schemas.

### Acceptance Tests

- [ ] T046 [US4] Add combined SQLite clean/WAL/SHM/journal/misleading-extension refusal, fresh DuckDB rebuild, saved-engine restart and compatible/incompatible AOI expansion cases in `testing\test_od_candidate_ledger.py`; snapshot all legacy file bytes and directory membership and prove zero changes, zero old-state reuse and exactly the expected new/invalidated pairs scheduled. Explicitly test reuse with unchanged prior decisions and added unrelated stages, and invalidation of affected prior results when a relevant producing engine decision changes; added stage inventory alone must not invalidate prior work, and resume must not silently reselect engines.
- [ ] T047 [P] [US4] Add end-to-end engine compatibility/provenance and historical immutability tests in `testing\test_publication_publish.py` and `testing\test_publication_interoperability.py`, verifying policy/estimator/operation-map/path/behavior-relevant versions survive the eligibility-to-candidate-to-solve-to-publication chain, current uint64 schemas stay unchanged and incompatible metadata is never silently adopted.

### Implementation and Operator Integration

- [ ] T048 [US4] Wire the canonical result-scoped engine compatibility payload from `specs\007-spatial-data-engines\data-model.md` and separate whole-run provenance through `src\h3_route_data_builder\eligibility\fingerprint.py`, `src\h3_route_data_builder\network\workflow.py`, `src\h3_route_data_builder\od\candidates.py`, `src\h3_route_data_builder\od\results.py`, and `src\h3_route_data_builder\publication\publish.py`; track transitive producing-operation dependencies rather than whole-run stage inventory, restore settings before fingerprinting, distinguish run-envelope version 1 from table schema 2 and ledger format 3, exclude volatile observations/timestamps from result compatibility, and reuse only compatible new-format work.
- [ ] T049 [US4] Update `docsrc\mkdocs\api.md`, `docsrc\mkdocs\configuration.md`, and `arcgis\README.md` with actual settings/defaults, explicit ledger close usage, reviewed spatial extra/version matrix, setup-only signed/offline Spatial provisioning, no runtime downloads, separate fresh working database/output instructions and immutable history guidance; replace success-shaped or migration-implying examples.
- [ ] T050 [US4] Update operator-visible engine/prerequisite/cutover descriptions in `arcgis\h3_route_data_builder.pyt` and `arcgis\h3_route_data_builder.GeometryEligibilityTool.pyt.xml` without unnecessary new parameters; extend the existing toolbox metadata checks in `testing\test_eligibility_config.py`, run them, and verify rendered tool/parameter help in ArcGIS Pro or record unavailable UI validation as a remaining gate in `specs\007-spatial-data-engines\quickstart.md`.
- [ ] T051 [US4] Synchronize active architecture/roadmap and directly affected design feature pages under `docsrc\mkdocs\design` plus Features 001-006 artifacts under `specs` with explicit Feature 007 supersession notes, preserving historical ArcPy/SQLite decisions; run T046-T047 fresh/reuse/publication acceptance and record unchanged historical bytes and governance/contract alignment in `specs\007-spatial-data-engines\quickstart.md`.

**Checkpoint**: Operator cutover and compatible new-format reuse are proven; missing PR approval,
Pro UI validation or external solver adoption must remain explicit, not inferred from local tests.

## Phase 7: Polish and Cross-Cutting Validation

- [ ] T052 Audit H3 types, spatial engine entry points, bounded source/pair/materialization paths, logger/error propagation and public exports across `src\h3_route_data_builder\eligibility`, `src\h3_route_data_builder\network`, `src\h3_route_data_builder\od`, and `src\h3_route_data_builder\publication`; close only feature-related gaps, preserve public argument lists and opaque non-H3 strings, and verify no unapproved fallback/import or runtime extension install remains.
- [ ] T053 Run the portable, spatial, resource/offline/delegation, persistence and publication selections in `specs\007-spatial-data-engines\quickstart.md`, combining related selectors with the existing pytest runner; verify all FR-001 through FR-017 and SC-001 through SC-006 thresholds/output shapes, keep source data read-only and report prerequisite/resource shortages distinctly.
- [ ] T054 Run configured real-network and full regression commands in `specs\007-spatial-data-engines\quickstart.md` and existing serial/parallel/probe/fallback tests in `testing\test_od_execution.py` and `testing\test_od_execution_probe.py`; preserve baseline classifications/costs/representatives, retry/lease/atomic-publication behavior and worker ceilings, recording known pre-existing logging failures separately from feature regressions.
- [ ] T055 Run existing Black checks at line length 100 on changed Python/toolbox sources under `src`, `testing`, and `arcgis`, compilation and available configured diagnostics, then whitespace/link checks on `specs\007-spatial-data-engines` and other modified documentation; resolve feature-caused issues, leave unrelated baseline formatting alone and report unavailable static/editor diagnostics honestly.
- [ ] T056 Record actual per-requirement/per-success-criterion acceptance results, exact resource metrics and remaining governance/environment/Pro UI/external gates in `specs\007-spatial-data-engines\quickstart.md`; update only completed task markers in `specs\007-spatial-data-engines\tasks.md`, leave requirements checklists reviewer-owned, check post-implementation hooks and clean only explicitly owned temporary artifacts without claiming measured speedups or unauthorized solver adoption.

## Dependencies and Execution Order

### Phase and Story Graph

```text
Setup:
  T001 baseline -> T002 amendment -> T003 guidance -> T004 dependencies
Foundation:
  T005 fixtures -> T006 red policy tests -> T007 policy -> T008 estimation/settings
  T009 red envelope tests -> T010 portable checkpoint
After foundation:
  US1 T011-T020 -----> US2 T021-T033 ---+
  US3 T034-T045 -----------------------+--> US4 T046-T051 --> T052-T056
```

All setup tasks precede foundation; all foundation tasks precede story implementation.
T009 tests are deliberately red until T019/T030: T010 runs the portable checkpoint only.
US3 may run first after foundation (recommended), or alongside US1 with coordinated ownership
of shared test/documentation files. No story may change a file concurrently with another task
that owns it, regardless of numbering or `[P]`.

### Exact Dependency Waves

- **US1**: T011, T012 and T013 follow T010. T012 is disjoint from T011/T013, which share one
  test file and must run sequentially. T014 follows all three red test tasks. T015 -> T016 ->
  T017 -> T018 -> T019 -> T020 is sequential integration.
- **US2**: Requires T020. T021 -> T023 share a test file; T022 is independent red test work.
  T024 follows all three test tasks. T025 may run alongside T024 (disjoint SQL/Python assets);
  T026 requires both. T027 -> T028 -> T029 -> T030 -> T031 -> T032 -> T033 follows sequentially.
- **US3**: Requires T010, not US1/US2. T034 -> T035 -> T036 share the ledger test file;
  T037 may run alongside them in separate execution test files. T038 follows all red tests.
  T039 -> T040 -> T041 -> T042 -> T043 -> T044 -> T045 follows sequentially. T042 must
  coordinate test-fixture ownership with any ongoing spatial work.
- **US4**: Requires T033 and T045. T046 and T047 are disjoint and may run together.
  T048 follows both. T049 -> T050 -> T051 follows, with the final tests using the integrated
  provenance/cutover behavior.
- **Polish**: T052 -> T053 -> T054 -> T055 -> T056 follows US4. If a check fails,
  fix only feature-caused issues and rerun the smallest relevant selection before escalation.

### Parallel Execution Examples

**US1**: Author T012 geometry/candidate expectations while T011 then T013 author adapter/type
tests. Do not split `testing\test_spatial_engines.py` between simultaneous writers.

**US2**: Author T022 workflow/candidate streaming tests while T021 then T023 author adapter and
resource/offline tests. After red tests, T024 adapter transfer and T025 SQL assets can run together;
T026 integration waits for both.

**US3**: Author T037 worker/coordinator tests while T034-T036 author ledger contract/crash tests.
Keep database runtime implementation in one owner; no concurrent edits to `od\ledger.py`.

**US4**: Author T046 legacy/reuse tests and T047 publication/provenance tests together after both
spatial and persistence checkpoints. T048 then integrates their actual handoff.

These examples authorize parallel work opportunities, not automatic subagent delegation.

## Implementation Strategy

### MVP First

Complete Setup and Foundation, then US1 for a testable small-data reference increment.
This is a correctness MVP, not a complete Feature 007 release: it does not claim large-data
resource acceptance or persistent-engine cutover. The plan's preferred storage-first sequence
may instead deliver US3 as the first independent P1 increment; it has its own lifecycle tests.

### Incremental Delivery

1. Freeze old behavior and amend governance before changing runtime geometry.
2. Deliver and validate portable resource policy/settings.
3. Prefer US3 durable storage next; no changes to candidate/network semantics.
4. Deliver US1 reference, then US2 bounded large-data behavior and exact resource evidence.
5. Deliver US4 provenance, fresh-state rebuild/reuse and operator/help consistency.
6. Complete cross-cutting regression/evidence. Do not release based on local passing probes,
   a DuckDB memory setting alone, skipped UI/resource tests or an unstated constitution exception.

## Requirement Coverage

| Requirements / success criteria | Tasks providing implementation and evidence |
|---|---|
| FR-001, FR-002 | T002-T004, T049-T051; amendment precedes code. |
| FR-003, FR-004, FR-008; SC-001 | T011-T020, T021-T022, T025-T030, T033; all geometry surfaces and bounded delegation. |
| FR-005, FR-006, FR-007; SC-003 | T006-T010, T019, T021-T024, T026-T030, T032; exact thresholds and measured accounting. |
| FR-009; SC-002 | T005, T013-T017, T024-T026, T034, T040, T043, T047-T048; exact types/values at boundaries. |
| FR-010, FR-011, FR-012, FR-014; SC-004 | T034-T045; transaction/WAL/lifetime ownership and strict preflight. |
| FR-013; SC-005 | T041, T046-T051; unchanged legacy files, fresh rebuild and exact compatible new-state reuse. |
| FR-015; SC-006 | T006, T010-T011, T014, T021-T023, T026, T030-T032, T039, T045, T049; portable/offline/errors. |
| FR-016 | T005-T006, T009, all story acceptance tasks, T053-T054; tests-first and integrated regression. |
| FR-017 | T003-T004, T049-T052, T055-T056; canonical guidance, dependencies, Pro help and final evidence. |

All 56 tasks start unchecked. `[P]` appears only on the five disjoint tasks described above;
task completion is not inferred from artifact creation or a quality-checklist marker.
