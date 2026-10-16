# Research: H3 Hexagon Review Feature Class Export

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

All Technical Context unknowns are resolved below. No `NEEDS CLARIFICATION` items remain.

## R1. H3 index storage type

- **Decision**: Store `h3_index` in an ArcGIS Text field of length 20 (`AddField` keyword `TEXT`;
  reported by `ListFields` as `String`) holding the exact decimal integer, `str(h3_id)`.
- **Rationale**: Feature 006 and the shared data contract define H3 identity as an exact integer.
  The user first chose Big Integer. Implementation showed that ArcGIS Big Integer fields are
  limited to 53 bits: inserting an H3 index fails with Esri error 161017, "Big integer values are
  currently limited to 53 bits". Every valid H3 cell index is at least 2^59, so no H3 index fits.
  The user then chose decimal text. A 64-bit unsigned integer has at most 20 decimal digits, so the
  value is exact, and `int(h3_index)` recovers the GeoParquet `uint64` `h3_id`.
- **Alternatives considered**:
    - Big Integer: infeasible because of the 53-bit limit (above).
    - Hexadecimal text: the canonical H3 string, but the user wants the integer identity and the
      contract removed hexadecimal identities.
    - `DOUBLE`: loses precision above 2^53, which corrupts H3 indices.
    - Two 32-bit `LONG` halves: lossless but unusable for interactive review and joins.

## R2. Platform and workspace support

- **Decision**: Require a geodatabase workspace (file, mobile, or enterprise) on the project's
  supported ArcGIS Pro release (Python 3.11+, so Pro 3.3+). Validate in `updateMessages` that the
  output's parent workspace `workspaceType` is `LocalDatabase` or `RemoteDatabase`, using the
  geodatabase that contains a feature dataset if needed; reject folders (shapefile output).
- **Rationale**: The schema uses non-nullable fields, which shapefiles do not support. One
  workspace family keeps one schema for the artifact. Unsupported enterprise configurations
  surface as an `AddField` failure, handled by FR-013 cleanup.
- **Alternatives considered**: Allowing shapefile output with nullable fields — rejected because
  it would produce two schemas for one artifact.

## R3. Source of rows: manifest-listed, checksum-verified parts

- **Decision**: Read rows only from parts listed in `run-manifest.json` `parts`, verified with the
  existing `read_verified_staged_part` (checksum, row count, integer schema). Resolve part paths
  relative to the run directory returned in `EligibilityBuildSummary.run_directory`, not the
  absolute `manifest["run_directory"]` string. Require `manifest["run_status"] == "complete"`.
- **Rationale**: Satisfies the resumed-run edge case (stale part files on disk are ignored),
  reuses the integrity checks used for resume, and tolerates a moved output folder.
- **Alternatives considered**: `rglob("*.parquet")` — rejected; can include superseded parts and
  skips integrity verification.

## R4. Deterministic ascending order with bounded memory

- **Decision**: Iterate `manifest["expected_partition_keys"]` in order. For each partition, read
  its verified parts, project to `h3_id`, `resolution`, `eligibility_status`, `cell_geometry`,
  sort by `h3_id`, and yield. Assert strictly increasing `h3_id` across the whole stream; a
  violation fails the export.
- **Rationale**: The workflow batches the canonically sorted candidate list into consecutive
  partitions, so partitions cover disjoint ascending ID ranges, but row order *within* a partition
  follows geometry processing order and is not guaranteed sorted. Sorting per partition bounds
  memory to one partition (at most the run's resolved `batch_size` rows — Principle VII) while
  producing a globally ascending stream. The strict check also catches duplicate IDs.
- **Alternatives considered**: Load all rows and sort — unbounded for large AOIs. K-way merge of
  all parts — needs every part open at once and is unnecessary given the partition invariant.

## R5. Geometry source

- **Decision**: Build each polygon from the row's stored `cell_geometry` WKB via
  `arcpy.FromWKB` with the WGS 84 spatial reference (`WGS84_CRS_NAME`), and create the feature
  class in that same spatial reference.
- **Rationale**: The stored geometry is already the validated canonical H3 boundary in WGS 84
  (enforced by `_validate_wgs84_geometry` at write time), so the review layer matches the
  GeoParquet exactly and no reprojection or recomputation occurs. Reuses the existing CRS
  constant rather than hardcoding a WKID.
- **Alternatives considered**: Recompute from `h3_cell_polygon(h3_id)` — duplicates work and could
  drift from the authoritative stored geometry.

## R6. H3 validation

- **Decision**: Validate each `h3_id` with the existing ArcPy-free `canonical_h3_ids` rules (exact
  `int`, unsigned 64-bit range, `is_valid_cell`) and require `h3.get_resolution(h3_id)` and the
  row `resolution` to equal `manifest["policy"]["h3_resolution"]`.
- **Rationale**: FR-010. Reuses Feature 006 validation semantics; resolution check catches mixed
  or corrupted output.

## R7. Failure atomicity and overwrite

- **Decision**: Write directly to the target, wrapping creation and insertion in
  `try`/`except`; on any exception delete the target if it exists (`arcpy.management.Delete`),
  log, and re-raise. Overwrite follows `arcpy.env.overwriteOutput`; `updateMessages` reports an
  error when the target exists and overwrite is off.
- **Rationale**: FR-013 requires no partial output. Writing via `memory` and copying would add a
  copy step and risk field-type changes during copy.
- **Alternatives considered**: Write to a temporary name then rename — `Rename` semantics vary by
  workspace; not needed for a non-published review artifact.

## R8. Module boundaries

- **Decision**:
    - `src/h3_route_data_builder/eligibility/review.py` (no ArcPy): manifest reading, part
      selection, validation, ordering; yields `ReviewCell` records.
    - `src/h3_route_data_builder/network/review_export.py` (ArcPy): feature class creation,
      Text `h3_index` field, insertion, cleanup.
    - `arcgis/h3_route_data_builder.pyt`: two appended parameters and delegation only.
- **Rationale**: Constitution Principle II and FR-015/FR-016. Mirrors the existing
  `eligibility/` (portable) vs `network/` (ArcPy) split.

## R9. Dependencies

- **Decision**: No new dependencies. Uses `pyarrow`, `h3` (v4 `basic_int` API), and ArcPy, all
  already present.
