"""Tests for capability probing and observable serial fallback."""

from pathlib import Path
from threading import Event, Timer
import time
from threading import Lock
from h3.api import basic_int as h3

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.execution import (
    ExecutionMode,
    ParallelExecutionConfig,
    PreparedSolveInput,
    ProbeAttempt,
    WorkAssignment,
    WorkerResult,
    execute_work,
    probe_parallel_capacity,
)
from h3_route_data_builder.od.ledger import ODLedger, WorkState
from h3_route_data_builder.od.preparation import prepare_solve_input
from h3_route_data_builder.od.preparation import iter_prepared_work_items
from h3_route_data_builder.od.results import classify_actual_cost


def _prepared(item, with_representatives=True):
    location = NetworkLocation(1, 2, 3, 4, 0.5, 1, 2)
    representatives = (
        {endpoint: location for key in item.expected_logical_od_keys for endpoint in key}
        if with_representatives
        else {}
    )
    return prepare_solve_input(item, representatives, "network", "driving", "Minutes", 3857)


def _successful_worker(assignment: WorkAssignment) -> WorkerResult:
    return WorkerResult(
        assignment.work_id,
        assignment.compatibility_fingerprint,
        assignment.attempt,
        assignment.fencing_value,
        tuple(
            classify_actual_cost(key, 1, 10, assignment.prepared_input.work_item.cost_unit)
            for key in assignment.expected_logical_od_keys
        ),
    )


def _crashing_worker(assignment: WorkAssignment) -> WorkerResult:
    raise RuntimeError("simulated worker crash")


def _initialization_failure_worker(assignment: WorkAssignment) -> WorkerResult:
    raise RuntimeError("ArcPy initialization failed")


def _license_failure_worker(assignment: WorkAssignment) -> WorkerResult:
    raise RuntimeError("Network Analyst license unavailable")


def _network_lock_failure_worker(assignment: WorkAssignment) -> WorkerResult:
    raise RuntimeError("network dataset lock failure")


def _slow_worker(assignment: WorkAssignment) -> WorkerResult:
    time.sleep(5)
    return _successful_worker(assignment)


def test_probe_steps_down_and_selects_highest_passing_worker_count(
    tmp_path: Path,
) -> None:
    item = ODLedger(tmp_path / "ledger.sqlite").plan_work(
        "fingerprint", 619056821839593471, [619056559457304575], 10, "m"
    )
    prepared = _prepared(item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 4}}, cpu_count=4
    )
    attempted_counts = []

    def probe(sample, worker_count, timeout_s, scratch_root):
        attempted_counts.append(worker_count)
        passed = worker_count == 2
        return ProbeAttempt(
            worker_count,
            "passed" if passed else "failed",
            0.1,
            tuple("passed" for _ in range(worker_count)) if passed else (),
            None if passed else "simulated resource contention",
        )

    report = probe_parallel_capacity(prepared, policy, probe)

    assert attempted_counts == [4, 3, 2]
    assert report.selected_worker_count == 2
    assert [attempt.worker_count for attempt in report.attempts] == [4, 3, 2]


def test_probe_exhaustion_and_unsafe_inputs_select_observable_serial_fallback(
    tmp_path: Path,
) -> None:
    item = ODLedger(tmp_path / "ledger.sqlite").plan_work(
        "fingerprint", 619056821839593471, [619056559457304575], 10, "m"
    )
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}}, cpu_count=2
    )
    calls = []

    def failure(sample, worker_count, timeout_s, scratch_root):
        calls.append(worker_count)
        return ProbeAttempt(worker_count, "failed", 0.1, (), "license unavailable")

    failed_report = probe_parallel_capacity(_prepared(item), policy, failure)
    unsafe_report = probe_parallel_capacity(_prepared(item, False), policy, failure)

    assert calls == [2]
    assert failed_report.selected_worker_count is None
    assert "license unavailable" in failed_report.fallback_reason
    assert not unsafe_report.attempts
    assert "no safely located" in unsafe_report.fallback_reason


