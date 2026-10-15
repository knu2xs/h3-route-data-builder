# Validation Guide: Spatial Data Engine Standardization

## Status and Prerequisites

This is the planned implementation acceptance guide, not a record of completed feature tests.
New tests listed below must be authored during implementation before their corresponding code.
No runtime code, dependencies or constitution were changed by `/speckit-plan`.

- Use the configured ArcGIS Pro clone at `env\python.exe`, with ArcPy and Network Analyst for
  spatial/solve integration.
- Install the reviewed project spatial extra/environment changes before spatial acceptance.
  Do not install arbitrary upgrades to work around a capability failure.
- Provision the matching signed DuckDB Spatial binary during environment setup, including
  offline/local-file instructions where required. Builds never execute `INSTALL`.
- Use only temporary synthetic source fixtures and outputs. The optional configured StreetMap
  dataset is read-only.
- Before conflicting implementation begins, complete the separate
  [constitution-update workflow](contracts/constitution-amendment.md) and required PR governance.
  Record the amendment PR and enacted version; local text preparation alone does not release this gate.
- Reserve local scratch space; resource acceptance needs at least 4 GiB configured scratch capacity
  plus room for fixture files, and a 128 MiB spatial budget. Raw data is never a scratch target.

See the [engine/storage contract](contracts/spatial-data-engines.md) for settings, exact budgets,
semantics, ownership and failure rules, and [data model](data-model.md) for record shapes.

## Establish the Baseline

From the repository root, before code changes:

```powershell
& .\env\python.exe -m pytest testing\test_eligibility_geometry.py testing\test_network_eligibility.py testing\test_od_candidate_geometry.py testing\test_od_candidates.py testing\test_od_ledger.py testing\test_od_solver.py -q --tb=short
```

Record exact eligible-cell IDs, representative source/measure/coordinates, directed keys,
classifications, costs and evidence in deterministic fixtures. Test each engine against those
expectations, not solely against the other newly implemented engine.

Prior Feature 006 evidence is context, not a fresh baseline: full suite had 331 passes and one
known real-network `caplog` logging-order failure; its final focused acceptance had 81 passes.
Reproduce and identify existing failures separately rather than weaken feature acceptance.

Feature 007 pre-change baseline on 2026-10-15:

- Interpreter: Python 3.13.13; DuckDB 1.3.2; Pandas 3.0.0; ArcGIS API for Python 2.4.3.1;
  H3 4.5.0; PyArrow 22.0.0.
- DuckDB Spatial is installed (`c5744ee`) but was not loaded during this non-spatial baseline.
- The command above completed with **116 passed in 25.83 seconds**.
- The separately known full-suite real-network logging-order `caplog` failure was not exercised by
  this selection; it remains a known baseline issue and is not treated as a Feature 007 result.

## Portable Policy and Durable Storage

After authoring the planned tests:

```powershell
& .\env\python.exe -m pytest testing\test_data_engines.py testing\test_od_ledger.py testing\test_od_candidate_ledger.py testing\test_od_execution_config.py testing\test_od_execution.py testing\test_od_execution_preparation.py testing\test_od_execution_workers.py -q --tb=short
```

Required outcomes:

- Below/equal/above-budget and unknown estimates choose the prescribed path before a full spatial
  table exists. Invalid limits/oversized records fail. Saved policy beats changed resources;
  incompatible explicit overrides fail instead of changing a resumed run.
- ArcGIS/ArcPy imports and Spatial loading are actively blocked during portable tests.
- A fresh format-3 DuckDB ledger uses `UBIGINT`, strict models/JSON and the exact endpoint domain.
  Close/reopen restores values at all resolutions without float/text conversions.
- Kill child processes at all lifecycle boundaries and immediately before/after transaction commit.
  Recover with actual WAL replay and prove no missing committed outcome/duplicate logical key.
  Include graceful-close tests, but never substitute them for killed-process recovery.
