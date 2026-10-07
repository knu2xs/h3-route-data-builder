"""Tests for eligibility run lifecycle and persistence."""

import pytest

from h3_route_data_builder.eligibility.models import (
    PartitionStatus,
    RunStatus,
)
from h3_route_data_builder.eligibility.run_state import (
    create_run_state,
    finalize_run,
    load_run_state,
    save_run_state,
    transition_partition,
)


def reconcile_partition(run_state, partition_key: str) -> None:
    """Move a partition through the valid completion lifecycle."""
    transition_partition(run_state, partition_key, PartitionStatus.PROCESSING)
    transition_partition(run_state, partition_key, PartitionStatus.STAGED)
    transition_partition(run_state, partition_key, PartitionStatus.RECONCILED)


def test_run_state_sorts_expected_partitions() -> None:
    run_state = create_run_state(
        "run-1", ["part-b", "part-a"], total_output_hard_cap=10
    )

    assert run_state.expected_partition_keys == ("part-a", "part-b")
    assert run_state.status == RunStatus.PROCESSING


def test_run_cannot_complete_before_every_partition_reconciles() -> None:
    run_state = create_run_state(
        "run-1", ["part-a", "part-b"], total_output_hard_cap=10
    )
    reconcile_partition(run_state, "part-a")

    with pytest.raises(ValueError, match="unreconciled partitions"):
        finalize_run(run_state, unique_solvable_cell_count=2)
    assert run_state.status == RunStatus.FAILED_INCOMPLETE


def test_total_hard_cap_overflow_leaves_run_incomplete() -> None:
    run_state = create_run_state("run-1", ["part-a"], total_output_hard_cap=2)
    reconcile_partition(run_state, "part-a")

    finalize_run(run_state, unique_solvable_cell_count=3)

    assert run_state.status == RunStatus.FAILED_INCOMPLETE


def test_completed_run_state_round_trips_through_json(temp_dir) -> None:
    run_state = create_run_state("run-1", ["part-a"], total_output_hard_cap=10)
    reconcile_partition(run_state, "part-a")
    finalize_run(run_state, unique_solvable_cell_count=2)
    state_path = temp_dir / "run-state.json"

    save_run_state(state_path, run_state)
    restored = load_run_state(state_path)

    assert restored == run_state


def test_invalid_partition_transition_is_rejected() -> None:
    run_state = create_run_state("run-1", ["part-a"], total_output_hard_cap=10)

    with pytest.raises(ValueError, match="Invalid partition transition"):
        transition_partition(run_state, "part-a", PartitionStatus.RECONCILED)