def test_probe_tries_every_level_down_to_two_before_serial_fallback(
    tmp_path: Path,
) -> None:
    item = ODLedger(tmp_path / "ledger.sqlite").plan_work(
        "fingerprint", 619056821839593471, [619056559457304575], 10, "m"
    )
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 4}}, cpu_count=4
    )
    attempts = []

    def fail(sample, worker_count, timeout_s, scratch_root):
        attempts.append(worker_count)
        return ProbeAttempt(worker_count, "failed", 0.1, (), "capability failure")

    report = probe_parallel_capacity(_prepared(item), policy, fail)

    assert attempts == [4, 3, 2]
    assert [attempt.worker_count for attempt in report.attempts] == attempts
    assert report.selected_worker_count is None


def test_probe_failure_serial_fallback_keeps_preparation_concurrent(
    tmp_path: Path,
) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    items = [
        ledger.plan_work(
            "fingerprint", h3.latlng_to_cell(1.0, index * 0.01, 9), [619056559457304575], 10, "m"
        )
        for index in range(4)
    ]
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}}, cpu_count=2
    )
    lock = Lock()
    active = 0
    maximum_active = 0

    def prepare(item):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        payload = _prepared(item)
        with lock:
            active -= 1
        return payload

    def failed_probe(sample, worker_count, timeout_s, scratch_root):
        return ProbeAttempt(worker_count, "failed", 0.1, (), "license unavailable")

    summary = execute_work(
        ledger,
        iter_prepared_work_items(items, prepare),
        "coordinator",
        30,
        policy,
        probe_runner=failed_probe,
        solver=lambda payload, scratch: _successful_worker(
            WorkAssignment(
                payload.work_item.work_id,
                payload.work_item.compatibility_fingerprint,
                "serial",
                1,
                1,
                payload.work_item.expected_logical_od_keys,
                payload,
                str(scratch),
            )
        ).outcomes,
    )

    assert maximum_active == 2
    assert summary.effective_mode is ExecutionMode.SERIAL
    assert "license unavailable" in summary.fallback_reason
    assert len(ledger.committed_outcomes("fingerprint")) == len(items)


def test_cpu_ceiling_below_two_skips_probe(tmp_path: Path) -> None:
    item = ODLedger(tmp_path / "ledger.sqlite").plan_work(
        "fingerprint", 619056821839593471, [619056559457304575], 10, "m"
    )
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 8}}, cpu_count=None
    )

    def unexpected_probe(*args):
        raise AssertionError("single-CPU policy must not probe")

    report = probe_parallel_capacity(_prepared(item), policy, unexpected_probe)

    assert policy.resource_worker_ceiling == 1
    assert not report.attempts
    assert "below two" in report.fallback_reason


def test_runtime_worker_failure_retries_serially_and_reports_fallback(
    tmp_path: Path,
) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
    prepared = _prepared(item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2}}, cpu_count=2
    )

    def probe(sample, worker_count, timeout_s, scratch_root):
        return ProbeAttempt(
            worker_count, "passed", 0.1, tuple("passed" for _ in range(worker_count))
        )

    summary = execute_work(
        ledger,
        [prepared],
        "coordinator",
        30,
        policy,
        worker=_crashing_worker,
        probe_runner=probe,
        solver=lambda payload, scratch: _successful_worker(
            WorkAssignment(
                payload.work_item.work_id,
                payload.work_item.compatibility_fingerprint,
                "serial",
                1,
                1,
                payload.work_item.expected_logical_od_keys,
                payload,
                str(scratch),
            )
        ).outcomes,
        scratch_root=tmp_path / "scratch",
    )

    assert ledger.get_work(item.work_id).state is WorkState.COMMITTED
    assert summary.effective_mode is ExecutionMode.SERIAL
    assert "simulated worker crash" in summary.fallback_reason
    assert dict(summary.work_counts)["failed"] == 1
    assert len(ledger.committed_outcomes("fingerprint")) == 1


