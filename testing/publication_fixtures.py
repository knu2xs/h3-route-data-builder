"""Small portable fixtures shared by GeoParquet publication tests."""

import struct
from pathlib import Path

import pyarrow as pa
from h3.api import basic_int as h3

from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
    NetworkLocation,
)
from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome


def point_wkb(x: float, y: float) -> bytes:
    """Return little-endian WKB for one point."""
    return struct.pack("<BIdd", 1, 1, x, y)


def polygon_wkb(x: float, y: float) -> bytes:
    """Return a valid unit-square polygon WKB near the supplied coordinate."""
    ring = [(x, y), (x + 0.001, y), (x + 0.001, y + 0.001), (x, y + 0.001), (x, y)]
    return (
        struct.pack("<BII", 1, 3, 1)
        + struct.pack("<I", len(ring))
        + b"".join(struct.pack("<dd", *coordinate) for coordinate in ring)
    )


def make_cell(h3_id: int, x: float = -122.0, y: float = 47.0) -> CellEligibilityResult:
    """Build a Feature 001 solvable record."""
    return CellEligibilityResult(
        h3_id=h3_id,
        resolution=h3.get_resolution(h3_id),
        eligibility_status=EligibilityStatus.SOLVABLE,
        eligibility_reason="eligible",
        intersecting_edge_count=2,
        representative=NetworkLocation(x, y, 1, 2, 0.5, 1, 0.0),
        build_fingerprint="eligibility-fingerprint",
    )


def make_geometry_map(
    cells: list[CellEligibilityResult],
) -> dict[str, tuple[bytes, bytes, bytes | None]]:
    """Serialize test geometries by H3 identifier."""
    return {
        cell.h3_id: (
            polygon_wkb(-122.0 + index * 0.01, 47.0),
            point_wkb(-122.0 + index * 0.01, 47.0),
            point_wkb(-122.0 + index * 0.01, 47.0),
        )
        for index, cell in enumerate(cells)
    }


def make_outcome(origin: int, destination: int, cost: float = 4.5) -> SolveOutcome:
    """Build a qualifying Feature 003 result."""
    return SolveOutcome(
        logical_od_key=(origin, destination),
        classification=OutcomeClass.QUALIFYING,
        actual_cost=cost,
        cost_unit="m",
    )


def make_publication_tables():
    """Return dimension and fact Arrow tables for publication tests."""
    from h3_route_data_builder.publication.convert import (
        outcomes_to_table,
        solvable_cells_to_table,
    )

    cells = [make_cell(617700169958293503), make_cell(617700169958031359)]
    dimension = solvable_cells_to_table(cells, make_geometry_map(cells))
    facts = outcomes_to_table(
        [make_outcome(cells[0].h3_id, cells[1].h3_id)],
        [(cells[0].h3_id, cells[0].h3_id)],
        dimension,
        travel_mode="Driving Time",
        build_fingerprint="result-fingerprint",
        impedance="distance",
        work_item_ids={(cells[0].h3_id, cells[1].h3_id): "work-1"},
    )
    return dimension, facts


def write_test_tables(directory: Path, dimension: pa.Table, facts: pa.Table):
    """Write dimension and fact GeoParquet files using the public writer."""
    from h3_route_data_builder.publication.write import write_table

    cell_path = directory / "solvable_cells.parquet"
    fact_path = directory / "od_facts.parquet"
    cell_part = write_table(dimension, cell_path, table_name="solvable_cells")
    fact_parts = write_table(facts, fact_path, table_name="od_facts", partition_by_origin=True)
    return cell_part, fact_parts
