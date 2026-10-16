# Implementation Plan: H3 Hexagon Review Feature Class Export

**Branch**: `008-h3-hexagon-review-export` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-h3-hexagon-review-export/spec.md`

## Summary

Add an optional checkbox and output feature class parameter to **Build H3 Geometry Eligibility**.
When checked, after the eligibility run completes, the tool writes a WGS 84 polygon feature class
with one hexagon per evaluated H3 cell, an `h3_index` Text field holding the exact decimal
integer H3 identity, and an `eligibility_status` text field. The export reads only manifest-listed,
checksum-verified staged parts, streams them in ascending `h3_id` order one partition at a time,
and never modifies the run's GeoParquet, manifest, state, or fingerprint. Logic is split between
an ArcPy-free reader (`eligibility/review.py`) and an ArcPy writer (`network/review_export.py`);
the `.pyt` only collects parameters and delegates. Tests, the tool XML sidecar, user docs, and a
non-contract section in the shared data contract are updated.

## Technical Context

**Language/Version**: Python 3.13 (ArcGIS Pro `arcgispro-py3` clone; minimum 3.11)

**Primary Dependencies**: ArcPy (the project's Python 3.11+ floor requires Pro 3.3+), `h3` v4 (`basic_int`
API), `pyarrow`; no new dependencies

**Storage**: Input: completed eligibility run directory (`run-manifest.json` + staged GeoParquet
parts). Output: polygon feature class in a file, mobile, or enterprise geodatabase

**Testing**: pytest; ArcPy-free unit tests plus ArcPy-gated tests via the `arcpy_module`,
`temp_dir`, and `temp_gdb` fixtures

**Target Platform**: Windows, the project's supported ArcGIS Pro release (3.3+, Python 3.11+)
with Network Analyst

**Project Type**: Python library with an ArcGIS Pro Python toolbox front end

**Performance Goals**: Export time is small relative to the eligibility run; analyst can symbolize
results within 1 minute of completion (SC-003)

**Constraints**: Memory bounded to one partition (≤ the run's resolved `batch_size` rows);
exact integer identity; no partial output on failure; no change to contract outputs or fingerprint

**Scale/Scope**: Up to the run's total solvable-cell hard cap (policy maximum 5,000,000 cells);
one new ArcPy-free module, one new ArcPy module, two toolbox parameters, three test files touched

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Pre-design assessment | Post-design disposition |
|---|---|---|
| I Explicit semantics | Field names/types and CRS must be explicit, not magic | PASS: CRS from `WGS84_CRS_NAME`; resolution from manifest `policy.h3_resolution`; field schema defined in contract. No new behavior-affecting config for contract outputs. The export checkbox and path are not recorded in the manifest because they affect only a non-contract review artifact, not dataset output; they are logged instead (Principle IX). |
| II ArcPy geometry boundary | Feature class writing needs ArcPy; selection/validation must not | PASS: ArcPy only in `network/review_export.py` and `.pyt`; reader/validation in ArcPy-free `eligibility/review.py`. |
| III Sparse correctness | Must not alter which cells are solvable | PASS: read-only derivative; statuses copied unchanged; no OD participation. |
| IV Immutable reproducibility | Must not edit published/run data or fingerprint inputs | PASS: run directory is read-only to the export; export choice excluded from fingerprint (spec assumption). |
| V Idempotent resumability | Re-export of the same run must be identical; resumed runs supported | PASS: manifest-listed parts, deterministic ascending order; works after completed-run early return. |
| VI Approximation transparency | Not applicable (no costs) | PASS: N/A. |
| VII Bounded execution | Export must not load unbounded rows | PASS: per-partition sort bounded by resolved `batch_size`; total bounded by run hard cap. |
| VIII Interoperability | No GeoPandas; Arrow allowed for Parquet I/O | PASS: PyArrow reads parts; ArcPy writes feature class; no GeoPandas. |
| IX Observable operation | Export must log start/target/count/completion and failures | PASS: logging specified in contract; count reconciled against manifest `cell_result_count`. |
| X Testable contracts | Acceptance scenarios map to tests; contract doc has schema tests | PASS: requirement-to-test matrix in quickstart; contract schema tests unchanged (SC-005). |
| XI Serial reference first | No parallelism introduced | PASS: N/A. |
| XII Deterministic representatives | Unaffected | PASS: N/A. |
| XIII Durable work lifecycle | OD lifecycle unaffected | PASS: N/A. |
| XIV Isolated workers | No workers | PASS: N/A. |
| XV Publish atomically | Review artifact is not a publication, but must not leave partial output | PASS: delete-on-failure; artifact excluded from publication and `_SUCCESS`. |
| XVI Pro tool documentation | Parameter changes require XML sidecar update and test | PASS: sidecar updated in same change; existing test asserts every parameter name appears; Pro UI verification in quickstart. |
| XVII Resource-aware limits | Must not change limit inference or manifest limits | PASS: export follows the run's saved partitions; no new limits. |

**Result**: PASS before and after design. No violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/008-h3-hexagon-review-export/
├── plan.md                        # This file
├── research.md                    # Phase 0 decisions
├── data-model.md                  # Phase 1 entities and lifecycle
├── quickstart.md                  # Phase 1 validation guide
├── contracts/
│   └── review-feature-class.md    # Tool parameters, package API, data contract addition
├── checklists/
│   └── requirements.md            # Spec quality checklist
└── tasks.md                       # Phase 2 output (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
src/h3_route_data_builder/
├── eligibility/
│   ├── review.py                  # NEW (ArcPy-free): ReviewCell, iter_review_cells,
│   │                              #   expected_review_cell_count
│   ├── cells.py                   # REUSED: canonical_h3_ids validation rules
│   └── staging.py                 # REUSED: StagedPart, read_verified_staged_part
└── network/
    ├── review_export.py           # NEW (ArcPy): export_eligibility_review_feature_class
    └── geometry.py                # REUSED: WGS84_CRS_NAME

arcgis/
├── h3_route_data_builder.pyt                               # MODIFIED: params 9-10, validation, delegation
└── h3_route_data_builder.GeometryEligibilityTool.pyt.xml   # MODIFIED: document params and fields

testing/
├── test_eligibility_review.py     # NEW: ArcPy-free reader tests
├── test_network_review_export.py  # NEW: ArcPy-gated export tests
└── test_h3_route_data_builder.py  # MODIFIED: expected parameter list

docsrc/
├── mkdocs/design/03-data-contract.md   # MODIFIED: "Review artifacts (non-contract)" section
├── mkdocs/review-export.md             # NEW: user guide for the review export
└── mkdocs.yml                          # MODIFIED: nav entry for review-export.md
```

