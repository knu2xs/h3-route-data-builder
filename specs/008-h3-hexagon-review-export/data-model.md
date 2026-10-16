# Data Model: H3 Hexagon Review Feature Class Export

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

## Entity: ReviewCell (in-memory, ArcPy-free)

One validated row selected for export. Produced by `iter_review_cells` in
`eligibility/review.py`.

| Attribute | Type | Source | Rules |
|---|---|---|---|
| `h3_id` | `int` | Part column `h3_id` (`uint64`) | Valid H3 cell; resolution equals run resolution; strictly greater than the previous yielded `h3_id` |
| `eligibility_status` | `str` | Part column `eligibility_status` | Non-empty; passed through unchanged |
| `cell_geometry_wkb` | `bytes` | Part column `cell_geometry` | Non-empty WKB; WGS 84 polygon |

Frozen dataclass; no behavior beyond validation at construction time.

## Entity: Eligibility Review Feature Class (ArcGIS output)

Optional, builder-local, non-contract review artifact. Written by
`export_eligibility_review_feature_class` in `network/review_export.py`.

| Property | Value |
|---|---|
| Geometry type | Polygon |
| Spatial reference | WGS 84 (`WGS84_CRS_NAME`, same as GeoParquet `cell_geometry`) |
| Workspace | File, mobile, or enterprise geodatabase (non-nullable fields; project floor Pro 3.3+) |
| Row cardinality | Exactly one row per evaluated H3 cell; count equals manifest `cell_result_count` |
| Row order | Ascending `h3_index` (insert order, therefore ascending ObjectID) |

### Fields

| Field | ArcGIS type | Length | Nullable | Value |
|---|---|---|---|---|
| `h3_index` | Text (`TEXT`) | 20 | No | Exact decimal integer, `str(h3_id)` of the GeoParquet row |
| `eligibility_status` | Text | 32 | No | GeoParquet `eligibility_status` unchanged |

System-managed fields (ObjectID, Shape, Shape_Length, Shape_Area) are added by the geodatabase.
No other user fields are allowed (FR-008).

## Entity: Eligibility Run (existing, read-only)

Inputs consumed from the completed run directory. This feature never writes to it (FR-012).

| Manifest key | Use |
|---|---|
| `run_status` | Must equal `complete` before export |
| `policy.h3_resolution` | Expected resolution for every exported cell |
| `expected_partition_keys` | Partition iteration order |
| `parts[*].partition_key`, `part_key`, `path`, `row_count`, `checksum` | Part selection and integrity verification (relative `path` resolved against the run directory) |
| `cell_result_count` | Expected exported row count |

## Relationships

```text
Eligibility Run (manifest + verified parts)
    └── 1..N partitions (ascending, disjoint h3_id ranges)
            └── 0..N parts ──► ReviewCell stream (sorted per partition)
                                    └──► Eligibility Review Feature Class rows (1:1)
```

## Export lifecycle

```text
not requested ──(checkbox unchecked)──► no output
requested ──► eligibility run completes? ──no──► no output (run error propagates)
                     │yes
                     ▼
               writing ──success──► written (count logged)
                     │
                     └─failure──► target deleted ──► error raised; run stays complete
```
