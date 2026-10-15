"""Bounded non-ArcPy preparation for OD work assignments."""

from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from h3_route_data_builder.eligibility.cells import canonical_h3_ids
from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.execution import PreparedSolveInput
from h3_route_data_builder.od.ledger import WorkItem
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

T = TypeVar("T")
_MAX_PREPARATION_WORKERS = 2
_MAX_PREPARED_BUFFER = 2


def prepare_solve_input(
    work_item: WorkItem,
    representatives: Mapping[int, NetworkLocation],
    network_dataset_path: str,
    travel_mode: str,
    cost_attribute: str,
    spatial_reference_wkid: int,
) -> PreparedSolveInput:
    """Normalize one existing bounded work item without changing its key set.

    Args:
        work_item: Planned Feature 003 work item.
        representatives: Feature 001 representative locations keyed by H3 ID.
        network_dataset_path: Network dataset identifier used by the solve.
        travel_mode: Selected Network Analyst travel mode.
        cost_attribute: Cost attribute expected from the travel mode.
        spatial_reference_wkid: WKID used to recreate the ArcPy spatial reference in a worker.

    Returns:
        Immutable serializable solve input with representative locations in canonical order.

    Raises:
        ValueError: If a required network setting or endpoint location is malformed.
    """
    if not isinstance(network_dataset_path, str) or not network_dataset_path.strip():
        raise ValueError("network_dataset_path must be non-empty")
    if not isinstance(travel_mode, str) or not travel_mode.strip():
        raise ValueError("travel_mode must be non-empty")
    if not isinstance(cost_attribute, str) or not cost_attribute.strip():
        raise ValueError("cost_attribute must be non-empty")
    if (
        isinstance(spatial_reference_wkid, bool)
        or not isinstance(spatial_reference_wkid, int)
        or spatial_reference_wkid <= 0
    ):
        raise ValueError("spatial_reference_wkid must be a positive integer")

    endpoints = {
        endpoint for logical_key in work_item.expected_logical_od_keys for endpoint in logical_key
    }
    canonical_h3_ids(endpoints)
    normalized_representatives: list[tuple[int, NetworkLocation]] = []
    for endpoint in sorted(endpoints):
        location = representatives.get(endpoint)
        if location is not None:
            if not isinstance(location, NetworkLocation):
                raise ValueError(f"representative for '{endpoint}' has an invalid type")
            normalized_representatives.append((endpoint, location))

    return PreparedSolveInput(
        work_item=work_item,
        representatives=tuple(normalized_representatives),
        network_dataset_path=network_dataset_path,
        travel_mode=travel_mode,
        cost_attribute=cost_attribute,
        spatial_reference_wkid=spatial_reference_wkid,
    )


def iter_prepared_work_items(
    work_items: Iterable[WorkItem],
    prepare: Callable[[WorkItem], T],
    max_workers: int = _MAX_PREPARATION_WORKERS,
    buffer_size: int = _MAX_PREPARED_BUFFER,
) -> Iterator[T]:
    """Prepare an incremental work stream with bounded concurrency and buffering.

    Results are yielded in input order. The submission window includes running tasks and
    completed payloads, so no more than ``buffer_size`` items can be active or waiting for
    dispatch. Executor shutdown waits for submitted preparation to stop before returning.
    """
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or not 1 <= max_workers <= _MAX_PREPARATION_WORKERS
    ):
        raise ValueError(f"max_workers must be from 1 to {_MAX_PREPARATION_WORKERS}")
    if (
        isinstance(buffer_size, bool)
        or not isinstance(buffer_size, int)
        or not 1 <= buffer_size <= _MAX_PREPARED_BUFFER
    ):
        raise ValueError(f"buffer_size must be from 1 to {_MAX_PREPARED_BUFFER}")

    iterator = iter(work_items)
    pending: deque[tuple[WorkItem, Future[T]]] = deque()
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        _fill_window(iterator, pending, executor, prepare, buffer_size)
        while pending:
            item, future = pending.popleft()
            try:
                yield future.result()
            except Exception as exc:
                message = f"OD preparation failed for work item '{item.work_id}': {exc}"
                logger.error(message)
                for _, pending_future in pending:
                    pending_future.cancel()
                raise RuntimeError(message) from exc
            _fill_window(iterator, pending, executor, prepare, buffer_size)
    finally:
        for _, pending_future in pending:
            pending_future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def _fill_window(
    work_items: Iterator[WorkItem],
    pending: deque[tuple[WorkItem, Future[T]]],
    executor: ThreadPoolExecutor,
    prepare: Callable[[WorkItem], T],
    buffer_size: int,
) -> None:
    while len(pending) < buffer_size:
        try:
            item = next(work_items)
        except StopIteration:
            return
        pending.append((item, executor.submit(prepare, item)))
