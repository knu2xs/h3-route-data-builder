"""Tests for the serial reference execution path."""

from pathlib import Path
from threading import Lock
import time

from h3.api import basic_int as h3
import pytest

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.execution import (
    ExecutionMode,
    ParallelExecutionConfig,
    execute_serial,
)
from h3_route_data_builder.od.ledger import ODLedger
from h3_route_data_builder.od.preparation import (
    iter_prepared_work_items,
    prepare_solve_input,
)
from h3_route_data_builder.od.results import (
    OutcomeClass,
    SolveOutcome,
    classify_actual_cost,
)


def _prepared(item):
    representative = NetworkLocation(1, 2, 3, 4, 0.5, 1, 2)
    return prepare_solve_input(
        item,
        {endpoint: representative for key in item.expected_logical_od_keys for endpoint in key},
        "network",
        "driving",
        "Minutes",
        3857,
    )


def test_serial_reference_commits_expected_keys_and_publication_outcomes(
    tmp_path: Path,
) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work(
        "fingerprint", 619056821839593471, [619056821832253439, 619056821839331327], 10, "m"
    )

    def solve(prepared, scratch_directory):
        assert scratch_directory.is_dir()
        return (
            classify_actual_cost((619056821839593471, 619056821832253439), 4, 10, "m"),
            SolveOutcome(
                (619056821839593471, 619056821839331327),
                OutcomeClass.UNREACHABLE,
                None,
                None,
            ),
        )

    summary = execute_serial(
        ledger,
        [_prepared(item)],
        "coordinator",
        30,
        solver=solve,
    )

    committed = ledger.committed_outcomes("fingerprint")
    assert {outcome.logical_od_key for outcome in committed} == set(item.expected_logical_od_keys)
    assert ledger.qualifying_outcomes("fingerprint") == (committed[0],)
    assert dict(summary.work_counts) == {
        "cancelled": 0,
        "committed": 1,
        "dispatched": 1,
        "failed": 0,
        "reconciled": 2,
        "retried": 0,
        "reused": 0,
    }
    assert dict(summary.key_counts) == {
        "cutoff_excluded": 0,
        "qualifying": 1,
        "unlocated": 0,
        "unreachable": 1,
    }
    assert summary.requested_mode is summary.effective_mode is ExecutionMode.SERIAL
    assert summary.probe_report.attempts == ()


@pytest.mark.parametrize("disabled", [False, True])
def test_serial_and_disabled_execution_skip_probe_but_prepare_in_parallel(
    tmp_path: Path, disabled: bool
) -> None:
    ledger = ODLedger(tmp_path / f"ledger-{disabled}.sqlite")
    items = [
        ledger.plan_work(
            "fingerprint", h3.latlng_to_cell(1.0, index * 0.01, 9), [619056559457304575], 10, "m"
        )
        for index in range(4)
    ]
    lock = Lock()
    active_preparation = 0
    max_active_preparation = 0
    solve_calls: list[str] = []

    def prepare(item):
        nonlocal active_preparation, max_active_preparation
        with lock:
            active_preparation += 1
            max_active_preparation = max(max_active_preparation, active_preparation)
        time.sleep(0.02)
        payload = _prepared(item)
        with lock:
            active_preparation -= 1
        return payload

    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"enabled": disabled}}, cpu_count=4
    )
    summary = execute_serial(
        ledger,
        iter_prepared_work_items(items, prepare),
        "coordinator",
        30,
        solver=lambda prepared, scratch: (
            solve_calls.append(prepared.work_item.work_id)
            or tuple(
                classify_actual_cost(key, 1, 10, "m")
                for key in prepared.work_item.expected_logical_od_keys
            )
        ),
        policy=policy,
    )

    assert max_active_preparation == 2
    assert len(solve_calls) == len(items)
    assert not summary.probe_report.attempts
    assert summary.effective_mode is ExecutionMode.SERIAL


def test_empty_serial_run_does_not_start_a_solve_or_probe(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")

    def unexpected_solver(prepared, scratch_directory):
        pytest.fail("zero-work execution must not invoke a solve worker")

    summary = execute_serial(
        ledger,
        (),
        "coordinator",
        30,
        solver=unexpected_solver,
    )

    assert dict(summary.work_counts) == {
        "cancelled": 0,
        "committed": 0,
        "dispatched": 0,
        "failed": 0,
        "reconciled": 0,
        "retried": 0,
        "reused": 0,
    }
    assert summary.probe_report.attempts == ()
