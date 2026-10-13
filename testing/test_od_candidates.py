"""Acceptance tests for portable sparse OD candidate planning."""

import logging
from itertools import product
import math

import h3
import pytest

from h3_route_data_builder.eligibility.limits import ExecutionLimits
from h3_route_data_builder.config import ConfigNode
from h3_route_data_builder.od.candidates import (
    CandidateBuildIncompleteError,
    build_candidate_plan,
    candidate_policy_fingerprint,
    classify_solved_costs,
    configured_prefilter_distance_error_bound_m,
    cutoff_reach_m,
)
from h3_route_data_builder.od.models import (
    CandidateDisposition,
    CandidateMode,
    CandidateScope,
    SolvableCell,
)


def make_cell(
    latitude: float,
    longitude: float,
    *,
    status: str = "solvable",
    resolution: int = 9,
) -> SolvableCell:
    """Build a small solvable endpoint fixture."""
    cell_id = h3.latlng_to_cell(latitude, longitude, resolution)
    return SolvableCell(
        h3_id_hex=cell_id,
        resolution=resolution,
        eligibility_status=status,
        representative=(longitude, latitude),
    )


def make_scope(
    cells: list[SolvableCell],
    *,
    mode: CandidateMode = CandidateMode.AOI_ONLY,
    destinations: list[str] | None = None,
    reach_distance_m: float = 1000.0,
) -> CandidateScope:
    """Build an AOI scope from fixture cell IDs."""
    ids = tuple(cell.h3_id_hex for cell in cells)
    return CandidateScope(
        mode=mode,
        origin_ids=ids,
        destination_ids=tuple(destinations if destinations is not None else ids),
        reach_distance_m=reach_distance_m,
        resolution=cells[0].resolution,
    )


def test_aoi_only_enumerates_unique_directed_product_independent_of_input_order() -> (
    None
):
    cells = [
        make_cell(0.0, 0.0),
        make_cell(0.0, 0.01),
        make_cell(0.01, 0.0),
    ]
    scope = make_scope(cells)

    forward = build_candidate_plan(cells, scope, 1000.0, "m")
    reverse = build_candidate_plan(list(reversed(cells)), scope, 1000.0, "m")
    expected = set(product(scope.origin_ids, scope.destination_ids))

    assert {pair.logical_od_key for pair in forward.pairs} == expected
    assert tuple(pair.logical_od_key for pair in forward.pairs) == tuple(
        pair.logical_od_key for pair in reverse.pairs
    )
    assert len(forward.pairs) == len(expected)
    assert forward.summary.scope_pair_count == len(expected)


def test_scope_rejects_missing_and_non_solvable_endpoints_with_reason_counts() -> None:
    solvable = make_cell(0.0, 0.0)
    ineligible = make_cell(0.0, 0.01, status="ineligible")
    missing = make_cell(0.05, 0.05)
    scope = CandidateScope(
        mode=CandidateMode.AOI_ONLY,
        origin_ids=(solvable.h3_id_hex, ineligible.h3_id_hex, missing.h3_id_hex),
        destination_ids=(solvable.h3_id_hex, ineligible.h3_id_hex, missing.h3_id_hex),
        reach_distance_m=1000.0,
        resolution=9,
    )

    plan = build_candidate_plan([solvable, ineligible], scope, 1000.0, "m")

    assert plan.summary.rejected_endpoint_reasons["not_solvable"] == 1
    assert plan.summary.rejected_endpoint_reasons["missing_cell"] == 1
    assert all(pair.origin_h3_id == solvable.h3_id_hex for pair in plan.pairs)
    assert all(pair.destination_h3_id == solvable.h3_id_hex for pair in plan.pairs)


def test_duplicate_cell_input_does_not_duplicate_pairs_and_reversing_is_distinct() -> (
    None
):
    first = make_cell(0.0, 0.0)
    second = make_cell(0.0, 0.01)
    scope = make_scope([first, second])

    plan = build_candidate_plan([first, second, first], scope, 1000.0, "m")
    keys = {pair.logical_od_key for pair in plan.pairs}

    assert len(keys) == 4
    assert (first.h3_id_hex, second.h3_id_hex) in keys
    assert (second.h3_id_hex, first.h3_id_hex) in keys
    assert plan.summary.duplicate_cell_input_count == 1


