"""ArcPy Network Analyst adapter for isolated directed OD cost-matrix solves."""

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.eligibility.cells import canonical_h3_ids
from h3_route_data_builder.od.execution import WorkAssignment, WorkerResult
from h3_route_data_builder.od.results import (
    OutcomeClass,
    SolveOutcome,
    classify_actual_cost,
)
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


def solve_network_od(
    network_dataset_path: str,
    expected_keys: Sequence[tuple[int, int]],
    representatives: Mapping[int, NetworkLocation],
    travel_mode: str,
    cost_attribute: str,
    cost_unit: str,
    cutoff: float,
    spatial_reference: Any,
    scratch_directory: str | Path,
) -> tuple[SolveOutcome, ...]:
    """Solve expected directed pairs using Feature 001 representative coordinates.

    ArcPy is imported lazily so importing this module does not make portable OD logic depend on
    ArcGIS Pro. The supplied scratch directory must be unique to the current work attempt.

    Args:
        network_dataset_path: Read-only network dataset path.
        expected_keys: Complete retained directed-key set for this bounded work item.
        representatives: H3 ID to Feature 001's validated Network Analyst location.
        travel_mode: Network Analyst travel mode name or JSON representation.
        cost_attribute: Expected impedance attribute in the selected travel mode.
        cost_unit: Configured cost unit used by the result contract and Network Analyst output.
        cutoff: Actual-network cost cutoff.
        spatial_reference: ArcPy spatial reference matching the representative coordinates.
        scratch_directory: Isolated, disposable directory owned by the coordinator.

    Returns:
        One classification per expected key. Missing or invalid representatives are classified
        as unlocated; pairs without a result line are classified as unreachable.

    Raises:
        ValueError: If endpoint, cutoff, or solve input identity is invalid.
        RuntimeError: If ArcPy or Network Analyst cannot complete the solve.
    """
    if not isinstance(network_dataset_path, str) or not network_dataset_path.strip():
        raise ValueError("network_dataset_path must be non-empty")
    if not travel_mode or not cost_attribute or not cost_unit:
        raise ValueError("travel_mode, cost_attribute, and cost_unit must be non-empty")
    if isinstance(cutoff, bool) or not isinstance(cutoff, (int, float)):
        raise ValueError("cutoff must be finite and non-negative")
    if not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError("cutoff must be finite and non-negative")
    if not expected_keys:
        return ()
    if any(not isinstance(key, tuple) or len(key) != 2 for key in expected_keys):
        raise ValueError("expected_keys must contain directed integer endpoint pairs")
    if len(expected_keys) != len(set(expected_keys)):
        raise ValueError("expected_keys must be unique")
    if len({origin for origin, _ in expected_keys}) != 1:
        raise ValueError("one work item must contain expected keys for exactly one origin")
    if any(origin == destination for origin, destination in expected_keys):
        raise ValueError("self-pairs must not be sent to the network solver")
    endpoint_ids = {endpoint_id for key in expected_keys for endpoint_id in key}
    canonical_h3_ids(endpoint_ids)
    labels_by_id = {
        cell_id: f"endpoint-{index}" for index, cell_id in enumerate(sorted(endpoint_ids))
    }
    ids_by_label = {label: cell_id for cell_id, label in labels_by_id.items()}
    valid_endpoint_ids = {
        endpoint_id
        for endpoint_id in endpoint_ids
        if _is_valid_location(representatives.get(endpoint_id))
    }
    unlocated_keys = [
        key
        for key in expected_keys
        if key[0] not in valid_endpoint_ids or key[1] not in valid_endpoint_ids
    ]
    outcomes_by_key = {
        key: SolveOutcome(
            logical_od_key=key,
            classification=OutcomeClass.UNLOCATED,
            actual_cost=None,
            cost_unit=None,
            diagnostic="Feature 001 deterministic representative is missing or invalid",
        )
        for key in unlocated_keys
    }
    solvable_keys = tuple(key for key in expected_keys if key not in outcomes_by_key)
    if not solvable_keys:
        return tuple(outcomes_by_key[key] for key in expected_keys)

    import arcpy

    if not arcpy.Exists(network_dataset_path):
        raise ValueError(f"ArcPy cannot resolve network dataset: {network_dataset_path}")
    travel_mode_definition = _resolve_travel_mode(
        arcpy, network_dataset_path, travel_mode, cost_attribute
    )
    cost_field, unit_property, unit_value = _cost_output_settings(cost_unit, arcpy)

    scratch = Path(scratch_directory)
    scratch.mkdir(parents=True, exist_ok=True)
    geodatabase = scratch / "od-solve.gdb"
    arcpy.management.CreateFileGDB(str(scratch), geodatabase.name)
    origins_fc = str(geodatabase / "origins")
    destinations_fc = str(geodatabase / "destinations")
    lines_fc = str(geodatabase / "od_lines")
    origins_result_fc = str(geodatabase / "origin_status")
    destinations_result_fc = str(geodatabase / "destination_status")
    _write_endpoint_features(
        arcpy,
        origins_fc,
        {origin for origin, _ in solvable_keys},
        representatives,
        spatial_reference,
        labels_by_id,
    )
    _write_endpoint_features(
        arcpy,
        destinations_fc,
        {destination for _, destination in solvable_keys},
        representatives,
        spatial_reference,
        labels_by_id,
    )

    try:
        solver = arcpy.nax.OriginDestinationCostMatrix(network_dataset_path)
        solver.travelMode = travel_mode_definition
        setattr(solver, unit_property, unit_value)
        solver.defaultDestinationCount = len({destination for _, destination in solvable_keys})
        solver.defaultImpedanceCutoff = None
        solver.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins, origins_fc)
        solver.load(
            arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations,
            destinations_fc,
        )
        result = solver.solve()
        if not result.solveSucceeded:
            messages = result.solverMessages(arcpy.nax.MessageSeverity.All)
            message = f"Network Analyst OD solve failed: {messages}"
            logger.error(message)
            raise RuntimeError(message)
        result.export(
            arcpy.nax.OriginDestinationCostMatrixOutputDataType.Lines,
            lines_fc,
        )
        result.export(
            arcpy.nax.OriginDestinationCostMatrixOutputDataType.Origins,
            origins_result_fc,
        )
        result.export(
            arcpy.nax.OriginDestinationCostMatrixOutputDataType.Destinations,
            destinations_result_fc,
        )
    except arcpy.ExecuteError as exc:
        message = f"Network Analyst OD solve failed: {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc

    field_names = {field.name for field in arcpy.ListFields(lines_fc)}
    missing_fields = {"OriginName", "DestinationName"}.difference(field_names)
    if missing_fields:
        raise RuntimeError(
            "Network Analyst OD output is missing required fields: "
            + ", ".join(sorted(missing_fields))
        )
    if cost_field not in field_names:
        raise RuntimeError(
            f"Network Analyst OD output is missing configured cost field {cost_field!r}"
        )
    endpoint_status = _read_endpoint_statuses(
        arcpy,
        origins_result_fc,
        destinations_result_fc,
        {origin for origin, _ in solvable_keys},
        {destination for _, destination in solvable_keys},
        ids_by_label,
    )
    costs: dict[tuple[int, int], float] = {}
    with arcpy.da.SearchCursor(lines_fc, ["OriginName", "DestinationName", cost_field]) as cursor:
        for origin_id, destination_id, cost in cursor:
            if origin_id not in ids_by_label or destination_id not in ids_by_label:
                message = "Network Analyst returned an unknown endpoint label"
                logger.error(message)
                raise RuntimeError(message)
            key = (ids_by_label[origin_id], ids_by_label[destination_id])
            if key not in solvable_keys:
                raise RuntimeError(f"Network Analyst returned unexpected OD key: {key!r}")
            if key in costs:
                raise RuntimeError(f"Network Analyst returned duplicate OD key: {key!r}")
            if cost is None:
                raise RuntimeError(f"Network Analyst returned a null cost for {key!r}")
            costs[key] = float(cost)

    for key in solvable_keys:
        unlocated_endpoint = next(
            (endpoint for endpoint in key if endpoint_status[endpoint] != 0), None
        )
        if unlocated_endpoint is not None:
            outcomes_by_key[key] = SolveOutcome(
                logical_od_key=key,
                classification=OutcomeClass.UNLOCATED,
                actual_cost=None,
                cost_unit=None,
                diagnostic=(
                    f"Network Analyst location status for endpoint "
                    f"{unlocated_endpoint!r} was {endpoint_status[unlocated_endpoint]}"
                ),
            )
        elif key not in costs:
            outcomes_by_key[key] = SolveOutcome(
                logical_od_key=key,
                classification=OutcomeClass.UNREACHABLE,
                actual_cost=None,
                cost_unit=None,
                diagnostic="Network Analyst returned no route line",
            )
        else:
            outcomes_by_key[key] = classify_actual_cost(key, costs[key], cutoff, cost_unit)
    return tuple(outcomes_by_key[key] for key in expected_keys)


