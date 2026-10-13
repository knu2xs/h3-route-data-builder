<!--
Sync Impact Report
- Version change: 2.0.0 -> 2.0.1
- Principle VIII: removed GeoPandas as a required reader and prohibited GeoPandas use in this builder;
  specified ArcGIS GeoAccessor and DuckDB Spatial as the spatial-operation paths, and clarified
  that Arrow/PyArrow remains approved for columnar schemas, interchange, Parquet I/O, and metadata.
- Reclassified Principle VIII as builder-specific; no solver constitution change is required.
- Technology Constraints now distinguish Arrow/Parquet data handling from spatial operations.
- Follow-up completed: Feature 004's reader acceptance criteria and assumptions now omit GeoPandas.
-->

# H3 Route Data Builder Constitution

The H3 Route Data Builder is the ArcGIS Pro / ArcPy half of a two-project system. It produces a
sparse, precomputed origin-destination (OD) network cost dataset over canonical H3 cells and
publishes it as Parquet/GeoParquet for the ArcPy-free
[h3-route-solver](https://github.com/knu2xs/h3-route-solver). Principles I-X are shared verbatim in
intent with the solver except Principles II and VIII, which are builder-specific; principles
XI-XVII also apply to this project only.

## Core Principles (Shared Except Where Noted)

### I. Explicit Semantics

Every behavior-affecting choice MUST be configuration, never an implicit constant:
edge eligibility, travel mode, H3 resolution, network cutoff, stretch cutoff, distance
conversion, speed, units, and tie-breaking.

- Configuration MUST be read through `config/config.yml` (via `h3_route_data_builder.config`)
  or explicit function arguments; magic numbers in pipeline code are prohibited.
- Every configured value that affects output MUST be recorded in the dataset manifest.
- Units MUST be explicit in field and parameter names (`_m`, `_s`, `_mps`).

*Rationale:* the solver can only interpret data correctly if every assumption is declared.

### II. Builder ArcPy Geometry Boundary

Only the builder imports ArcPy. Within the builder, ArcPy usage MUST be confined to
network/geoprocessing modules. AOI geometry validation, geometry reprojection, edge/cell
intersection, and representative geometry operations for eligibility MUST use ArcPy capabilities.
Shapely and pyproj MUST NOT be used for those operations. H3 index calculations, deterministic
non-spatial eligibility/state rules, candidate planning, ledger, manifest, and non-spatial
validation logic MUST remain importable and testable without ArcPy.

*Rationale:* uses ArcGIS geometry behavior consistently for this builder's spatial operations
while preserving the ArcPy-free H3 solver and portable non-spatial builder logic.

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

### VIII. Builder Interoperability

Published spatial files MUST validate against the selected GeoParquet specification (1.0+),
including geometry metadata, CRS, and bbox/covering columns, and MUST be readable by PyArrow,
and DuckDB. GeoPandas MUST NOT be used in this project, including in production code, tests, or
tooling. Arrow/PyArrow MAY be used for columnar schemas, data interchange, Parquet/GeoParquet
serialization, and file/metadata validation; these uses are distinct from spatial DataFrame
operations. When spatial operations use Pandas, the ArcGIS GeoAccessor MUST be used; large-data
spatial processing MUST use DuckDB with its spatial extension.

*Rationale:* the dataset remains interoperable through portable Arrow/GeoParquet readers and writers,
while spatial operations follow the project's ArcGIS and DuckDB toolchain.

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

### XVI. Complete Pro Tool Documentation

Every tool class exposed by an ArcGIS Pro Python toolbox MUST ship a matching Pro-readable XML
metadata sidecar using ArcGIS Pro's naming convention (for example,
`h3_route_data_builder.GeometryEligibilityTool.pyt.xml`). The sidecar MUST describe the tool's
purpose and usage, every input and output parameter, units, validation rules, and defaults or
inferred values. Documentation MUST match the `.pyt` implementation and MUST NOT contain empty
template text or generic placeholders.

- Tests MUST verify each exposed tool has a matching, well-formed XML sidecar and that its
  documented parameter names match the parameters declared by the tool.
- Before a toolbox change is complete, verify in ArcGIS Pro that the tool's help and parameter
  descriptions appear and are accurate in the Geoprocessing UI.
