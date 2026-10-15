"""Tests for bounded, deterministic OD solve-input preparation."""

import pickle
from threading import Lock
import time
from pathlib import Path

from h3.api import basic_int as h3
import pytest

from h3_route_data_builder.od.execution import ParallelExecutionConfig
from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.ledger import ODLedger, WorkItem, WorkState
from h3_route_data_builder.od.preparation import (
    iter_prepared_work_items,
    prepare_solve_input,
)


def test_integer_payload_preserves_exact_keys_and_representatives(
    integer_work_item: WorkItem,
) -> None:
    location = NetworkLocation(1, 2, 3, 4, 0.5, 1, 2)
    keys = integer_work_item.expected_logical_od_keys
    prepared = prepare_solve_input(
        integer_work_item,
        {endpoint: location for key in keys for endpoint in key},
        "network",
        "driving",
        "Minutes",
        3857,
    )
    assert all(
        type(endpoint) is int and endpoint > 2**53 for endpoint, _ in prepared.representatives
    )
    assert tuple(endpoint for endpoint, _ in prepared.representatives) == tuple(sorted(keys[0]))
    assert pickle.loads(pickle.dumps(prepared)) == prepared


@pytest.mark.parametrize("endpoint", ["8928308280fffff", "617700169958293503", True, 1.0, None])
def test_integer_payload_rejects_textual_or_coerced_endpoints(
    integer_work_item: WorkItem,
    endpoint: object,
) -> None:
    from dataclasses import replace

    invalid = replace(
        integer_work_item, expected_logical_od_keys=((endpoint, integer_work_item.origin_h3_id),)
    )
    with pytest.raises(ValueError, match="H3"):
        prepare_solve_input(invalid, {}, "network", "driving", "Minutes", 3857)


def _work_item(index: int) -> WorkItem:
    origin = h3.latlng_to_cell(1.0, index * 0.01, 9)
    destination = h3.latlng_to_cell(2.0, index * 0.01, 9)
    return WorkItem(
        work_id=f"work-{index}",
        compatibility_fingerprint="fingerprint",
        origin_h3_id=origin,
        destination_batch=(destination,),
        expected_logical_od_keys=((origin, destination),),
        cutoff=10.0,
        cost_unit="m",
        state=WorkState.PLANNED,
        attempt_count=0,
        fencing_value=0,
        lease=None,
        committed_part_id=None,
        failure_evidence=None,
    )


def test_parallel_preparation_preserves_input_order_and_bounds_concurrency() -> None:
    lock = Lock()
    active = 0
    maximum_active = 0

    def prepare(item: WorkItem) -> str:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return item.work_id

    results = tuple(
        iter_prepared_work_items(
            (_work_item(index) for index in range(6)),
            prepare,
        )
    )

    assert results == tuple(f"work-{index}" for index in range(6))
    assert 2 <= maximum_active <= 2


def test_preparation_streams_with_a_two_item_submission_window() -> None:
    consumed = 0

    def work_items():
        nonlocal consumed
        for index in range(8):
            consumed += 1
            yield _work_item(index)

    iterator = iter_prepared_work_items(work_items(), lambda item: item.work_id)

    assert next(iterator) == "work-0"
    assert consumed <= 3
    iterator.close()


def test_preparation_failure_identifies_work_item() -> None:
    def prepare(item: WorkItem) -> str:
        if item.work_id == "work-1":
            raise OSError("cannot normalize")
        return item.work_id

    iterator = iter_prepared_work_items(
        (_work_item(index) for index in range(3)),
        prepare,
    )
    assert next(iterator) == "work-0"

    with pytest.raises(RuntimeError, match="work-1"):
        next(iterator)


def test_explicit_serial_policy_keeps_preparation_concurrency_enabled() -> None:
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"enabled": False}}, cpu_count=1
    )

    assert policy.preparation_worker_ceiling == 2


def test_payload_normalization_preserves_keys_order_and_ledger_state(
    tmp_path: Path,
) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work(
        "fingerprint", 619056821839593471, [619056821839331327, 619056821832253439], 100, "m"
    )
    before = ledger.get_work(item.work_id)
    location = NetworkLocation(1, 2, 3, 4, 0.5, 1, 2)

    prepared = prepare_solve_input(
        item,
        {619056821839593471: location, 619056821832253439: location},
        "network",
        "driving",
        "Minutes",
        3857,
    )

    assert prepared.work_item == item
    assert prepared.work_item.expected_logical_od_keys == (
        (619056821839593471, 619056821832253439),
        (619056821839593471, 619056821839331327),
    )
    assert tuple(h3_id for h3_id, _ in prepared.representatives) == (
        619056821832253439,
        619056821839593471,
    )
    assert pickle.loads(pickle.dumps(prepared)) == prepared
    assert ledger.get_work(item.work_id) == before


@pytest.mark.parametrize(
    ("max_workers", "buffer_size"),
    [(0, 1), (3, 1), (1, 0), (1, 3)],
)
def test_preparation_rejects_limits_outside_hard_bounds(max_workers: int, buffer_size: int) -> None:
    with pytest.raises(ValueError):
        tuple(
            iter_prepared_work_items(
                (_work_item(0),),
                lambda item: item.work_id,
                max_workers=max_workers,
                buffer_size=buffer_size,
            )
        )
