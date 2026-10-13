"""Acceptance tests for Feature 003 logical-key reconciliation handoff."""

import h3
import pytest

from h3_route_data_builder.od.candidates import (
    build_candidate_plan,
    classify_solved_costs,
    reconcile_candidate_work,
    restore_candidate_policy,
)
from h3_route_data_builder.od.models import (
    CandidatePlan,
    CandidateScope,
    LedgerEvidence,
    SolvableCell,
)


def make_cells() -> list[SolvableCell]:
    """Create two deterministic solvable cell references."""
    return [
        SolvableCell(
            h3_id_hex=h3.latlng_to_cell(0.0, 0.0, 9),
            resolution=9,
            eligibility_status="solvable",
            representative=(0.0, 0.0),
        ),
        SolvableCell(
            h3_id_hex=h3.latlng_to_cell(0.0, 0.01, 9),
            resolution=9,
            eligibility_status="solvable",
            representative=(0.01, 0.0),
        ),
        SolvableCell(
            h3_id_hex=h3.latlng_to_cell(0.01, 0.0, 9),
            resolution=9,
            eligibility_status="solvable",
            representative=(0.0, 0.01),
        ),
    ]


def make_plan() -> tuple[CandidatePlan, tuple[tuple[str, str], ...]]:
    """Build the four-key directed product and return its off-diagonal keys."""
    cells = make_cells()
    scope = CandidateScope(
        mode="aoi_only",
        origin_ids=tuple(cell.h3_id_hex for cell in cells),
        destination_ids=tuple(cell.h3_id_hex for cell in cells),
        reach_distance_m=1000.0,
        resolution=9,
    )
    plan = build_candidate_plan(cells, scope, 1000.0, "m")
    retained = tuple(
        pair.logical_od_key
        for pair in plan.pairs
        if pair.origin_h3_id != pair.destination_h3_id
    )
    return plan, retained


def test_reconciliation_reuses_committed_resumes_recoverable_and_plans_missing_once() -> (
    None
):
    plan, keys = make_plan()
    entries = [
        LedgerEvidence(keys[0], "fp", "committed"),
        LedgerEvidence(keys[1], "fp", "solving"),
    ]

    result = reconcile_candidate_work(plan, entries, "fp", destination_batch_size=1)

    assert result.reused_keys == (keys[0],)
    assert result.resumed_keys == (keys[1],)
    assert set(result.planned_keys) == set(keys[2:])
    scheduled = [key for unit in result.work_units for key in unit.logical_od_keys]
    assert len(scheduled) == len(keys[2:])
    assert len(set(scheduled)) == len(scheduled)
    assert result.summary["expected_non_self_key_count"] == len(keys)


def test_incompatible_committed_evidence_is_missing_for_current_fingerprint() -> None:
    plan, keys = make_plan()

    result = reconcile_candidate_work(
        plan,
        [LedgerEvidence(keys[0], "old-fingerprint", "committed")],
        "new-fingerprint",
        destination_batch_size=10,
    )

    assert result.reused_keys == ()
    assert set(result.planned_keys) == set(keys)


def test_reconciliation_counts_each_expected_key_once_and_reports_failures() -> None:
    plan, keys = make_plan()
    evidence = [LedgerEvidence(key, "fp", "terminal_failure") for key in keys]

    result = reconcile_candidate_work(plan, evidence, "fp", destination_batch_size=10)

    assert result.completion_status == "complete_with_failures"
    assert result.summary["committed_count"] == 0
    assert result.summary["retryable_failure_count"] == 0
    assert result.summary["terminal_failure_count"] == len(keys)
    assert result.summary["unresolved_count"] == 0
    assert sum(
        result.summary[name]
        for name in (
            "committed_count",
            "retryable_failure_count",
            "terminal_failure_count",
            "unresolved_count",
        )
    ) == len(result.expected_keys)


