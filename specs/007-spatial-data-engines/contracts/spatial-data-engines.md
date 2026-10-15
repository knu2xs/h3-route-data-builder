# Contract: Spatial Engines and Durable Working Storage

## Scope

Internal builder contract plus the operator configuration surface. This does not change the
published schema or create a web API. It applies to source ingestion, AOI preparation,
eligibility, representative processing, candidate geometry, and the OD coordinator ledger.

## Configuration

Add `data_engines` under `environments.default` in `config/config.yml`.
All fields may be omitted for inferred defaults:

| Setting | Default / constraint |
|---|---|
| memory_budget_bytes | `min(1 GiB, initial available memory // 4)`; at least 64 MiB. |
| batch_target_bytes | `min(64 MiB, budget // 8)`; positive and at most budget/8. |
| duckdb_memory_limit_bytes | `budget // 2`; positive and at most budget/2. |
| temp_directory | Configured root, default `data/interim/engine-scratch`; resolve unique per-run child. |
| max_temp_directory_bytes | `min(8 GiB, initial scratch-volume free bytes // 4)`; at least 128 MiB. |
| coordinate_tolerance_degrees | `1e-9`, finite non-negative comparison tolerance. |
| distance_tolerance_m | `1e-6`, finite non-negative comparison tolerance. |
| measure_tolerance | `1e-12`, finite non-negative comparison tolerance. |

Use byte integers, not ambiguous MB strings, in persisted policy. Set DuckDB settings through
bound validated values or its connection configuration. Existing Principle XVII batch/part/cap
settings remain in force: effective batch size satisfies both existing row and new byte limits.
Do not add a toolbox parameter just to expose every internal setting; existing configuration
input suffices. Update operator-visible help to explain engine policy, prerequisites and cutover.

Fresh resource inference happens once. Saved policy wins on restart; changed explicit overrides
are refused for that run. A new resource snapshot is only a safety check: if it cannot support
the saved allocation/spill policy, fail with guidance, not a silently different engine.

## Selection and Estimation

For a spatial stage, estimator version 1 defines:

```text
base_bytes = geometry_wkb_bytes + attribute_bytes + 512 * input_row_count
estimated_working_set_bytes = 8 * base_bytes + 64 * pair_upper_bound
```

`input_row_count` covers both sides and AOI/helper records. `pair_upper_bound` includes potential
join/intersection results; use the full Cartesian count unless a stronger bound is proven.
An operation without pair production uses zero. Retained integer indexes and control arrays
count toward attributes/overhead; H3 generation/sorting must not bypass the budget.

Gather upper bounds from reliable metadata or bounded cursor scans, optionally writing WKB/
Arrow spool batches. Never load a complete DataFrame to choose an engine. A sampled average is
not an upper bound; unknown lengths/counts select DuckDB. Estimates at or below budget choose
GeoAccessor; larger/unknown estimates choose DuckDB.

Before allocating a conversion, split at row and byte limits. Include decoded geometry expansion
using the same conservative factor. A record that cannot fit alone fails with its stage/source
identifier. Do not recursively split forever. AOI union/dissolve must use bounded ArcGIS
geoprocessing on scratch storage when needed; refuse a final geometry too large to operate on
safely, rather than gathering every source geometry into a list.

## Small Spatial Path

- Construct bounded spatially enabled tables through `arcgis.features.GeoAccessor`.
- Required identity fields are explicitly `uint64` before and after joins/overlays.
- Perform small spatial operations through GeoAccessor/GeoSeries; use approved ArcGIS geometry
  capabilities for exact projection, dimensional intersections, geodesic and measure operations.
- Require ArcPy availability and test operations with open-source geometry fallback blocked.
  `ARCGIS_IO_ENGINE=arcpy` may control feature I/O where supported; it is not proof that all
  geometry computation uses ArcPy.
- No direct GeoPandas/Shapely/pyproj imports or fallback. No remote GIS authentication/service
  request is needed for the local source paths covered by this builder.

## Large Spatial Path

- Load installed Spatial only for spatial stages, on explicitly configured local connections.
- Stream network source cursors and Arrow/WKB batches into temporary DuckDB tables. Do not
  `list()` all edges, `.fetchall()` a full spatial join, or `.df()` a large result.
