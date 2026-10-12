"""Optional read-only Network Analyst smoke test for StreetMap Premium."""

import json
from uuid import uuid4

import pytest

from h3_route_data_builder.config import ConfigNode
from h3_route_data_builder.network.workflow import run_geometry_eligibility


def test_streetmap_network_calculates_location_fields_without_modifying_source(
    arcpy_module,
    real_network_dataset: str,
) -> None:
    """Calculate one in-memory test location using the configured StreetMap network."""
    network_path = real_network_dataset
    travel_modes = arcpy_module.na.GetTravelModes(network_path)
    assert "Driving Time" in travel_modes

    spatial_reference = arcpy_module.Describe(network_path).spatialReference
    feature_class_name = f"h3_location_smoke_{uuid4().hex}"
    feature_class = f"memory/{feature_class_name}"
    try:
        arcpy_module.management.CreateFeatureclass(
            out_path="memory",
            out_name=feature_class_name,
            geometry_type="POINT",
            spatial_reference=spatial_reference,
        )
        point = arcpy_module.PointGeometry(
            arcpy_module.Point(-73.9857, 40.7484),
            spatial_reference,
        )
        with arcpy_module.da.InsertCursor(feature_class, ["SHAPE@"]) as cursor:
            cursor.insertRow([point])

        arcpy_module.na.CalculateLocations(
            in_point_features=feature_class,
            in_network_dataset=network_path,
            travel_mode="Driving Time",
        )

        required_fields = ["SourceID", "SourceOID", "PosAlong", "SideOfEdge"]
        available_fields = {
            field.name for field in arcpy_module.ListFields(feature_class)
        }
        assert set(required_fields) <= available_fields
        with arcpy_module.da.SearchCursor(feature_class, required_fields) as cursor:
            location = next(cursor)
        assert all(value is not None for value in location)
    finally:
        if arcpy_module.Exists(feature_class):
            arcpy_module.management.Delete(feature_class)

    assert arcpy_module.Exists(network_path)


def test_streetmap_network_builds_reconciled_small_aoi_without_source_edits(
    arcpy_module,
    real_network_dataset: str,
    temp_dir,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Build a small real-network AOI into temporary output without editing its source."""
    network_path = real_network_dataset
    network_reference = arcpy_module.Describe(network_path).spatialReference
    aoi_name = f"h3_aoi_smoke_{uuid4().hex}"
    aoi_path = f"memory/{aoi_name}"
    arcpy_module.management.CreateFeatureclass(
        out_path="memory",
        out_name=aoi_name,
        geometry_type="POLYGON",
        spatial_reference=network_reference,
    )
    ring = arcpy_module.Array(
        [
            arcpy_module.Point(x_coord, y_coord)
            for x_coord, y_coord in [
                (-74.005, 40.743),
                (-73.975, 40.743),
                (-73.975, 40.755),
                (-74.005, 40.755),
                (-74.005, 40.743),
            ]
        ]
    )
    aoi = arcpy_module.Polygon(ring, network_reference)
    with arcpy_module.da.InsertCursor(aoi_path, ["SHAPE@"]) as cursor:
        cursor.insertRow([aoi])

    travel_mode = json.loads(
        str(arcpy_module.na.GetTravelModes(network_path)["Driving Time"])
    )
    config_node = ConfigNode(
        {
            "spatial": {
                "h3_resolution": 9,
                "intersection_policy": "inclusive",
                "representative_snap_tolerance_m": 0.1,
            },
            "network": {
                "travel_mode": "Driving Time",
                "restrictions": travel_mode["restrictionAttributeNames"],
            },
            "eligibility": {
                "representative_policy": "nearest_centroid_then_source_id_oid_measure",
            },
        }
    )
    output_directory = temp_dir / "eligibility-output"
    try:
        result = run_geometry_eligibility(
            aoi_path,
            network_path,
            output_directory,
            config_node,
        )
        assert result.run_status == "complete"
        assert result.expected_partition_count == result.reconciled_partition_count
        assert result.cell_result_count > 0
        manifest_path = result.run_directory / "run-manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert {
            name: limit["source"]
            for name, limit in manifest["execution_limits"].items()
            if name in {"batch_size", "part_row_limit", "total_output_hard_cap"}
        } == {
            "batch_size": "inferred",
            "part_row_limit": "inferred",
            "total_output_hard_cap": "inferred",
        }
        assert all(
            int(limit["value"]) > 0
            for name, limit in manifest["execution_limits"].items()
            if name in {"batch_size", "part_row_limit", "total_output_hard_cap"}
        )
        assert manifest["execution_limits"]["policy_version"] == "1"
        assert (
            manifest["execution_limits"]["resource_snapshot"]["available_memory_bytes"]
            > 0
        )
        assert (
            manifest["execution_limits"]["resource_snapshot"]["available_disk_bytes"]
            > 0
        )
        assert "Execution limit batch_size=" in caplog.text
        assert "inferred" in caplog.text
        assert (result.run_directory / "run-state.json").is_file()
        resumed_result = run_geometry_eligibility(
            aoi_path,
            network_path,
            output_directory,
            config_node,
        )
        assert resumed_result.run_id == result.run_id
        assert "reused from existing run" in caplog.text
        caplog.clear()
        with pytest.raises(
            ValueError,
            match="Explicit execution limits differ from the existing run",
        ):
            run_geometry_eligibility(
                aoi_path,
                network_path,
                output_directory,
                config_node,
                batch_size=int(manifest["execution_limits"]["batch_size"]["value"]) + 1,
            )
    finally:
        if arcpy_module.Exists(aoi_path):
            arcpy_module.management.Delete(aoi_path)
    assert arcpy_module.Exists(network_path)