def test_reconciliation_separates_committed_retryable_terminal_and_unresolved() -> None:
    plan, keys = make_plan()
    evidence = [
        LedgerEvidence(keys[0], "fp", "committed"),
        LedgerEvidence(keys[1], "fp", "retryable_failure"),
        LedgerEvidence(keys[2], "fp", "terminal_failure"),
    ]

    result = reconcile_candidate_work(plan, evidence, "fp", destination_batch_size=10)

    assert result.completion_status == "in_progress"
    assert result.summary["committed_count"] == 1
    assert result.summary["retryable_failure_count"] == 1
    assert result.summary["terminal_failure_count"] == 1
    assert result.summary["unresolved_count"] == len(keys) - 3
    assert sum(
        result.summary[name]
        for name in (
            "committed_count",
            "retryable_failure_count",
            "terminal_failure_count",
            "unresolved_count",
        )
    ) == len(result.expected_keys)


def test_reconciliation_reports_all_success_only_when_all_keys_committed() -> None:
    plan, keys = make_plan()
    evidence = [LedgerEvidence(key, "fp", "committed") for key in keys]

    result = reconcile_candidate_work(plan, evidence, "fp", destination_batch_size=10)

    assert result.completion_status == "all_success"
    assert result.summary["committed_count"] == len(keys)
    assert result.summary["unresolved_count"] == 0


def test_zero_candidate_reconciliation_is_all_success() -> None:
    cell = make_cells()[0]
    scope = CandidateScope(
        mode="aoi_only",
        origin_ids=(cell.h3_id_hex,),
        destination_ids=(cell.h3_id_hex,),
        reach_distance_m=1000.0,
        resolution=9,
    )
    plan = build_candidate_plan([cell], scope, 1000.0, "m")

    result = reconcile_candidate_work(plan, [], "fp", destination_batch_size=10)

    assert result.expected_keys == ()
    assert result.completion_status == "all_success"
    assert result.summary["all_success"] == 1
    assert result.summary["unresolved_count"] == 0


def test_terminal_failure_stays_unscheduled_until_explicitly_invalidated() -> None:
    plan, keys = make_plan()

    terminal = reconcile_candidate_work(
        plan,
        [LedgerEvidence(keys[0], "fp", "terminal_failure")],
        "fp",
        destination_batch_size=10,
    )
    invalidated = reconcile_candidate_work(
        plan,
        [LedgerEvidence(keys[0], "fp", "terminal_failure", invalidated=True)],
        "fp",
        destination_batch_size=10,
    )

    assert terminal.terminal_keys == (keys[0],)
    assert keys[0] not in terminal.planned_keys
    assert keys[0] in invalidated.planned_keys


def test_invalidated_committed_and_recoverable_work_are_planned_once() -> None:
    plan, keys = make_plan()
    evidence = [
        LedgerEvidence(keys[0], "fp", "committed", invalidated=True),
        LedgerEvidence(keys[1], "fp", "retryable", invalidated=True),
    ]

    result = reconcile_candidate_work(plan, evidence, "fp", destination_batch_size=10)

    assert set(result.planned_keys) == set(keys)
    scheduled = [key for unit in result.work_units for key in unit.logical_od_keys]
    assert len(scheduled) == len(set(scheduled))


def test_reconciliation_excludes_self_and_prefilter_pruned_pairs() -> None:
    plan, _ = make_plan()
    result = reconcile_candidate_work(plan, [], "fp", destination_batch_size=10)

    assert all(origin != destination for origin, destination in result.expected_keys)
    assert result.expected_keys == result.planned_keys


def test_missing_earlier_batch_key_does_not_shift_deterministic_batch_assignment() -> (
    None
):
    plan, keys = make_plan()
    all_planned = reconcile_candidate_work(plan, [], "fp", destination_batch_size=1)
    first_key = keys[0]
    first_origin_units = [
        unit for unit in all_planned.work_units if unit.origin_h3_id == first_key[0]
    ]
    assert first_origin_units[0].logical_od_keys == (first_key,)

    after_commit = reconcile_candidate_work(
        plan,
        [LedgerEvidence(first_key, "fp", "committed")],
        "fp",
        destination_batch_size=1,
    )
    later_key = next(key for key in keys if key[0] == first_key[0] and key != first_key)
    later_unit = next(
        unit for unit in after_commit.work_units if later_key in unit.logical_od_keys
    )

    assert later_unit.batch_index == 1


