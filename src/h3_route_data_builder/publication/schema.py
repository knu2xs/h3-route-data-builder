"""Canonical Arrow schemas and GeoParquet metadata for published tables."""

import json
from typing import Any

import pyarrow as pa

from h3_route_data_builder.eligibility.output import _WGS84_PROJJSON
from h3_route_data_builder.publication.models import (
    CELL_SCHEMA_VERSION,
    FACT_SCHEMA_VERSION,
    GEOPARQUET_VERSION,
)


def _geometry_metadata(geometry_type: str) -> dict[str, Any]:
    return {
        "encoding": "WKB",
        "geometry_types": [geometry_type],
        "crs": _WGS84_PROJJSON,
    }


SOLVABLE_CELLS_SCHEMA = pa.schema(
    [
        pa.field("h3_id_hex", pa.string(), nullable=False),
        pa.field("h3_id_uint64", pa.uint64()),
        pa.field("resolution", pa.uint8(), nullable=False),
        pa.field("cell_geometry", pa.binary(), nullable=False),
        pa.field("centroid_geometry", pa.binary(), nullable=False),
        pa.field("representative_geometry", pa.binary(), nullable=False),
        pa.field("intersecting_edge_count", pa.uint32(), nullable=False),
        pa.field("network_source_id", pa.int32(), nullable=False),
        pa.field("network_source_oid", pa.int64(), nullable=False),
        pa.field("network_pos_along", pa.float64(), nullable=False),
        pa.field("network_side_of_edge", pa.int8(), nullable=False),
        pa.field("representative_snap_distance_m", pa.float64(), nullable=False),
        pa.field("eligibility_status", pa.string(), nullable=False),
        pa.field("eligibility_reason", pa.string(), nullable=False),
        pa.field("eligibility_fingerprint", pa.string(), nullable=False),
    ],
    metadata={
        b"publication_table": b"solvable_cells",
        b"schema_version": CELL_SCHEMA_VERSION.encode(),
        b"geo": json.dumps(
            {
                "version": GEOPARQUET_VERSION,
                "primary_column": "cell_geometry",
                "columns": {
                    "cell_geometry": _geometry_metadata("Polygon"),
                    "centroid_geometry": _geometry_metadata("Point"),
                    "representative_geometry": _geometry_metadata("Point"),
                },
            },
            sort_keys=True,
        ).encode(),
    },
)

OD_FACTS_SCHEMA = pa.schema(
    [
        pa.field("origin_h3_id_hex", pa.string(), nullable=False),
        pa.field("destination_h3_id_hex", pa.string(), nullable=False),
        pa.field("travel_mode", pa.string(), nullable=False),
        pa.field("network_distance_m", pa.float64()),
        pa.field("network_time_s", pa.float64()),
        pa.field("origin_representative_snap_distance_m", pa.float64(), nullable=False),
        pa.field(
            "destination_representative_snap_distance_m", pa.float64(), nullable=False
        ),
        pa.field("solve_status", pa.string(), nullable=False),
        pa.field("work_item_id", pa.string()),
        pa.field("build_fingerprint", pa.string(), nullable=False),
    ],
    metadata={
        b"publication_table": b"od_facts",
        b"schema_version": FACT_SCHEMA_VERSION.encode(),
    },
)


def schema_for(table_name: str) -> pa.Schema:
    """Return the canonical schema for a named logical table."""
    if table_name == "solvable_cells":
        return SOLVABLE_CELLS_SCHEMA
    if table_name == "od_facts":
        return OD_FACTS_SCHEMA
    raise ValueError(f"Unknown publication table: {table_name}")


def geoparquet_metadata(
    schema: pa.Schema, extents: dict[str, list[float]]
) -> dict[str, Any]:
    """Return file-level GeoParquet 1.1 metadata with per-column bounding boxes."""
    existing = schema.metadata or {}
    raw_geo = existing.get(b"geo")
    if raw_geo is None:
        raise ValueError("GeoParquet schema metadata is required")
    metadata = json.loads(raw_geo)
    metadata["version"] = GEOPARQUET_VERSION
    for column_name, extent in extents.items():
        if column_name not in metadata["columns"]:
            raise ValueError(f"Unknown GeoParquet geometry column: {column_name}")
        metadata["columns"][column_name]["bbox"] = extent
    return metadata
