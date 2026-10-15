"""
Pytest configuration file for h3-route-data-builder tests.

It is used to set up fixtures and configurations for running tests,
especially when tests are spread acrsoss multiple files.
"""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from h3.api import basic_int as h3
from h3_route_data_builder.od.ledger import WorkItem, WorkState


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
