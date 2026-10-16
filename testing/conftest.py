"""
Pytest configuration file for h3-route-data-builder tests.

It is used to set up fixtures and configurations for running tests,
especially when tests are spread acrsoss multiple files.
"""

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Generator

import pytest
from h3.api import basic_int as h3
from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
)
from h3_route_data_builder.eligibility.output import (
    GeometryWkb,
    eligibility_results_to_table,
)
from h3_route_data_builder.eligibility.staging import write_staged_part
from h3_route_data_builder.od.ledger import WorkItem, WorkState

H3_TEST_RESOLUTION = 9
"""H3 resolution used by the synthetic completed eligibility run fixtures."""

REVIEW_PARTITION_KEYS = ("partition-000000", "partition-000001")
"""Partition keys written by the synthetic completed eligibility run fixtures."""

GeometryWkbFactory = Callable[[int], GeometryWkb]


@pytest.fixture
def integer_h3_cells() -> tuple[int, ...]:
    """Return portable cells, pentagons, and maximum valid cells at every resolution."""
    cells: list[int] = []
    for resolution in range(16):
        greatest_cell = max(h3.get_res0_cells())
        for _ in range(resolution):
            greatest_cell = max(h3.cell_to_children(greatest_cell))
        cells.extend(
            (
                h3.latlng_to_cell(0.0, 0.0, resolution),
                h3.latlng_to_cell(0.0, 0.01, resolution),
                h3.get_pentagons(resolution)[0],
                greatest_cell,
            )
        )
    return tuple(cells)