def test_each_origin_has_one_self_pair_and_self_pairs_are_not_route_work() -> None:
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    plan = build_candidate_plan(cells, make_scope(cells), 1000.0, "m")

    self_pairs = [
        pair
        for pair in plan.pairs
        if pair.disposition == CandidateDisposition.SELF_RESOLVED
    ]
    fake_solver_calls = [
        pair.logical_od_key
        for pair in plan.pairs
        if pair.disposition == CandidateDisposition.RETAINED
    ]

    assert len(self_pairs) == len(cells)
    assert all(pair.solved_cost == 0.0 for pair in self_pairs)
    assert len(fake_solver_calls) == len(cells) * (len(cells) - 1)
    assert all(origin != destination for origin, destination in fake_solver_calls)


@pytest.mark.parametrize(
    ("cutoff", "unit", "speed", "expected"),
    [
        (2.0, "km", None, 2000.0),
        (2.0, "mi", None, pytest.approx(3218.688)),
        (10.0, "min", 20.0, 12_000.0),
        (1.0, "h", 10.0, 36_000.0),
    ],
)
def test_cutoff_reach_is_converted_to_geodesic_meters(
    cutoff: float, unit: str, speed: float | None, expected: float
) -> None:
    assert cutoff_reach_m(cutoff, unit, speed) == expected


def test_time_cutoff_requires_a_proven_positive_maximum_speed() -> None:
    with pytest.raises(ValueError, match="maximum_network_speed_mps"):
        cutoff_reach_m(60.0, "s")
    with pytest.raises(ValueError, match="positive"):
        cutoff_reach_m(60.0, "s", 0.0)


@pytest.mark.parametrize("cutoff", [-1.0, math.nan, math.inf])
def test_invalid_cutoff_is_rejected(cutoff: float) -> None:
    with pytest.raises(ValueError, match="cutoff"):
        cutoff_reach_m(cutoff, "m")


@pytest.mark.parametrize("bound", [-0.1, math.nan, math.inf])
def test_invalid_configured_error_bound_fails_before_planning(bound: float) -> None:
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    distances = {(cells[0].h3_id_hex, cells[1].h3_id_hex): 10_000.0}

    with pytest.raises(ValueError, match="prefilter_distance_error_bound_m"):
        build_candidate_plan(
            cells,
            make_scope(cells),
            1000.0,
            "m",
            representative_distances_m=distances,
            prefilter_distance_error_bound_m=bound,
        )


def test_configured_prefilter_error_bound_is_read_and_validated() -> None:
    config = ConfigNode({"network": {"prefilter_distance_error_bound_m": 12.5}})
    invalid_config = ConfigNode(
        {"network": {"prefilter_distance_error_bound_m": math.inf}}
    )

    assert configured_prefilter_distance_error_bound_m(config) == 12.5
    with pytest.raises(ValueError, match="prefilter_distance_error_bound_m"):
        configured_prefilter_distance_error_bound_m(invalid_config)


def test_missing_bound_or_invalid_measurement_retains_candidates() -> None:
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    key = (cells[0].h3_id_hex, cells[1].h3_id_hex)
    scope = make_scope(cells)

    no_bound = build_candidate_plan(
        cells, scope, 100.0, "m", representative_distances_m={key: 50_000.0}
    )
    bad_measurement = build_candidate_plan(
        cells,
        scope,
        100.0,
        "m",
        representative_distances_m={key: math.nan},
        prefilter_distance_error_bound_m=0.0,
    )

    assert all(
        pair.disposition != CandidateDisposition.PREFILTER_PRUNED
        for pair in no_bound.pairs
    )
    assert all(
        pair.disposition != CandidateDisposition.PREFILTER_PRUNED
        for pair in bad_measurement.pairs
    )
    assert no_bound.summary.prefilter_unbounded_retained_count == 2
    assert bad_measurement.summary.prefilter_unbounded_retained_count == 2


