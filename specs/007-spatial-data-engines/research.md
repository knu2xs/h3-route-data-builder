# Research: Spatial Data Engine Standardization

**Date**: 2026-10-15

## Decision: Amend Governance Before Runtime Changes

- **Decision**: Propose constitution 3.0.0, redefining builder-specific Principle II and expanding
  VIII/Technology Constraints for GeoAccessor, DuckDB Spatial, bounded delegation and native
  DuckDB persistence. Preserve principles I and III-VII and IX-XVII in intent.
- **Rationale**: Constitution 2.0.1 already mentions GeoAccessor/DuckDB in VIII but II still
  mandates ArcPy for eligibility geometry. The user's explicit policy supersedes that design
  intent only through a governed amendment, not by pretending the conflict is already resolved.
- **Alternatives considered**: Patch clarification is insufficient for a redefined principle;
  retaining ArcPy-only eligibility contradicts the confirmed scope.

## Decision: Exact Typed Interchange, Not Inference

- **Decision**: Required Pandas H3 columns use `uint64`, Arrow uses non-null `pa.uint64()`, DuckDB
  uses `UBIGINT`. Nullable ancillary integer fields use explicit nullable dtypes; reject missing
  identities. Validate exact Python `int` and H3 identity before conversion, then verify dtypes
  and values after every adapter. Use Arrow batches rather than inferred DataFrame interchange.
- **Rationale**: Valid H3 cells fit signed int64 today but the canonical storage contract is
  unsigned 64-bit. Dtype inference, nullable mixed columns, JSON object keys, feature-class
  floating fields and `iterrows()` can lose exactness or change scalar types.
- **Alternatives considered**: Text/float aliases violate Feature 006; deprecated DataFrame
  interchange APIs are unnecessary; a geodatabase H3 field is not required for temporary labels.
