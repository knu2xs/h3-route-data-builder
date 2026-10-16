"""
This is a stubbed out test file designed to be used with PyTest, but can
easily be modified to support any testing framework.
"""

import importlib.machinery
import importlib.util
import logging
from collections.abc import Iterator
from pathlib import Path
import sys
from types import SimpleNamespace
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


@pytest.fixture(autouse=True)
def restore_package_logger() -> Iterator[None]:
    """Undo toolbox logger changes so later ``caplog`` tests still see package records."""
    package_logger = logging.getLogger("h3_route_data_builder")
    propagate = package_logger.propagate
    handlers = list(package_logger.handlers)
    level = package_logger.level
    yield
    package_logger.propagate = propagate
    package_logger.handlers[:] = handlers
    package_logger.setLevel(level)


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
        "export_review_feature_class",
        "review_feature_class",
    ]
    export_parameter = parameters_by_name["export_review_feature_class"]
    assert export_parameter.datatype in {"GPBoolean", "Boolean"}
    assert export_parameter.value is False
    review_parameter = parameters_by_name["review_feature_class"]
    assert review_parameter.datatype in {"DEFeatureClass", "Feature Class"}
    assert review_parameter.direction == "Output"
    assert review_parameter.parameterType == "Optional"
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


def _load_geometry_toolbox_module(module_name: str) -> Any:
    """Load the Python toolbox as a module so tests can patch its delegated workflow calls."""
    toolbox_path = dir_prj / "arcgis" / "h3_route_data_builder.pyt"
    loader = importlib.machinery.SourceFileLoader(module_name, str(toolbox_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _execute_parameters(export_review: bool, review_feature_class: str | None) -> list[Any]:
    """Return lightweight parameter stand-ins for ``GeometryEligibilityTool.execute``."""
    values = [
        ("aoi", "aoi_layer"),
        ("network_dataset", "network.nd"),
        ("output_folder", "output"),
        ("h3_resolution", 9),
        ("travel_mode", "Driving"),
        ("snap_tolerance_m", 100.0),
        ("batch_size", None),
        ("part_row_limit", None),
        ("total_output_hard_cap", None),
        ("export_review_feature_class", export_review),
        ("review_feature_class", review_feature_class),
    ]
    return [
        SimpleNamespace(name=name, value=value, valueAsText=None if value is None else str(value))
        for name, value in values
    ]


@pytest.fixture
def toolbox_with_recorders(
    arcpy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, list[tuple], list[str]]:
    """Return the toolbox module with the run and review export replaced by recorders."""
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_execute_test")
    export_calls: list[tuple] = []
    call_order: list[str] = []

    def fake_run(*args: Any, **kwargs: Any) -> SimpleNamespace:
        call_order.append("run")
        return SimpleNamespace(
            run_id="run-id", solvable_cell_count=1, run_directory=Path("run-directory")
        )

    def fake_export(*args: Any) -> int:
        call_order.append("export")
        export_calls.append(args)
        return 7

    monkeypatch.setattr(
        module.arcpy.na,
        "GetTravelModes",
        lambda _: {"Driving": '{"restrictionAttributeNames": []}'},
    )
    monkeypatch.setattr(module, "run_geometry_eligibility", fake_run)
    monkeypatch.setattr(module, "export_eligibility_review_feature_class", fake_export)
    return module, export_calls, call_order


def test_review_feature_class_parameter_disabled_by_default(arcpy_module: Any) -> None:
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_default_test")
    tool = module.GeometryEligibilityTool()
    parameters = tool.getParameterInfo()

    tool.updateParameters(parameters)

    assert parameters[9].value is False
    assert parameters[10].enabled is False


def test_review_feature_class_parameter_enabled_when_checkbox_checked(
    arcpy_module: Any,
) -> None:
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_enabled_test")
    tool = module.GeometryEligibilityTool()
    parameters = tool.getParameterInfo()
    parameters[9].value = True

    tool.updateParameters(parameters)

    assert parameters[10].enabled is True


def test_execute_unchecked_does_not_call_review_export(
    toolbox_with_recorders: tuple[Any, list[tuple], list[str]],
) -> None:
    module, export_calls, _ = toolbox_with_recorders

    module.GeometryEligibilityTool().execute(_execute_parameters(False, None), None)

    assert export_calls == []


def test_execute_checked_calls_review_export_after_run_with_summary_run_directory(
    toolbox_with_recorders: tuple[Any, list[tuple], list[str]],
) -> None:
    module, export_calls, call_order = toolbox_with_recorders

    module.GeometryEligibilityTool().execute(_execute_parameters(True, "review.gdb\\hexes"), None)

    assert export_calls == [(Path("run-directory"), "review.gdb\\hexes")]
    assert call_order == ["run", "export"]


def test_execute_does_not_export_when_run_raises(
    toolbox_with_recorders: tuple[Any, list[tuple], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, export_calls, _ = toolbox_with_recorders

    def failing_run(*args: Any, **kwargs: Any) -> None:
        raise ValueError("run incomplete")

    monkeypatch.setattr(module, "run_geometry_eligibility", failing_run)

    with pytest.raises(ValueError, match="run incomplete"):
        module.GeometryEligibilityTool().execute(
            _execute_parameters(True, "review.gdb\\hexes"), None
        )
    assert export_calls == []


def _validated_review_parameters(
    module: Any, export_review: bool, review_feature_class: str | None
) -> list[Any]:
    tool = module.GeometryEligibilityTool()
    parameters = tool.getParameterInfo()
    parameters[9].value = export_review
    parameters[10].value = review_feature_class
    tool.updateParameters(parameters)
    tool.updateMessages(parameters)
    return parameters


def test_validation_requires_review_feature_class_when_checked(
    arcpy_module: Any,
) -> None:
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_required_test")

    parameters = _validated_review_parameters(module, True, None)

    assert parameters[10].hasError()
    assert "required" in parameters[10].message


def test_validation_rejects_non_geodatabase_review_output(
    arcpy_module: Any, temp_dir: Path
) -> None:
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_workspace_test")

    parameters = _validated_review_parameters(module, True, str(temp_dir / "hexes.shp"))

    assert parameters[10].hasError()
    assert "geodatabase" in parameters[10].message


def test_validation_rejects_existing_review_output_without_overwrite(
    arcpy_module: Any, temp_gdb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_exists_test")
    arcpy_module.management.CreateFeatureclass(
        out_path=str(temp_gdb), out_name="hexes", geometry_type="POLYGON"
    )
    monkeypatch.setattr(arcpy_module.env, "overwriteOutput", False)

    parameters = _validated_review_parameters(module, True, str(temp_gdb / "hexes"))

    assert parameters[10].hasError()
    assert "already exists" in parameters[10].message


def test_validation_ignores_empty_review_output_when_unchecked(
    arcpy_module: Any,
) -> None:
    module = _load_geometry_toolbox_module("h3_rdb_toolbox_unchecked_test")

    parameters = _validated_review_parameters(module, False, None)

    assert not parameters[10].hasError()
