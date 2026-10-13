"""Tests for publication-table conversion from upstream feature records."""

import pytest

from h3_route_data_builder.eligibility.models import EligibilityStatus
from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome
from h3_route_data_builder.publication.convert import (
    outcomes_to_table,
    solvable_cells_to_table,
)
from testing.publication_fixtures import make_cell, make_geometry_map, make_outcome


def test_cell_conversion_keeps_scope_cells_without_retained_pairs() -> None:
    cells = [make_cell("8928308280fffff"), make_cell("8928308280bffff")]

    table = solvable_cells_to_table(cells, make_geometry_map(cells))

    assert table.column("h3_id_hex").to_pylist() == sorted(
        cell.h3_id_hex for cell in cells
    )
    assert table.column("eligibility_status").to_pylist() == ["solvable", "solvable"]
    assert table.column("eligibility_fingerprint").to_pylist() == [
        "eligibility-fingerprint",
        "eligibility-fingerprint",
    ]


def test_cell_conversion_rejects_non_solvable_or_duplicate_cells() -> None:
    cell = make_cell("8928308280fffff")
    invalid = cell.__class__(
        h3_id_hex=cell.h3_id_hex,
        resolution=cell.resolution,
        eligibility_status=EligibilityStatus.INELIGIBLE,
        eligibility_reason="not solvable",
        intersecting_edge_count=0,
    )

    with pytest.raises(ValueError, match="solvable"):
        solvable_cells_to_table([invalid], make_geometry_map([cell]))
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        solvable_cells_to_table([cell, cell], make_geometry_map([cell]))


def test_fact_conversion_keeps_direction_cost_and_self_pair() -> None:
    cells = [make_cell("8928308280fffff"), make_cell("8928308280bffff")]
    dimension = solvable_cells_to_table(cells, make_geometry_map(cells))
    reverse = make_outcome(cells[1].h3_id_hex, cells[0].h3_id_hex)

    facts = outcomes_to_table(
        [make_outcome(cells[0].h3_id_hex, cells[1].h3_id_hex), reverse],
        [(cells[0].h3_id_hex, cells[0].h3_id_hex)],
        dimension,
        travel_mode="Driving Time",
        build_fingerprint="result-fingerprint",
        impedance="distance",
        work_item_ids={
            (cells[0].h3_id_hex, cells[1].h3_id_hex): "work-1",
            (cells[1].h3_id_hex, cells[0].h3_id_hex): "work-2",
        },
    )

    assert facts.num_rows == 3
    assert facts.column("origin_h3_id_hex").to_pylist() == sorted(
        [cells[0].h3_id_hex, cells[1].h3_id_hex, cells[0].h3_id_hex]
    )
    assert facts.column("network_distance_m").to_pylist() == [4.5, 4.5, 0.0]
    assert facts.column("network_time_s").to_pylist() == [None, None, 0.0]
    assert facts.column("work_item_id").to_pylist() == ["work-2", "work-1", None]
    assert facts.column("solve_status").to_pylist() == ["solved", "solved", "self_pair"]


@pytest.mark.parametrize(
    "outcome",
    [
        SolveOutcome(("a", "b"), OutcomeClass.UNLOCATED, None, None),
        SolveOutcome(("a", "b"), OutcomeClass.UNREACHABLE, None, None),
        SolveOutcome(("a", "b"), OutcomeClass.CUTOFF_EXCLUDED, 99.0, "m"),
    ],
)
def test_non_route_outcomes_are_not_serialized_as_facts(outcome) -> None:
    cells = [make_cell("8928308280fffff"), make_cell("8928308280bffff")]
    dimension = solvable_cells_to_table(cells, make_geometry_map(cells))

    facts = outcomes_to_table(
        [outcome],
        [],
        dimension,
        travel_mode="Driving Time",
        build_fingerprint="result-fingerprint",
        impedance="distance",
    )
    assert facts.num_rows == 0
