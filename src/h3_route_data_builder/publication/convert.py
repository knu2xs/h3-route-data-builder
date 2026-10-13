"""Convert validated upstream records to canonical publication Arrow tables."""

import math
from collections.abc import Mapping, Sequence

import h3
import pyarrow as pa

from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
)
from h3_route_data_builder.od.results import (
    OutcomeClass,
    SolveOutcome,
    validate_outcome,
)
from h3_route_data_builder.publication.schema import (
    OD_FACTS_SCHEMA,
    SOLVABLE_CELLS_SCHEMA,
)
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

GeometryWkb = tuple[bytes, bytes, bytes | None]
LogicalKey = tuple[str, str]


def solvable_cells_to_table(
    results: Sequence[CellEligibilityResult],
    geometry_wkb: Mapping[str, GeometryWkb],
) -> pa.Table:
    """Convert Feature 001 solvable cells into the publication dimension.

    Geometry is consumed as already validated WKB; this function performs no spatial
    operations and does not import ArcPy.
    """
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for result in sorted(results, key=lambda item: item.h3_id_hex):
        cell_id = _canonical_h3(result.h3_id_hex, result.resolution)
        if cell_id in seen:
            raise ValueError(f"Duplicate solvable cell identifier: {cell_id}")
        seen.add(cell_id)
        if result.eligibility_status is not EligibilityStatus.SOLVABLE:
            raise ValueError(f"Cell {cell_id} is not marked solvable")
        representative = result.representative
        if representative is None or result.intersecting_edge_count < 1:
            raise ValueError(f"Solvable cell {cell_id} lacks representative evidence")
        geometry = geometry_wkb.get(cell_id) or geometry_wkb.get(result.h3_id_hex)
        if geometry is None or len(geometry) != 3:
            raise ValueError(
                f"Missing cell, centroid, or representative WKB for {cell_id}"
            )
        cell_wkb, centroid_wkb, representative_wkb = geometry
        if not cell_wkb or not centroid_wkb or not representative_wkb:
            raise ValueError(f"Cell {cell_id} requires three non-empty WKB geometries")
        numeric_values = (
            representative.pos_along,
            representative.snap_distance_m,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise ValueError(
                f"Cell {cell_id} has non-finite representative measurements"
            )
        if representative.snap_distance_m < 0 or not result.build_fingerprint:
            raise ValueError(f"Cell {cell_id} has invalid representative evidence")
        rows.append(
            {
                "h3_id_hex": cell_id,
                "h3_id_uint64": h3.str_to_int(cell_id),
                "resolution": result.resolution,
                "cell_geometry": cell_wkb,
                "centroid_geometry": centroid_wkb,
                "representative_geometry": representative_wkb,
                "intersecting_edge_count": result.intersecting_edge_count,
                "network_source_id": representative.source_id,
                "network_source_oid": representative.source_oid,
                "network_pos_along": representative.pos_along,
                "network_side_of_edge": representative.side_of_edge,
                "representative_snap_distance_m": representative.snap_distance_m,
                "eligibility_status": EligibilityStatus.SOLVABLE.value,
                "eligibility_reason": result.eligibility_reason,
                "eligibility_fingerprint": result.build_fingerprint,
            }
        )
    return _rows_to_table(rows, SOLVABLE_CELLS_SCHEMA)


def outcomes_to_table(
    outcomes: Sequence[SolveOutcome],
    self_pairs: Sequence[LogicalKey],
    solvable_cells: pa.Table,
    travel_mode: str,
    build_fingerprint: str,
    impedance: str,
    work_item_ids: Mapping[LogicalKey, str] | None = None,
) -> pa.Table:
    """Convert qualifying Feature 003 outcomes and Feature 002 self-pairs to OD facts."""
    if not travel_mode.strip() or not build_fingerprint.strip():
        raise ValueError("travel_mode and build_fingerprint must be non-empty")
    if impedance not in {"distance", "time"}:
        raise ValueError("impedance must be 'distance' or 'time'")
    cell_rows = solvable_cells.to_pylist()
    cell_by_id = {row["h3_id_hex"]: row for row in cell_rows}
    if len(cell_by_id) != solvable_cells.num_rows:
        raise ValueError("Solvable-cell dimension contains duplicate identifiers")
    rows_by_key: dict[LogicalKey, dict[str, object]] = {}
    work_item_ids = work_item_ids or {}

    for outcome in outcomes:
        key = outcome.logical_od_key
        if outcome.classification is not OutcomeClass.QUALIFYING:
            continue
        if outcome.actual_cost is None or outcome.cost_unit is None:
            raise ValueError(f"Qualifying outcome {key} is missing its actual cost")
        _validate_impedance_unit(outcome.cost_unit, impedance)
        validate_outcome(outcome, float(outcome.actual_cost), outcome.cost_unit)
        if key in rows_by_key:
            raise ValueError(f"Duplicate directed OD key: {key}")
        work_item_id = work_item_ids.get(key)
        if not work_item_id:
            raise ValueError(f"Qualifying OD key {key} requires a work_item_id")
        rows_by_key[key] = _fact_row(
            key,
            cell_by_id,
            travel_mode,
            float(outcome.actual_cost) if impedance == "distance" else None,
            float(outcome.actual_cost) if impedance == "time" else None,
            "solved",
            work_item_id,
            build_fingerprint,
        )

    for raw_key in self_pairs:
        if len(raw_key) != 2:
            raise ValueError("Self-pair key must contain two endpoint identifiers")
        key = (_canonical_h3(raw_key[0]), _canonical_h3(raw_key[1]))
        if key[0] != key[1]:
            raise ValueError(f"Self-pair endpoints differ: {key}")
        if key in rows_by_key:
            raise ValueError(f"Duplicate directed OD key: {key}")
        rows_by_key[key] = _fact_row(
            key,
            cell_by_id,
            travel_mode,
            0.0,
            0.0,
            "self_pair",
            None,
            build_fingerprint,
        )

    rows = [rows_by_key[key] for key in sorted(rows_by_key)]
    logger.info("Converted %s directed OD facts", len(rows))
    return _rows_to_table(rows, OD_FACTS_SCHEMA)


def _fact_row(
    key: LogicalKey,
    cell_by_id: dict[str, dict[str, object]],
    travel_mode: str,
    distance_m: float | None,
    time_s: float | None,
    status: str,
    work_item_id: str | None,
    build_fingerprint: str,
) -> dict[str, object]:
    for endpoint in key:
        if endpoint not in cell_by_id:
            raise ValueError(f"OD endpoint {endpoint} is absent from solvable cells")
    if distance_m is None and time_s is None:
        raise ValueError(f"OD key {key} has no actual network cost")
    for value in (distance_m, time_s):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"OD key {key} has an invalid network cost")
    if status == "self_pair" and (distance_m != 0.0 or time_s != 0.0 or work_item_id):
        raise ValueError("Self-pairs require zero costs and null work_item_id")
    return {
        "origin_h3_id_hex": key[0],
        "destination_h3_id_hex": key[1],
        "travel_mode": travel_mode,
        "network_distance_m": distance_m,
        "network_time_s": time_s,
        "origin_representative_snap_distance_m": cell_by_id[key[0]][
            "representative_snap_distance_m"
        ],
        "destination_representative_snap_distance_m": cell_by_id[key[1]][
            "representative_snap_distance_m"
        ],
        "solve_status": status,
        "work_item_id": work_item_id,
        "build_fingerprint": build_fingerprint,
    }


def _validate_impedance_unit(cost_unit: str, impedance: str) -> None:
    normalized_unit = cost_unit.strip().casefold()
    supported = (
        {"m", "meter", "meters", "metre", "metres"}
        if impedance == "distance"
        else {"s", "sec", "second", "seconds"}
    )
    if normalized_unit not in supported:
        raise ValueError(
            f"Outcome cost unit {cost_unit!r} is incompatible with {impedance} impedance"
        )


def _canonical_h3(value: str, resolution: int | None = None) -> str:
    if not isinstance(value, str) or value != value.lower():
        raise ValueError(
            "H3 identifiers must be canonical lowercase hexadecimal strings"
        )
    try:
        canonical = h3.int_to_str(h3.str_to_int(value))
        actual_resolution = h3.get_resolution(canonical)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid H3 identifier: {value}") from exc
    if canonical != value or (
        resolution is not None and actual_resolution != resolution
    ):
        raise ValueError(
            f"H3 identifier {value} is not canonical at resolution {resolution}"
        )
    return canonical


def _rows_to_table(rows: list[dict[str, object]], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)
