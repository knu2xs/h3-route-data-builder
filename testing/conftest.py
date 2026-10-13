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
        pytest.skip(
            "ArcPy cannot resolve the configured real network dataset: "
            f"{network_path}"
        )
    return network_path