def test_cancellation_stops_worker_and_retries_work_serially(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
    prepared = _prepared(item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2, "shutdown_grace_s": 1}},
        cpu_count=2,
    )
    cancel_event = Event()

    def probe(sample, worker_count, timeout_s, scratch_root):
        return ProbeAttempt(
            worker_count, "passed", 0.1, tuple("passed" for _ in range(worker_count))
        )

    timer = Timer(0.5, cancel_event.set)
    timer.start()
    try:
        summary = execute_work(
            ledger,
            [prepared],
            "coordinator",
            30,
            policy,
            worker=_slow_worker,
            probe_runner=probe,
            solver=lambda payload, scratch: _successful_worker(
                WorkAssignment(
                    payload.work_item.work_id,
                    payload.work_item.compatibility_fingerprint,
                    "serial",
                    1,
                    1,
                    payload.work_item.expected_logical_od_keys,
                    payload,
                    str(scratch),
                )
            ).outcomes,
            scratch_root=tmp_path / "scratch",
            cancel_event=cancel_event,
        )
    finally:
        timer.cancel()

    assert ledger.get_work(item.work_id).state is WorkState.COMMITTED
    assert summary.effective_mode is ExecutionMode.SERIAL
    assert "cancelled" in summary.fallback_reason


def test_initialization_license_and_lock_failures_fall_back_serially(
    tmp_path: Path,
) -> None:
    failure_workers = (
        (_initialization_failure_worker, "initialization failed"),
        (_license_failure_worker, "license unavailable"),
        (_network_lock_failure_worker, "lock failure"),
    )
    for index, (worker, expected_message) in enumerate(failure_workers):
        ledger = ODLedger(tmp_path / f"ledger-{index}.sqlite")
        item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
        prepared = _prepared(item)
        policy = ParallelExecutionConfig.from_mapping(
            {"parallel_solving": {"max_workers": 2}}, cpu_count=2
        )

        def probe(sample, worker_count, timeout_s, scratch_root):
            return ProbeAttempt(
                worker_count,
                "passed",
                0.1,
                tuple("passed" for _ in range(worker_count)),
            )

        summary = execute_work(
            ledger,
            [prepared],
            "coordinator",
            30,
            policy,
            worker=worker,
            probe_runner=probe,
            solver=lambda payload, scratch: _successful_worker(
                WorkAssignment(
                    payload.work_item.work_id,
                    payload.work_item.compatibility_fingerprint,
                    "serial",
                    1,
                    1,
                    payload.work_item.expected_logical_od_keys,
                    payload,
                    str(scratch),
                )
            ).outcomes,
            scratch_root=tmp_path / f"scratch-{index}",
        )

        assert expected_message in summary.fallback_reason
        assert ledger.get_work(item.work_id).state is WorkState.COMMITTED


def test_worker_timeout_falls_back_to_serial(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 10, "m")
    prepared = _prepared(item)
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": 2, "shutdown_grace_s": 1}},
        cpu_count=2,
    )

    def probe(sample, worker_count, timeout_s, scratch_root):
        return ProbeAttempt(
            worker_count, "passed", 0.1, tuple("passed" for _ in range(worker_count))
        )

    summary = execute_work(
        ledger,
        [prepared],
        "coordinator",
        0.5,
        policy,
        worker=_slow_worker,
        probe_runner=probe,
        solver=lambda payload, scratch: _successful_worker(
            WorkAssignment(
                payload.work_item.work_id,
                payload.work_item.compatibility_fingerprint,
                "serial",
                1,
                1,
                payload.work_item.expected_logical_od_keys,
                payload,
                str(scratch),
            )
        ).outcomes,
        scratch_root=tmp_path / "scratch",
    )

    assert ledger.get_work(item.work_id).state is WorkState.COMMITTED
    assert summary.effective_mode is ExecutionMode.SERIAL
    assert "exceeded its time limit" in summary.fallback_reason
