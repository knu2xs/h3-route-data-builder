# Implementation Plan: H3 Geometry Eligibility Spike

**Branch**: `001-geometry-spike` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-geometry-spike/spec.md`

## Summary

Build an auditable set of H3 cells supported by eligible network edges inside a validated AOI.
Use ArcPy geometry capabilities for AOI/edge/H3 geometry validation, reprojection, intersection,
and representative spatial calculations inside network/geoprocessing modules. Keep H3 index
calculations and non-spatial eligibility state, batching, and reconciliation logic portable.
Isolate network-source eligibility and Network Analyst location calculation in ArcPy adapters.
Process stable input partitions in bounded batches, reconcile deduplicated cells and run evidence,
and mark the eligibility run complete only after every partition is reconciled. No candidate
generation, OD solving, cost calculation, or final publication is included.

## Technical Context

**Language/Version**: Python 3.13 in ArcGIS Pro `arcgispro-py3`; package minimum Python 3.11.

**Primary Dependencies**: Existing `h3` v4, ArcPy/Network Analyst, PyArrow, and pytest. ArcPy is
provided by ArcGIS Pro. No Shapely or pyproj dependency is used or added for this feature.

**Storage**: Per-run staging directory with one atomically written spatial part per bounded batch,
plus run/partition reconciliation metadata. The exact staging encoding follows the existing
solvable-cell data contract; final publication is out of scope.

**Testing**: pytest. H3 indexing, non-spatial eligibility rules, batching, deduplication, and
reconciliation tests run without ArcPy. Geometry/reprojection and Network Analyst integration
tests are marked and run in an ArcGIS Pro environment; they are skipped when ArcPy is unavailable.
A separate read-only integration test exercises the supplied StreetMap Premium network when its
path resolves through `arcpy.Exists`; synthetic acceptance fixtures remain the required test gate.

**Target Platform**: ArcGIS Pro on Windows for geometry, reprojection, and network-dataset
operations; H3 indexing and non-spatial reconciliation remain platform-portable and ArcPy-free.

**Project Type**: Python package with an ArcGIS Pro Python toolbox entry point.

**Performance Goals**: No wall-clock target is defined by the spec. Bound memory and staged-part
size with explicit configuration; process all partitions serially and deterministically before
any parallel implementation is considered.

**Constraints**: Reject AOIs with unknown CRS; use configured area-appropriate working CRS and
ArcPy projection capabilities with explicit datum transformation when required; do not repair
invalid input silently. The H3 candidate cover is a superset only; exact ArcPy geometry
intersection is authoritative. Intersection acceptance must include nonempty zero-dimensional
and one-dimensional ArcPy intersection results so point touches and coincident boundary segments
are both counted. Do not expose partial staging as complete. Never pass a cell without an eligible
intersecting edge and valid location to OD work.

**Scale/Scope**: All eligible input partitions for an AOI, processed in bounded batches. A
configured per-part limit triggers deterministic subdivision/retry. A required, distinct total
hard cap counts unique solvable H3 IDs; exceeding it fails the run incomplete. OD candidate
counts, solves, and published dataset scale are outside this feature.

## Constitution Check

*Gate before Phase 0 research: PASS.*

- **I. Explicit Semantics**: Pass. Working CRS, H3 resolution, travel mode/restrictions,
  intersection policy, representative tie-breaks, tolerance, batch limits, and required total cap
  are explicit inputs/configuration and recorded as run evidence.
- **II. Builder ArcPy Geometry Boundary**: Pass after the builder-specific amendment. ArcPy geometry,
  reprojection, and network operations stay in network/geoprocessing modules; H3 indexing and
  non-spatial state/validation logic remain importable without ArcPy. The solver remains ArcPy-free.
- **III. Sparse Correctness**: Pass. Inclusive exact intersection plus valid eligible-edge
  evidence gates `solvable`; the OD handoff contains only validated solvable rows.
- **IV. Immutable Reproducibility**: Pass. Run fingerprints include network/travel-mode and
  eligibility policies, schema version, and Python/ArcGIS Pro/H3/package versions; deterministic
  logical part keys make repeated staging idempotent.
- **V. Idempotent Resumability**: Pass. Partition/batch states, atomic part writes, and logical
  reconciliation support retry without duplicate committed cells.
- **VI. Approximation Transparency**: Pass. No estimated distance/time or OD cost is produced.
- **VII. Bounded Execution**: Pass. Per-part limits, recursive deterministic subdivision, and a
  required total hard cap bound work/output; no silent truncation.
- **VIII. Interoperability**: Pass for the eligibility handoff by preserving the existing
  solvable-cell schema and CRS metadata. Final GeoParquet publication validation is out of scope.
- **IX. Observable Operation**: Pass. Structured logs and durable partition/run states reconcile
  expected and completed work counts before completion.
- **X. Testable Contracts**: Pass. Each acceptance scenario maps to portable H3/non-spatial tests
  or marked ArcPy geometry/network tests; shared data-contract fields remain unchanged.
- **XI. Serial Reference Path First**: Pass. This design is serial; parallel work is not added.
- **XII. Deterministic Representatives**: Pass. Closest point on an eligible intersecting edge,
  followed by source ID, source OID, and measure tie-breaks; validate zero snap distance.
- **XIII. Durable Work Lifecycle**: Pass for eligibility partitions. Persist run and partition
  states outside worker scratch; no OD work lifecycle is introduced.
- **XIV. Isolated Workers**: Not applicable; this feature creates no workers or concurrent solves.
- **XV. Publish Atomically**: Pass at the eligibility-run boundary: completion is recorded only
  after reconciliation; a cap failure remains incomplete. Final publication is excluded.

**Post-design gate**: PASS after the builder-specific Principle II amendment. The design adds no
new runtime dependencies; ArcPy is provided by ArcGIS Pro. The solver constitution and package
remain unchanged and ArcPy-free.

## Project Structure

### Documentation

```text
specs/001-geometry-spike/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── eligibility-output.md
└── tasks.md                 # Created by /speckit-tasks, not this plan
```

### Source Code and Tests

```text
src/h3_route_data_builder/
├── eligibility/             # H3 IDs, non-spatial eligibility state, staging/reconciliation
└── network/                 # ArcPy geometry, reprojection, edge eligibility, NA locations

arcgis/h3_route_data_builder.pyt  # Toolbox entry point delegates to package

testing/
├── test_eligibility_rules.py     # Portable H3 indexing and non-spatial status rules
├── test_eligibility_geometry.py  # ArcPy geometry/reprojection acceptance tests
├── test_eligibility_staging.py   # Batching, part limits, dedupe, cap, reconciliation
├── test_network_eligibility.py   # ArcGIS Pro synthetic network tests; skipped without ArcPy
└── test_real_network_dataset.py  # Read-only StreetMap Premium smoke test; path-gated
```

**Structure Decision**: Add focused package modules under `eligibility/` and `network/` rather
than embedding behavior in the toolbox. Keep ArcPy geometry operations in network/geoprocessing
modules and portable H3 indexing/non-spatial reconciliation in `eligibility/`. Test files mirror
the package modules under `testing/`; ArcPy geometry tests are marked integration tests. The
eligibility handoff is documented against, but does not alter, the shared data contract.

## Complexity Tracking

No constitution violations after the builder-specific Principle II amendment. Every run requires
a configured total solvable-cell hard cap in addition to per-part limits. No package dependencies
are added; ArcPy is supplied by ArcGIS Pro.
