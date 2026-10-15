"""Portable tests for OD solve outcome classification and coordination."""

import json
import math
from collections.abc import Iterator
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.network.solver import solve_network_od
from h3_route_data_builder.od.ledger import ODLedger, WorkState
from h3_route_data_builder.od.results import (
    OutcomeClass,
    SolveOutcome,
    classify_actual_cost,
    compatibility_fingerprint,
)
from h3_route_data_builder.od.solving import solve_work_item

ORIGIN = 617700169958293503
FAR = 617700169958555647
INVALID = 617700169958817791
NEAR = 617700169959079935


def test_compatibility_fingerprint_excludes_run_provenance() -> None:
    result_inputs = {
        "network": {"id": "streets", "version": "1"},
        "cost": {"attribute": "Length", "unit": "m"},
        "candidate_policy": {
            "cutoff": 1000,
            "cutoff_unit": "m",
            "mode": "aoi_only",
            "reach_distance_m": 1000,
        },
        "aoi": "first-area",
        "batch_size": 100,
    }
    expanded = {
        **result_inputs,
        "aoi": "larger-area",
        "batch_size": 25,
        "execution_limits": {"hard_cap": 100_000},
        "candidate_policy": {
            "cutoff": 1000,
            "cutoff_unit": "m",
            "mode": "aoi_to_surrounding",
            "reach_distance_m": 3000,
        },
    }

    assert compatibility_fingerprint(result_inputs) == compatibility_fingerprint(expanded)


def test_compatibility_fingerprint_changes_for_result_affecting_inputs() -> None:
    original = {"network": "streets-v1", "cost_unit": "m"}

    assert compatibility_fingerprint(original) != compatibility_fingerprint(
        {"network": "streets-v2", "cost_unit": "m"}
    )
    assert compatibility_fingerprint({"candidate_policy": {"cutoff": 10}}) != (
        compatibility_fingerprint({"candidate_policy": {"cutoff": 11}})
    )


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (10.0, OutcomeClass.QUALIFYING),
        (10.01, OutcomeClass.CUTOFF_EXCLUDED),
    ],
)
def test_actual_cost_controls_cutoff_classification(cost: float, expected: OutcomeClass) -> None:
    outcome = classify_actual_cost((ORIGIN, NEAR), cost, 10.0, "m")

    assert outcome.classification is expected
    assert outcome.actual_cost == cost
    assert outcome.cost_unit == "m"


@pytest.mark.parametrize("cost", [-1.0, math.nan, math.inf])
def test_invalid_actual_cost_is_rejected(cost: float) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        classify_actual_cost((ORIGIN, NEAR), cost, 10.0, "m")


def test_unroutable_outcomes_have_no_route_cost() -> None:
    outcome = SolveOutcome(
        logical_od_key=(ORIGIN, NEAR),
        classification=OutcomeClass.UNLOCATED,
        actual_cost=None,
        cost_unit=None,
        diagnostic="destination could not be located",
    )

    assert outcome.actual_cost is None
    assert outcome.classification is OutcomeClass.UNLOCATED


def test_network_adapter_records_missing_representative_as_unlocated(
    tmp_path: Path,
) -> None:
    (outcome,) = solve_network_od(
        network_dataset_path="network",
        expected_keys=((ORIGIN, NEAR),),
        representatives={},
        travel_mode="driving",
        cost_attribute="TravelTime",
        cost_unit="minutes",
        cutoff=10.0,
        spatial_reference=None,
        scratch_directory=tmp_path,
    )

    assert outcome.logical_od_key == (ORIGIN, NEAR)
    assert outcome.classification is OutcomeClass.UNLOCATED
    assert outcome.actual_cost is None
    assert outcome.diagnostic


