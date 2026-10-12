"""
This is a stubbed out test file designed to be used with PyTest, but can
easily be modified to support any testing framework.
"""

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest
from h3_route_data_builder.utils._logging import ArcpyHandler

# get paths to useful resources - notably where the src directory is
self_pth = Path(__file__)
dir_test = self_pth.parent
dir_prj = dir_test.parent
dir_src = dir_prj / "src"

# insert the src directory into the path and import the projct package
sys.path.insert(0, str(dir_src))
import h3_route_data_builder


def test_example():
    assert 2 + 2 == 4


def test_geometry_toolbox_exposes_expected_parameters(
    arcpy_module: Any,
) -> None:
    toolbox_path = dir_prj / "arcgis" / "h3_route_data_builder.pyt"
    loader = importlib.machinery.SourceFileLoader(
        "h3_rdb_toolbox_test", str(toolbox_path)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    toolbox = module.Toolbox()
    tool = module.GeometryEligibilityTool()
    assert tool.logger is toolbox.logger
    assert (
        sum(isinstance(handler, ArcpyHandler) for handler in toolbox.logger.handlers)
        == 1
    )
    toolbox.logger.addHandler(ArcpyHandler())
    module.Toolbox()
    assert (
        sum(isinstance(handler, ArcpyHandler) for handler in toolbox.logger.handlers)
        == 1
    )
    parameters = tool.getParameterInfo()
    parameter_names = [parameter.name for parameter in parameters]
    parameters_by_name = {parameter.name: parameter for parameter in parameters}

    assert parameter_names == [
        "aoi",
        "network_dataset",
        "output_folder",
        "h3_resolution",
        "travel_mode",
        "snap_tolerance_m",
        "batch_size",
        "part_row_limit",
        "total_output_hard_cap",
    ]
    for name in ("batch_size", "part_row_limit", "total_output_hard_cap"):
        parameter = parameters_by_name[name]
        assert parameter.parameterType == "Optional"
        assert int(parameter.value) > 0
        assert tool._limit_override(parameter) is None
    assert parameters_by_name["snap_tolerance_m"].value == 100.0
    assert parameters_by_name["snap_tolerance_m"].value == module.config.get(
        "spatial"
    ).get("representative_snap_tolerance_m")

    metadata = arcpy_module.metadata.Metadata(
        f"{toolbox_path}\\GeometryEligibilityTool"
    )
    assert metadata.summary
    assert metadata.description
    for parameter in parameters:
        assert parameter.name in metadata.description
    assert "policy version 1" in metadata.description
    assert "inferred or set" in metadata.description
    assert "restore the saved values from the manifest" in metadata.description
    assert "fails the run incomplete" in metadata.description

    batch_parameter = parameters_by_name["batch_size"]
    batch_parameter.value = int(batch_parameter.value) + 1
    tool._set_inferred_limit_defaults(parameters, dir_prj)
    assert tool._limit_override(batch_parameter) == int(batch_parameter.value)