def run_network_assignment(assignment: WorkAssignment) -> WorkerResult:
    """Execute one serialized assignment in an isolated ArcPy worker process.

    The worker has no ledger or publication handle. Its only writable location is the
    coordinator-provided assignment scratch directory.
    """
    if not isinstance(assignment, WorkAssignment):
        raise TypeError("assignment must be a WorkAssignment")
    prepared = assignment.prepared_input
    work_item = prepared.work_item
    expected_keys = assignment.expected_logical_od_keys
    if not expected_keys or len(expected_keys) != len(set(expected_keys)):
        raise ValueError("assignment must contain unique expected logical OD keys")
    if assignment.probe:
        if not set(expected_keys).issubset(work_item.expected_logical_od_keys):
            raise ValueError("probe assignment keys must belong to its source work item")
    elif expected_keys != work_item.expected_logical_od_keys:
        raise ValueError("assignment keys do not match its bounded work item")

    scratch = Path(assignment.scratch_directory)
    if not scratch.is_dir():
        raise ValueError("assignment scratch directory must be created by the coordinator")

    import arcpy

    license_status = arcpy.CheckExtension("Network")
    if license_status != "Available":
        raise RuntimeError(f"Network Analyst extension is unavailable in worker: {license_status}")
    checkout_status = arcpy.CheckOutExtension("Network")
    if checkout_status != "CheckedOut":
        raise RuntimeError(
            f"Network Analyst extension checkout failed in worker: {checkout_status}"
        )
    outcomes = solve_network_od(
        network_dataset_path=prepared.network_dataset_path,
        expected_keys=expected_keys,
        representatives=dict(prepared.representatives),
        travel_mode=prepared.travel_mode,
        cost_attribute=prepared.cost_attribute,
        cost_unit=work_item.cost_unit,
        cutoff=work_item.cutoff,
        spatial_reference=arcpy.SpatialReference(prepared.spatial_reference_wkid),
        scratch_directory=scratch,
    )
    return WorkerResult(
        work_id=assignment.work_id,
        compatibility_fingerprint=assignment.compatibility_fingerprint,
        attempt=assignment.attempt,
        fencing_value=assignment.fencing_value,
        outcomes=outcomes,
    )


