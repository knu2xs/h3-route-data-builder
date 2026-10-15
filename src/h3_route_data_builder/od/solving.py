"""Serial coordinator for isolated, resumable OD solve work."""

from collections.abc import Callable, Iterable
import tempfile
from pathlib import Path

from h3_route_data_builder.od.execution import WorkAssignment, WorkerResult
from h3_route_data_builder.od.ledger import Lease, ODLedger, WorkItem
from h3_route_data_builder.od.results import SolveOutcome
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

SolveFunction = Callable[[WorkItem, Path], Iterable[SolveOutcome]]


def accept_worker_result(
    ledger: ODLedger,
    assignment: WorkAssignment,
    lease: Lease,
    result: WorkerResult,
) -> str:
    """Accept, validate, and commit one worker result under its current lease.

    The worker response is only transient evidence. Feature 003 rechecks fencing during staging
    and validates exact-key coverage before its atomic commit.
    """
    item = ledger.get_work(assignment.work_id)
    if (
        item.compatibility_fingerprint != assignment.compatibility_fingerprint
        or item.attempt_count != assignment.attempt
        or item.fencing_value != assignment.fencing_value
        or item.expected_logical_od_keys != assignment.expected_logical_od_keys
        or lease.owner_id != assignment.owner_id
        or lease.fencing_value != assignment.fencing_value
    ):
        raise RuntimeError("assignment no longer matches current Feature 003 work evidence")
    if (
        result.work_id != assignment.work_id
        or result.compatibility_fingerprint != assignment.compatibility_fingerprint
        or result.attempt != assignment.attempt
        or result.fencing_value != assignment.fencing_value
    ):
        raise ValueError("worker result identity does not match its assignment")

    ledger.stage_results(assignment.work_id, lease, result.outcomes)
    ledger.validate_staged(assignment.work_id)
    return ledger.commit(assignment.work_id)


def solve_work_item(
    ledger: ODLedger,
    work_id: str,
    owner_id: str,
    solver: SolveFunction,
    lease_seconds: float,
    scratch_root: str | Path | None = None,
) -> str:
    """Lease, solve, stage, validate, and commit one bounded work item serially.

    Args:
        ledger: Durable Feature 003 work ledger.
        work_id: Deterministic identity of the bounded work item.
        owner_id: Non-empty coordinator/worker identity for the lease.
        solver: Function that writes only inside the supplied unique scratch directory.
        lease_seconds: Positive lease duration.
        scratch_root: Optional parent directory for isolated temporary solve workspaces.

    Returns:
        Immutable committed result-part ID.

    Raises:
        RuntimeError: If solving fails or the work item cannot be committed.
        ValueError: If staged outcomes fail coordinator validation.
    """
    item = ledger.get_work(work_id)
    lease = ledger.acquire_lease(work_id, owner_id, lease_seconds)
    ledger.start_solving(work_id, lease)
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"h3-od-{work_id[:12]}-", dir=scratch_root
        ) as scratch_directory:
            outcomes = tuple(solver(item, Path(scratch_directory)))
    except Exception as exc:
        message = f"OD solve failed for work item '{work_id}': {exc}"
        logger.error(message)
        if ledger.get_work(work_id).state.value == "solving":
            try:
                ledger.fail(work_id, lease, "system_failure", message)
            except RuntimeError as lease_error:
                raise RuntimeError(
                    f"OD solve failed for work item '{work_id}' after its lease " f"was lost: {exc}"
                ) from lease_error
        raise RuntimeError(message) from exc

    ledger.stage_results(work_id, lease, outcomes)
    ledger.validate_staged(work_id)
    return ledger.commit(work_id)