def test_conservative_prefilter_has_no_false_negatives_for_bounded_distance_error() -> (
    None
):
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    scope = make_scope(cells, reach_distance_m=1000.0)
    actual_route_cost_m = 1000.0
    maximum_measurement_error_m = 25.0
    measured_distance_m = actual_route_cost_m - maximum_measurement_error_m
    distances = {
        (cells[0].h3_id_hex, cells[1].h3_id_hex): measured_distance_m,
        (cells[1].h3_id_hex, cells[0].h3_id_hex): measured_distance_m,
    }

    plan = build_candidate_plan(
        cells,
        scope,
        1000.0,
        "m",
        representative_distances_m=distances,
        prefilter_distance_error_bound_m=maximum_measurement_error_m,
    )

    assert plan.summary.prefilter_pruned_count == 0
    assert plan.summary.prefilter_retained_count == 2


def test_prefilter_prunes_only_strictly_above_conservative_reach() -> None:
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    key_forward = (cells[0].h3_id_hex, cells[1].h3_id_hex)
    key_reverse = (cells[1].h3_id_hex, cells[0].h3_id_hex)
    distances = {key_forward: 1000.0, key_reverse: 1001.0}

    plan = build_candidate_plan(
        cells,
        make_scope(cells, reach_distance_m=1000.0),
        1000.0,
        "m",
        representative_distances_m=distances,
        prefilter_distance_error_bound_m=0.0,
    )

    by_key = {pair.logical_od_key: pair.disposition for pair in plan.pairs}
    assert by_key[key_forward] == CandidateDisposition.RETAINED
    assert by_key[key_reverse] == CandidateDisposition.PREFILTER_PRUNED
    assert plan.summary.prefilter_pruning_ratio == pytest.approx(0.5)


def test_actual_solved_cost_controls_cutoff_including_equality() -> None:
    cells = [
        make_cell(0.0, 0.0),
        make_cell(0.0, 0.01),
        make_cell(0.01, 0.0),
    ]
    plan = build_candidate_plan(cells, make_scope(cells), 1000.0, "m")
    costs = {
        (cells[0].h3_id_hex, cells[1].h3_id_hex): 999.9,
        (cells[0].h3_id_hex, cells[2].h3_id_hex): 1000.0,
        (cells[1].h3_id_hex, cells[0].h3_id_hex): 1000.1,
    }

    classified = classify_solved_costs(plan, costs)
    statuses = {pair.logical_od_key: pair.disposition for pair in classified.pairs}

    assert (
        statuses[(cells[0].h3_id_hex, cells[1].h3_id_hex)]
        == CandidateDisposition.QUALIFYING
    )
    assert (
        statuses[(cells[0].h3_id_hex, cells[2].h3_id_hex)]
        == CandidateDisposition.QUALIFYING
    )
    assert (
        statuses[(cells[1].h3_id_hex, cells[0].h3_id_hex)]
        == CandidateDisposition.CUTOFF_EXCLUDED
    )
    assert classified.summary.solved_result_count == 3
    assert classified.summary.cutoff_excluded_count == 1


def test_over_cutoff_actual_cost_is_excluded_and_estimates_are_not_accepted() -> None:
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    plan = build_candidate_plan(cells, make_scope(cells), 1000.0, "m")
    costs = {
        (cells[0].h3_id_hex, cells[1].h3_id_hex): 1000.1,
        (cells[1].h3_id_hex, cells[0].h3_id_hex): 500.0,
    }

    classified = classify_solved_costs(plan, costs)

    assert classified.summary.cutoff_excluded_count == 1
    assert any(
        pair.disposition == CandidateDisposition.CUTOFF_EXCLUDED
        and pair.solved_cost == 1000.1
        for pair in classified.pairs
    )
    with pytest.raises(ValueError, match="actual solved cost"):
        classify_solved_costs(plan, {next(iter(costs)): None})