- Hold a live coordinator while a second spawned process tries the same database. It must fail
  clearly without mutation. Same-process duplicate handles, different-PID use and serialization
  of live handles are also refused. An unlocked leftover ownership file permits valid restart.
- Exercise lease expiry/reclaim, renewals, stale fencing, invalid staged keys/digests, transaction
  rollback, retries/terminal failures and idempotent commit.
- Invalidate and recommit, proving active claims change but historical committed parts do not.
  Use multi-row/chunk cases to expose DuckDB index/constraint differences from SQLite.
- Include corrupt/missing/wrong-format metadata, schema/type/primary-key mismatches and pending
  WALs in preflight acceptance; incompatible original files remain unchanged.
- SQLite fixtures include clean DB, WAL/SHM/journal sidecars and misleading file extensions.
  Snapshot bytes and directory membership before/after refusal. Require zero changes and
  separate-fresh-location guidance, without SQLite runtime persistence.
- Fresh-state AOI expansion reuses exactly the compatible new-format completed pairs and
  schedules only new/invalidated pairs. No legacy work is claimed as reused.

## Spatial Equivalence and Delegation

```powershell
& .\env\python.exe -m pytest testing\test_spatial_engines.py testing\test_eligibility_geometry.py testing\test_network_eligibility.py testing\test_od_candidate_geometry.py testing\test_od_solver.py -q --tb=short
```

Require reference equality for crossing/touch, non-intersection, restrictions/direction,
disconnected inputs, representative ties, CRS/projection, empty/invalid geometry and antimeridian
fixtures. Test all required engine entry points:

- AOI validation/projection/union.
- H3 polygon and centroid creation and cell-edge filtering/intersection.
- Nearest representative/source-measure/snap decisions and location handoff.
- Candidate AOI membership, geodesic offsets and surrounding expansion.

Valid empty datasets/zero planned work must reconcile without unnecessary spatial execution.
Empty/invalid individual geometry and missing CRS fail explicitly unless an existing rule defines
otherwise. Valid antimeridian fixtures must preserve reference semantics, not fail merely for
crossing the antimeridian. Unsupported operations delegate under policy or fail actionably.

For small fixtures prove actual GeoAccessor spatial operations execute, with Shapely fallback
blocked. A typed table wrapped around the unchanged pipeline is not acceptance.
For large fixtures prove actual DuckDB filtering/query execution and bounded batch transfer;
delegation must be explicit, scoped and recorded. Include one forced unsupported operation and
one semantic-equivalence delegation case.

Compare coordinates at `1e-9` degrees, distances at `1e-6` m and source measures at `1e-12`.
Discrete membership/representative/key/classification differences are failures regardless of
those tolerances. Do not widen tolerances after seeing a mismatch.

At every applicable Pandas/GeoAccessor/Arrow/DuckDB/manifest/worker boundary, compare exact
integer values across resolutions 0-15, including pentagons, greatest valid samples and values
above `2^53`. Required H3 null/bool/float/text inputs must be rejected; nullable ancillary
integer attributes must not coerce identity columns.

## Resource and Offline Failure Acceptance

The planned `test_spatial_engines.py` tests use `resource_`, `offline_`, and `delegation_` in
their names so the expensive acceptance group can be selected without a new runner:

```powershell
& .\env\python.exe -m pytest testing\test_spatial_engines.py -k "resource_ or offline_ or delegation_" -q --tb=short
```

- Generate a synthetic input of at least 256 MiB encoded data, with a 128 MiB policy budget and
  4 GiB permitted scratch usage. No source files outside temporary fixtures are changed.
- Instrument whole-input materialization calls and all retained byte-accounted structures.
  Require zero whole-input client tables, accounted peak <=128 MiB and warmed child-process
  working-set delta <=320 MiB, sampled every 20 ms. Record baseline, delta, input size, batch
  sizes and actual DuckDB settings; a passed buffer limit alone is insufficient evidence.