@pytest.mark.parametrize(
    "invalid_output",
    [
        None,
        "unknown_status",
        "duplicate_status",
        "missing_status",
        "unknown_route",
        "duplicate_route",
    ],
)
def test_network_adapter_solves_all_destinations_without_applying_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_output: str | None
) -> None:
    solver_instances: list[Any] = []
    inserted_rows: list[tuple[Any, ...]] = []

    class Cursor:
        def __init__(self, rows: tuple[tuple[Any, ...], ...] = ()) -> None:
            self.rows = rows

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
            return False

        def __iter__(self) -> Iterator[tuple[Any, ...]]:
            return iter(self.rows)

        def insertRow(self, row: tuple[Any, ...]) -> None:
            inserted_rows.append(row)

    class FakeSolver:
        def __init__(self, network_path: str) -> None:
            self.network_path = network_path
            solver_instances.append(self)

        def load(self, data_type: str, feature_class: str) -> None:
            pass

        def solve(self) -> Any:
            return SimpleNamespace(
                solveSucceeded=True,
                export=lambda output_type, path: None,
            )

    arcpy = ModuleType("arcpy")
    arcpy.AddMessage = lambda message: None
    arcpy.AddWarning = lambda message: None
    arcpy.AddError = lambda message: None
    arcpy.Exists = lambda path: True
    arcpy.ExecuteError = type("ExecuteError", (Exception,), {})
    arcpy.GetMessages = lambda severity: ""
    arcpy.Point = lambda x, y: (x, y)
    arcpy.PointGeometry = lambda point, reference: point
    arcpy.management = SimpleNamespace(
        CreateFileGDB=lambda *args, **kwargs: None,
        CreateFeatureclass=lambda *args, **kwargs: None,
        AddField=lambda *args, **kwargs: None,
    )

    def search_cursor(path: str, fields: list[str]) -> Cursor:
        if fields == ["Name", "Status"]:
            rows = (
                (("endpoint-0", 0),)
                if path.endswith("origin_status")
                else (("endpoint-1", 0), ("endpoint-2", 1), ("endpoint-3", 0))
            )
            if path.endswith("destination_status"):
                if invalid_output == "unknown_status":
                    rows = (*rows[:-1], ("unknown", 0))
                elif invalid_output == "duplicate_status":
                    rows = (*rows, rows[0])
                elif invalid_output == "missing_status":
                    rows = rows[:-1]
        else:
            rows = (("endpoint-0", "endpoint-3", 5.0), ("endpoint-0", "endpoint-1", 12.0))
            if invalid_output == "unknown_route":
                rows = (("endpoint-0", "unknown", 5.0),)
            elif invalid_output == "duplicate_route":
                rows = (*rows, rows[0])
        return Cursor(rows)

    arcpy.da = SimpleNamespace(
        InsertCursor=lambda *args, **kwargs: Cursor(),
        SearchCursor=search_cursor,
    )
    arcpy.ListFields = lambda path: [
        SimpleNamespace(name=name)
        for name in (
            ("OriginName", "DestinationName", "Total_Time")
            if path.endswith("od_lines")
            else ("Name", "Status")
        )
    ]
    arcpy.nax = SimpleNamespace(
        OriginDestinationCostMatrix=FakeSolver,
        OriginDestinationCostMatrixInputDataType=SimpleNamespace(
            Origins="origins", Destinations="destinations"
        ),
        OriginDestinationCostMatrixOutputDataType=SimpleNamespace(
            Lines="lines", Origins="origins", Destinations="destinations"
        ),
        MessageSeverity=SimpleNamespace(All="all"),
        TimeUnits=SimpleNamespace(Minutes="minutes"),
        DistanceUnits=SimpleNamespace(Meters="meters"),
    )
    arcpy.na = SimpleNamespace(
        GetTravelModes=lambda network_path: {"driving": '{"impedanceAttributeName":"TravelTime"}'}
    )
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    representatives = {
        endpoint: NetworkLocation(
            x=index,
            y=index,
            source_id=1,
            source_oid=index,
            pos_along=0.5,
            side_of_edge=1,
            snap_distance_m=0.0,
        )
        for index, endpoint in enumerate((ORIGIN, NEAR, FAR, INVALID), start=1)
    }
    if invalid_output is not None:
        with pytest.raises(RuntimeError, match="unknown|duplicate|omitted"):
            solve_network_od(
                "network",
                ((ORIGIN, NEAR), (ORIGIN, FAR), (ORIGIN, INVALID)),
                representatives,
                "driving",
                "TravelTime",
                "minutes",
                10.0,
                "projected-reference",
                tmp_path,
            )
        return
    outcomes = solve_network_od(
        network_dataset_path="network",
        expected_keys=(
            (ORIGIN, NEAR),
            (ORIGIN, FAR),
            (ORIGIN, INVALID),
        ),
        representatives=representatives,
        travel_mode="driving",
        cost_attribute="TravelTime",
        cost_unit="minutes",
        cutoff=10.0,
        spatial_reference="projected-reference",
        scratch_directory=tmp_path,
    )

    assert solver_instances[0].defaultDestinationCount == 3
    assert solver_instances[0].defaultImpedanceCutoff is None
    assert solver_instances[0].timeUnits == "minutes"
    assert [outcome.logical_od_key for outcome in outcomes] == [
        (ORIGIN, NEAR),
        (ORIGIN, FAR),
        (ORIGIN, INVALID),
    ]
    assert {row[0] for row in inserted_rows} == {
        "endpoint-0",
        "endpoint-1",
        "endpoint-2",
        "endpoint-3",
    }
    assert [row[1:5] for row in inserted_rows] == [
        (1, 1, 0.5, 1),
        (1, 3, 0.5, 1),
        (1, 4, 0.5, 1),
        (1, 2, 0.5, 1),
    ]
    assert tuple(outcome.classification for outcome in outcomes) == (
        OutcomeClass.QUALIFYING,
        OutcomeClass.CUTOFF_EXCLUDED,
        OutcomeClass.UNLOCATED,
    )