def test_empty_nonself_scope_has_zero_pruning_ratio() -> None:
    cell = make_cell(0.0, 0.0)

    plan = build_candidate_plan([cell], make_scope([cell]), 1000.0, "m")

    assert plan.summary.non_self_prefilter_input_count == 0
    assert plan.summary.prefilter_pruning_ratio == 0.0


def test_invalid_representative_and_resolution_mismatch_are_rejected_by_reason() -> (
    None
):
    invalid_representative = SolvableCell(
        h3_id_hex=h3.latlng_to_cell(0.0, 0.01, 9),
        resolution=9,
        eligibility_status="solvable",
        representative=(math.nan, 0.0),
    )
    wrong_resolution = make_cell(0.0, 0.0, resolution=8)
    requested_resolution = CandidateScope(
        mode=CandidateMode.AOI_ONLY,
        origin_ids=(invalid_representative.h3_id_hex, wrong_resolution.h3_id_hex),
        destination_ids=(invalid_representative.h3_id_hex, wrong_resolution.h3_id_hex),
        reach_distance_m=1000.0,
        resolution=9,
    )

    plan = build_candidate_plan(
        [invalid_representative, wrong_resolution], requested_resolution, 1000.0, "m"
    )

    assert plan.summary.rejected_endpoint_reasons["invalid_representative"] == 1
    assert plan.summary.rejected_endpoint_reasons["resolution_mismatch"] == 1
    assert plan.pairs == ()


def test_candidate_limit_excess_fails_explicitly_incomplete() -> None:
    cells = [make_cell(0.0, 0.0), make_cell(0.0, 0.01)]
    limits = ExecutionLimits(10, "set", 100, "set", 1, "set")

    with pytest.raises(CandidateBuildIncompleteError, match="failed incomplete"):
        build_candidate_plan(cells, make_scope(cells), 1000.0, "m", limits=limits)


def test_candidate_policy_fingerprint_tracks_cutoff_bound_and_limit_provenance() -> (
    None
):
    limits = ExecutionLimits(10, "set", 100, "set", 1000, "inferred")
    first = candidate_policy_fingerprint(
        cutoff=1000.0,
        cutoff_unit="m",
        reach_distance_m=1000.0,
        prefilter_distance_error_bound_m=None,
        limits=limits,
    )
    changed_bound = candidate_policy_fingerprint(
        cutoff=1000.0,
        cutoff_unit="m",
        reach_distance_m=1000.0,
        prefilter_distance_error_bound_m=1.0,
        limits=limits,
    )
    changed_source = candidate_policy_fingerprint(
        cutoff=1000.0,
        cutoff_unit="m",
        reach_distance_m=1000.0,
        prefilter_distance_error_bound_m=None,
        limits=ExecutionLimits(10, "inferred", 100, "set", 1000, "inferred"),
    )

    assert first != changed_bound
    assert first != changed_source


def test_plan_emits_reconcilable_structured_metrics_and_limit_provenance(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells = [make_cell(0.0, 0.0)]
    limits = ExecutionLimits(10, "set", 100, "inferred", 1000, "set")
    candidate_logger = logging.getLogger("h3_route_data_builder.od.candidates")
    monkeypatch.setattr(candidate_logger, "handlers", [caplog.handler])
    monkeypatch.setattr(candidate_logger, "propagate", False)
    monkeypatch.setattr(candidate_logger, "disabled", False)
    caplog.set_level(logging.INFO, logger="h3_route_data_builder.od.candidates")

    build_candidate_plan(cells, make_scope(cells), 1000.0, "m", limits=limits)

    event = next(
        record
        for record in caplog.records
        if getattr(record, "event_name", None) == "od_candidate_plan"
    )
    assert event.metrics["scope_pair_count"] == 1
    assert event.metrics["self_pair_count"] == 1
    assert event.execution_limits["batch_size"] == {"value": 10, "source": "set"}
