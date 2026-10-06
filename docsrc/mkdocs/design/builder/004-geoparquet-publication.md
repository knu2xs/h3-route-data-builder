# Feature 004: GeoParquet Publication

- Partition OD facts by canonical solvable-origin H3.
- Keep geometry in the solvable-cell dimension; OD facts may be ordinary Parquet.
- Write valid GeoParquet metadata for geometry columns.
- Add bbox/covering metadata where supported; spatially order rows and write useful row-group statistics.
- Publish dataset and partition manifests with checksums, row counts, extents, schema versions, and completion state.
- Use staging and publish `_SUCCESS` only after full validation.
- Support compaction without changing logical rows.

Acceptance requires GeoParquet validation, successful reads by target ArcPy-free engines, origin partition pruning, and proof that every published cell satisfies eligibility.
