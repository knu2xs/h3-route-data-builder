# Feature 004: GeoParquet Publication

Feature 006 advances new dataset/cell/fact schemas to `2.0.0`, retaining GeoParquet `1.1.0`.
Cells require `uint64` `h3_id`; facts require `uint64` `origin_h3_id` and `destination_h3_id`.
No hexadecimal or optional numeric aliases remain. Manifest origin arrays contain integers;
decimal partition directory labels are not authoritative identities. Historical publications
remain immutable. Coordinated solver adoption of the proposed shared contract is still a release gate.

- Partition OD facts by canonical solvable-origin H3.
- Keep geometry in the solvable-cell dimension; OD facts may be ordinary Parquet.
- Write valid GeoParquet metadata for geometry columns.
- Add bbox/covering metadata where supported; spatially order rows and write useful row-group statistics.
- Publish dataset and partition manifests with checksums, row counts, extents, schema versions, and completion state.
- Use staging and publish `_SUCCESS` only after full validation.
- Support compaction without changing logical rows.

Acceptance requires GeoParquet validation, successful reads by target ArcPy-free engines, origin partition pruning, and proof that every published cell satisfies eligibility.