- Preserve numeric H3 ordering via SQL ordering/external sort. Stream candidate H3 generation
  and partition windows where complete ID collections would exceed the budget.
  Bound allocations before invoking H3 APIs that return complete collections: generate candidates
  from conservatively bounded spatial partitions, persist/deduplicate IDs in DuckDB, and apply
  existing exact membership rules. Partition geometry, cover results, deduplication buffers and
  retained candidate/scope IDs all count toward the shared budget. Full-cover generation followed
  by batching or external sorting is not bounded generation.
  Before implementation, document why partition coverage and size bounds preserve every reference
  candidate, including boundary duplicates and antimeridian cases. Verify exact equality against
  tractable reference covers; fail explicitly if a safe bound cannot be established. A sampled
  count is not proof. Preserve existing small list-returning helpers; use internal disk-backed
  processing for large paths without rebuilding complete endpoint tuples downstream.
- Query/filter/reduce in DuckDB, consuming bounded record batches in stable cell/source order.
  Do not retain every pair/intersection for a high-degree cell; incrementally reduce candidates
  using existing representative rank rules and spill evidence as needed.
- Use only verified-equivalent predicates as exact exclusions. Unproved topology/CRS/antimeridian
  cases use conservative candidate envelopes followed by exact bounded ArcGIS checks. Every
  retained reference match must survive the prefilter.
- Delegate exact representative nearest/source-measure, geodesic AOI buffer/offset and ambiguous
  dimensional topology operations to bounded GeoAccessor/ArcPy batches. Record operation/reason,
  versions, limits, counts and failures. Delegation cannot silently become the entire in-memory
  pipeline or waive the budget.
- If a configured operation, capability or single-record size is unsupported, fail before
  authoritative output; no automatic switch to a third engine or unrequested library upgrade.

## Memory and Disk Acceptance

The configured budget covers shared spatial-stage working data. It is not a promise that total
ArcGIS Pro/Network Analyst RSS stays below that number. DuckDB's buffer limit alone does not
bound its client arrays, geometry allocations or every query operator.

Use all of the following:

1. Track simultaneous converted batch bytes, input/decoded-geometry estimates, result buffers
   and reducer state; refuse an allocation that would exceed the stage budget.
2. Limit DuckDB buffer manager to budget/2 and all conversion batches to their shared budget;
   serialize spatial stages initially. Stream results rather than nested `list` aggregates.
3. Set unique `temp_directory` and `max_temp_directory_size`; preflight free space and report
   spill exhaustion. Persistent ledger storage growth is also checked, not misreported as spill.
4. In an isolated warmed child process, sample Windows working set every 20 ms with ctypes and
   report peak delta from a post-import baseline; also assert internal accounted peak <= budget.
   The large fixture must exceed budget in encoded input size and complete without whole-table
   client materialization. Its peak process working-set delta must be <= `2 * budget + 64 MiB`.
   Report both metrics; do not substitute one for the other or claim the sampler catches every
   instantaneous allocation. Use a 128 MiB budget and at least 256 MiB encoded input for this
   acceptance fixture, with a 4 GiB scratch allocation and enough available local disk.
5. An injected oversized record, excessive pair fan-out, allocation overrun or spill write error
   must fail explicitly and leave the run incomplete. Fixture sizes are acceptance controls,
   not throughput promises.

## Semantic Equivalence

Compare both paths against fixed pre-change fixtures, not just each other:

- Exact eligible cell membership, directed reverse/self keys, classifications, source ID/OID,
  representative choice and ordering.
- Same restrictions, direction evaluators, inclusive touch policy, cutoff and sparse pruning.
- Same declared CRS/datum transformations and geodesic-meter interpretation.
- Coordinate comparisons <= `1e-9` degrees, distance <= `1e-6` m, source measure <= `1e-12`.
  These do not change existing `snap_tolerance_m`, ties, or acceptance decisions. If numerical
  differences change a discrete choice, delegate the operation or fail; do not widen tolerances.
- Exact integer identity round-trips at all 16 resolutions, including pentagons and greatest
  valid samples; typed null/float/text/bool rejection remains.

## Ledger Public Boundary

Preserve constructor arguments and existing lifecycle methods:
`ODLedger(database_path, max_attempts=3)`.

