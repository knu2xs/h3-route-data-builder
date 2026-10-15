# Data Model: Spatial Data Engine Standardization

## EnginePolicy

Portable immutable settings, resolved through existing configuration inputs.

| Field | Domain / rule |
|---|---|
| policy_version | Literal `"1"`; unknown versions rejected. |
| memory_budget_bytes | Positive exact integer; default `min(1 GiB, available_memory_bytes // 4)`; minimum 64 MiB. |
| batch_target_bytes | Positive exact integer; default `min(64 MiB, memory_budget_bytes // 8)`; must not exceed budget/8. |
| duckdb_memory_limit_bytes | Default budget/2; positive, no greater than budget/2. |
| temp_directory | Configured scratch root, default `data/interim/engine-scratch`; unique run child, never raw/source/ledger directory. |
| max_temp_directory_bytes | Default `min(8 GiB, free_scratch_bytes // 4)`; minimum 128 MiB; explicit value must fit free space. |
| source | `inferred` or `set` for each resolved field. |
| resource_snapshot | Available memory and scratch-volume free bytes used during initial resolution. |
| estimator_version | Literal `"1"`; controls conservative estimate rules. |
| numerical_tolerances | Coordinate tolerance `1e-9` degrees; distance `1e-6` m; source measure `1e-12`. |

Reject booleans, strings and non-finite/fractional settings instead of coercing them. Validate
all cross-field bounds even for explicit settings. Tolerances are comparison tolerances, never
new eligibility thresholds or representative tie rules.

The budget is shared by spatial tasks in one coordinator, not independently allocated to each
thread. Run one spatial stage at a time initially. Preserve existing non-spatial preparation and
solve worker concurrency; do not give every worker another copy of the spatial budget.

## WorkloadEstimate

- `stage_key`: Stable operation/partition identity.
- `cell_count`, `edge_count`, `other_row_count`: Exact non-negative counts or unknown.
- `geometry_wkb_bytes`, `attribute_bytes`: Upper-bound encoded sizes or unknown.
- `max_record_bytes`: Largest input record including geometry.
- `pair_upper_bound`: Conservative candidate pair count, normally cell count times edge count.
- `estimated_working_set_bytes`: Formula from the engine contract, or null when unbounded/unknown.
- `provenance`: Source metadata upper bound or bounded streaming scan; never a sample extrapolated
  as a proven maximum.

Estimation includes both inputs and intermediate pair fan-out. Unknown estimate chooses DuckDB.
Oversized single records fail explicitly before DataFrame or query-result materialization.

## EngineDecision

- `stage_key`, `policy_version`, `estimator_version`.
- `selected_path`: `geoaccessor` or `duckdb`.
- `estimate`: WorkloadEstimate and resolved budget.
- `reason`: `fits_budget`, `exceeds_budget`, or `unknown_estimate`.
- `versions`: Python, Pandas, ArcGIS, ArcGIS Pro, DuckDB, Spatial binary where available, H3, package.
- `delegations`: Operation, bounded batch count, reason (`unsupported` or `semantic_equivalence`),
  ArcGIS capability, relevant settings/tolerances and completed/failed status.

Persist selection before execution, then append bounded summary evidence (not per-pair logs).
Resume restores decisions; explicit policy changes reject the existing run. Delegation selected
by the versioned operation capability map is reproducible; unavailable capability causes failure.

## SpatialBatch

- Required non-null integer `h3_id`, or directed `origin_h3_id`/`destination_h3_id` as appropriate.
- Source ID/OID, direction evaluator attributes and stable opaque record indices.
- Geometry as ArcGIS geometry in bounded GeoAccessor tables; WKB plus declared CRS at DuckDB/
  Arrow transfer boundaries.
- GeoAccessor H3 dtype `uint64`; Arrow H3 type non-null `uint64`; DuckDB H3 type `UBIGINT`.
- Required geometry/CRS validated before operations; unknown CRS is an error, not a default.

Record ordering is explicit numeric H3, then source ID/OID/name, then existing measure/tie rules.
No H3-bearing JSON object keys, inferred float columns, or identity reconstruction from paths.

## Run Engine Envelope

Extend existing run-manifest policy/provenance sections:

- `engine_metadata_version = "1"`.
- Saved EnginePolicy and resource provenance.
- Stable stage decisions and delegation summaries.
- Semantic engine compatibility digest.

Keep eligibility table schema 2 separate from this envelope version. Missing envelope is a
pre-feature working run and requires a new output root. Old completed publications are not
working runs and remain readable under the current publication contract.