- Changes to tool parameters or user-visible behavior MUST update the XML sidecar in the same
  change.

*Rationale:* Python source docstrings alone do not ensure operators see complete, current help in
the ArcGIS Pro interface.

### XVII. Resource-Aware Execution Limits

The builder MAY infer default input batch size, staged-part row limit, and total solvable-cell hard
cap from available physical memory, output-volume free space, and known candidate count when the
caller omits these optional values. Explicit positive caller values MUST override the corresponding
inferred value. Inference policy MUST be deterministic for a resource snapshot and versioned with
the implementation.

- Policy version 1 MUST derive batch size as 100 candidates per GiB of available physical memory,
  bounded to 100-2,000 and candidate count; staged-part row limit as 1,000 rows per 128 MiB,
  bounded to 500-50,000; and total cap as half of output-volume free bytes divided by 8 KiB per
  cell, bounded to 1-5,000,000.

- Each resolved limit MUST be logged with its value and source (`inferred` or `set`).
- Resolved values, their source, and the inference-policy version MUST be recorded in the run
  manifest and included in the behavior fingerprint.
- A resumed run MUST reuse the manifest's resolved limits rather than recalculate them from current
  hardware or free space. Changed explicit overrides MUST identify a distinct run or fail clearly.
- The total solvable-cell hard cap MUST always resolve to a positive value. Exceeding it MUST fail
  the run incomplete; resource inference MUST never silently truncate output.
- Pro may show inferred limits as optional editable suggestions; unchanged suggestions MUST be
  passed as inferred, and operator-edited values MUST be passed as explicit overrides.

*Rationale:* local capacity defaults reduce setup friction while keeping bounded execution,
auditable settings, and deterministic recovery.

## Technology Constraints

- Python version matches the ArcGIS Pro `arcgispro-py3` environment (currently 3.13; minimum 3.11).
- Environment is a clone of `arcgispro-py3` plus `environment.yml` (`make env`).
- Core libraries: ArcPy + Network Analyst, `h3` (v4 API), `pyarrow`, `pandas`, `duckdb`.
- GeoPandas MUST NOT be added as a dependency or used in source code, tests, or tooling. Use
  Arrow/PyArrow for columnar data schemas, interchange, and Parquet/GeoParquet I/O where appropriate.
  Use ArcGIS GeoAccessor for spatial Pandas workflows and DuckDB with the spatial extension for
  large spatial datasets.
- `src/` layout; package `h3_route_data_builder`; ArcGIS Pro tools live in `arcgis/*.pyt` and
  delegate all logic to the package.
- Adding dependencies MUST be flagged in the plan and justified.

## Development Workflow & Quality Gates

- Features follow spec-kit: `/speckit-specify` -> `/speckit-clarify` -> `/speckit-plan` ->
  `/speckit-tasks` -> `/speckit-analyze` -> `/speckit-implement`.
- Feature order follows `docsrc/mkdocs/design/10-roadmap.md` phases 1-4.
- Every plan MUST pass a Constitution Check against principles I-XVII before research and again
  after design; violations require a recorded justification in the plan's Complexity Tracking.
- Tests are written with or before implementation; `make test` MUST pass before merge.
- Unit tests for H3 indexing, state, ledger, manifest, and other non-spatial logic MUST NOT require
  ArcPy. ArcPy-dependent geometry and network tests MUST be marked and skipped when ArcPy is
  unavailable.
- Code follows `AGENTS.md` conventions (black, type hints, Google docstrings, `pathlib`,
  module-level loggers).

## Governance

- This constitution supersedes other practice documents; `AGENTS.md` provides runtime coding
  guidance subordinate to it.
- Principles I and III-VII and IX-X are shared in intent with `h3-route-solver`; Principles II and
  VIII and principles XI-XVII are builder-specific. Builder-specific amendments do not change the
  solver constitution. Changes to the shared principles MUST be mirrored in the solver constitution
  in the same release cycle.
- Amendments require a pull request describing the change, rationale, and migration impact, and
  updating dependent templates and docs.
- Versioning: MAJOR for removed/redefined principles, MINOR for added principles or materially
  expanded guidance, PATCH for clarifications.
- Reviews MUST verify compliance; unjustified complexity is rejected.

**Version**: 2.0.1 | **Ratified**: 2026-10-06 | **Last Amended**: 2026-10-13