@pytest.fixture
def integer_work_item() -> WorkItem:
    """Return a portable integer-keyed assignment source without opening a ledger."""
    origin, destination = sorted(h3.grid_disk(h3.latlng_to_cell(0, 0, 9), 1))[:2]
    return WorkItem(
        work_id="integer-work",
        compatibility_fingerprint="integer-fixture",
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


@pytest.fixture
def integer_od_keys(integer_work_item: WorkItem) -> tuple[tuple[int, int], ...]:
    """Return exact directed reverse and self pairs for portable conformance tests."""
    origin, destination = integer_work_item.expected_logical_od_keys[0]
    return ((origin, destination), (destination, origin), (origin, origin))


@pytest.fixture
def invalid_h3_values() -> tuple[object, ...]:
    """Return malformed types, invalid cells, and out-of-domain identity values."""
    return ("8928308280fffff", "617700169958293503", True, 1.0, None, -1, 0, 2**64 - 1, 2**64)


@pytest.fixture(scope="function")
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for testing purposes. When the test is done, the directory and its contents are deleted."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture(scope="function")
def temp_gdb(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary file geodatabase for testing purposes. When the test is done, the geodatabase and its contents are deleted."""
    import arcpy

    gdb_pth: str = arcpy.management.CreateFileGDB(str(temp_dir), "test.gdb")[0]
    yield Path(gdb_pth)
    # do a little cleanup so the temporary directory can be removed by temp_dir fixture
    if arcpy.Exists(gdb_pth):
        arcpy.management.Delete(gdb_pth)


@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Set up any necessary environment variables or configurations before tests run."""
    # Example: Set an environment variable
    import os

    os.environ["TEST_ENV"] = "true"
    yield
    # Teardown code can go here if needed
    del os.environ["TEST_ENV"]


@pytest.fixture(scope="session")
def arcpy_module():
    """Return ArcPy when available or skip ArcPy-dependent tests."""
    return pytest.importorskip("arcpy")


@pytest.fixture(scope="session")
def real_network_dataset(arcpy_module):
    """Return the Feature 001 StreetMap network or an explicit local override."""
    network_path = os.environ.get(
        "H3_RDB_TEST_NETWORK",
        r"D:\data\ba_data\usa_2025\Data\StreetMap Premium Data"
        r"\northamerica.geodatabase\main.Routing\main.Routing_ND",
    )
    if not arcpy_module.Exists(network_path):
        pytest.skip("ArcPy cannot resolve the configured real network dataset: " f"{network_path}")
    return network_path


def _placeholder_geometry_wkb(cell_id: int) -> GeometryWkb:
    """Return opaque geometry bytes; the ArcPy-free reader never parses geometry."""
    return (f"cell-wkb-{cell_id}".encode(), f"centroid-wkb-{cell_id}".encode(), None)


def _review_run_cells() -> list[int]:
    """Return a small sorted set of valid integer cells at the fixture resolution."""
    return sorted(h3.grid_disk(h3.latlng_to_cell(0.0, 0.0, H3_TEST_RESOLUTION), 1))


@pytest.fixture
def make_completed_eligibility_run(temp_dir: Path) -> Callable[..., Path]:
    """Return a factory that builds a completed eligibility run directory without ArcPy.

    The run has two partitions with disjoint ascending ``h3_id`` ranges. Each partition's
    part is written in descending ``h3_id`` order so readers must sort per partition.
    """
    created_count = 0

    def _make(geometry_wkb_factory: GeometryWkbFactory | None = None) -> Path:
        nonlocal created_count
        factory = geometry_wkb_factory or _placeholder_geometry_wkb
        run_directory = temp_dir / f"completed-run-{created_count}"
        created_count += 1
        cells = _review_run_cells()
        split_index = len(cells) // 2 + 1
        partition_cells = (cells[:split_index], cells[split_index:])

        parts: list[dict[str, Any]] = []
        partition_summaries: dict[str, dict[str, int]] = {}
        for partition_key, cell_ids in zip(REVIEW_PARTITION_KEYS, partition_cells):
            results = [
                CellEligibilityResult(
                    h3_id=cell_id,
                    resolution=H3_TEST_RESOLUTION,
                    eligibility_status=(
                        EligibilityStatus.SOLVABLE
                        if index % 2 == 0
                        else EligibilityStatus.INELIGIBLE
                    ),
                    eligibility_reason="fixture",
                    intersecting_edge_count=0,
                    build_fingerprint="fixture-fingerprint",
                )
                for index, cell_id in enumerate(sorted(cell_ids, reverse=True))
            ]
            table = eligibility_results_to_table(
                results, {cell_id: factory(cell_id) for cell_id in cell_ids}
            )
            part_key = f"{partition_key}-000000"
            staged = write_staged_part(
                table,
                run_directory / "parts" / partition_key / f"{part_key}.parquet",
                part_key,
                row_limit=len(results),
            )
            parts.append(
                {
                    "partition_key": partition_key,
                    "part_key": staged.part_key,
                    "path": staged.path.relative_to(run_directory).as_posix(),
                    "row_count": staged.row_count,
                    "checksum": staged.checksum,
                }
            )
            partition_summaries[partition_key] = {
                "cell_result_count": len(results),
                "solvable_cell_count": sum(
                    result.eligibility_status == EligibilityStatus.SOLVABLE for result in results
                ),
            }

        manifest = {
            "run_id": "fixture-run",
            "run_directory": str(temp_dir / "unrelated" / "original-location"),
            "policy": {"h3_resolution": H3_TEST_RESOLUTION},
            "expected_partition_keys": list(REVIEW_PARTITION_KEYS),
            "parts": parts,
            "partition_summaries": partition_summaries,
            "cell_result_count": sum(
                summary["cell_result_count"] for summary in partition_summaries.values()
            ),
            "solvable_cell_count": sum(
                summary["solvable_cell_count"] for summary in partition_summaries.values()
            ),
            "run_status": "complete",
        }
        (run_directory / "run-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return run_directory

    return _make


@pytest.fixture
def completed_eligibility_run(
    make_completed_eligibility_run: Callable[..., Path],
) -> Path:
    """Return a completed eligibility run directory with placeholder geometry bytes."""
    return make_completed_eligibility_run()


@pytest.fixture
def manifest_rewriter() -> Callable[..., None]:
    """Return a callable that applies top-level key changes to a run manifest."""

    def _rewrite(run_directory: Path, **changes: object) -> None:
        manifest_path = Path(run_directory) / "run-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(changes)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return _rewrite


@pytest.fixture
def arcpy_completed_eligibility_run(
    arcpy_module: Any, make_completed_eligibility_run: Callable[..., Path]
) -> Path:
    """Return a completed eligibility run whose geometry is real WGS 84 WKB built by ArcPy."""
    from h3_route_data_builder.eligibility.cells import h3_cell_boundary
    from h3_route_data_builder.network.geometry import WGS84_CRS_NAME

    spatial_reference = arcpy_module.SpatialReference(WGS84_CRS_NAME)

    def _arcpy_geometry_wkb(cell_id: int) -> GeometryWkb:
        boundary = h3_cell_boundary(cell_id)
        ring = [*boundary, boundary[0]]
        polygon = arcpy_module.Polygon(
            arcpy_module.Array([arcpy_module.Point(lon, lat) for lon, lat in ring]),
            spatial_reference,
        )
        centroid = arcpy_module.PointGeometry(
            arcpy_module.Point(*h3.cell_to_latlng(cell_id)[::-1]), spatial_reference
        )
        return (bytes(polygon.WKB), bytes(centroid.WKB), None)

    return make_completed_eligibility_run(_arcpy_geometry_wkb)