Separate whole-run identity/provenance from reusable-result compatibility as defined below.
Record volatile resource observations as provenance; include resolved limits according to
existing fingerprint rules, not new timestamps. Restore saved policy before deriving the same build fingerprint.
Stable input discovery can find saved settings without incorporating current resource availability.

### Compatibility Digest Scope

Run identity/provenance retains the complete stage inventory, decisions, estimates, resource
observations and delegation/execution evidence. It may change during expansion without making
every prior result incompatible.

The canonical reusable-result payload contains:

- Existing network/travel/eligibility/candidate/solve semantic compatibility fields, unchanged.
- Engine metadata version, policy version, estimator version and operation-map version.
- Resolved compatibility-relevant limits and behavior settings under existing fingerprint rules.
- Producing operation dependencies, sorted by stable semantic operation role, each containing its
  selected path, behavior-relevant engine/capability versions and behavior settings. Include
  transitive producing operations; do not substitute the entire run's stage-decision list.

Serialize using the existing canonical fingerprint encoding. Exclude stage-instance/partition
identifiers, unrelated stage additions, estimates, volatile snapshots, timestamps, execution counts
and delegation completion status from the reusable-result digest; retain these in run provenance.
Adding a stage does not alone change an existing result's digest. A changed relevant producing
engine path/version/setting invalidates affected reuse under existing lifecycle rules, even if a
particular fixture happens to produce equal values. Determine affected dependencies conservatively;
missing dependency evidence cannot establish compatibility.

Acceptance covers unchanged prior decisions during expansion, added unrelated stages, and changed
engine decisions affecting previously completed work. Resume restores existing saved decisions;
these compatibility rules do not authorize silently reselecting an engine within an existing run.

## Durable Ledger Format 3

Keep `ODLedger` and its existing domain records. Backend metadata:

| Key | Required value / validation |
|---|---|
| engine | `duckdb` |
| format_version | `"3"` |
| h3_identity_encoding | `"2"` |
| work_id_encoding | `"2"` |
| max_attempts | Positive integer matching reopen request. |

Tables retain existing semantics:

- `work_items`: work ID primary key; compatibility; `origin_h3_id UBIGINT NOT NULL`; strict JSON
  numeric destination/expected-key arrays; cutoff/unit; state; attempts; fencing; lease;
  staged JSON/fencing/digest; committed reference; failure evidence.
- `ledger_metadata`: exact string key/value settings with a primary key.
- `committed_parts`: immutable part ID, work ID, checksum, payload JSON, commit time.
- `active_outcomes`: composite primary key `(compatibility_fingerprint, origin_h3_id,
  destination_h3_id)` with required `UBIGINT` endpoints and immutable-part reference/payload.
- `work_events`: sequence-generated `BIGINT` event key, work ID, from/to states, recorded time,
  details JSON. Sequence gaps are allowed; event order uses event ID.

Use application H3 validation even though DuckDB may cast bound numeric values to `UBIGINT`.
Do not rely on database casting to reject floats/bools/strings. Restore JSON through the same
strict validator and compare computed work IDs/expected keys.

State transitions remain Feature 003's exact `_ALLOWED_TRANSITIONS`:

```text
planned -> leased -> solving -> staged -> validated -> committed
active failures -> retryable_failure -> planned, or terminal_failure
planned/active/terminal/committed -> invalidated
invalidated -> planned only when still expected
```

This diagram is descriptive; existing per-state transition sets, lease renewal/reclaim,
attempt limits, stale fencing rejection and coordinator validation remain authoritative.
Commit atomically inserts an immutable part and active claims and advances the state/event.
Invalidation withdraws active claims but never edits an immutable committed part.

## Ownership and Lifetime

- One live canonical-path owner per process, additionally holding an OS sibling ownership-file
  lock for the complete preflight/open/transaction lifetime.
- DuckDB native locks enforce exclusion from other native writers.
- One creator PID and serialized coordinator connection; worker serialization/open attempts fail.
- `close()` is idempotent; context exit rolls back any pending transaction and releases connection,
  ownership lock and same-process registration even after an error.
- Second owner is rejected, never queued indefinitely or enabled by lock-file deletion.
- A crash releases OS locks. File existence alone does not block a legitimate restart.

SQLite header detection precedes ownership-file creation and DuckDB open. It preserves the entire
legacy directory snapshot. DuckDB candidate preflight checks an isolated database+WAL copy under
ownership, verifies stable source statistics, and validates schema/metadata before adopting state.
Incompatible/corrupt originals are preserved; preflight copies are specifically cleaned up.
