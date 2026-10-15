"""Tests for coordinator acceptance and isolated worker execution."""

from pathlib import Path
from h3.api import basic_int as h3
import pytest

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.execution import (
    ExecutionMode,
    ParallelExecutionConfig,
    ProbeAttempt,
    WorkAssignment,
    WorkerResult,
    _run_spawned_batch,
    execute_work,
)
from h3_route_data_builder.od.ledger import ODLedger, WorkItem, WorkState
from h3_route_data_builder.od.preparation import prepare_solve_input
from h3_route_data_builder.od.results import (
    OutcomeClass,
    SolveOutcome,
    classify_actual_cost,
)
from h3_route_data_builder.od.solving import accept_worker_result


def test_integer_payload_spawn_round_trip(
    integer_work_item: WorkItem,
    tmp_path: Path,
) -> None:
    assignment = WorkAssignment(
        work_id=integer_work_item.work_id,
        compatibility_fingerprint=integer_work_item.compatibility_fingerprint,
        owner_id="coordinator",
        attempt=1,
        fencing_value=1,
        expected_logical_od_keys=integer_work_item.expected_logical_od_keys,
        prepared_input=_prepared(integer_work_item),
        scratch_directory=str(tmp_path),
    )
    (result,) = _run_spawned_batch(
        [assignment],
        _scratch_worker,
        timeout_s=30,
        shutdown_grace_s=2,
    )
    assert result.outcomes[0].logical_od_key == integer_work_item.expected_logical_od_keys[0]
    assert all(
        type(endpoint) is int and endpoint > 2**53 for endpoint in result.outcomes[0].logical_od_key
    )


def _prepared(item):
    location = NetworkLocation(1, 2, 3, 4, 0.5, 1, 2)
    return prepare_solve_input(
        item,
        {endpoint: location for key in item.expected_logical_od_keys for endpoint in key},
        "network",
        "driving",
        "Minutes",
        3857,
    )


def _assignment(item, lease, prepared, scratch_directory, probe=False):
    return WorkAssignment(
        work_id=item.work_id,
        compatibility_fingerprint=item.compatibility_fingerprint,
        owner_id=lease.owner_id,
        attempt=item.attempt_count + (0 if probe else 1),
        fencing_value=lease.fencing_value,
        expected_logical_od_keys=item.expected_logical_od_keys,
        prepared_input=prepared,
        scratch_directory=str(scratch_directory),
        probe=probe,
    )


def _scratch_worker(assignment: WorkAssignment) -> WorkerResult:
    marker = Path(assignment.scratch_directory) / "worker-marker.txt"
    marker.write_text(assignment.work_id, encoding="utf-8")
    outcomes = tuple(
        classify_actual_cost(key, 1, 10, assignment.prepared_input.work_item.cost_unit)
        for key in assignment.expected_logical_od_keys
    )
    return WorkerResult(
        assignment.work_id,
        assignment.compatibility_fingerprint,
        assignment.attempt,
        assignment.fencing_value,
        outcomes,
        (str(marker),),
    )


def _equivalence_worker(assignment: WorkAssignment) -> WorkerResult:
    outcomes = (
        classify_actual_cost(
            assignment.expected_logical_od_keys[0],
            5,
            10,
            assignment.prepared_input.work_item.cost_unit,
        ),
        SolveOutcome(
            assignment.expected_logical_od_keys[1],
            OutcomeClass.UNREACHABLE,
            None,
            None,
        ),
    )
    return WorkerResult(
        assignment.work_id,
        assignment.compatibility_fingerprint,
        assignment.attempt,
        assignment.fencing_value,
        outcomes,
    )


def test_spawned_workers_use_distinct_scratch_and_return_bounded_results(
    tmp_path: Path,
) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    items = [
        ledger.plan_work(
            "fingerprint", h3.latlng_to_cell(1.0, index * 0.01, 9), [619056559457304575], 10, "m"
        )
        for index in range(2)
    ]
    assignments = []
    for index, item in enumerate(items):
        lease = ledger.acquire_lease(item.work_id, "coordinator", 30)
        ledger.start_solving(item.work_id, lease)
        scratch = tmp_path / f"scratch-{index}"
        scratch.mkdir()
        assignments.append(_assignment(item, lease, _prepared(item), scratch))

    results = _run_spawned_batch(
        assignments,
        _scratch_worker,
        timeout_s=30,
        shutdown_grace_s=2,
    )

    marker_paths = [Path(result.diagnostics[0]) for result in results]
    assert len(set(marker_paths)) == len(assignments)
    assert all(path.is_file() for path in marker_paths)
    assert all(ledger.get_work(item.work_id).state is WorkState.SOLVING for item in items)


@pytest.mark.parametrize("invalid_case", ["missing", "duplicate", "unexpected"])
def test_coordinator_rejects_invalid_worker_key_coverage(tmp_path: Path, invalid_case: str) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work(
        "fingerprint", 619056821839593471, [619056821832253439, 619056821839331327], 10, "m"
    )
    lease = ledger.acquire_lease(item.work_id, "coordinator", 30)
    ledger.start_solving(item.work_id, lease)
    assignment = _assignment(item, lease, _prepared(item), tmp_path / "scratch")
    keys = item.expected_logical_od_keys
    valid_outcomes = tuple(classify_actual_cost(key, 1, 10, "m") for key in keys)
    if invalid_case == "missing":
        outcomes = valid_outcomes[:1]
    elif invalid_case == "duplicate":
        outcomes = (valid_outcomes[0], valid_outcomes[0])
    else:
        outcomes = (
            valid_outcomes[0],
            classify_actual_cost((619056821839593471, 619056821840379903), 1, 10, "m"),
        )
    result = WorkerResult(
        item.work_id,
        item.compatibility_fingerprint,
        assignment.attempt,
        assignment.fencing_value,
        outcomes,
    )

    with pytest.raises(ValueError, match="staged output rejected"):
        accept_worker_result(ledger, assignment, lease, result)

    assert ledger.get_work(item.work_id).state is WorkState.RETRYABLE_FAILURE
    assert not ledger.committed_outcomes("fingerprint")