def _write_endpoint_features(
    arcpy: Any,
    feature_class: str,
    endpoint_ids: set[int],
    representatives: Mapping[int, NetworkLocation],
    spatial_reference: Any,
    labels_by_id: Mapping[int, str],
) -> None:
    arcpy.management.CreateFeatureclass(
        str(Path(feature_class).parent),
        Path(feature_class).name,
        "POINT",
        spatial_reference=spatial_reference,
    )
    arcpy.management.AddField(feature_class, "Name", "TEXT", field_length=64)
    arcpy.management.AddField(feature_class, "SourceID", "LONG")
    arcpy.management.AddField(feature_class, "SourceOID", "LONG")
    arcpy.management.AddField(feature_class, "PosAlong", "DOUBLE")
    arcpy.management.AddField(feature_class, "SideOfEdge", "SHORT")
    with arcpy.da.InsertCursor(
        feature_class,
        ["Name", "SourceID", "SourceOID", "PosAlong", "SideOfEdge", "SHAPE@"],
    ) as cursor:
        for endpoint_id in sorted(endpoint_ids):
            location = representatives[endpoint_id]
            point = arcpy.PointGeometry(arcpy.Point(location.x, location.y), spatial_reference)
            cursor.insertRow(
                (
                    labels_by_id[endpoint_id],
                    location.source_id,
                    location.source_oid,
                    location.pos_along,
                    location.side_of_edge,
                    point,
                )
            )


