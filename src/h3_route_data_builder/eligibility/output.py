"""Portable conversion of eligibility results to the staged GeoParquet schema."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa

from .models import CellEligibilityResult
from .fingerprint import ELIGIBILITY_SCHEMA_VERSION
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

GeometryWkb = tuple[bytes, bytes, bytes | None]

_WGS84_PROJJSON = {
    "$schema": "https://proj.org/schemas/v0.4/projjson.schema.json",
    "type": "GeographicCRS",
    "name": "WGS 84",
    "datum_ensemble": {
        "name": "World Geodetic System 1984 ensemble",
        "members": [
            {
                "name": "World Geodetic System 1984 (Transit)",
                "id": {"authority": "EPSG", "code": 1166},
            },
            {
                "name": "World Geodetic System 1984 (G730)",
                "id": {"authority": "EPSG", "code": 1152},
            },
            {
                "name": "World Geodetic System 1984 (G873)",
                "id": {"authority": "EPSG", "code": 1153},
            },
            {
                "name": "World Geodetic System 1984 (G1150)",
                "id": {"authority": "EPSG", "code": 1154},
            },
            {
                "name": "World Geodetic System 1984 (G1674)",
                "id": {"authority": "EPSG", "code": 1155},
            },
            {
                "name": "World Geodetic System 1984 (G1762)",
                "id": {"authority": "EPSG", "code": 1156},
            },
            {
                "name": "World Geodetic System 1984 (G2139)",
                "id": {"authority": "EPSG", "code": 1309},
            },
        ],
        "ellipsoid": {
            "name": "WGS 84",
            "semi_major_axis": 6378137,
            "inverse_flattening": 298.257223563,
        },
        "accuracy": "2.0",
        "id": {"authority": "EPSG", "code": 6326},
    },
    "coordinate_system": {
        "subtype": "ellipsoidal",
        "axis": [
            {
                "name": "Geodetic latitude",
                "abbreviation": "Lat",
                "direction": "north",
                "unit": "degree",
            },
            {
                "name": "Geodetic longitude",
                "abbreviation": "Lon",
                "direction": "east",
                "unit": "degree",
            },
        ],
    },
    "scope": "Horizontal component of 3D system.",
    "area": "World.",
    "bbox": {
        "south_latitude": -90,
        "west_longitude": -180,
        "north_latitude": 90,
        "east_longitude": 180,
    },
    "id": {"authority": "EPSG", "code": 4326},
}

_GEO_METADATA = {
    "version": "1.0.0",
    "primary_column": "cell_geometry",
    "columns": {
        "cell_geometry": {
            "encoding": "WKB",
            "geometry_types": ["Polygon"],
            "crs": _WGS84_PROJJSON,
        },
        "centroid_geometry": {
            "encoding": "WKB",
            "geometry_types": ["Point"],
            "crs": _WGS84_PROJJSON,
        },
        "representative_geometry": {
            "encoding": "WKB",
            "geometry_types": ["Point"],
            "crs": _WGS84_PROJJSON,
        },
    },
}


def eligibility_results_to_table(
    results: Sequence[CellEligibilityResult],
    geometry_wkb: Mapping[int, GeometryWkb],
) -> pa.Table:
    """Build a deterministic GeoParquet-compatible Arrow table from cell results.

    Geometry projection/WKB encoding is performed by the ArcPy network adapter. This function
    only serializes validated WKB and non-spatial evidence and does not import ArcPy.

    Args:
        results: Globally reconciled cell eligibility results.
        geometry_wkb: H3 ID to cell, centroid, and optional representative WKB tuple.

    Returns:
        Arrow table with GeoParquet 1.0 geometry metadata and contract fields.

    Raises:
        ValueError: If any row is missing required polygon/centroid WKB.
    """
    rows: list[dict[str, Any]] = []
    for result in results:
        geometries = geometry_wkb.get(result.h3_id)
        if geometries is None:
            raise ValueError(f"Missing serialized geometries for H3 cell {result.h3_id}")
        cell_wkb, centroid_wkb, representative_wkb = geometries
        if not cell_wkb or not centroid_wkb:
            raise ValueError(f"Cell and centroid WKB are required for H3 cell {result.h3_id}")

        representative = result.representative
        rows.append(
            {
                "h3_id": result.h3_id,
                "resolution": result.resolution,
                "cell_geometry": cell_wkb,
                "centroid_geometry": centroid_wkb,
                "representative_geometry": representative_wkb,
                "intersecting_edge_count": result.intersecting_edge_count,
                "network_source_id": (representative.source_id if representative else None),
                "network_source_oid": (representative.source_oid if representative else None),
                "pos_along": representative.pos_along if representative else None,
                "side_of_edge": representative.side_of_edge if representative else None,
                "representative_snap_distance_m": (
                    representative.snap_distance_m if representative else None
                ),
                "eligibility_status": result.eligibility_status.value,
                "eligibility_reason": result.eligibility_reason,
                "edge_evidence_json": json.dumps(
                    [
                        {
                            "source_id": edge.source_id,
                            "source_oid": edge.source_oid,
                            "eligibility_status": edge.eligibility_status,
                            "reason": edge.reason,
                            "travel_direction": edge.travel_direction,
                        }
                        for edge in result.edge_evidence
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "policy_evidence_json": json.dumps(
                    result.policy_evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "build_fingerprint": result.build_fingerprint,
            }
        )

    schema = pa.schema(
        [
            pa.field("h3_id", pa.uint64(), nullable=False),
            pa.field("resolution", pa.int8(), nullable=False),
            pa.field("cell_geometry", pa.binary(), nullable=False),
            pa.field("centroid_geometry", pa.binary(), nullable=False),
            pa.field("representative_geometry", pa.binary()),
            pa.field("intersecting_edge_count", pa.int32(), nullable=False),
            pa.field("network_source_id", pa.int32()),
            pa.field("network_source_oid", pa.int64()),
            pa.field("pos_along", pa.float64()),
            pa.field("side_of_edge", pa.int8()),
            pa.field("representative_snap_distance_m", pa.float64()),
            pa.field("eligibility_status", pa.string(), nullable=False),
            pa.field("eligibility_reason", pa.string(), nullable=False),
            pa.field("edge_evidence_json", pa.string(), nullable=False),
            pa.field("policy_evidence_json", pa.string(), nullable=False),
            pa.field("build_fingerprint", pa.string(), nullable=False),
        ],
        metadata={
            b"geo": json.dumps(_GEO_METADATA, sort_keys=True).encode("utf-8"),
            b"eligibility_schema_version": ELIGIBILITY_SCHEMA_VERSION.encode(),
        },
    )
    arrays = [pa.array([row[field.name] for row in rows], type=field.type) for field in schema]
    table = pa.Table.from_arrays(arrays, schema=schema)
    logger.info("Serialized %s eligibility rows for GeoParquet staging", table.num_rows)
    return table