- Stress high edge fan-out, one oversized geometry, unknown source sizes, multiple source
  partitions and candidate ID sorting. Neither source lists nor per-cell candidate arrays may
  grow without limit.
- Exceed the budget with candidate IDs alone; trap full H3 cover allocation before batching and
  full endpoint/scope reconstruction afterward. Account for partition geometry and cover results,
  verify partition-boundary deduplication and antimeridian completeness, and compare exact sets
  against tractable reference covers. Record the conservative allocation/coverage justification.
- Test AOI expansion with unchanged prior producing decisions, added unrelated stages and changed
  relevant producing engine choices. Require exact compatible reuse or affected-work invalidation
  according to the result-scoped digest, not the entire run's stage inventory.
- Inject memory-budget refusal, insufficient scratch, spill failure and ledger disk-write failure.
  Require explicit errors, durable completed work retained, incomplete evidence and no `_SUCCESS`.
- Simulate missing Spatial and unavailable ArcGIS capability, with outbound download/network
  attempts trapped. Require zero runtime `INSTALL` or extension downloads and actionable errors.
- Confirm non-spatial persistent ledger/query operations still work when Spatial cannot load.

## Publication, Pro Help and Complete Regression

```powershell
& .\env\python.exe -m pytest testing\test_publication_schema.py testing\test_publication_conversion.py testing\test_publication_interoperability.py testing\test_publication_publish.py testing\test_publication_validation.py testing\test_real_network_dataset.py -q --tb=short
& .\env\python.exe -m pytest -q --tb=short
```

Validate serial/parallel/fallback equivalence, current schema versions and uint64 columns,
manifest engine provenance, logical uniqueness/membership and atomic publication.
Historical publications must have unchanged bytes/checksums.
Run existing toolbox metadata tests and verify updated tool/parameter help in the Pro UI;
record unavailable UI access as a gate, not a passing check.

Use existing Black checks on changed Python files at line length 100, compilation, configured
diagnostics when available and `git diff --check`. Report unrelated formatting/logging baseline
issues separately; do not refactor them to force a green result.

## Requirement and Success-Criterion Evidence Map

| Requirements | Required evidence |
|---|---|
| FR-001, FR-002, FR-017 | Amended governance, guidance/dependency review, supersession notes and updated Pro/XML help. |
| FR-003, FR-004, FR-008; SC-001 | All geometry entry points exercised, GeoAccessor reference path, DuckDB path, bounded exact delegation, fixed reference fixtures/tolerances. |
| FR-005, FR-006, FR-007; SC-003 | Policy boundaries, saved decisions, conservative estimator, >budget input, memory observations, byte/spill accounting and overrun failures. |
| FR-009; SC-002 | Exact identity/domain/dtype/JSON/spawn tests at every resolution and boundary. |
| FR-010, FR-011, FR-012, FR-014; SC-004 | Format-3 native database, strict preflight, transaction/WAL crash recovery, ownership, leases/fencing, claims and immutable parts. |
| FR-013; SC-005 | Byte/directory-preserving SQLite refusal, fresh rebuild, new-state resume/expansion and historical publication immutability. |
| FR-015; SC-006 | Portable blocked-import tests, setup-only extension provisioning, zero downloads, actionable error evidence and no success-shaped fallback. |
| FR-016 | Combined lifecycle, resource, geometry, offline, storage and configured-network coverage above. |

## Planning-Phase Evidence

Recorded 2026-10-15 with no package changes:

- Pandas 3.0.0, ArcGIS 2.4.3.1, DuckDB 1.3.2, H3 4.5.0 and PyArrow module 22.0.0 are available.
- A GeoAccessor point table retained a `uint64` above-`2^53` H3 value; ArcPy geometry capability
  was available and Shapely was reported unavailable.
- Sixteen resolution samples round-tripped exactly through Pandas/Arrow/DuckDB.
- Installed Spatial loaded with automatic installation/loading disabled.
- A transaction update rolled back correctly.

Full feature tests above have not been run or claimed passing during planning.
