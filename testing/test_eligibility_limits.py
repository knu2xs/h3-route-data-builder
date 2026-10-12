"""Tests for inferred and explicit eligibility execution limits."""

import pytest

from h3_route_data_builder.eligibility.limits import (
    ExecutionLimits,
    ResourceSnapshot,
    recommend_execution_limits,
    resolve_execution_limits,
)


def test_recommendations_scale_with_memory_and_output_volume() -> None:
    resources = ResourceSnapshot(
        available_memory_bytes=8 * 1024**3,
        available_disk_bytes=1024**3,
    )

    limits = recommend_execution_limits(resources=resources)

    assert limits.batch_size == 800
    assert limits.batch_size_source == "inferred"
    assert limits.part_row_limit == 50_000
    assert limits.part_row_limit_source == "inferred"
    assert limits.total_output_hard_cap == 65_536
    assert limits.total_output_hard_cap_source == "inferred"


def test_inferred_batch_size_does_not_exceed_candidate_count() -> None:
    resources = ResourceSnapshot(
        available_memory_bytes=8 * 1024**3,
        available_disk_bytes=1024**3,
    )

    limits = recommend_execution_limits(resources=resources, candidate_count=12)

    assert limits.batch_size == 12


def test_explicit_values_override_only_their_inferred_recommendations() -> None:
    resources = ResourceSnapshot(
        available_memory_bytes=8 * 1024**3,
        available_disk_bytes=1024**3,
    )

    limits = resolve_execution_limits(
        ".",
        batch_size=333,
        resources=resources,
    )

    assert limits.batch_size == 333
    assert limits.batch_size_source == "set"
    assert limits.part_row_limit == 50_000
    assert limits.part_row_limit_source == "inferred"
    assert limits.total_output_hard_cap == 65_536
    assert limits.total_output_hard_cap_source == "inferred"


def test_fully_explicit_limits_do_not_probe_hardware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_probe(*args: object, **kwargs: object) -> ExecutionLimits:
        raise AssertionError("Explicit limits do not require resource probing")

    monkeypatch.setattr(
        "h3_route_data_builder.eligibility.limits.recommend_execution_limits",
        unexpected_probe,
    )

    limits = resolve_execution_limits(
        ".",
        batch_size=100,
        part_row_limit=500,
        total_output_hard_cap=5000,
    )

    assert limits.batch_size_source == "set"
    assert limits.part_row_limit_source == "set"
    assert limits.total_output_hard_cap_source == "set"
    assert limits.resource_snapshot is None


def test_resume_reuses_saved_limits_without_reprobing_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = ExecutionLimits(
        batch_size=120,
        batch_size_source="set",
        part_row_limit=4000,
        part_row_limit_source="set",
        total_output_hard_cap=80_000,
        total_output_hard_cap_source="set",
    )

    def unexpected_probe(*args: object, **kwargs: object) -> ExecutionLimits:
        raise AssertionError("A resumed run must reuse its manifest values")

    monkeypatch.setattr(
        "h3_route_data_builder.eligibility.limits.recommend_execution_limits",
        unexpected_probe,
    )

    resumed = resolve_execution_limits(".", saved_limits=saved)

    assert resumed == saved
    assert ExecutionLimits.from_manifest(resumed.to_manifest()) == saved


@pytest.mark.parametrize("value", [0, -1, True])
def test_non_positive_or_boolean_override_is_rejected(value: int | bool) -> None:
    resources = ResourceSnapshot(
        available_memory_bytes=4 * 1024**3,
        available_disk_bytes=1024**3,
    )

    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        resolve_execution_limits(".", batch_size=value, resources=resources)


def test_resource_probe_failure_does_not_use_silent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_memory_probe() -> int:
        raise OSError("memory query denied")

    monkeypatch.setattr(
        "h3_route_data_builder.eligibility.limits._available_memory_bytes",
        fail_memory_probe,
    )

    with pytest.raises(RuntimeError, match="Could not infer execution limits"):
        recommend_execution_limits(".")