def test_resolved_limits_bound_default_destination_batches() -> None:
    from h3_route_data_builder.eligibility.limits import ExecutionLimits

    cells = make_cells()
    scope = CandidateScope(
        mode="aoi_only",
        origin_ids=tuple(cell.h3_id_hex for cell in cells),
        destination_ids=tuple(cell.h3_id_hex for cell in cells),
        reach_distance_m=1000.0,
        resolution=9,
    )
    limits = ExecutionLimits(
        batch_size=1,
        batch_size_source="set",
        part_row_limit=3,
        part_row_limit_source="set",
        total_output_hard_cap=100,
        total_output_hard_cap_source="set",
    )
    plan = build_candidate_plan(cells, scope, 1000.0, "m", limits=limits)

    result = reconcile_candidate_work(plan, [], "fp")

    assert result.work_units
    assert all(len(unit.destination_ids) <= 1 for unit in result.work_units)


def test_duplicate_ledger_evidence_for_same_fingerprint_is_rejected() -> None:
    plan, keys = make_plan()
    duplicate = [
        LedgerEvidence(keys[0], "fp", "committed"),
        LedgerEvidence(keys[0], "fp", "solving"),
    ]

    with pytest.raises(ValueError, match="duplicate compatible ledger evidence"):
        reconcile_candidate_work(plan, duplicate, "fp", destination_batch_size=10)


def test_synthetic_solver_handoff_excludes_actual_over_cutoff_cost_before_commit() -> (
    None
):
    plan, keys = make_plan()
    solved_costs = {
        keys[0]: 999.0,
        keys[1]: 1000.0,
        keys[2]: 1001.0,
    }

    classified = classify_solved_costs(plan, solved_costs)
    committed_as_qualifying = [
        pair.logical_od_key
        for pair in classified.pairs
        if pair.disposition.value == "qualifying"
    ]

    assert committed_as_qualifying == [keys[0], keys[1]]
    assert classified.summary.cutoff_excluded_count == 1
    assert (
        next(
            pair for pair in classified.pairs if pair.logical_od_key == keys[2]
        ).solved_cost
        == 1001.0
    )


def test_resume_restores_execution_limits_and_candidate_policy_without_reinference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from h3_route_data_builder.eligibility.limits import ExecutionLimits

    cells = make_cells()
    limits = ExecutionLimits(
        batch_size=7,
        batch_size_source="set",
        part_row_limit=80,
        part_row_limit_source="inferred",
        total_output_hard_cap=900,
        total_output_hard_cap_source="set",
    )
    scope = CandidateScope(
        mode="aoi_only",
        origin_ids=tuple(cell.h3_id_hex for cell in cells),
        destination_ids=tuple(cell.h3_id_hex for cell in cells),
        reach_distance_m=1000.0,
        resolution=9,
    )
    plan = build_candidate_plan(
        cells,
        scope,
        1000.0,
        "m",
        prefilter_distance_error_bound_m=None,
        limits=limits,
    )

    def fail_if_rederived(*args: object, **kwargs: object) -> float:
        raise AssertionError("Resume must use the saved reach without recalculation")

    monkeypatch.setattr(
        "h3_route_data_builder.od.candidates.cutoff_reach_m", fail_if_rederived
    )
    policy, restored_limits, restored_fingerprint = restore_candidate_policy(
        plan.candidate_policy
    )
    with pytest.raises(ValueError, match="use a distinct run"):
        restore_candidate_policy(plan.candidate_policy, {"cutoff": 2000.0})

    assert restored_limits == limits
    assert policy["candidate_policy_version"] == "1"
    assert policy["cutoff"] == plan.cutoff
    assert policy["reach_distance_m"] == plan.scope.reach_distance_m
    assert (
        policy["prefilter_distance_error_bound_m"]
        == plan.prefilter_distance_error_bound_m
    )
    assert restored_fingerprint == plan.candidate_policy_fingerprint
