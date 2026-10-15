"""Portable policy and execution records for parallel OD solving."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain, islice
import math
import multiprocessing
from multiprocessing.connection import Connection, wait
import os
from pathlib import Path
import tempfile
import time
import shutil
from threading import Event
from typing import Any

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.ledger import Lease, ODLedger, WorkItem, WorkState
from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)
_AUTO_CPU_COUNT = object()

_DEFAULTS: dict[str, Any] = {
    "enabled": None,
    "max_workers": 2,
    "probe_timeout_s": 60,
    "shutdown_grace_s": 10,
}
_ALLOWED_SETTINGS = frozenset(_DEFAULTS)
_MAX_WORKERS = 64
_MAX_PROBE_TIMEOUT_S = 3600
_MAX_SHUTDOWN_GRACE_S = 60


@dataclass(frozen=True)
class ParallelExecutionConfig:
    """Validated, CPU-bounded execution policy."""

    enabled: bool
    max_workers: int
    probe_timeout_s: float
    shutdown_grace_s: float
    resource_worker_ceiling: int

    @property
    def preparation_worker_ceiling(self) -> int:
        """Return the fixed maximum for non-ArcPy preparation concurrency."""
        return 2

    def preparation_workers(self, eligible_units: int) -> int:
        """Resolve preparation concurrency for the currently eligible units."""
        if isinstance(eligible_units, bool) or not isinstance(eligible_units, int):
            raise ValueError("eligible_units must be a non-negative integer")
        if eligible_units < 0:
            raise ValueError("eligible_units must be a non-negative integer")
        return min(self.preparation_worker_ceiling, eligible_units)

    @classmethod
    def from_mapping(
        cls,
        settings: Any,
        cpu_count: int | None | object = _AUTO_CPU_COUNT,
    ) -> "ParallelExecutionConfig":
        """Load and validate the ``parallel_solving`` configuration section.

        Args:
            settings: Project configuration containing an optional
                ``parallel_solving`` mapping.
            cpu_count: CPU count override, primarily for deterministic tests.

        Returns:
            Validated policy, with an effective CPU ceiling of one if the
            runtime cannot determine the CPU count.

        Raises:
            ValueError: If the section is malformed or contains invalid values.
        """
        if not isinstance(settings, Mapping):
            to_dict = getattr(settings, "to_dict", None)
            if callable(to_dict):
                settings = to_dict()
        if not isinstance(settings, Mapping):
            raise ValueError("project settings must be a mapping or ConfigNode")
        section = settings.get("parallel_solving", {})
        if section is None:
            section = {}
        if not isinstance(section, Mapping):
            raise ValueError("parallel_solving must be a mapping")
        unknown = set(section) - _ALLOWED_SETTINGS
        if unknown:
            raise ValueError(
                f"parallel_solving contains unknown setting(s): {', '.join(sorted(unknown))}"
            )
        values = {**_DEFAULTS, **section}

        enabled = values["enabled"]
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("parallel_solving.enabled must be true, false, or null")

        max_workers = values["max_workers"]
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or not 1 <= max_workers <= _MAX_WORKERS
        ):
            raise ValueError(
                f"parallel_solving.max_workers must be an integer from 1 to {_MAX_WORKERS}"
            )

        probe_timeout_s = _bounded_number(
            values["probe_timeout_s"],
            "parallel_solving.probe_timeout_s",
            maximum=_MAX_PROBE_TIMEOUT_S,
        )
        shutdown_grace_s = _bounded_number(
            values["shutdown_grace_s"],
            "parallel_solving.shutdown_grace_s",
            maximum=_MAX_SHUTDOWN_GRACE_S,
        )

        detected_cpu_count = os.cpu_count() if cpu_count is _AUTO_CPU_COUNT else cpu_count
        if isinstance(detected_cpu_count, bool) or (
            detected_cpu_count is not None and not isinstance(detected_cpu_count, int)
        ):
            raise ValueError("cpu_count must be a positive integer or null")
        if detected_cpu_count is not None and detected_cpu_count < 1:
            raise ValueError("cpu_count must be a positive integer or null")
        resource_ceiling = min(max_workers, detected_cpu_count or 1)
        resolved_enabled = enabled is not False
        if detected_cpu_count is None:
            logger.info("CPU count unavailable; parallel network solving is limited to serial")

        return cls(
            enabled=resolved_enabled,
            max_workers=max_workers,
            probe_timeout_s=probe_timeout_s,
            shutdown_grace_s=shutdown_grace_s,
            resource_worker_ceiling=resource_ceiling,
        )


class ExecutionMode(StrEnum):
    """Requested or effective network-solving execution mode."""

    SERIAL = "serial"
    PARALLEL = "parallel"


@dataclass(frozen=True)
class PreparedSolveInput:
    """Immutable, serializable normalization of a Feature 003 work item."""

    work_item: WorkItem
    representatives: tuple[tuple[int, NetworkLocation], ...]
    network_dataset_path: str
    travel_mode: str
    cost_attribute: str
    spatial_reference_wkid: int


@dataclass(frozen=True)
class WorkAssignment:
    """Coordinator-issued solve assignment bound to current lease evidence."""

    work_id: str
    compatibility_fingerprint: str
    owner_id: str
    attempt: int
    fencing_value: int
    expected_logical_od_keys: tuple[tuple[int, int], ...]
    prepared_input: PreparedSolveInput
    scratch_directory: str
    probe: bool = False


@dataclass(frozen=True)
class WorkerResult:
    """Transient worker response; only the coordinator may accept or commit it."""

    work_id: str
    compatibility_fingerprint: str
    attempt: int
    fencing_value: int
    outcomes: tuple[SolveOutcome, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeAttempt:
    """Evidence from one isolated capability-probe concurrency attempt."""

    worker_count: int
    status: str
    elapsed_s: float
    worker_evidence: tuple[str, ...]
    failure_reason: str | None = None


@dataclass(frozen=True)
class ProbeReport:
    """Ordered capability attempts and the selected safe concurrency."""

    attempts: tuple[ProbeAttempt, ...] = ()
    selected_worker_count: int | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ExecutionSummary:
    """Coordinator summary reconciled to Feature 003 durable outcomes."""

    requested_mode: ExecutionMode
    effective_mode: ExecutionMode
    probe_report: ProbeReport
    fallback_reason: str | None
    work_counts: tuple[tuple[str, int], ...]
    key_counts: tuple[tuple[str, int], ...]
    configured_worker_ceiling: int = 0
    resource_worker_ceiling: int = 0
    selected_worker_count: int = 1
    preparation_counts: tuple[tuple[str, int], ...] = ()


SolverAdapter = Callable[[PreparedSolveInput, Path], Iterable[SolveOutcome]]
WorkerAdapter = Callable[[WorkAssignment], WorkerResult]
ProbeRunner = Callable[[PreparedSolveInput, int, float, Path | None], ProbeAttempt]


def execute_serial(
    ledger: ODLedger,
    prepared_inputs: Iterable[PreparedSolveInput],
    owner_id: str,
    lease_seconds: float,
    solver: SolverAdapter | None = None,
    scratch_root: str | Path | None = None,
    policy: ParallelExecutionConfig | None = None,
    requested_mode: ExecutionMode = ExecutionMode.SERIAL,
    fallback_reason: str | None = None,
    probe_report: ProbeReport | None = None,
    selected_worker_count: int = 1,
    log_summary: bool = True,
) -> ExecutionSummary:
    """Run prepared work serially through Feature 003's existing lifecycle.

    Args:
        ledger: Durable Feature 003 OD ledger.
        prepared_inputs: Incremental, bounded Feature 005 preparation stream.
        owner_id: Coordinator identity used for each Feature 003 lease.
        lease_seconds: Positive lease duration for each item.
        solver: Optional portable adapter used by tests and alternate network integrations.
        scratch_root: Optional parent for unique serial solve scratch directories.
        policy: Validated execution policy used for run provenance.
        requested_mode: Original requested mode, which may be parallel during fallback.
        fallback_reason: Observable reason for serial fallback, if applicable.

    Returns:
        Coordinator summary of committed work and outcome classifications.

    Raises:
        RuntimeError: If a solve or Feature 003 commit fails.
        ValueError: If prepared inputs do not match their durable work item.
    """
    from h3_route_data_builder.od.solving import solve_work_item

    resolved_policy = policy or ParallelExecutionConfig.from_mapping({})
    work_counts = {
        "cancelled": 0,
        "committed": 0,
        "dispatched": 0,
        "failed": 0,
        "reconciled": 0,
        "retried": 0,
        "reused": 0,
    }
    key_counts = {classification.value: 0 for classification in OutcomeClass}
    preparation_count = 0

    for prepared in prepared_inputs:
        preparation_count += 1
        item = ledger.get_work(prepared.work_item.work_id)
        _validate_prepared_identity(item, prepared)
        if item.state is WorkState.COMMITTED:
            work_counts["reused"] += 1
            work_counts["reconciled"] += len(item.expected_logical_od_keys)
            continue
        if item.state is WorkState.RETRYABLE_FAILURE or (
            item.lease is not None and item.lease.expires_at <= time.time()
        ):
            work_counts["retried"] += 1

        captured_outcomes: list[SolveOutcome] = []

        def solve_adapter(work_item: WorkItem, scratch_directory: Path) -> tuple[SolveOutcome, ...]:
            if work_item.work_id != prepared.work_item.work_id:
                raise RuntimeError("ledger returned a different work item for prepared input")
            outcomes = tuple(
                solver(prepared, scratch_directory)
                if solver is not None
                else _solve_prepared_input(prepared, scratch_directory)
            )
            captured_outcomes.extend(outcomes)
            return outcomes

        work_counts["dispatched"] += 1
        solve_work_item(
            ledger,
            item.work_id,
            owner_id,
            solve_adapter,
            lease_seconds,
            scratch_root,
        )
        work_counts["committed"] += 1
        work_counts["reconciled"] += len(item.expected_logical_od_keys)
        for outcome in captured_outcomes:
            key_counts[outcome.classification.value] += 1

    summary = ExecutionSummary(
        requested_mode=requested_mode,
        effective_mode=ExecutionMode.SERIAL,
        probe_report=probe_report or ProbeReport(),
        fallback_reason=fallback_reason,
        work_counts=tuple(sorted(work_counts.items())),
        key_counts=tuple(sorted(key_counts.items())),
        configured_worker_ceiling=resolved_policy.max_workers,
        resource_worker_ceiling=resolved_policy.resource_worker_ceiling,
        selected_worker_count=selected_worker_count,
        preparation_counts=(("completed", preparation_count), ("failed", 0)),
    )
    if log_summary:
        _log_summary(summary)
    return summary


def _validate_prepared_identity(item: WorkItem, prepared: PreparedSolveInput) -> None:
    if (
        item.compatibility_fingerprint != prepared.work_item.compatibility_fingerprint
        or item.expected_logical_od_keys != prepared.work_item.expected_logical_od_keys
        or item.destination_batch != prepared.work_item.destination_batch
        or item.origin_h3_id != prepared.work_item.origin_h3_id
    ):
        raise ValueError(f"prepared input does not match durable work item '{item.work_id}'")


def _solve_prepared_input(
    prepared: PreparedSolveInput, scratch_directory: Path
) -> tuple[SolveOutcome, ...]:
    import arcpy

    from h3_route_data_builder.network.solver import solve_network_od

    item = prepared.work_item
    return solve_network_od(
        network_dataset_path=prepared.network_dataset_path,
        expected_keys=item.expected_logical_od_keys,
        representatives=dict(prepared.representatives),
        travel_mode=prepared.travel_mode,
        cost_attribute=prepared.cost_attribute,
        cost_unit=item.cost_unit,
        cutoff=item.cutoff,
        spatial_reference=arcpy.SpatialReference(prepared.spatial_reference_wkid),
        scratch_directory=scratch_directory,
    )


def probe_parallel_capacity(
    prepared_sample: PreparedSolveInput,
    policy: ParallelExecutionConfig,
    probe_runner: ProbeRunner | None = None,
    scratch_root: Path | None = None,
) -> ProbeReport:
    """Probe descending process counts and return the highest passing capacity."""
    if not policy.enabled:
        return ProbeReport(fallback_reason="parallel solving is explicitly disabled")
    if policy.resource_worker_ceiling < 2:
        return ProbeReport(
            fallback_reason=(
                "CPU-resolved worker ceiling is below two; parallel solving was not probed"
            )
        )
    representative_ids = {h3_id for h3_id, _ in prepared_sample.representatives}
    safe_key = next(
        (
            key
            for key in prepared_sample.work_item.expected_logical_od_keys
            if key[0] in representative_ids and key[1] in representative_ids
        ),
        None,
    )
    if safe_key is None:
        return ProbeReport(
            fallback_reason="no safely located expected OD key is available for probing"
        )

    if probe_runner is None:

        def run_probe(
            prepared: PreparedSolveInput,
            worker_count: int,
            timeout_s: float,
            root: Path | None,
        ) -> ProbeAttempt:
            return _run_probe_attempt(
                prepared,
                worker_count,
                timeout_s,
                root,
                policy.shutdown_grace_s,
            )

    else:
        run_probe = probe_runner
    attempts: list[ProbeAttempt] = []
    for worker_count in range(policy.resource_worker_ceiling, 1, -1):
        started_at = time.monotonic()
        try:
            attempt = run_probe(
                prepared_sample,
                worker_count,
                policy.probe_timeout_s,
                scratch_root,
            )
        except Exception as exc:
            message = f"parallel capability probe failed at {worker_count} workers: {exc}"
            logger.warning(message)
            attempt = ProbeAttempt(
                worker_count=worker_count,
                status="timed_out" if isinstance(exc, TimeoutError) else "failed",
                elapsed_s=time.monotonic() - started_at,
                worker_evidence=(),
                failure_reason=message,
            )
        if attempt.worker_count != worker_count:
            attempt = ProbeAttempt(
                worker_count=worker_count,
                status="failed",
                elapsed_s=attempt.elapsed_s,
                worker_evidence=attempt.worker_evidence,
                failure_reason="probe runner returned evidence for the wrong worker count",
            )
        if (
            attempt.status == "passed"
            and len(attempt.worker_evidence) == worker_count
            and math.isfinite(attempt.elapsed_s)
            and attempt.elapsed_s >= 0
            and attempt.elapsed_s <= policy.probe_timeout_s
        ):
            attempts.append(attempt)
            return ProbeReport(tuple(attempts), worker_count)
        if attempt.status == "passed":
            attempt = ProbeAttempt(
                worker_count=worker_count,
                status="inconclusive",
                elapsed_s=attempt.elapsed_s,
                worker_evidence=attempt.worker_evidence,
                failure_reason=("probe evidence was incomplete or exceeded its configured timeout"),
            )
        attempts.append(attempt)

    fallback_reason = (
        attempts[-1].failure_reason
        if attempts and attempts[-1].failure_reason
        else "no tested concurrency of at least two workers passed"
    )
    return ProbeReport(tuple(attempts), fallback_reason=fallback_reason)


def execute_work(
    ledger: ODLedger,
    prepared_inputs: Iterable[PreparedSolveInput],
    owner_id: str,
    lease_seconds: float,
    policy: ParallelExecutionConfig,
    requested_mode: ExecutionMode = ExecutionMode.PARALLEL,
    solver: SolverAdapter | None = None,
    worker: WorkerAdapter | None = None,
    probe_runner: ProbeRunner | None = None,
    scratch_root: str | Path | None = None,
    cancel_event: Event | None = None,
) -> ExecutionSummary:
    """Execute a streamed plan serially or with isolated, coordinator-owned workers."""
    prepared_iterator = iter(prepared_inputs)
    try:
        first = next(prepared_iterator)
    except StopIteration:
        return _log_summary(
            ExecutionSummary(
                requested_mode=requested_mode,
                effective_mode=requested_mode,
                probe_report=ProbeReport(),
                fallback_reason=None,
                work_counts=(
                    ("cancelled", 0),
                    ("committed", 0),
                    ("dispatched", 0),
                    ("failed", 0),
                    ("reconciled", 0),
                    ("retried", 0),
                    ("reused", 0),
                ),
                key_counts=tuple((classification.value, 0) for classification in OutcomeClass),
                configured_worker_ceiling=policy.max_workers,
                resource_worker_ceiling=policy.resource_worker_ceiling,
                selected_worker_count=0,
            )
        )
    stream = chain((first,), prepared_iterator)

    if requested_mode is ExecutionMode.SERIAL:
        return execute_serial(ledger, stream, owner_id, lease_seconds, solver, scratch_root, policy)
    if not policy.enabled:
        return execute_serial(
            ledger,
            stream,
            owner_id,
            lease_seconds,
            solver,
            scratch_root,
            policy,
            requested_mode,
            "parallel solving is explicitly disabled",
        )
    if policy.resource_worker_ceiling < 2:
        reason = "CPU-resolved worker ceiling is below two; serial solving selected"
        return execute_serial(
            ledger,
            stream,
            owner_id,
            lease_seconds,
            solver,
            scratch_root,
            policy,
            requested_mode,
            reason,
        )

    reused_before_probe = 0
    reconciled_before_probe = 0
    probe_sample = first
    probe_item = ledger.get_work(probe_sample.work_item.work_id)
    while probe_item.state is WorkState.COMMITTED:
        reused_before_probe += 1
        reconciled_before_probe += len(probe_item.expected_logical_od_keys)
        try:
            probe_sample = next(prepared_iterator)
            probe_item = ledger.get_work(probe_sample.work_item.work_id)
        except StopIteration:
            return _log_summary(
                ExecutionSummary(
                    requested_mode=requested_mode,
                    effective_mode=ExecutionMode.PARALLEL,
                    probe_report=ProbeReport(),
                    fallback_reason=None,
                    work_counts=(
                        ("cancelled", 0),
                        ("committed", 0),
                        ("dispatched", 0),
                        ("failed", 0),
                        ("reconciled", reconciled_before_probe),
                        ("retried", 0),
                        ("reused", reused_before_probe),
                    ),
                    key_counts=tuple((classification.value, 0) for classification in OutcomeClass),
                    configured_worker_ceiling=policy.max_workers,
                    resource_worker_ceiling=policy.resource_worker_ceiling,
                    selected_worker_count=0,
                    preparation_counts=(
                        ("completed", reused_before_probe),
                        ("failed", 0),
                    ),
                )
            )
    stream = chain((probe_sample,), prepared_iterator)

    probe_report = probe_parallel_capacity(
        probe_sample,
        policy,
        probe_runner=probe_runner,
        scratch_root=Path(scratch_root) if scratch_root is not None else None,
    )
    selected_workers = probe_report.selected_worker_count
    if selected_workers is None:
        return execute_serial(
            ledger,
            stream,
            owner_id,
            lease_seconds,
            solver,
            scratch_root,
            policy,
            requested_mode,
            probe_report.fallback_reason,
            probe_report,
        )

    worker_function = worker or _network_assignment_worker
    base_scratch = (
        Path(scratch_root)
        if scratch_root is not None
        else Path(tempfile.mkdtemp(prefix="h3-od-execution-"))
    )
    base_scratch.mkdir(parents=True, exist_ok=True)
    owns_scratch_root = scratch_root is None
    work_counts = {
        "cancelled": 0,
        "committed": 0,
        "dispatched": 0,
        "failed": 0,
        "reconciled": reconciled_before_probe,
        "retried": 0,
        "reused": reused_before_probe,
    }
    key_counts = {classification.value: 0 for classification in OutcomeClass}
    prepared_count = reused_before_probe
    fallback_reason: str | None = None
    iterator = iter(stream)
    try:
        while True:
            batch = tuple(islice(iterator, min(2, selected_workers)))
            if not batch:
                break
            prepared_count += len(batch)
            active: list[tuple[PreparedSolveInput, WorkAssignment, Any, Path]] = []
            lease_by_work_id: dict[str, Any] = {}
            try:
                for prepared in batch:
                    item = ledger.get_work(prepared.work_item.work_id)
                    _validate_prepared_identity(item, prepared)
                    if item.state is WorkState.COMMITTED:
                        work_counts["reused"] += 1
                        work_counts["reconciled"] += len(item.expected_logical_od_keys)
                        continue
                    if item.state is WorkState.RETRYABLE_FAILURE or (
                        item.lease is not None and item.lease.expires_at <= time.time()
                    ):
                        work_counts["retried"] += 1
                    scratch_directory = Path(
                        tempfile.mkdtemp(
                            prefix=f"{item.work_id[:12]}-",
                            dir=base_scratch,
                        )
                    )
                    lease = None
                    try:
                        lease = ledger.acquire_lease(item.work_id, owner_id, lease_seconds)
                        ledger.start_solving(item.work_id, lease)
                    except Exception:
                        _remove_assignment_scratch(scratch_directory)
                        if lease is not None:
                            _fail_active_work(
                                ledger,
                                item.work_id,
                                lease,
                                "worker dispatch could not start",
                            )
                        raise
                    if lease is None:
                        raise RuntimeError("work lease acquisition returned no lease")
                    assignment = WorkAssignment(
                        work_id=item.work_id,
                        compatibility_fingerprint=item.compatibility_fingerprint,
                        owner_id=lease.owner_id,
                        attempt=item.attempt_count + 1,
                        fencing_value=lease.fencing_value,
                        expected_logical_od_keys=item.expected_logical_od_keys,
                        prepared_input=prepared,
                        scratch_directory=str(scratch_directory),
                    )
                    active.append((prepared, assignment, lease, scratch_directory))

                if not active:
                    continue
                lease_by_work_id = {assignment.work_id: lease for _, assignment, lease, _ in active}

                def renew_active_leases() -> None:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("parallel execution cancelled by coordinator")
                    for _, assignment, lease, _ in active:
                        current_lease = lease_by_work_id[assignment.work_id]
                        if current_lease.expires_at > time.time() + lease_seconds / 2:
                            continue
                        renewed = ledger.renew_lease(
                            assignment.work_id, current_lease, lease_seconds
                        )
                        lease_by_work_id[assignment.work_id] = renewed

                work_counts["dispatched"] += len(active)
                worker_results = _run_spawned_batch(
                    tuple(assignment for _, assignment, _, _ in active),
                    worker_function,
                    timeout_s=lease_seconds,
                    shutdown_grace_s=policy.shutdown_grace_s,
                    on_wait=renew_active_leases,
                )
                for result in worker_results:
                    matching = next(entry for entry in active if entry[1].work_id == result.work_id)
                    _, assignment, _, _ = matching
                    from h3_route_data_builder.od.solving import accept_worker_result

                    accept_worker_result(
                        ledger,
                        assignment,
                        lease_by_work_id[assignment.work_id],
                        result,
                    )
                    work_counts["committed"] += 1
                    work_counts["reconciled"] += len(assignment.expected_logical_od_keys)
                    for outcome in result.outcomes:
                        key_counts[outcome.classification.value] += 1
            except Exception as exc:
                fallback_reason = f"parallel execution failed; retrying serially: {exc}"
                logger.warning(fallback_reason)
                failed_assignments = 0
                for _, assignment, lease, _ in active:
                    if ledger.get_work(assignment.work_id).state is not WorkState.COMMITTED:
                        failed_assignments += 1
                    _fail_active_work(
                        ledger,
                        assignment.work_id,
                        lease_by_work_id.get(assignment.work_id, lease),
                        fallback_reason,
                    )
                work_counts["failed"] += failed_assignments
                if isinstance(exc, InterruptedError):
                    work_counts["cancelled"] += failed_assignments
                retry_stream = chain(batch, iterator)
                serial_summary = execute_serial(
                    ledger,
                    retry_stream,
                    owner_id,
                    lease_seconds,
                    solver,
                    scratch_root,
                    policy,
                    requested_mode,
                    fallback_reason,
                    probe_report,
                    selected_workers,
                    log_summary=False,
                )
                return _log_summary(
                    _merge_summaries(serial_summary, work_counts, key_counts, reused_before_probe)
                )
            finally:
                for _, _, _, scratch_directory in active:
                    _remove_assignment_scratch(scratch_directory)

        return _log_summary(
            ExecutionSummary(
                requested_mode=requested_mode,
                effective_mode=ExecutionMode.PARALLEL,
                probe_report=probe_report,
                fallback_reason=None,
                work_counts=tuple(sorted(work_counts.items())),
                key_counts=tuple(sorted(key_counts.items())),
                configured_worker_ceiling=policy.max_workers,
                resource_worker_ceiling=policy.resource_worker_ceiling,
                selected_worker_count=selected_workers,
                preparation_counts=(("completed", prepared_count), ("failed", 0)),
            )
        )
    finally:
        if owns_scratch_root:
            shutil.rmtree(base_scratch)


def _network_assignment_worker(assignment: WorkAssignment) -> WorkerResult:
    from h3_route_data_builder.network.solver import run_network_assignment

    return run_network_assignment(assignment)


def _run_probe_attempt(
    prepared: PreparedSolveInput,
    worker_count: int,
    timeout_s: float,
    scratch_root: Path | None,
    shutdown_grace_s: float = 10,
) -> ProbeAttempt:
    representative_ids = {h3_id for h3_id, _ in prepared.representatives}
    probe_key = next(
        key
        for key in prepared.work_item.expected_logical_od_keys
        if key[0] in representative_ids and key[1] in representative_ids
    )
    parent = scratch_root
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="h3-od-probe-", dir=parent) as root:
        assignments = tuple(
            WorkAssignment(
                work_id=f"{prepared.work_item.work_id}-probe-{index}",
                compatibility_fingerprint=prepared.work_item.compatibility_fingerprint,
                owner_id=f"probe-{index}",
                attempt=max(1, prepared.work_item.attempt_count),
                fencing_value=prepared.work_item.fencing_value,
                expected_logical_od_keys=(probe_key,),
                prepared_input=prepared,
                scratch_directory=str(Path(root) / f"worker-{index}"),
                probe=True,
            )
            for index in range(worker_count)
        )
        for assignment in assignments:
            Path(assignment.scratch_directory).mkdir()
        started_at = time.monotonic()
        results = _run_spawned_batch(
            assignments,
            _network_assignment_worker,
            timeout_s=timeout_s,
            shutdown_grace_s=shutdown_grace_s,
        )
        elapsed_s = time.monotonic() - started_at
        evidence: list[str] = []
        for result in results:
            if tuple(outcome.logical_od_key for outcome in result.outcomes) != (probe_key,):
                raise ValueError("probe worker returned invalid logical-key evidence")
            evidence.append(f"{result.work_id}: bounded solve passed")
        return ProbeAttempt(worker_count, "passed", elapsed_s, tuple(evidence))


def _run_spawned_batch(
    assignments: Sequence[WorkAssignment],
    worker: WorkerAdapter,
    timeout_s: float,
    shutdown_grace_s: float,
    on_wait: Callable[[], None] | None = None,
) -> tuple[WorkerResult, ...]:
    """Run a bounded set of isolated assignments with spawn and hard time limits."""
    if not assignments:
        return ()
    context = multiprocessing.get_context("spawn")
    records: list[tuple[WorkAssignment, Any, Connection]] = []
    results: dict[str, WorkerResult] = {}
    started_at = time.monotonic()
    try:
        for assignment in assignments:
            receive_connection, send_connection = context.Pipe(duplex=False)
            process = context.Process(
                target=_worker_process_entry,
                args=(send_connection, assignment, worker),
            )
            records.append((assignment, process, receive_connection))
            try:
                process.start()
            finally:
                send_connection.close()

        pending = {connection: (assignment, process) for assignment, process, connection in records}
        deadline = started_at + timeout_s
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("spawned OD worker batch exceeded its time limit")
            ready = wait(tuple(pending), timeout=min(0.25, remaining))
            if not ready:
                if on_wait is not None:
                    on_wait()
                continue
            for connection in ready:
                assignment, process = pending.pop(connection)
                try:
                    message = connection.recv()
                except EOFError as exc:
                    raise RuntimeError(
                        f"worker '{assignment.work_id}' exited without a result"
                    ) from exc
                process.join(timeout=shutdown_grace_s)
                if process.is_alive():
                    raise RuntimeError(
                        f"worker '{assignment.work_id}' did not exit after returning"
                    )
                if process.exitcode != 0:
                    raise RuntimeError(
                        f"worker '{assignment.work_id}' exited with code {process.exitcode}"
                    )
                if message[0] == "error":
                    raise RuntimeError(
                        f"worker {message[1]} for '{assignment.work_id}': {message[2]}"
                    )
                result = message[1]
                if not isinstance(result, WorkerResult):
                    raise TypeError("spawned worker returned an invalid result record")
                if result.work_id in results:
                    raise ValueError(f"duplicate worker response for '{result.work_id}'")
                results[result.work_id] = result
        return tuple(results[assignment.work_id] for assignment in assignments)
    finally:
        for _, process, connection in records:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(timeout=shutdown_grace_s)
                if process.is_alive():
                    process.kill()
                    process.join()
            connection.close()
            if process.exitcode is not None:
                process.close()


def _worker_process_entry(
    connection: Connection, assignment: WorkAssignment, worker: WorkerAdapter
) -> None:
    try:
        connection.send(("result", worker(assignment)))
    except BaseException as exc:
        connection.send(("error", type(exc).__name__, str(exc)))
    finally:
        connection.close()


def _fail_active_work(ledger: ODLedger, work_id: str, lease: Lease, message: str) -> None:
    item = ledger.get_work(work_id)
    if (
        item.state in {WorkState.LEASED, WorkState.SOLVING}
        and item.lease is not None
        and item.lease.owner_id == lease.owner_id
        and item.lease.fencing_value == lease.fencing_value
    ):
        try:
            ledger.fail(work_id, lease, "system_failure", message)
        except RuntimeError as exc:
            logger.warning(f"Work item '{work_id}' could not be failed under its lease: {exc}")


def _remove_assignment_scratch(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        message = f"Could not remove isolated OD scratch '{path}': {exc}"
        logger.error(message)
        raise RuntimeError(message) from exc


def _merge_summaries(
    serial: ExecutionSummary,
    prior_work_counts: Mapping[str, int],
    prior_key_counts: Mapping[str, int],
    prior_prepared_count: int,
) -> ExecutionSummary:
    work_counts = dict(serial.work_counts)
    for name, count in prior_work_counts.items():
        work_counts[name] = work_counts.get(name, 0) + count
    key_counts = dict(serial.key_counts)
    for name, count in prior_key_counts.items():
        key_counts[name] = key_counts.get(name, 0) + count
    preparation_counts = dict(serial.preparation_counts)
    preparation_counts["completed"] = preparation_counts.get("completed", 0) + prior_prepared_count
    return ExecutionSummary(
        requested_mode=serial.requested_mode,
        effective_mode=serial.effective_mode,
        probe_report=serial.probe_report,
        fallback_reason=serial.fallback_reason,
        work_counts=tuple(sorted(work_counts.items())),
        key_counts=tuple(sorted(key_counts.items())),
        configured_worker_ceiling=serial.configured_worker_ceiling,
        resource_worker_ceiling=serial.resource_worker_ceiling,
        selected_worker_count=serial.selected_worker_count,
        preparation_counts=tuple(sorted(preparation_counts.items())),
    )


def _log_summary(summary: ExecutionSummary) -> ExecutionSummary:
    logger.info(
        "OD execution summary: requested=%s effective=%s configured_workers=%s "
        "resource_workers=%s selected_workers=%s fallback=%r work_counts=%s "
        "key_counts=%s preparation_counts=%s probe_attempts=%s",
        summary.requested_mode.value,
        summary.effective_mode.value,
        summary.configured_worker_ceiling,
        summary.resource_worker_ceiling,
        summary.selected_worker_count,
        summary.fallback_reason,
        dict(summary.work_counts),
        dict(summary.key_counts),
        dict(summary.preparation_counts),
        tuple(
            (attempt.worker_count, attempt.status, attempt.failure_reason)
            for attempt in summary.probe_report.attempts
        ),
    )
    return summary


def _bounded_number(value: Any, name: str, maximum: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number from greater than 0 to {maximum}")
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be a number from greater than 0 to {maximum}")
    return float(value)