def test_coordinator_rejects_stale_worker_fencing_evidence(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
    first_lease = ledger.acquire_lease(item.work_id, "old-owner", 10, now=100)
    ledger.start_solving(item.work_id, first_lease, now=101)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assignment = _assignment(item, first_lease, _prepared(item), scratch)
    result = _scratch_worker(assignment)

    second_lease = ledger.acquire_lease(item.work_id, "new-owner", 10, now=111)
    ledger.start_solving(item.work_id, second_lease, now=112)

    with pytest.raises(RuntimeError, match="no longer matches"):
        accept_worker_result(ledger, assignment, first_lease, result)
    assert ledger.get_work(item.work_id).lease == second_lease
    assert ledger.get_work(item.work_id).state is WorkState.SOLVING


def test_parallel_coordinator_commits_only_worker_results(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
    prepared = _prepared(item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}}, cpu_count=2
    )

    def probe(sample, worker_count, timeout, scratch_root):
        return ProbeAttempt(
            worker_count,
            "passed",
            0.1,
            tuple(f"worker-{index} passed" for index in range(worker_count)),
        )

    summary = execute_work(
        ledger,
        [prepared],
        "coordinator",
        30,
        policy,
        worker=_scratch_worker,
        probe_runner=probe,
        scratch_root=tmp_path / "run-scratch",
    )

    assert ledger.get_work(item.work_id).state is WorkState.COMMITTED
    assert len(ledger.committed_outcomes("fingerprint")) == 1
    assert summary.requested_mode is ExecutionMode.PARALLEL
    assert summary.effective_mode is ExecutionMode.PARALLEL
    assert dict(summary.work_counts)["committed"] == 1


def test_completed_compatible_work_skips_probe_and_is_reused(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
    prepared = _prepared(item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}}, cpu_count=2
    )
    execution = execute_work(
        ledger,
        [prepared],
        "coordinator",
        30,
        policy,
        requested_mode=ExecutionMode.SERIAL,
        solver=lambda payload, scratch: (
            classify_actual_cost(payload.work_item.expected_logical_od_keys[0], 1, 10, "m"),
        ),
    )
    assert execution.effective_mode is ExecutionMode.SERIAL

    def unexpected_probe(*args):
        raise AssertionError("fully reused work must not start a capability probe")

    reused = execute_work(
        ledger,
        [prepared],
        "coordinator",
        30,
        policy,
        probe_runner=unexpected_probe,
    )

    assert not reused.probe_report.attempts
    assert dict(reused.work_counts)["reused"] == 1
    assert dict(reused.work_counts)["reconciled"] == 1
    assert reused.selected_worker_count == 0


def test_serial_and_parallel_execution_have_identical_logical_outcomes(
    tmp_path: Path,
) -> None:
    serial_ledger = ODLedger(tmp_path / "serial.sqlite")
    parallel_ledger = ODLedger(tmp_path / "parallel.sqlite")
    serial_item = serial_ledger.plan_work(
        "fingerprint", 619056821839593471, [619056821832253439, 619056821839331327], 10, "m"
    )
    parallel_item = parallel_ledger.plan_work(
        "fingerprint", 619056821839593471, [619056821832253439, 619056821839331327], 10, "m"
    )
    serial_prepared = _prepared(serial_item)
    parallel_prepared = _prepared(parallel_item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}}, cpu_count=2
    )

    def serial_solver(prepared, scratch):
        return _equivalence_worker(
            WorkAssignment(
                work_id=prepared.work_item.work_id,
                compatibility_fingerprint=prepared.work_item.compatibility_fingerprint,
                owner_id="coordinator",
                attempt=1,
                fencing_value=1,
                expected_logical_od_keys=prepared.work_item.expected_logical_od_keys,
                prepared_input=prepared,
                scratch_directory=str(scratch),
            )
        ).outcomes

    serial_summary = execute_work(
        serial_ledger,
        [serial_prepared],
        "serial-coordinator",
        30,
        policy,
        requested_mode=ExecutionMode.SERIAL,
        solver=serial_solver,
    )

    def probe(sample, worker_count, timeout, scratch_root):
        return ProbeAttempt(
            worker_count, "passed", 0.1, tuple("passed" for _ in range(worker_count))
        )

    parallel_summary = execute_work(
        parallel_ledger,
        [parallel_prepared],
        "parallel-coordinator",
        30,
        policy,
        worker=_equivalence_worker,
        probe_runner=probe,
        scratch_root=tmp_path / "parallel-scratch",
    )

    serial_outcomes = serial_ledger.committed_outcomes("fingerprint")
    parallel_outcomes = parallel_ledger.committed_outcomes("fingerprint")
    assert serial_outcomes == parallel_outcomes
    assert serial_summary.key_counts == parallel_summary.key_counts
