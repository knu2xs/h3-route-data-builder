"""Run and partition state transitions with atomic JSON persistence."""

import json
import os
from pathlib import Path
from typing import Any

from .models import EligibilityRunState, PartitionStatus, RunStatus
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


_ALLOWED_PARTITION_TRANSITIONS: dict[PartitionStatus, set[PartitionStatus]] = {
    PartitionStatus.PENDING: {PartitionStatus.PROCESSING, PartitionStatus.FAILED},
    PartitionStatus.PROCESSING: {PartitionStatus.STAGED, PartitionStatus.FAILED},
    PartitionStatus.STAGED: {PartitionStatus.RECONCILED, PartitionStatus.FAILED},
    PartitionStatus.RECONCILED: set(),
    PartitionStatus.FAILED: {PartitionStatus.PROCESSING},
}


def create_run_state(
    run_id: str,
    expected_partition_keys: list[str],
    total_output_hard_cap: int,
) -> EligibilityRunState:
    """Create validated initial run state with deterministic partition order.

    Args:
        run_id: Stable identifier for the input and policy combination.
        expected_partition_keys: Keys for all input partitions in this run.
        total_output_hard_cap: Positive upper bound on unique solvable H3 cells.

    Returns:
        Initial run state with every expected partition pending.

    Raises:
        ValueError: If the run ID, partition keys, or hard cap is invalid.
    """
    if not run_id:
        raise ValueError("run_id must be non-empty")
    if total_output_hard_cap <= 0:
        raise ValueError("total_output_hard_cap must be positive")
    if any(not key for key in expected_partition_keys):
        raise ValueError("partition keys must be non-empty")
    if len(expected_partition_keys) != len(set(expected_partition_keys)):
        raise ValueError("partition keys must be unique")

    ordered_keys = tuple(sorted(expected_partition_keys))
    return EligibilityRunState(
        run_id=run_id,
        expected_partition_keys=ordered_keys,
        total_output_hard_cap=total_output_hard_cap,
        partition_status={key: PartitionStatus.PENDING for key in ordered_keys},
    )


def transition_partition(
    run_state: EligibilityRunState,
    partition_key: str,
    new_status: PartitionStatus,
) -> None:
    """Apply a permitted transition to an expected partition.

    Args:
        run_state: Run state to update.
        partition_key: Expected partition key.
        new_status: Requested partition state.

    Raises:
        ValueError: If the partition is unknown or the transition is invalid.
    """
    if run_state.status != RunStatus.PROCESSING:
        raise ValueError(f"Cannot change partitions for a {run_state.status.value} run")
    if partition_key not in run_state.partition_status:
        raise ValueError(f"Unknown partition key: {partition_key}")

    current_status = run_state.partition_status[partition_key]
    if new_status not in _ALLOWED_PARTITION_TRANSITIONS[current_status]:
        raise ValueError(
            f"Invalid partition transition: {current_status.value} -> {new_status.value}"
        )
    run_state.partition_status[partition_key] = new_status
    logger.info(
        "Run %s partition %s transitioned %s -> %s",
        run_state.run_id,
        partition_key,
        current_status.value,
        new_status.value,
    )


def finalize_run(
    run_state: EligibilityRunState, unique_solvable_cell_count: int
) -> None:
    """Mark a run complete only after reconciliation and hard-cap validation.

    Args:
        run_state: Run state to finalize.
        unique_solvable_cell_count: Number of distinct validated solvable H3 IDs.

    Raises:
        ValueError: If the count is negative or partitions are not all reconciled.
    """
    if run_state.status != RunStatus.PROCESSING:
        raise ValueError(f"Cannot finalize a {run_state.status.value} run")
    if unique_solvable_cell_count < 0:
        raise ValueError("unique_solvable_cell_count must be non-negative")
    if any(
        status != PartitionStatus.RECONCILED
        for status in run_state.partition_status.values()
    ):
        run_state.status = RunStatus.FAILED_INCOMPLETE
        logger.warning(
            "Run %s cannot complete with unreconciled partitions", run_state.run_id
        )
        raise ValueError("Cannot complete a run with unreconciled partitions")

    run_state.unique_solvable_cell_count = unique_solvable_cell_count
    if unique_solvable_cell_count > run_state.total_output_hard_cap:
        run_state.status = RunStatus.FAILED_INCOMPLETE
        logger.error(
            "Run %s exceeded total solvable-cell cap: %s > %s",
            run_state.run_id,
            unique_solvable_cell_count,
            run_state.total_output_hard_cap,
        )
        return
    run_state.status = RunStatus.COMPLETE
    logger.info(
        "Run %s completed with %s unique solvable cells",
        run_state.run_id,
        unique_solvable_cell_count,
    )


def save_run_state(
    path: str | os.PathLike[str], run_state: EligibilityRunState
) -> None:
    """Atomically persist run state to a caller-selected durable path.

    Args:
        path: State file path outside worker scratch storage.
        run_state: State to serialize.
    """
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "run_id": run_state.run_id,
        "expected_partition_keys": list(run_state.expected_partition_keys),
        "total_output_hard_cap": run_state.total_output_hard_cap,
        "partition_status": {
            key: status.value
            for key, status in sorted(run_state.partition_status.items())
        },
        "status": run_state.status.value,
        "unique_solvable_cell_count": run_state.unique_solvable_cell_count,
    }
    temporary_path = state_path.with_name(f"{state_path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary_path.replace(state_path)


def load_run_state(path: str | os.PathLike[str]) -> EligibilityRunState:
    """Load previously persisted run state.

    Args:
        path: Durable state file path.

    Returns:
        Reconstructed eligibility run state.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    partition_status = {
        key: PartitionStatus(value)
        for key, value in payload["partition_status"].items()
    }
    return EligibilityRunState(
        run_id=payload["run_id"],
        expected_partition_keys=tuple(payload["expected_partition_keys"]),
        total_output_hard_cap=payload["total_output_hard_cap"],
        partition_status=partition_status,
        status=RunStatus(payload["status"]),
        unique_solvable_cell_count=payload["unique_solvable_cell_count"],
    )
