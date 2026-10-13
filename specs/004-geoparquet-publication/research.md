# Research: GeoParquet Publication

## Decisions

### Use GeoParquet 1.1.0 with root-level WKB geometry columns

**Decision**: Serialize the solvable-cell dimension with PyArrow Parquet tables, WKB `binary`
geometry columns, and a UTF-8 JSON `geo` file-metadata value conforming to GeoParquet 1.1.0.
Declare `cell_geometry` as the primary geometry and record every geometry column's actual type,
WGS 84 / EPSG:4326 PROJJSON, and usable file/part bounding box. Keep geometry columns at the
schema root and non-repeated.

**Rationale**: The project already converts eligibility records to Arrow tables and stages
GeoParquet through PyArrow. WKB is a standard GeoParquet encoding and lets ArcPy-free readers
access the ordinary Parquet data without requiring a spatial dataframe package. The selected
metadata and geometry types are directly testable against the versioned GeoParquet contract.

**Alternatives considered**:

- GeoArrow-native geometry encodings. Rejected for the initial contract because the existing
  eligibility handoff already provides WKB and WKB has a direct precedent in this codebase.
- A custom geometry column format. Rejected because it would not satisfy the published
  GeoParquet interoperability requirement.

### Split metadata and geometry validation between PyArrow and DuckDB Spatial

**Decision**: Use PyArrow to inspect Parquet schemas, file metadata, `geo` JSON, row counts, and
physical file integrity. Use DuckDB with its spatial extension to read and query geometry and
tabular values without ArcPy. Neither production nor test code may import or use GeoPandas.

**Rationale**: GeoParquet 1.1.0 stores its file-level metadata in ordinary Parquet key/value
metadata, and WKB geometry is a binary column. PyArrow can validate those contracts without a
spatial dataframe abstraction; DuckDB Spatial supplies the independently implemented spatial
reader and large-data processing path required by the constitution.

**Alternatives considered**:

- GeoPandas as an independent reader. Rejected by the constitution and the Feature 004
  clarification.
- DuckDB alone for all checks. Rejected because explicit inspection of the raw Parquet metadata
  and checksum/manifest evidence is part of validation.

### Keep the Arrow row contract distinct from publication state

**Decision**: Model the solvable-cell dimension and OD facts as separate logical tables. Treat
manifests, immutable part references, reconciliation totals, and completion markers as
publication-control records rather than extra OD facts.

**Rationale**: The shared data contract assigns geometry and eligibility evidence to cells, and
actual network cost to directed OD facts. Control records must not be mistaken for route
outcomes.

**Alternatives considered**:

- Embed manifest or classification state in OD rows. Rejected because non-route dispositions are
  explicitly not OD facts and dataset state applies beyond a single row.

### Publish immutable versions only after key and file reconciliation

**Decision**: Stage a complete version, validate schemas, GeoParquet metadata, references,
checksums, row counts, extents, endpoint membership, and expected-key reconciliation, then expose
the version through one atomic visibility operation. A completion marker belongs only to a
validated version and is not inferred from part filenames.

**Rationale**: This follows the spec's atomic publication contract and the constitution's
immutable reproducibility and resumability principles. An explicit final visibility point makes
crash recovery testable without prescribing a specific store.

**Alternatives considered**:

- Treat a populated output directory or a set of Parquet files as success. Rejected because
  interrupted staging and orphan files cannot prove logical completeness.
- Mutate an already published version during compaction. Rejected because published versions
  must remain immutable.

### Preserve origin pruning when compaction changes physical files

**Decision**: Keep the canonical origin identifier typed in each fact row and in logical
partition metadata. Physical layout may combine origins only if row-group or equivalent published
statistics still allow a single-origin filter to skip unrelated rows/files as required by the
acceptance criteria.

**Rationale**: Feature 004 permits physical compaction across origins, while its pruning
acceptance criterion requires measurable origin-based skipping. This constraint preserves both
requirements without fixing a directory naming convention.

**Alternatives considered**:

- Prohibit all cross-origin compaction. Rejected because the feature explicitly permits physical
  parts spanning multiple origins.
- Rely on directory names alone after compaction. Rejected because a combined part no longer
  corresponds to just one origin.

### Preserve Feature ownership and cutoff-aware candidate scope

**Decision**: Consume Feature 002's expected keys, scope, self-pairs, and prefilter provenance
without redefining how they are generated. Proximal scope is evaluated separately for each
solvable in-AOI origin. AOI-wide covers every in-AOI pair retained by Feature 002's existing
conservative cutoff prefilter; the configured actual-cost cutoff still controls which solved
routes qualify as facts. Exclude prefilter-pruned pairs from expected-key reconciliation while
recording their counts and policy provenance.

**Rationale**: This reflects the accepted Feature 004 clarification and preserves Feature 002 and
Feature 003 ownership boundaries. It resolves the question of whether AOI-wide bypasses the
prefilter: it does not.

**Alternatives considered**:

- Bypass Feature 002's prefilter in AOI-wide mode. Rejected by the accepted clarification.
- Make publication recalculate candidate keys. Rejected because candidate selection and key
  creation belong to Feature 002.

## Project Evidence

- `src/h3_route_data_builder/eligibility/output.py` converts validated eligibility rows to
  Arrow tables and provides GeoParquet geometry metadata using WKB and WGS 84 PROJJSON.
- `src/h3_route_data_builder/eligibility/staging.py` writes bounded immutable Parquet parts,
  computes SHA-256 checksums, and verifies stored row counts and checksums.
- `src/h3_route_data_builder/od/models.py` represents directed logical keys, candidate
  provenance, and retained-key reconciliation for the Feature 003 handoff.
- `specs/003-resumable-od-solving/contracts/solver-ledger.md` makes committed compatible solve
  outcomes authoritative and assigns final schemas, layout, manifests, and `_SUCCESS` to Feature
  004.
- Constitution Principles IV, V, VIII, IX, X, XV, and XVII govern immutable versions, resumability,
  GeoParquet interoperability, observable reconciliation, contract tests, atomic publication,
  and bounded resource-aware execution.

## Sources

- [GeoParquet 1.1.0 specification](https://geoparquet.org/releases/v1.1.0/)
- [GeoParquet 1.1.0 metadata schema](https://geoparquet.org/releases/v1.1.0/schema.json)
- [DuckDB Spatial extension overview](https://duckdb.org/docs/current/core_extensions/spatial/overview.html)
- [DuckDB Parquet metadata documentation](https://duckdb.org/docs/current/data/parquet/metadata)

## Unresolved Implementation Choices

None are specification blockers. Publication storage, version-directory layout, physical
partition encoding, compression, exact ordering algorithm, checksum algorithm, and compaction
trigger remain implementation choices, subject to the observable contracts and pruning/recovery
tests. Reader and metadata tests must run against the versions available in the project test
environment; do not assume GeoPandas or use it as a fallback.