def test_network_adapter_solves_a_located_pair_on_configured_network(
    arcpy_module: Any,
    real_network_dataset: str,
    temp_dir: Path,
) -> None:
    arcpy = arcpy_module
    travel_mode = "Driving Time"
    network_reference = arcpy.Describe(real_network_dataset).spatialReference
    feature_name = f"od_solver_smoke_{uuid4().hex}"
    feature_class = f"memory/{feature_name}"
    arcpy.management.CreateFeatureclass(
        out_path="memory",
        out_name=feature_name,
        geometry_type="POINT",
        spatial_reference=network_reference,
    )
    arcpy.management.AddField(feature_class, "Name", "TEXT", field_length=64)
    coordinates = {
        "origin": (-73.9857, 40.7484),
        "destination": (-73.9772, 40.7527),
    }
    ids_by_label = {"origin": ORIGIN, "destination": NEAR}
    with arcpy.da.InsertCursor(feature_class, ["Name", "SHAPE@"]) as cursor:
        for endpoint, (x, y) in coordinates.items():
            point = arcpy.PointGeometry(arcpy.Point(x, y), network_reference)
            cursor.insertRow((endpoint, point))
    try:
        arcpy.na.CalculateLocations(
            in_point_features=feature_class,
            in_network_dataset=real_network_dataset,
            travel_mode=travel_mode,
        )
        representatives = {}
        with arcpy.da.SearchCursor(
            feature_class,
            [
                "Name",
                "SHAPE@XY",
                "SourceID",
                "SourceOID",
                "PosAlong",
                "SideOfEdge",
                "DistanceToNetworkInMeters",
            ],
        ) as cursor:
            for (
                endpoint,
                xy,
                source_id,
                source_oid,
                pos_along,
                side,
                snap_distance,
            ) in cursor:
                representatives[ids_by_label[endpoint]] = NetworkLocation(
                    x=xy[0],
                    y=xy[1],
                    source_id=source_id,
                    source_oid=source_oid,
                    pos_along=pos_along,
                    side_of_edge=side,
                    snap_distance_m=snap_distance,
                )
        mode = json.loads(str(arcpy.na.GetTravelModes(real_network_dataset)[travel_mode]))
        (outcome,) = solve_network_od(
            network_dataset_path=real_network_dataset,
            expected_keys=((ORIGIN, NEAR),),
            representatives=representatives,
            travel_mode=travel_mode,
            cost_attribute=mode["impedanceAttributeName"],
            cost_unit="minutes",
            cutoff=120.0,
            spatial_reference=network_reference,
            scratch_directory=temp_dir / "od-solver-scratch",
        )
        assert outcome.classification is OutcomeClass.QUALIFYING
        assert outcome.actual_cost is not None
        assert outcome.cost_unit == "minutes"
    finally:
        if arcpy.Exists(feature_class):
            arcpy.management.Delete(feature_class)


def test_coordinator_solves_in_isolated_scratch_and_commits(tmp_path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    work = ledger.plan_work("fp", ORIGIN, (NEAR,), 10.0, "m")
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    observed_scratch = []

    def solver(work_item, scratch_directory):
        observed_scratch.append(scratch_directory)
        assert scratch_directory.parent == scratch_root
        assert scratch_directory.is_dir()
        return (classify_actual_cost(work_item.expected_logical_od_keys[0], 5.0, 10.0, "m"),)

    part_id = solve_work_item(
        ledger, work.work_id, "serial-coordinator", solver, 60.0, scratch_root
    )

    assert part_id
    assert not observed_scratch[0].exists()
    assert ledger.get_work(work.work_id).state is WorkState.COMMITTED
    assert len(ledger.committed_outcomes("fp")) == 1


def test_system_solve_failure_is_durable_and_not_a_route_fact(tmp_path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    work = ledger.plan_work("fp", ORIGIN, (NEAR,), 10.0, "m")

    def fail_solve(work_item, scratch_directory):
        raise OSError("synthetic network failure")

    with pytest.raises(RuntimeError, match="synthetic network failure"):
        solve_work_item(ledger, work.work_id, "serial-coordinator", fail_solve, 60.0)

    failed = ledger.get_work(work.work_id)
    assert failed.state is WorkState.RETRYABLE_FAILURE
    assert failed.failure_evidence.classification == "system_failure"
    assert ledger.committed_outcomes("fp") == ()
