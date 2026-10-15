"""Tests for portable parallel OD execution policy."""

import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from h3_route_data_builder.config import ConfigNode
from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.od.execution import (
    ExecutionMode,
    ExecutionSummary,
    ParallelExecutionConfig,
    PreparedSolveInput,
    ProbeAttempt,
    ProbeReport,
    WorkAssignment,
    WorkerResult,
)
from h3_route_data_builder.od.ledger import ODLedger


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"parallel_solving": {"enabled": None}},
        {"parallel_solving": {"enabled": True}},
    ],
)
def test_parallel_solving_defaults_to_enabled(settings: dict) -> None:
    policy = ParallelExecutionConfig.from_mapping(settings, cpu_count=4)

    assert policy.enabled
    assert policy.max_workers == 2
    assert policy.resource_worker_ceiling == 2


def test_explicit_false_disables_only_parallel_solving() -> None:
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"enabled": False}}, cpu_count=4
    )

    assert not policy.enabled
    assert policy.preparation_worker_ceiling == 2


def test_config_node_is_accepted_directly() -> None:
    policy = ParallelExecutionConfig.from_mapping(
        ConfigNode({"parallel_solving": {"enabled": False}}),
        cpu_count=4,
    )

    assert not policy.enabled


@pytest.mark.parametrize(
    ("configured_workers", "cpu_count", "expected"),
    [(2, 8, 2), (8, 2, 2), (8, None, 1)],
)
def test_worker_ceiling_is_bounded_by_cpu_resources(
    configured_workers: int, cpu_count: int | None, expected: int
) -> None:
    policy = ParallelExecutionConfig.from_mapping(
        {"parallel_solving": {"max_workers": configured_workers}},
        cpu_count=cpu_count,
    )

    assert policy.resource_worker_ceiling == expected


@pytest.mark.parametrize(
    "settings",
    [
        {"enabled": "false"},
        {"max_workers": True},
        {"max_workers": 0},
        {"max_workers": 65},
        {"probe_timeout_s": 0},
        {"probe_timeout_s": 3601},
        {"shutdown_grace_s": -1},
        {"shutdown_grace_s": 61},
    ],
)
def test_invalid_parallel_solving_settings_are_rejected(settings: dict) -> None:
    with pytest.raises(ValueError):
        ParallelExecutionConfig.from_mapping({"parallel_solving": settings}, cpu_count=4)


def test_unknown_parallel_solving_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        ParallelExecutionConfig.from_mapping({"parallel_solving": {"unexpected": 1}}, cpu_count=4)


def test_execution_records_are_pickle_serializable(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    item = ledger.plan_work("fingerprint", 619056821839593471, [619056559457304575], 100, "m")
    location = NetworkLocation(1, 2, 3, 4, 0.5, 1, 2)
    prepared = PreparedSolveInput(
        work_item=item,
        representatives=((619056821839593471, location), (619056559457304575, location)),
        network_dataset_path="network",
        travel_mode="driving",
        cost_attribute="Minutes",
        spatial_reference_wkid=3857,
    )
    assignment = WorkAssignment(
        work_id=item.work_id,
        compatibility_fingerprint=item.compatibility_fingerprint,
        owner_id="coordinator",
        attempt=1,
        fencing_value=1,
        expected_logical_od_keys=item.expected_logical_od_keys,
        prepared_input=prepared,
        scratch_directory="scratch/work-1",
    )
    records = (
        prepared,
        assignment,
        WorkerResult(item.work_id, item.compatibility_fingerprint, 1, 1, ()),
        ProbeAttempt(2, "passed", 0.2, ("worker-1 ok", "worker-2 ok")),
        ProbeReport((ProbeAttempt(2, "passed", 0.2, ("ok",)),), 2),
        ExecutionSummary(
            ExecutionMode.PARALLEL,
            ExecutionMode.PARALLEL,
            ProbeReport(),
            None,
            (("dispatched", 1),),
            (("qualifying", 1),),
        ),
    )

    for record in records:
        assert pickle.loads(pickle.dumps(record)) == record


def test_importing_execution_does_not_import_arcpy() -> None:
    code = (
        "import sys; "
        "import h3_route_data_builder.od.execution; "
        "import h3_route_data_builder.od.preparation; "
        "assert not any(name == 'arcpy' or name.startswith('arcpy.') "
        "for name in sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
