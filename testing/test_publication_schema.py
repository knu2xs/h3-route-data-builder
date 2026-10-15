"""Canonical schema tests for GeoParquet publication."""

import subprocess
import sys

import pyarrow as pa

from h3_route_data_builder.publication.schema import (
    OD_FACTS_SCHEMA,
    SOLVABLE_CELLS_SCHEMA,
    schema_for,
)


def test_cell_schema_has_exact_contract_types_and_required_geometry_fields() -> None:
    assert SOLVABLE_CELLS_SCHEMA.names == [
        "h3_id",
        "resolution",
        "cell_geometry",
        "centroid_geometry",
        "representative_geometry",
        "intersecting_edge_count",
        "network_source_id",
        "network_source_oid",
        "network_pos_along",
        "network_side_of_edge",
        "representative_snap_distance_m",
        "eligibility_status",
        "eligibility_reason",
        "eligibility_fingerprint",
    ]
    assert [field.type for field in SOLVABLE_CELLS_SCHEMA] == [
        pa.uint64(),
        pa.uint8(),
        pa.binary(),
        pa.binary(),
        pa.binary(),
        pa.uint32(),
        pa.int32(),
        pa.int64(),
        pa.float64(),
        pa.int8(),
        pa.float64(),
        pa.string(),
        pa.string(),
        pa.string(),
    ]
    assert all(not field.nullable for field in SOLVABLE_CELLS_SCHEMA)
    assert SOLVABLE_CELLS_SCHEMA.field("h3_id").type == pa.uint64()
    assert SOLVABLE_CELLS_SCHEMA.metadata[b"schema_version"] == b"2.0.0"


def test_fact_schema_is_geometry_free_and_direction_sensitive() -> None:
    assert OD_FACTS_SCHEMA.names == [
        "origin_h3_id",
        "destination_h3_id",
        "travel_mode",
        "network_distance_m",
        "network_time_s",
        "origin_representative_snap_distance_m",
        "destination_representative_snap_distance_m",
        "solve_status",
        "work_item_id",
        "build_fingerprint",
    ]
    assert not any("geometry" in name for name in OD_FACTS_SCHEMA.names)
    for name in ("origin_h3_id", "destination_h3_id"):
        assert OD_FACTS_SCHEMA.field(name).type == pa.uint64()
        assert not OD_FACTS_SCHEMA.field(name).nullable
    assert OD_FACTS_SCHEMA.metadata[b"schema_version"] == b"2.0.0"
    assert schema_for("od_facts") is OD_FACTS_SCHEMA
    assert schema_for("solvable_cells") is SOLVABLE_CELLS_SCHEMA


def test_publication_package_imports_without_arcpy_or_geopandas() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import h3_route_data_builder.publication; "
                "assert 'arcpy' not in sys.modules; "
                "assert 'geopandas' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
