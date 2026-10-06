<!--
Sync Impact Report
- Version change: (template) -> 1.0.0
- Ratified from: h3-route-solver-specs/01-shared-constitution.md (shared principles I-X)
  plus builder-specific principles XI-XV.
- Added sections: Core Principles, Builder Principles, Technology Constraints,
  Development Workflow & Quality Gates, Governance.
- Templates reviewed: .specify/templates/plan-template.md (Constitution Check gate applies),
  spec-template.md, tasks-template.md - no structural changes required.
- Follow-up TODOs: resolve open clarifications listed in docsrc/mkdocs/design/10-roadmap.md
  via /speckit-clarify before the first /speckit-plan.
-->

# H3 Route Data Builder Constitution

The H3 Route Data Builder is the ArcGIS Pro / ArcPy half of a two-project system. It produces a
sparse, precomputed origin-destination (OD) network cost dataset over canonical H3 cells and
publishes it as Parquet/GeoParquet for the ArcPy-free
[h3-route-solver](https://github.com/knu2xs/h3-route-solver). Principles I-X are shared verbatim in
intent with the solver; principles XI-XV apply to this project only.

## Core Principles (Shared)

### I. Explicit Semantics

Every behavior-affecting choice MUST be configuration, never an implicit constant:
edge eligibility, travel mode, H3 resolution, network cutoff, stretch cutoff, distance
conversion, speed, units, and tie-breaking.

- Configuration MUST be read through `config/config.yml` (via `h3_route_data_builder.config`)
  or explicit function arguments; magic numbers in pipeline code are prohibited.
- Every configured value that affects output MUST be recorded in the dataset manifest.
- Units MUST be explicit in field and parameter names (`_m`, `_s`, `_mps`).

*Rationale:* the solver can only interpret data correctly if every assumption is declared.

### II. ArcPy Isolation

Only the builder imports ArcPy. Within the builder, ArcPy usage MUST be confined to
network/geoprocessing modules; H3 math, candidate planning, ledger, manifest, and validation
logic MUST be importable and testable without ArcPy.

*Rationale:* keeps most logic portable, fast to test, and reusable by the solver contract.

### III. Sparse Correctness (NON-NEGOTIABLE)

No H3 cell whose polygon does not intersect an eligible traversable edge may enter OD work.

- Only rows with `eligibility_status=solvable` participate in candidate generation.
- Intersection semantics (including boundary touch) MUST be defined in configuration and
  covered by tests using a synthetic network with crossing, nearby-but-not-intersecting,
  restricted, one-way, and disconnected edges.

*Rationale:* sparsity is the product; a single leaked cell inflates cost and corrupts meaning.

### IV. Immutable Reproducibility

Published data is immutable, versioned, and fingerprinted from network source, travel mode,
restrictions, eligibility/representative/cutoff policy, schema version, and software versions
(Python, ArcGIS Pro, h3, this package).

- Any change to a fingerprint input MUST produce a new fingerprint; published partitions are
  never edited in place.

*Rationale:* consumers must be able to prove which inputs produced a given cost.

### V. Idempotent Resumability

Deterministic work keys, staging, validation, atomic commit, and reconciliation are mandatory.

- Re-running any step with the same inputs MUST produce logically identical output.
- An interrupted build MUST resume without losing or duplicating committed results.

*Rationale:* national-scale OD solves take long enough that interruption is the normal case.

### VI. Approximation Transparency

H3-derived distance and speed-derived time are always labeled estimates. The builder MUST NOT
persist query-time stretch as network cost; OD facts contain actual network solve results only.

*Rationale:* mixing estimated and solved costs silently destroys trust in the numbers.

### VII. Bounded Execution

All ring expansion, candidate evaluation, batch sizes, and outputs have configured limits.
Unbounded loops over cells, rings, or candidates are prohibited.

*Rationale:* predictable memory, runtime, and licensing behavior.

### VIII. Interoperability

Published spatial files MUST validate against the selected GeoParquet specification (1.0+),
including geometry metadata, CRS, and bbox/covering columns, and MUST be readable by PyArrow,
DuckDB, and GeoPandas.

*Rationale:* the dataset is a contract consumed outside ArcGIS.

### IX. Observable Operation

Structured logs (via `get_logger`) and durable ledger states MUST reconcile all work: every
planned work unit ends in a recorded terminal state with counts that sum to the plan.

*Rationale:* operators must be able to answer "what happened?" without rerunning anything.

### X. Testable Contracts

Every requirement has acceptance coverage. Each spec's acceptance scenarios MUST map to tests in
`testing/`, and the shared data contract (`docsrc/mkdocs/design/03-data-contract.md`) MUST have
schema-level tests.

*Rationale:* the two projects evolve independently; tests are the only enforceable boundary.

## Builder Principles

### XI. Serial Reference Path First

A single-process serial pipeline MUST exist and be correct before any parallelism. Parallel
output MUST be logically identical to serial output for the same inputs, verified by tests.

### XII. Deterministic Representatives

Each solvable cell gets exactly one network representative on an eligible intersecting edge,
selected deterministically (initially nearest eligible point to the centroid, tie-broken by
source ID, OID, then measure). Representative snap distance MUST be zero within tolerance.

### XIII. Durable Work Lifecycle

OD work follows `planned -> leased -> solving -> staged -> validated -> committed`, plus
retryable, terminal, and invalidated failures.

- The ledger MUST live outside worker scratch geodatabases.
- Leases MUST expire. Only the coordinator commits.
- Reconciliation MUST compare expected logical OD keys, never filenames.
- Failures MUST be classified (unlocated, unreachable, cutoff-excluded, system).

### XIV. Isolated Workers

Each worker gets a unique scratch workspace. A capability probe MUST decide whether concurrent
ArcPy solves are safe; otherwise execution falls back to serial solves with parallel non-ArcPy
preparation.

### XV. Publish Atomically

Publication stages output, validates it (schema, checksums, row counts, GeoParquet metadata),
writes manifests, and only then marks success (`_SUCCESS`). Partial publications MUST never be
visible to readers.

## Technology Constraints

- Python version matches the ArcGIS Pro `arcgispro-py3` environment (currently 3.13; minimum 3.11).
- Environment is a clone of `arcgispro-py3` plus `environment.yml` (`make env`).
- Core libraries: ArcPy + Network Analyst, `h3` (v4 API), `pyarrow`, `pandas`, `duckdb`.
- `src/` layout; package `h3_route_data_builder`; ArcGIS Pro tools live in `arcgis/*.pyt` and
  delegate all logic to the package.
- Adding dependencies MUST be flagged in the plan and justified.

## Development Workflow & Quality Gates

- Features follow spec-kit: `/speckit-specify` -> `/speckit-clarify` -> `/speckit-plan` ->
  `/speckit-tasks` -> `/speckit-analyze` -> `/speckit-implement`.
- Feature order follows `docsrc/mkdocs/design/10-roadmap.md` phases 1-4.
- Every plan MUST pass a Constitution Check against principles I-XV before research and again
  after design; violations require a recorded justification in the plan's Complexity Tracking.
- Tests are written with or before implementation; `make test` MUST pass before merge.
- Unit tests MUST NOT require ArcPy; ArcPy-dependent tests are marked and skipped when ArcPy is
  unavailable.
- Code follows `AGENTS.md` conventions (black, type hints, Google docstrings, `pathlib`,
  module-level loggers).

## Governance

- This constitution supersedes other practice documents; `AGENTS.md` provides runtime coding
  guidance subordinate to it.
- Principles I-X are shared with `h3-route-solver`. Amending a shared principle MUST be mirrored
  in the solver constitution in the same release cycle.
- Amendments require a pull request describing the change, rationale, and migration impact, and
  updating dependent templates and docs.
- Versioning: MAJOR for removed/redefined principles, MINOR for added principles or materially
  expanded guidance, PATCH for clarifications.
- Reviews MUST verify compliance; unjustified complexity is rejected.

**Version**: 1.0.0 | **Ratified**: 2026-10-06 | **Last Amended**: 2026-10-06