**Structure Decision**: Follow the existing single-package split: portable logic in
`eligibility/`, ArcPy geoprocessing in `network/`, and a thin toolbox in `arcgis/`. Tests mirror
modules in `testing/`.

## Phase 0: Research Outcome

See [research.md](./research.md). Key decisions:

- Text (length 20) `h3_index` storing the exact decimal integer `h3_id`, because ArcGIS Big
  Integer is limited to 53 bits (R1); requires a geodatabase (R2).
- Read only manifest-listed, checksum-verified parts relative to the summary's run directory (R3).
- Sort per partition and enforce strictly ascending IDs across partitions for bounded,
  deterministic output (R4).
- Use stored `cell_geometry` WKB in WGS 84; no recomputation or reprojection (R5).
- Delete partial output on failure; honor `overwriteOutput` (R7).

## Phase 1: Design and Delivery Order

Design artifacts: [data-model.md](./data-model.md),
[contracts/review-feature-class.md](./contracts/review-feature-class.md),
[quickstart.md](./quickstart.md).

Recommended delivery order (each step independently testable):

1. **ArcPy-free reader** — `eligibility/review.py` with `test_eligibility_review.py` built from
   synthetic manifests and parts written with existing staging helpers (US1, FR-009–FR-011,
   FR-016–FR-017).
2. **ArcPy writer** — `network/review_export.py` with `test_network_review_export.py` using
   `temp_gdb` (US1, US3, FR-004–FR-008, FR-013–FR-014, FR-018).
3. **Toolbox wiring** — append parameters 9–10, enable/required/workspace/overwrite validation,
   post-run delegation; update `test_h3_route_data_builder.py` (US2, US3, FR-001–FR-003).
4. **Documentation** — XML sidecar, user guide page and nav, data contract section
   (FR-019–FR-022).
5. **Regression** — `make test`; manual Pro verification per quickstart.

### Compatibility and Public API Boundaries

- No existing public symbol is renamed or changes signature; `run_geometry_eligibility` and
  `EligibilityBuildSummary` are unchanged.
- Existing tool parameter names and indices 0–8 are unchanged; new parameters are appended.
- Shared data contract and schema versions are unchanged; the addition is explicitly
  non-contract. Notify `h3-route-solver` maintainers of the documentation addition.

## Complexity Tracking

No constitution violations to justify.