- **Sources**: [Arrow/Pandas integration](https://arrow.apache.org/docs/python/pandas.html),
  [Pandas Arrow integration](https://pandas.pydata.org/docs/user_guide/pyarrow.html),
  [DuckDB numeric types](https://duckdb.org/docs/stable/sql/data_types/numeric.html).

## Decision: GeoAccessor with Verified ArcGIS Geometry Capability

- **Decision**: Lazy-import `arcgis.features` and Pandas inside `network/spatial.py`; explicitly
  validate ArcPy/ArcGIS geometry availability before operations. Use GeoAccessor/GeoSeries spatial
  operations on bounded tables and preserve typed non-geometry columns separately from opaque
  feature transport. Use ArcPy for required geoprocessing and exact representative operations.
- **Rationale**: GeoAccessor can use more than one geometry/I/O engine. Merely importing it does
  not prove the operation uses ArcGIS. Local package docstrings distinguish `ARCGIS_IO_ENGINE`
  from geometry execution: do not invent an environment variable that forces every operation.
  Capability tests must make Shapely fallback fail and prove the selected operations still work.
- **Alternatives considered**: Private `_HASARCPY` flags alone are insufficient as an application
  contract; direct Shapely/pyproj and GeoPandas are prohibited.
- **Source**: [Esri SEDF introduction](https://developers.arcgis.com/python/latest/guide/introduction-to-the-spatially-enabled-dataframe/).
- **Local evidence**: ArcGIS 2.4.3.1 reports geometry availability `(True, False)` in this clone;
  one GeoAccessor point table retained `uint64` exactly. Full joins, projection, overlays, dtype
  retention and compatibility with Pandas 3.0.0 still require implementation acceptance tests.

## Decision: Conservative Large-Data Prefilters, Exact ArcGIS Delegation

- **Decision**: Use DuckDB 1.3.2 Spatial for bounded typed filtering/intersection candidates.
  Use conservative envelopes where reference semantics might differ; never exclude a pair from
  an unproved predicate. Stream exact ArcGIS validation for dimensional boundary intersections,
  ambiguous topology, geodesic AOI offsets/buffers and nearest/source-measure representatives.
  Record each delegated operation and reason; reduce candidates with the existing tie ordering.
- **Rationale**: Planar geometry distance in geographic coordinates is not geodesic meters.
  Installed capabilities, not the latest documentation's function list, define available APIs.
  Arbitrary large joins and high fan-out still need streaming even if an index is available.
- **Alternatives considered**: Full DuckDB-only nearest/geodesic replacement risks changed
  representatives; an unbounded ArcGIS fallback violates the confirmed clarification.
- **Source**: [DuckDB Spatial functions](https://duckdb.org/docs/stable/core_extensions/spatial/functions.html).
- **Local evidence**: `ST_Intersects`, `ST_Intersection` and `ST_Distance_Spheroid` exist after
  loading installed Spatial. `ST_ClosestPoint` was not in the queried function set. Do not add
  a DuckDB upgrade to obtain it; delegate nearest-point/source-measure work instead.

## Decision: Resource Policy 1 with Accounted Headroom

- **Decision**: Reuse `ResourceSnapshot`, leave Principle XVII's existing inference untouched,
  and add separate `data_engines` policy version 1. See the contract for exact settings/formulas.
  Default spatial budget is one quarter of available memory, capped at 1 GiB, with a 64 MiB
  minimum to run. Explicit budgets take precedence. Use bounded streaming estimates that include
  geometry, retained attributes and worst-case pair fan-out; unknown bounds select the large path.
- **Rationale**: DuckDB `memory_limit` is not a process-wide cap. Geometry objects, vectors,
  client result batches and ArcGIS/Pandas allocations also need headroom and instrumentation.
  A claimed hard RSS ceiling from `SET memory_limit` would be false.
- **Alternatives considered**: Full input sampling into a DataFrame defeats the purpose;
  row-count-only thresholds ignore geometry size/fan-out; automatic retry on a different engine
  after memory failure risks inconsistent resume and concealed failure.
- **Sources**: [DuckDB memory guidance](https://duckdb.org/docs/stable/guides/performance/how_to_tune_workloads.html),
  [configuration](https://duckdb.org/docs/stable/configuration/overview.html),
  [OOM troubleshooting](https://duckdb.org/docs/stable/guides/troubleshooting/oom_errors.html).

## Decision: One Lifetime-Owned DuckDB Ledger

- **Decision**: Keep `ODLedger` as the public boundary, replacing SQLite completely. Hold one
  connection for its explicit lifetime; reject duplicate canonical-path owners in the same
  process and rely on DuckDB native locks to exclude other writer processes. Serialize
  coordinator calls, guard creator PID, and make live handles non-serializable. Add close/context
  lifecycle and update callers/tests to release before reopening.
- **Rationale**: Current SQLite opens/closes per method; blindly porting that allows competing
  coordinators to alternate ownership. DuckDB's native read-write model is single-process.
  Monitoring during builds must go through coordinator snapshots, not a second file connection.
- **Alternatives considered**: Multi-process writers, server/Quack/DuckLake, and dual backend
  abstractions are out of scope. A transient connection per query does not hold ownership.
- **Source**: [DuckDB concurrency](https://duckdb.org/docs/stable/connect/concurrency.html).

## Decision: Preserve Transactional Parts and Strict Constraints

- **Decision**: Format 3 stores the existing five ledger tables with `UBIGINT` endpoints and
  explicit `NOT NULL`/primary keys; use a sequence for monotonic event IDs. Preserve staged JSON
  and immutable committed payload/checksum records inside the database. One transaction inserts
  a committed part, its unique active outcomes, and committed work state/event.
- **Rationale**: Current ledger parts are database payloads, not external files. Keeping them
  avoids introducing a new cross-filesystem commit protocol during an engine change.
  `BEGIN IMMEDIATE`, SQLite row factories, `typeof` checks and PRAGMAs must be replaced, not
  mechanically copied. DuckDB constraint/update corner cases require targeted tests.
- **Alternatives considered**: Moving parts to external files adds unrelated atomicity work;
  `INSERT OR REPLACE` can hide conflicting claims. Avoid unnecessary foreign keys and SQLite
  auto-increment assumptions; preserve key constraints and semantic validation.
- **Sources**: [transactions](https://duckdb.org/docs/stable/sql/statements/transactions.html),
  [constraints](https://duckdb.org/docs/stable/sql/constraints.html),
  [sequences](https://duckdb.org/docs/stable/sql/statements/create_sequence.html),
  [storage/WAL](https://duckdb.org/docs/stable/internals/storage.html).
- **Validation decision**: Prove abort/reopen/WAL recovery using killed child processes on
  temporary databases, not graceful-close tests alone. Gaps in sequence IDs are legal.

## Decision: Refuse Legacy State Without Opening It for Mutation

- **Decision**: Inspect file headers before DuckDB connect; SQLite's magic header triggers a
  logged fresh-location refusal regardless of suffix. Preserve all legacy sidecars. Existing
  DuckDB state receives isolated database+WAL snapshot preflight with original ownership held,
  schema/metadata validation and recovery on the snapshot; source compatibility is checked
  before its authoritative read-write connection is opened. An ambiguous/unstable snapshot,
  corrupt file or unsupported format fails explicitly.
- **Rationale**: Feature 006 tests already showed that even SQLite read-only open can create
  sidecars. Do not use SQLite to inspect legacy state or ignore a DuckDB WAL during validation.
  Close/release the temporary preflight handle before opening the authoritative database.
- **Alternatives considered**: Automatic migration conflicts with the user's confirmed lossy
  pre-alpha choice; extension-based detection can adopt a renamed legacy file.
- **Design constraint**: Protect snapshot/authoritative-open handoff with a coordinator ownership
  lock held across preflight and ledger lifetime. Use a Windows OS file lock on a new sibling
  ownership file for DuckDB candidates, plus DuckDB's native lock; release on close/crash.
  Header-rejected SQLite candidates create no such file. Same-process canonical-path guard
  handles Windows lock semantics. Never remove another process's lock file based on timestamps.
  The ownership file's mere existence is not evidence of a live owner; the OS lock is.

## Decision: Setup-Only Extension Provisioning

- **Decision**: Build connections disable `autoinstall_known_extensions` and
  `autoload_known_extensions`; issue `LOAD spatial` only in spatial adapters. Environment
  setup may explicitly install a matching official signed extension or an approved local file.
- **Rationale**: Extension binaries must match DuckDB version/platform. Offline execution must
  not discover a runtime download requirement or substitute another geometry stack.
- **Alternatives considered**: Runtime `INSTALL` and opt-in runtime downloads were rejected by
  the user. The non-spatial ledger does not require Spatial.
- **Sources**: [Spatial setup](https://duckdb.org/docs/stable/core_extensions/spatial/overview.html),
  [offline installation](https://duckdb.org/docs/stable/extensions/advanced_installation_methods.html).

## Local Feasibility Evidence and Limits

Probes used `env\python.exe` on 2026-10-15 without dependency changes, source-data writes or
runtime extension installation:

- DuckDB 1.3.2; Pandas 3.0.0; ArcGIS 2.4.3.1; H3 4.5.0; PyArrow module 22.0.0.
  PyArrow distribution metadata was unavailable despite a working import; report module version
  rather than incorrectly treating it as a missing package.
- All 16 sampled resolution IDs round-tripped exactly through Pandas `uint64`, Arrow and DuckDB.
- `LOAD spatial` succeeded with auto-install/autoload disabled; extension was already installed.
- An explicit transaction update rolled back to `planned`.
- GeoAccessor retained an above-`2^53` H3 identity in a small geometry table.

These are not completed feature acceptance tests. Crash recovery, competing ownership, memory,
full geometry equivalence and real-network integration remain mandatory implementation validation.
No unresolved technology choice is delegated to the implementer; capability failures must be
reported and the plan revisited rather than hidden by an unapproved package upgrade.
