# Implementation Plan: GeoParquet Publication

**Branch**: `004-geoparquet-publication` | **Date**: 2026-10-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-geoparquet-publication/spec.md`

## Summary

Publish Feature 001 solvable cells and Feature 003's authoritative compatible OD outcomes as an
immutable, versioned GeoParquet 1.1.0 dataset. Use PyArrow tables and root-level WKB geometry
columns with explicit GeoParquet metadata; keep the solvable-cell dimension separate from
geometry-free directed OD facts. Validate all staged files, manifests, geometry metadata, endpoint
references, key counts, and checksums before one atomic publication visibility point. Retain
origin-based pruning and logical equivalence across compaction.

User Story 1 writes the canonical dimension and fact tables as GeoParquet and validates their
schemas, metadata, and readable logical rows with PyArrow and DuckDB Spatial. These table files
are not exposed as a complete dataset version and do not receive a valid `_SUCCESS` marker until
User Story 2 completes reconciliation, manifest validation, and atomic publication.

The publication boundary consumes Feature 002's candidate contract without generating candidates.
For both candidate scopes, prefilter-pruned pairs remain outside expected-key reconciliation and
are accounted for in provenance. In AOI-wide scope, all in-AOI pairs retained by Feature 002's
existing conservative prefilter are expected; its actual-cost cutoff still controls qualifying
facts. Unlocated, unreachable, and cutoff-excluded outcomes remain reconciliation dispositions,
not OD facts.

## Technical Context

**Language/Version**: Python 3.13 in ArcGIS Pro; project minimum Python 3.11.

**Primary Dependencies**: PyArrow for Arrow schemas, Parquet I/O, and raw file metadata;
DuckDB Spatial for ArcPy-free geometry reads and large spatial processing; existing package
utilities and pytest. ArcPy remains confined to existing network/geoprocessing modules.
GeoPandas is prohibited. PyArrow and DuckDB are declared runtime dependencies because publication
imports them directly for GeoParquet serialization, file validation, and DuckDB Spatial reads.
The configured environment was verified with PyArrow 22.0.0, DuckDB 1.3.2, and a loadable Spatial
extension.

**Storage**: Immutable versioned Parquet parts and dataset/partition manifests. The physical
store, directory convention, catalog/reference mechanism, compression, and checksum algorithm
remain open. Staging must be undiscoverable as complete until all validation passes, then exposed
through one atomic visibility operation. Parts are never modified after publication.

**Testing**: pytest. Schema, conversion, GeoParquet writing and reader interoperability, manifest,
key reconciliation, checksums, failure recovery, and compaction equivalence tests remain ArcPy-free.
Validate GeoParquet metadata and physical integrity with PyArrow and independently read/query the
tables with DuckDB Spatial. Tests must not use GeoPandas. ArcPy-specific geometry eligibility is
consumed as Feature 001 evidence rather than reimplemented here.

**Target Platform**: ArcGIS Pro / `arcgispro-py3` for the builder pipeline; published data is
readable by ArcPy-free PyArrow and DuckDB consumers.

**Project Type**: Python package and ArcGIS Pro geoprocessing pipeline.

**Performance Goals**: Support bounded publication using Feature 001/002 resolved execution
limits. A single-origin query must skip unrelated fact files or row groups. No fixed throughput,
latency, or compaction target is specified.

**Constraints**: Preserve the canonical field types, units, nullability, identifiers, and
eligibility semantics in the Feature 004 spec and shared data contract. Use GeoParquet 1.1.0,
WGS 84 / EPSG:4326 PROJJSON, and explicit geometry metadata. Use only compatible authoritative
Feature 003 committed outcomes; never infer success from filenames, process status, or staged
parts. Keep non-route classifications out of OD facts. No GeoPandas dependency, import, or use.
Update the shared data contract only through a coordinated, reviewed change if implementation
finds an actual contract mismatch.

**Scale/Scope**: National-scale outputs with bounded staged parts and a potentially large directed
fact set. Reuse Feature 001 resource-aware part limits and Feature 002 candidate counts where
applicable; do not materialize unbounded datasets solely to validate or compact them. A successful
publication accounts for every retained expected key once as a qualifying/self fact or a resolved
non-route classification; unresolved or retryable work prevents success.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Before Research

- **I. Explicit semantics**: PASS. The spec fixes canonical fields, units, nullability, GeoParquet
  version, CRS, key identity, fingerprints, and publication states; behavior-affecting provenance
  is recorded in manifests.
- **II. Builder ArcPy geometry boundary**: PASS. Publication serializes Feature 001 geometry
  evidence and remains ArcPy-free; it does not perform eligibility geometry operations.
- **III. Sparse correctness**: PASS. Only Feature 001 solvable cells and Feature 002 candidate
  keys can contribute to the dimension or fact tables.
- **IV. Immutable reproducibility**: PASS. Each published or compacted version is immutable and
  carries schema, compatibility, and provenance identities.
- **V. Idempotent resumability**: PASS. Publication staging, validation, one atomic visibility
  point, and logical-key reconciliation are required; prior versions are preserved.
- **VI. Approximation transparency**: PASS. Only actual compatible network costs are facts;
  estimated stretch or candidate bounds are not converted into network costs.
- **VII. Bounded execution**: PASS. The plan uses resolved bounded part limits and requires
  streaming/partition-wise processing for large outputs.
- **VIII. Builder interoperability**: PASS. GeoParquet 1.1.0, WKB, CRS and extent metadata, and
  PyArrow/DuckDB reader checks are explicit; GeoPandas is prohibited.
- **IX. Observable operation**: PASS. Dataset and partition manifests carry counts, states,
  fingerprints, file references, checksums, and reconciliation evidence.
- **X. Testable contracts**: PASS. Schema and manifest contracts plus the quickstart map to
  reader, pruning, integrity, atomicity, eligibility, and compaction tests.
- **XI. Serial reference path first**: PASS. Publication is coordinator-owned and deterministic;
  it adds no parallel-worker policy.
- **XII. Deterministic representatives**: PASS. The publisher preserves, rather than recomputes,
  Feature 001 representative geometry and evidence.
- **XIII. Durable work lifecycle**: PASS. Feature 003 remains authoritative for solve lifecycle
  and outcomes; publication checks its committed, reconciled handoff.
- **XIV. Isolated workers**: PASS. Worker execution and scratch ownership remain with Feature 005;
  only the coordinator publishes.
- **XV. Publish atomically**: PASS. Staging, full validation, immutable manifests, a single
  visibility operation, and a completion marker after successful validation are core behavior.
- **XVI. Complete Pro tool documentation**: PASS. The plan does not require a new toolbox tool
  or user-facing parameter; any later exposure through a tool requires the prescribed XML
  sidecar in the same change.
- **XVII. Resource-aware execution limits**: PASS. Bounded writing and validation use recorded
  execution limits; no rows may be silently dropped when limits are exceeded.

No pre-research gate violations.

### Post-Design Check

- **I-VII**: PASS. Canonical logical tables, compatibility, reconciliation, immutable version
  behavior, actual-cost-only facts, and bounded part processing are captured in the data model and
  publication contract.
- **VIII**: PASS. The contract uses GeoParquet 1.1.0 metadata and PyArrow/DuckDB validation only;
  no GeoPandas dependency, import, or test use is allowed. Spatial Pandas work, if introduced,
  must use ArcGIS GeoAccessor; large spatial processing must use DuckDB Spatial.
- **IX-X**: PASS. Manifests and contract tests expose publication state and exact count/integrity
  reconciliation.
- **XI-XIV**: PASS. The publisher is coordinator-owned, uses deterministic Feature 001 cell
  evidence, consumes Feature 003 committed output, and does not define worker concurrency.
- **XV**: PASS. A version is discoverable as successful only after validation and the atomic
  publication point; marker and manifest validity are required by readers.
- **XVI**: PASS. No new ArcGIS Pro tool surface is required in the planned source structure.
- **XVII**: PASS. Parts remain bounded; origin-based pruning metadata must survive compaction.

No post-design gate violations. No complexity exceptions require tracking.

## Project Structure

### Documentation (this feature)

```text
specs/004-geoparquet-publication/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── publication-contract.md
└── tasks.md
```

### Source Code

```text
src/h3_route_data_builder/
├── eligibility/
│   └── output.py                 # Existing Feature 001 Arrow/WKB handoff
├── od/
│   └── results.py                # Existing Feature 003 outcome classifications
└── publication/
    ├── __init__.py
    ├── models.py                 # Version, manifest, part, and validation records
    ├── schema.py                 # Arrow schemas and GeoParquet metadata
    ├── convert.py                # Feature 001/002/003 inputs to canonical Arrow tables
    ├── write.py                  # Bounded GeoParquet table-file writing for US1
    ├── manifest.py               # Dataset and partition manifest construction
    ├── validation.py             # File, key, geometry, and reconciliation validation
    ├── publish.py                # Staging, atomic exposure, and completion marker
    ├── partition.py              # Origin pruning metadata and bounded fact-part layout
    └── compact.py                # Immutable physical compaction

testing/
├── test_publication_schema.py
├── test_publication_conversion.py
├── test_publication_interoperability.py
├── test_publication_manifest.py
├── test_publication_validation.py
├── test_publication_publish.py
├── test_publication_pruning.py
└── test_publication_compaction.py
```

**Structure Decision**: Add a focused `publication` package adjacent to the existing
`eligibility`, `network`, and `od` packages. Preserve existing eligibility serializers and OD
outcome logic as upstream inputs. Tests mirror the new package modules under `testing/`; portable
publication and contract validation must not import ArcPy.

## Complexity Tracking

No constitution violations or additional architectural complexity require justification.

## Implementation Validation

- The focused Feature 004 publication suite passes: 28 tests.
- Formatting, Pylance diagnostics for the publication package, and `git diff --check` pass.
- The full repository suite reports 181 passed and one suite-only failure in
  `testing/test_real_network_dataset.py`
  (`test_streetmap_network_builds_reconciled_small_aoi_without_source_edits`):
  its `caplog` assertion is empty although the INFO messages appear in captured stdout. The same
  real-network test passes when run alone. No missing runtime dependencies were found; the
  publication package's direct PyArrow and DuckDB imports are declared in both dependency manifests.
