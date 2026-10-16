# Review Export

The **Build H3 Geometry Eligibility** tool can also save its H3 cells as a feature class of
hexagons. Use it to review eligibility interactively in ArcGIS Pro: symbolize, select, and
identify cells on a map.

!!! warning
    The review feature class is a builder-local review aid. It is optional and never published,
    versioned, or fingerprinted. Solver consumers, including `h3-route-solver`, must not read it as
    contract data. The GeoParquet output remains the authoritative eligibility dataset.

## Enable the export

1. Open **Build H3 Geometry Eligibility** and set the usual inputs.
2. Check **Also Save Hexagons as Feature Class**.
3. Set **Output Hexagon Feature Class** to a feature class path in a geodatabase, for example
   `C:\work\review.gdb\eligibility_hexagons`.
4. Run the tool.

The output path is disabled until the checkbox is checked. After the eligibility run completes,
the tool writes the feature class from the completed run and reports the feature count. Leaving
the box unchecked keeps the tool's behavior and outputs exactly as before.

## Requirements

- The output must be in a file, mobile, or enterprise geodatabase. Folder (shapefile) outputs are
  rejected during validation because the schema uses non-nullable fields.
- If the feature class already exists, enable the geoprocessing overwrite setting or choose a new
  name. Otherwise validation reports an error.

## Fields

| Field | Type | Value |
|---|---|---|
| `h3_index` | Text (20) | Exact decimal integer H3 index, equal to GeoParquet `h3_id` |
| `eligibility_status` | Text (32) | Eligibility status copied unchanged from the GeoParquet row |

!!! note
    `h3_index` is stored as text because ArcGIS Big Integer fields are limited to 53 bits, and
    every H3 index needs about 60 bits. The text holds the full decimal integer, so no precision is
    lost. For example, `617700169958293503` is the integer form of H3 cell `8928308280fffff`.

Features are inserted in ascending `h3_id` order, so ObjectID order matches H3 order.

## Coordinate system

Hexagons are written in WGS 84, the same coordinate system as the GeoParquet `cell_geometry`
column. The stored cell polygons are copied as is; they are not recomputed or reprojected.

## Join to GeoParquet

Join on `h3_index` = `h3_id`. Because `h3_id` is an unsigned 64-bit integer, convert one side
so the types match. In Python, use `int(h3_index)` or `str(h3_id)`.

```python
import pyarrow.parquet as pq

table = pq.read_table("parts/partition-000000/partition-000000-000000.parquet")
status_by_index = {
    str(h3_id): status
    for h3_id, status in zip(
        table["h3_id"].to_pylist(), table["eligibility_status"].to_pylist()
    )
}
```

## Symbolize by eligibility status

In ArcGIS Pro, set the layer's symbology to **Unique Values** on `eligibility_status` so solvable
and non-solvable cells are easy to tell apart.

## Zero cells and failures

- If the run evaluated no cells, the tool creates an empty feature class and logs a warning.
- The export runs only after the eligibility run completes. If the run fails, no feature class is
  written.
- If the export fails, any partially written feature class is deleted and the error is raised.
  The completed GeoParquet run is never modified.