def _is_valid_location(location: NetworkLocation | None) -> bool:
    if not isinstance(location, NetworkLocation):
        return False
    network_fields = (
        location.source_id,
        location.source_oid,
        location.side_of_edge,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in network_fields):
        return False
    values = (location.x, location.y, location.pos_along, location.snap_distance_m)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return False
    try:
        return (
            all(math.isfinite(value) for value in values)
            and 0.0 <= location.pos_along <= 1.0
            and location.snap_distance_m >= 0
        )
    except OverflowError:
        return False


def _resolve_travel_mode(
    arcpy: Any, network_dataset_path: str, travel_mode: str, cost_attribute: str
) -> Any:
    modes = arcpy.na.GetTravelModes(network_dataset_path)
    if travel_mode in modes:
        definition = modes[travel_mode]
    else:
        try:
            mode_data = json.loads(travel_mode)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unknown travel mode {travel_mode!r} for network dataset") from exc
        if not isinstance(mode_data, dict):
            raise ValueError("travel mode JSON must be an object")
        definition = travel_mode
    try:
        definition_data = json.loads(str(definition))
    except (TypeError, ValueError) as exc:
        raise ValueError("travel mode definition is not valid JSON") from exc
    if not isinstance(definition_data, dict):
        raise ValueError("travel mode definition must be a JSON object")
    if definition_data.get("impedanceAttributeName") != cost_attribute:
        raise ValueError("configured cost_attribute does not match the travel mode impedance")
    return definition


def _cost_output_settings(cost_unit: str, arcpy: Any) -> tuple[str, str, Any]:
    normalized = cost_unit.strip().casefold()
    time_units = {
        "s": "Seconds",
        "sec": "Seconds",
        "second": "Seconds",
        "seconds": "Seconds",
        "min": "Minutes",
        "minute": "Minutes",
        "minutes": "Minutes",
        "h": "Hours",
        "hr": "Hours",
        "hour": "Hours",
        "hours": "Hours",
    }
    distance_units = {
        "m": "Meters",
        "meter": "Meters",
        "meters": "Meters",
        "km": "Kilometers",
        "kilometer": "Kilometers",
        "kilometers": "Kilometers",
        "ft": "Feet",
        "foot": "Feet",
        "feet": "Feet",
        "mi": "Miles",
        "mile": "Miles",
        "miles": "Miles",
    }
    if normalized in time_units:
        return (
            "Total_Time",
            "timeUnits",
            getattr(arcpy.nax.TimeUnits, time_units[normalized]),
        )
    if normalized in distance_units:
        return (
            "Total_Distance",
            "distanceUnits",
            getattr(arcpy.nax.DistanceUnits, distance_units[normalized]),
        )
    raise ValueError(f"Unsupported Network Analyst cost unit: {cost_unit!r}")


def _read_endpoint_statuses(
    arcpy: Any,
    origins_path: str,
    destinations_path: str,
    expected_origins: set[int],
    expected_destinations: set[int],
    ids_by_label: Mapping[str, int],
) -> dict[int, int]:
    statuses: dict[int, int] = {}
    for feature_class, expected_names in (
        (origins_path, expected_origins),
        (destinations_path, expected_destinations),
    ):
        field_names = {field.name for field in arcpy.ListFields(feature_class)}
        if not {"Name", "Status"} <= field_names:
            raise RuntimeError(
                f"Network Analyst location output is missing Name or Status: " f"{feature_class}"
            )
        with arcpy.da.SearchCursor(feature_class, ["Name", "Status"]) as cursor:
            for endpoint_name, status in cursor:
                if endpoint_name not in ids_by_label:
                    message = "Network Analyst returned an unknown endpoint label"
                    logger.error(message)
                    raise RuntimeError(message)
                endpoint_id = ids_by_label[endpoint_name]
                if endpoint_id not in expected_names or endpoint_id in statuses:
                    raise RuntimeError(
                        f"Network Analyst returned unexpected or duplicate endpoint "
                        f"status: {endpoint_id!r}"
                    )
                if isinstance(status, bool) or not isinstance(status, int):
                    raise RuntimeError(
                        f"Network Analyst returned invalid location status for "
                        f"{endpoint_id!r}: {status!r}"
                    )
                statuses[endpoint_id] = status
        if not expected_names.issubset(statuses):
            missing = sorted(expected_names.difference(statuses))
            raise RuntimeError(
                "Network Analyst omitted endpoint location status for: "
                + ", ".join(map(str, missing))
            )
    return statuses
