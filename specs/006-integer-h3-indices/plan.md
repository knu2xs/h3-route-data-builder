# Implementation Plan: Integer H3 Index Standardization

**Feature context**: `006-integer-h3-indices` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

Spec Kit resolves this feature through `.specify/feature.json`; the actual Git branch is `main`.
This planning pass does not create or switch a branch.

**Input**: Feature specification from `specs/006-integer-h3-indices/spec.md`

## Summary

Standardize builder-owned H3 cell identity, directed OD keys, durable working state, and newly
published fields on exact integer H3 indices. Use `h3.api.basic_int` rather than repeated
hexadecimal conversions. Confine text-only integration labels to their external boundary.
Preserve candidate, route, and lifecycle semantics,
version the incompatible published/shared contract, and coordinate the solver consumer update.
Since the project is pre-alpha, reject legacy hexadecimal-keyed working ledgers and rebuild into a
new ledger when explicitly requested; never silently delete the prior ledger. Keep existing
published datasets immutable and identifiable as historical schemas.

## Technical Context

**Language/Version**: Python 3.11+; ArcGIS Pro environment currently uses Python 3.13.

**Primary Dependencies**: Existing `h3>=4.0`, PyArrow, DuckDB, ArcPy, and Network Analyst. No new
dependency is anticipated.

**Storage**: SQLite-backed Feature 003 ledger; Arrow/Parquet/GeoParquet staged and published
records; JSON manifests and run metadata; shared builder-solver contract.

**Representation**: Python `int` for validated cells, `tuple[int, int]` for directed keys,
SQLite `INTEGER` for indexed endpoints, and Arrow `uint64` for staged/published H3 columns.
Valid H3 cells have their high bit clear and fit SQLite's signed 64-bit storage; arbitrary uint64
values are not valid endpoints. JSON uses integer-valued fields/arrays, not H3-keyed objects.

**Testing**: Pytest; portable tests for identity, candidate/ledger state, conversion boundaries,
and schemas; ArcPy-marked integration tests only for network/geometry adapters.

**Target Platform**: ArcGIS Pro builder on Windows; portable shared-contract consumers, including
constrained edge devices.

**Project Type**: Python `src/` package, ArcGIS Pro toolbox, immutable data publication contract.

**Performance Goals**: Integer representation aims to reduce storage, comparison, and transfer
overhead, particularly for edge consumers. No numeric performance or latency target is in scope.

**Constraints**: Preserve cell membership, candidate selection, OD semantics, route outcomes,
deterministic ordering, resumability of new-format work, serial/parallel parity, and atomic
publication. Do not use GeoPandas. Do not rewrite historical publications. Do not automatically
delete, translate, or resume legacy hex-keyed ledgers.

**Scale/Scope**: All builder-owned H3 indices, keys, working records and new publication fields;
the builder's shared data contract and coordinated solver-consumer contract. No phone application
or device-specific client implementation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Plan assessment |
|---|---|---|
| I. Explicit Semantics | Pass | Integer domain, field names, schema version, and compatibility behavior are specified. |
| II. Builder ArcPy Geometry Boundary | Pass | Identity validation remains portable; external-library conversions stay in narrow adapters. |
| III. Sparse Correctness | Pass | Eligibility and candidate membership do not change. |
| IV. Immutable Reproducibility | Pass | New schema/contract identity participates in compatibility; historical publications stay immutable. |
| V. Idempotent Resumability | Pass with approved pre-alpha reset | New-format work remains resumable. Legacy hex ledgers are rejected; new runs use a separate ledger and rebuild. |
| VI. Approximation Transparency | Pass | Distance, time, and route-cost semantics do not change. |
| VII. Bounded Execution | Pass | Candidate, batch, solve, and publication limits are unchanged. |
| VIII. Builder Interoperability | Pass | New published fields are typed integers in columnar schemas; no GeoPandas is introduced. |
| IX. Observable Operation | Pass | Legacy incompatibility and rebuild are explicit; old ledger files are preserved. |
| X. Testable Contracts | Pass | Portable identity, boundary, ledger, compatibility, and schema tests are planned. |
| XI-XVII. Builder principles | Pass | Serial/parallel parity, representatives, durable ownership, isolated workers, atomic publication, tool documentation, and resource limits remain unchanged. |

