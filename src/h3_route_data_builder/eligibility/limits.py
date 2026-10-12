"""Hardware-based execution limit recommendations and resolution."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Any

from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

_GIB = 1024**3
_MIB = 1024**2
_ESTIMATED_OUTPUT_BYTES_PER_CELL = 8192
EXECUTION_LIMIT_POLICY_VERSION = "1"


@dataclass(frozen=True)
class ResourceSnapshot:
    """Machine resources used to infer bounded execution limits."""

    available_memory_bytes: int
    available_disk_bytes: int


@dataclass(frozen=True)
class ExecutionLimits:
    """Resolved execution limits and whether each was inferred or explicitly set."""

    batch_size: int
    batch_size_source: str
    part_row_limit: int
    part_row_limit_source: str
    total_output_hard_cap: int
    total_output_hard_cap_source: str
    resource_snapshot: ResourceSnapshot | None = None

    def to_manifest(self) -> dict[str, Any]:
        """Serialize values and provenance for deterministic run resumption."""
        return {
            "policy_version": EXECUTION_LIMIT_POLICY_VERSION,
            "resource_snapshot": (
                {
                    "available_memory_bytes": self.resource_snapshot.available_memory_bytes,
                    "available_disk_bytes": self.resource_snapshot.available_disk_bytes,
                }
                if self.resource_snapshot is not None
                else None
            ),
            "batch_size": {"value": self.batch_size, "source": self.batch_size_source},
            "part_row_limit": {
                "value": self.part_row_limit,
                "source": self.part_row_limit_source,
            },
            "total_output_hard_cap": {
                "value": self.total_output_hard_cap,
                "source": self.total_output_hard_cap_source,
            },
        }

    @classmethod
    def from_manifest(cls, value: dict[str, Any]) -> "ExecutionLimits":
        """Restore previously resolved limits from a run manifest."""
        if value.get("policy_version") != EXECUTION_LIMIT_POLICY_VERSION:
            raise ValueError("Run manifest uses an unsupported execution limit policy")
        try:
            resource_data = value.get("resource_snapshot")
            limits = cls(
                batch_size=int(value["batch_size"]["value"]),
                batch_size_source=str(value["batch_size"]["source"]),
                part_row_limit=int(value["part_row_limit"]["value"]),
                part_row_limit_source=str(value["part_row_limit"]["source"]),
                total_output_hard_cap=int(value["total_output_hard_cap"]["value"]),
                total_output_hard_cap_source=str(
                    value["total_output_hard_cap"]["source"]
                ),
                resource_snapshot=(
                    ResourceSnapshot(
                        available_memory_bytes=int(
                            resource_data["available_memory_bytes"]
                        ),
                        available_disk_bytes=int(resource_data["available_disk_bytes"]),
                    )
                    if resource_data is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Run manifest has invalid execution limit settings"
            ) from exc
        if (
            min(
                limits.batch_size,
                limits.part_row_limit,
                limits.total_output_hard_cap,
            )
            <= 0
        ):
            raise ValueError("Run manifest execution limits must be positive")
        return limits


def recommend_execution_limits(
    output_directory: str | os.PathLike[str] | None = None,
    resources: ResourceSnapshot | None = None,
    candidate_count: int | None = None,
) -> ExecutionLimits:
    """Recommend serial batch, staged-part, and output-cap limits for this machine.

    Args:
        output_directory: Output location used to inspect its volume capacity.
        resources: Optional resource snapshot, primarily for deterministic tests.
        candidate_count: Optional H3 candidate count used to avoid oversized batches.

    Returns:
        Positive limits tagged with source ``inferred``.
    """
    resource_snapshot = resources or system_resource_snapshot(output_directory)
    memory_gib = max(1, resource_snapshot.available_memory_bytes // _GIB)
    batch_size = min(2000, max(100, memory_gib * 100))
    if candidate_count is not None:
        if isinstance(candidate_count, bool) or candidate_count < 0:
            raise ValueError("candidate_count must be non-negative")
        batch_size = min(batch_size, max(1, candidate_count))
    part_row_limit = min(
        50_000,
        max(500, (resource_snapshot.available_memory_bytes // (128 * _MIB)) * 1000),
    )
    disk_row_limit = (
        resource_snapshot.available_disk_bytes // 2 // _ESTIMATED_OUTPUT_BYTES_PER_CELL
    )
    total_output_hard_cap = min(5_000_000, max(1, disk_row_limit))
    return ExecutionLimits(
        batch_size=batch_size,
        batch_size_source="inferred",
        part_row_limit=part_row_limit,
        part_row_limit_source="inferred",
        total_output_hard_cap=total_output_hard_cap,
        total_output_hard_cap_source="inferred",
        resource_snapshot=resource_snapshot,
    )


def resolve_execution_limits(
    output_directory: str | os.PathLike[str],
    batch_size: int | None = None,
    part_row_limit: int | None = None,
    total_output_hard_cap: int | None = None,
    saved_limits: ExecutionLimits | None = None,
    resources: ResourceSnapshot | None = None,
    candidate_count: int | None = None,
) -> ExecutionLimits:
    """Resolve explicit overrides, saved resume values, and inferred defaults.

    Args:
        output_directory: Output location used to inspect its volume capacity.
        batch_size: Optional explicit input batch-size override.
        part_row_limit: Optional explicit staged-part row-limit override.
        total_output_hard_cap: Optional explicit solvable-cell cap override.
        saved_limits: Previously resolved values for resuming an existing run.
        resources: Optional resource snapshot for deterministic testing.
        candidate_count: Optional H3 candidate count used to bound inferred batches.

    Returns:
        Positive values with source tags of ``set`` or ``inferred``.

    Raises:
        ValueError: If any explicit or saved limit is not positive.
    """
    needs_recommendation = any(
        explicit is None and saved is None
        for explicit, saved in (
            (batch_size, saved_limits.batch_size if saved_limits else None),
            (part_row_limit, saved_limits.part_row_limit if saved_limits else None),
            (
                total_output_hard_cap,
                saved_limits.total_output_hard_cap if saved_limits else None,
            ),
        )
    )
    inferred = (
        recommend_execution_limits(output_directory, resources, candidate_count)
        if needs_recommendation
        else None
    )
    return ExecutionLimits(
        batch_size=_resolve_one(
            batch_size,
            saved_limits.batch_size if saved_limits else None,
            inferred.batch_size if inferred else 1,
            "batch_size",
        ),
        batch_size_source=_limit_source(
            batch_size,
            saved_limits.batch_size_source if saved_limits else None,
        ),
        part_row_limit=_resolve_one(
            part_row_limit,
            saved_limits.part_row_limit if saved_limits else None,
            inferred.part_row_limit if inferred else 1,
            "part_row_limit",
        ),
        part_row_limit_source=_limit_source(
            part_row_limit,
            saved_limits.part_row_limit_source if saved_limits else None,
        ),
        total_output_hard_cap=_resolve_one(
            total_output_hard_cap,
            saved_limits.total_output_hard_cap if saved_limits else None,
            inferred.total_output_hard_cap if inferred else 1,
            "total_output_hard_cap",
        ),
        total_output_hard_cap_source=_limit_source(
            total_output_hard_cap,
            saved_limits.total_output_hard_cap_source if saved_limits else None,
        ),
        resource_snapshot=(
            inferred.resource_snapshot
            if inferred is not None
            else saved_limits.resource_snapshot if saved_limits is not None else None
        ),
    )


def system_resource_snapshot(
    output_directory: str | os.PathLike[str] | None = None,
) -> ResourceSnapshot:
    """Read available physical memory and free bytes on the output volume."""
    try:
        output_path = (
            Path(output_directory) if output_directory is not None else Path.cwd()
        )
        while not output_path.exists() and output_path != output_path.parent:
            output_path = output_path.parent
        if output_path.is_file():
            output_path = output_path.parent
        disk_usage = shutil.disk_usage(output_path)
        available_memory = _available_memory_bytes()
    except (OSError, ValueError) as exc:
        message = f"Could not infer execution limits from local resources: {exc}"
        logger.error(message)
        raise RuntimeError(message) from exc
    return ResourceSnapshot(
        available_memory_bytes=available_memory,
        available_disk_bytes=disk_usage.free,
    )


def _available_memory_bytes() -> int:
    """Return currently available physical memory without a third-party package."""
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        memory_status = MemoryStatus()
        memory_status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
            raise OSError("Windows could not report available physical memory")
        return int(memory_status.ullAvailPhys)

    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
    return page_size * available_pages


def _resolve_one(
    explicit_value: int | None,
    saved_value: int | None,
    inferred_value: int,
    name: str,
) -> int:
    value = explicit_value if explicit_value is not None else saved_value
    if value is None:
        value = inferred_value
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _limit_source(explicit_value: int | None, saved_source: str | None) -> str:
    if explicit_value is not None:
        return "set"
    return saved_source or "inferred"