Add explicit idempotent `close()` and context-manager support. A closed handle rejects calls.
Reuse after close requires a new instance. Update in-repository callers to close deterministically.
Retain current work-ID encoding 2, result fields, legal transitions and method return shapes.

### Open and Ownership

1. Normalize the path and inspect an existing file header without opening a database engine.
   Detect SQLite independently of suffix; refuse it without creating files or touching sidecars.
2. For a fresh or DuckDB candidate, acquire an OS sibling ownership-file lock and same-process
   canonical-path guard; retain both through preflight and lifetime. Lock conflict is actionable,
   not a retry loop or timestamp-based stale-lock deletion. Use standard-library Windows locking
   and the corresponding OS lock for portable test platforms.
3. For an existing DuckDB file, snapshot DB and any WAL under ownership, verify source
   size/mtime stability and no WAL appearance/disappearance, and recover/inspect only the copy.
   Verify format 3, engine, retry policy, all required tables/columns/types/keys and restored
   domain values. Incompatible originals are not opened for writes.
4. Open the validated source using native DuckDB locks, automatic extension install/load disabled.
   The ledger never loads Spatial. On fresh creation initialize schema/metadata transactionally.
5. Reject different creator PID, duplicate same-process owner, serialization of live handles,
   or second-process writer. Workers receive neither path nor connection. Native non-cooperating
   writers are excluded by DuckDB while the source is open; arbitrary external file tampering is
   not supported.
6. Close before releasing locks; clean only named owned scratch paths. A leftover unlocked
   ownership file is harmless and is not deleted to decide ownership.

### Transaction and Result Acceptance

- A coordinator lock serializes transactions. Use `BEGIN TRANSACTION`, explicit rollback on
  exceptions, commit only after complete validation, and surface DuckDB errors with context.
- Use typed record mapping from cursor description/results, not `sqlite3.Row`.
- Bound parameters for all values and load external SQL through `load_sql()`. Fixed identifiers
  are repository-owned constants; do not interpolate source input into identifiers.
- Commit the immutable part JSON/checksum, unique active-key claims and work/event state in
  one database transaction. No side filesystem publication is added to ledger commit.
- Fail conflicting active logical-key claims; never replace or merge them silently.
- Invalidation removes active claims, not old immutable parts. Test delete/reinsert and
  invalidation/recommit against DuckDB index constraint behavior.
- Sequence event IDs may have gaps. Persist retry limits, attempts, leases and fencing exactly.
- Killed-process recovery must use native WAL replay. Do not delete WALs to make a test pass,
  use `immutable` shortcuts that ignore them, or treat graceful close as crash evidence.

## Extensions and Dependencies

Set `autoinstall_known_extensions=false` and `autoload_known_extensions=false` for builder-owned
DuckDB connections, including existing publication query connections. Issue `LOAD spatial`
only when a spatial operation needs it. Tests must prove zero `INSTALL`, remote extension
download or network fallback during builds.

Environment setup may run an explicit operator-approved installation with a binary matching the
DuckDB version/platform. Document signed local-file installation for offline environments.
Check loaded function capabilities at spatial entry and log an actionable setup failure.
Non-spatial imports and ledger tests must work with Spatial and ArcGIS imports blocked.

## Provenance, Compatibility and Failures

Persist engine metadata version 1 in run envelopes, alongside the existing table schema identity.
Restore saved settings before re-deriving fingerprints. Missing/unknown metadata requires fresh
working state, not adopting rows by counts/paths. Keep historical publication bytes unchanged.

Engine-policy/estimator/operation-map versions, resolved settings and behavior-relevant engine
versions enter compatibility. Use the canonical result-scoped payload defined in the
[data model](../data-model.md#compatibility-digest-scope); whole-run stage inventory is provenance,
not a reusable-result dependency. Resource snapshots and delegation evidence remain auditable.
New-format AOI reuse is allowed only when existing network/travel/eligibility/candidate/solve
compatibility rules plus the engine compatibility digest agree.

Prerequisite, memory, spill, geometry, ownership, transaction and corrupt-state failures receive
stage/path context in repository-standard logs and exceptions. If a run exists, record its
failure evidence through the coordinator. No `_SUCCESS`, misleading empty table or incomplete
commit is a permitted error fallback.
