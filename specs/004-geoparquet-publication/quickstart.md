# Quickstart: GeoParquet Publication

This guide describes the acceptance path for Feature 004 publication. It verifies data integrity,
consumer interoperability, pruning, crash behavior, and compaction without GeoPandas.

## Prerequisites

- Run from the repository root in the project environment.
- The configured environment must provide PyArrow and DuckDB with its Spatial extension.
- Use small synthetic Feature 001 solvable-cell records, Feature 002 candidate plans, and
  Feature 003 authoritative solve outcomes; portable tests must not require ArcPy.
- See the [data model](data-model.md), [publication contract](contracts/publication-contract.md),
  and [feature specification](spec.md).

## Run Portable Publication Tests

From PowerShell at the repository root:

```powershell
.\env\python.exe -m pytest `
    testing\test_publication_schema.py `
    testing\test_publication_conversion.py `
    testing\test_publication_interoperability.py `
    testing\test_publication_manifest.py `
    testing\test_publication_validation.py `
    testing\test_publication_publish.py `
    testing\test_publication_pruning.py `
    testing\test_publication_compaction.py -q
```

Expected outcomes:

- Arrow schemas match the versioned cell and fact contracts, including types, units, nullability,
  canonical logical keys, and geometry-free facts.
- PyArrow inspects GeoParquet 1.1.0 metadata, CRS PROJJSON, geometry types, extents, checksums,
  and row counts. DuckDB Spatial reads and queries both tables without ArcPy.
- A filter for one origin skips unrelated files or row groups using recorded pruning metadata.
- Missing, duplicate, unexpected, corrupt, incompatible, or unreconciled output is rejected and
  cannot acquire a successful publication marker.
- Non-route outcomes are counted but do not appear as OD facts. Every solvable dimension row and
  fact endpoint satisfies Feature 001 eligibility evidence.
- Feature 002 prefilter-pruned pairs are excluded from expected publication keys and their count
  and provenance remain in the manifest.

## Verify Atomic Publication Recovery

Inject process interruption at staging, data validation, manifest creation, and publication
exposure. Restart and reconcile using manifests, file references, and logical keys.

Expected outcomes:

- Consumers observe either the previous complete version or the new complete version.
- No incomplete stage is accepted as a completed dataset.
- The completion marker is absent or invalid unless every required check passes.
- Re-running validation or publication does not create duplicate logical facts or mutate an
  earlier version.

## Verify Compaction Equivalence

Compact a multi-origin fixture into a new immutable version. Independently read both versions
with PyArrow and DuckDB Spatial and compare canonical cell and fact records by logical identity.

Expected outcomes:

- Logical rows, identifiers, values, units, nullability, geometry semantics, and reconciliation
  remain identical.
- Checksums, row counts, extents, and partition totals agree with the new version's manifests.
- Origin filtering continues to skip unrelated origin data after physical parts are combined.
- The pre-compaction version and its parts remain unchanged.

## Verify GeoPandas Is Not Used

Run the feature dependency/import checks together with the publication tests.

Expected outcomes:

- No GeoPandas dependency, import, or usage exists in Feature 004 source, tests, or tooling.
- ArcPy-free reader checks use PyArrow and DuckDB only.