No constitution violations are identified. Updating the external `knu2xs/h3-route-solver` contract
and implementation is a coordination dependency. Integer-keyed data must not be advertised as
compatible with the prior hex-keyed contract until that consumer is updated and verified.

### Post-Design Recheck

The data model and contract preserve the Feature 001–005 ownership boundaries, version incompatible
records, and make legacy-ledger rebuilding explicit. The final design introduces no new ArcPy
dependency into portable logic, no unbounded execution, no GeoPandas usage, and no publication
mutation. All constitution gates remain passing.

## Project Structure

### Documentation (this feature)

```text
specs/006-integer-h3-indices/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── integer-h3-index-contract.md
└── tasks.md
```

`tasks.md` is the subsequent task-generation deliverable and is not created by this planning pass.

### Source Code

```text
src/h3_route_data_builder/
├── eligibility/          # H3 identity helpers, eligibility records, staged output
├── network/              # Integer geometry calls, Network Analyst labels, workflow versioning
├── od/                   # Candidate keys, solve records, and durable ledger
└── publication/          # Arrow schemas, conversion, manifests, partitions, validation, writes

testing/
├── test_eligibility_*.py
├── test_network_*.py
├── test_od_*.py
└── test_publication_*.py

docsrc/mkdocs/design/
└── 03-data-contract.md   # Shared builder-solver contract source
```

**Structure Decision**: Update existing modules in place rather than create a parallel
integer-index subsystem. Maintain the existing source/test layout. The solver remains an external
coordinated consumer, not a new project in this repository.

## Implementation Approach

1. Reuse `eligibility/cells.py` as the shared portable cell validator/canonicalizer; keep public
   helper names unless a representation-specific name needs replacing. Use `h3.api.basic_int` in
   cell generation, validation, geometry, centroid, ring, and resolution operations. Reject
   non-integers and booleans before calling H3. Canonicalization validates type, range, and cell
   validity without an expected-resolution argument; eligibility and candidate callers compare
   the cell resolution with their existing configured resolution before using or scheduling cells.
   Preserve public parameter lists; covering still validates its existing resolution argument.
   Canonical output is a numerically sorted, deduplicated list of Python integers.
2. Update eligibility models, candidate endpoints, OD keys, prepared worker payloads, solve
   outcomes, durable ledger endpoints, ordering, deterministic work-ID inputs, logs, and
   serialization to carry exact integer values. Remove deserializers' `str(endpoint)` coercions;
   reject persisted string values rather than adopting them. Keep fingerprints and opaque work IDs
   as strings. Serialize H3-keyed mappings as sorted record arrays with integer fields; use integer
   arrays for destination batches and logical keys.
3. Change staged and published Arrow schemas to required unsigned 64-bit `h3_id`,
   `origin_h3_id`, and `destination_h3_id` fields. Remove hex and duplicate alias fields, and
   version all affected schema and contract identities. Publication dataset/cell/fact versions
   change from `1.0.0` to `2.0.0`; eligibility staged schema, ledger format, work-ID encoding, and
   compatibility encoding use version `2` for this cutover. GeoParquet remains `1.1.0`.
4. Update the shared builder data contract and builder publication documents. Specify the matching
   change required in the external solver project; do not make a cross-project compatibility claim
   until its consumer and contract tests are coordinated. Version `2.0.0` is the proposed shared
   contract; consumer agreement and fixture verification are release dependencies, not evidence
   already supplied by this planning pass.
