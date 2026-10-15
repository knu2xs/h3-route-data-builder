"""Optional read-only Network Analyst smoke test for StreetMap Premium."""

import json
import os
from uuid import uuid4

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from h3_route_data_builder.config import ConfigNode
from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.network.workflow import run_geometry_eligibility
from h3_route_data_builder.od.execution import (
    ParallelExecutionConfig,
    probe_parallel_capacity,
)
from h3_route_data_builder.od.ledger import ODLedger, WorkState
from h3_route_data_builder.od.preparation import prepare_solve_input


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
        available_fields = {field.name for field in arcpy_module.ListFields(feature_class)}
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

    travel_mode = json.loads(str(arcpy_module.na.GetTravelModes(network_path)["Driving Time"]))
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
        assert manifest["schema_version"] == "2"
        for part in manifest["parts"]:
            table = pq.ParquetFile(result.run_directory / part["path"]).read()
            assert table.schema.field("h3_id").type == pa.uint64()
            assert all(
                type(cell_id) is int and cell_id > 2**53
                for cell_id in table.column("h3_id").to_pylist()
            )
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
        assert manifest["execution_limits"]["resource_snapshot"]["available_memory_bytes"] > 0
        assert manifest["execution_limits"]["resource_snapshot"]["available_disk_bytes"] > 0
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


def test_parallel_probe_uses_configured_network_and_keeps_output_non_authoritative(
    arcpy_module,
    real_network_dataset: str,
    temp_dir,
) -> None:
    """Exercise the actual network/license probe without writing to the durable ledger."""
    network_path = real_network_dataset
    license_status = arcpy_module.CheckExtension("Network")
    if license_status not in {"Available", "CheckedOut"}:
        pytest.skip(f"Network Analyst extension is unavailable: {license_status}")
    cpu_count = os.cpu_count()
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}},
        cpu_count=cpu_count,
    )
    if policy.resource_worker_ceiling < 2:
        pytest.skip("At least two logical CPUs are required to exercise the probe")

    network_reference = arcpy_module.Describe(network_path).spatialReference
    wkid = network_reference.factoryCode
    if not isinstance(wkid, int) or wkid <= 0:
        pytest.skip("Configured network dataset has no portable spatial-reference WKID")
    feature_class_name = f"h3_probe_locations_{uuid4().hex}"
    feature_class = f"memory/{feature_class_name}"
    try:
        arcpy_module.management.CreateFeatureclass(
            out_path="memory",
            out_name=feature_class_name,
            geometry_type="POINT",
            spatial_reference=network_reference,
        )
        with arcpy_module.da.InsertCursor(feature_class, ["SHAPE@"]) as cursor:
            for x_coord, y_coord in (
                (-73.9857, 40.7484),
                (-73.9760, 40.7490),
            ):
                point = arcpy_module.PointGeometry(
                    arcpy_module.Point(x_coord, y_coord),
                    network_reference,
                )
                cursor.insertRow([point])
        arcpy_module.na.CalculateLocations(
            in_point_features=feature_class,
            in_network_dataset=network_path,
            travel_mode="Driving Time",
        )
        fields = [
            "SHAPE@XY",
            "SourceID",
            "SourceOID",
            "PosAlong",
            "SideOfEdge",
            "DistanceToNetworkInMeters",
        ]
        with arcpy_module.da.SearchCursor(feature_class, fields) as cursor:
            locations = tuple(cursor)
    finally:
        if arcpy_module.Exists(feature_class):
            arcpy_module.management.Delete(feature_class)

    if len(locations) != 2 or any(any(value is None for value in row[1:]) for row in locations):
        pytest.skip("Configured network did not locate both probe representatives")
    representatives = {
        h3_id: NetworkLocation(
            x=float(row[0][0]),
            y=float(row[0][1]),
            source_id=int(row[1]),
            source_oid=int(row[2]),
            pos_along=float(row[3]),
            side_of_edge=int(row[4]),
            snap_distance_m=float(row[5]),
        )
        for h3_id, row in zip((619056821839593471, 619056559457304575), locations)
    }
    travel_mode = arcpy_module.na.GetTravelModes(network_path)["Driving Time"]
    cost_attribute = json.loads(str(travel_mode))["impedanceAttributeName"]
    ledger = ODLedger(temp_dir / "probe-ledger.sqlite")
    item = ledger.plan_work(
        "probe-compatibility",
        619056821839593471,
        [619056559457304575],
        30,
        "minutes",
    )
    prepared = prepare_solve_input(
        item,
        representatives,
        network_path,
        "Driving Time",
        cost_attribute,
        wkid,
    )
    scratch_root = temp_dir / "probe-scratch"

    report = probe_parallel_capacity(prepared, policy, scratch_root=scratch_root)

    assert report.attempts
    assert report.selected_worker_count is not None or report.fallback_reason
    assert ledger.get_work(item.work_id).state is WorkState.PLANNED
    assert not ledger.committed_outcomes(item.compatibility_fingerprint)
    assert not list(scratch_root.iterdir())