5. Detect prior hexadecimal-keyed ledgers before resume. Require an explicitly selected new
   working ledger for rebuild, preserve the old ledger, and report that its work is not reused.
   Inspect existing schema/version read-only before any WAL or schema initialization; reject
   inconsistent new-format metadata/columns as well as legacy state. Version
   eligibility run identities as well so old staged parts and completed-run summaries cannot be
   adopted by `network/workflow.py`. No automatic ledger migration or old-dataset reader is added.
   Leave previously published datasets unmodified.
6. Prove conversion-boundary round trips and invalid-input rejection; compare candidate sets,
   directed keys, serial/parallel results, and published outcome semantics to fixed pre-change
   fixtures. Verify uint64 schema typing and historical schema recognition.

### Relevant Change Surfaces

- `eligibility/cells.py`, `models.py`, `engine.py`, `reconcile.py`, `output.py`, and run-state/
  staging helpers: integer references, numeric ordering, typed columns, versioned recovery.
- `network/geometry.py`, `locations.py`, `representatives.py`, `workflow.py`, and `solver.py`:
  integer geometry dictionaries, endpoint lookups, deterministic representatives, and text-only
  Network Analyst labels mapped to validated integer cells. Use assignment-local opaque labels
  rather than storing cell indices in geodatabase floating-point fields.
- `od/models.py`, `candidates.py`, `results.py`, `ledger.py`, `solving.py`, `preparation.py`, and
  `execution.py`: integer logical keys, result deserialization, lease/worker payload identity,
  versioned work hashing, SQLite endpoint columns, and unchanged coordinator ownership.
- All affected `publication/` modules, including conversion, schemas, models, writing, partition
  pruning, compaction, manifests, aggregate validation, and publication: integer origins throughout.
  Filesystem labels may contain decimal text (`origin_h3_id=<decimal>`); identity comes from typed
  columns and integer manifest values, never filename parsing or partition type inference.
- `testing/` fixtures and directly related design/API docs: replace string cell fixtures with
  valid integer cells; use deliberate invalid values only in negative tests. Update Feature 001–005
  representation descriptions with a Feature 006 cutover reference, not a behavioral redesign.
  Update toolbox sidecars only if existing help describes changed H3 output fields.

### Validation Mapping

| Requirements | Planned acceptance evidence |
|---|---|
| FR-001–002, SC-002 | Valid cell samples across resolutions 0–15; values above `2^53`; booleans, strings, floats, nulls, invalid bits, wrong resolution, and uint64 overflow rejected |
| FR-003–006, SC-001/003 | Integer-only model/key/payload round-trips; input permutation/deduplication; geometry/representative invariance; Network Analyst label round-trips |
| FR-007, SC-005 | Required uint64 cell/endpoint schemas; no aliases; Arrow and DuckDB exact reads; integer manifest origins, pruning and compaction |
| FR-008–009 | Proposed contract/schema versions, changed compatibility identity, stable new work IDs, separate consumer approval/fixture evidence |
| FR-010–011, SC-004/005 | Legacy ledger rejected before mutation; fresh rebuild, old files unchanged, legacy eligibility stages not adopted, historical publication not rewritten |
| FR-012 | Candidate-set, route cost/classification, restart/fencing/reclaim, serial/parallel, and atomic publication regression tests |

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Default H3 API returns hex strings | Import the existing `basic_int` variant and verify integer inputs/outputs; do not add a conversion subsystem. |
| Feature 004 consumers expect hex names/types | Version the schemas, update the shared contract, and coordinate solver changes before claiming interoperability. |
| Legacy work is accidentally resumed or silently lost | Detect the ledger format before opening work; require a distinct new ledger and preserve the old file. |
| Representation changes alter ordering or identity | Test canonical permutation invariance, expected key sets, work IDs, and reconciliation on fixed fixtures. |
| JSON keys become strings or clients round integers | Encode H3 identities as numeric fields/arrays, require integer-preserving parsers, and test values above `2^53`. |
| Broad string replacement changes unrelated identifiers | Update typed H3 fields and their serialization surfaces selectively; preserve non-H3 strings and IDs. |

## Complexity Tracking

No constitution violations.
