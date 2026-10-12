# -*- coding: utf-8 -*-
__version__ = "0.0.0"
__author__ = "Joel McCune"

__license__ = "Apache 2.0"


import importlib.util
from pathlib import Path
import sys
from typing import Any

import arcpy
import json


def find_pkg_source(package_name) -> Path:
    """Helper to find relative package name"""
    # get the path to the current directory
    file_dir = Path(__file__).parent

    # try to find the package in progressively higher levels
    for idx in range(4):
        tmp_pth = file_dir / "src" / package_name
        if tmp_pth.exists():
            return tmp_pth.parent
        else:
            file_dir = file_dir.parent

    # if nothing fund, nothing returned
    return None


# account for using relative path to package
if importlib.util.find_spec("h3_route_data_builder") is None:
    src_dir = find_pkg_source("h3_route_data_builder")
    if src_dir is not None:
        sys.path.append(str(src_dir))

# include custom code
import h3_route_data_builder
from h3_route_data_builder.utils import get_logger
from h3_route_data_builder.config import ConfigNode, config
from h3_route_data_builder.eligibility.limits import recommend_execution_limits
from h3_route_data_builder.network.workflow import run_geometry_eligibility

logger = None


def _initialize_toolbox_logger() -> Any:
    """Return the single ArcPy logger shared by the toolbox and its tools."""
    global logger
    logger = get_logger(
        "h3_route_data_builder",
        level="INFO",
        propagate=False,
        add_arcpy_handler=True,
    )
    return logger


class Toolbox:
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.logger = _initialize_toolbox_logger()
        self.label = "h3-route-data-builder"
        self.alias = "h3_route_data_builder"

        # List of tool classes associated with this toolbox
        self.tools = [
            GeometryEligibilityTool,
        ]


class GeometryEligibilityTool:
    """Build auditable H3 cells supported by eligible network edges without solving OD pairs."""

    def __init__(self) -> None:
        self.label = "Build H3 Geometry Eligibility"
        self.description = (
            "Validates a polygon AOI, identifies H3 cells intersecting traversable network edges, "
            "and writes auditable eligibility GeoParquet in WGS 84 / EPSG:4326. Representative "
            "and snap distances are geodesic meters. This tool does not generate OD candidates "
            "or solve routes. Optional execution limits are inferred from local resources unless "
            "overridden."
        )
        self.category = "H3 Route Data Builder"
        self.logger = _initialize_toolbox_logger()
        self._inferred_limit_defaults: dict[str, int] = {}
        self._explicit_limit_names: set[str] = set()

    def getParameterInfo(self) -> list[arcpy.Parameter]:
        """Define AOI, network, and bounded-run parameters."""
        aoi = arcpy.Parameter(
            displayName="Area of Interest",
            name="aoi",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        aoi.filter.list = ["Polygon"]

        network = arcpy.Parameter(
            displayName="Network Dataset",
            name="network_dataset",
            datatype="DENetworkDataset",
            parameterType="Required",
            direction="Input",
        )
        output = arcpy.Parameter(
            displayName="Eligibility Output Folder",
            name="output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        h3_resolution = arcpy.Parameter(
            displayName="H3 Resolution",
            name="h3_resolution",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        h3_resolution.filter.type = "Range"
        h3_resolution.filter.list = [0, 15]

        travel_mode = arcpy.Parameter(
            displayName="Travel Mode",
            name="travel_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        travel_mode.filter.type = "ValueList"

        snap_tolerance = arcpy.Parameter(
            displayName="Representative Snap Tolerance (meters)",
            name="snap_tolerance_m",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input",
        )
        snap_tolerance.value = config.get("spatial").get(
            "representative_snap_tolerance_m"
        )
        batch_size = arcpy.Parameter(
            displayName="Input Batch Size",
            name="batch_size",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        part_limit = arcpy.Parameter(
            displayName="Staged Part Row Limit",
            name="part_row_limit",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        output_cap = arcpy.Parameter(
            displayName="Total Solvable Cell Hard Cap",
            name="total_output_hard_cap",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        parameters = [
            aoi,
            network,
            output,
            h3_resolution,
            travel_mode,
            snap_tolerance,
            batch_size,
            part_limit,
            output_cap,
        ]
        self._set_inferred_limit_defaults(parameters, Path.cwd())
        return parameters

    def isLicensed(self) -> bool:
        """Require the Network Analyst extension to be licensed."""
        return arcpy.CheckExtension("Network") in {"Available", "CheckedOut"}

    def updateParameters(self, parameters: list[arcpy.Parameter]) -> None:
        """Populate travel-mode choices from the selected network dataset."""
        network, travel_mode = parameters[1], parameters[4]
        if network.valueAsText and network.altered:
            try:
                modes = arcpy.na.GetTravelModes(network.valueAsText)
                travel_mode.filter.list = sorted(modes)
                default_mode = arcpy.Describe(network.valueAsText).defaultTravelModeName
                if default_mode in modes and not travel_mode.altered:
                    travel_mode.value = default_mode
            except Exception as exc:
                self.logger.warning(f"Could not load network travel modes: {exc}")
        if parameters[2].valueAsText:
            self._set_inferred_limit_defaults(parameters, parameters[2].valueAsText)

    def _set_inferred_limit_defaults(
        self,
        parameters: list[arcpy.Parameter],
        output_directory: str | Path,
    ) -> None:
        """Populate unmodified optional run limits using local resources."""
        recommendations = recommend_execution_limits(output_directory).to_manifest()
        for parameter in parameters:
            recommendation = recommendations.get(parameter.name)
            if recommendation is None:
                continue
            recommended_value = int(recommendation["value"])
            previous_default = self._inferred_limit_defaults.get(parameter.name)
            current_value = (
                int(parameter.value) if parameter.value is not None else None
            )
            if current_value is None:
                parameter.value = recommended_value
                self._explicit_limit_names.discard(parameter.name)
            elif parameter.name in self._explicit_limit_names:
                pass
            elif previous_default is None or current_value == previous_default:
                parameter.value = recommended_value
            else:
                self._explicit_limit_names.add(parameter.name)
            self._inferred_limit_defaults[parameter.name] = recommended_value

    def _limit_override(self, parameter: arcpy.Parameter) -> int | None:
        """Return a set override, or None when the displayed value is inferred."""
        if parameter.value is None:
            return None
        parameter_value = int(parameter.value)
        if parameter.name in self._explicit_limit_names:
            return parameter_value
        if parameter_value == self._inferred_limit_defaults.get(parameter.name):
            return None
        return parameter_value

    def updateMessages(self, parameters: list[arcpy.Parameter]) -> None:
        """Validate input layer shape and configured positive processing values."""
        aoi, network = parameters[0], parameters[1]
        if aoi.valueAsText:
            try:
                aoi_description = arcpy.Describe(aoi.valueAsText)
                if aoi_description.shapeType.casefold() != "polygon":
                    aoi.setErrorMessage("Area of Interest must be polygon geometry.")
                elif (
                    aoi_description.spatialReference is None
                    or aoi_description.spatialReference.name == "Unknown"
                ):
                    aoi.setErrorMessage(
                        "Area of Interest must have a defined coordinate system."
                    )
            except Exception as exc:
                aoi.setErrorMessage(f"Could not inspect AOI: {exc}")
        if network.valueAsText:
            try:
                if arcpy.Describe(network.valueAsText).dataType != "NetworkDataset":
                    network.setErrorMessage("Input must be a Network Dataset.")
            except Exception as exc:
                network.setErrorMessage(f"Could not inspect network dataset: {exc}")
        for parameter_index in (6, 7, 8):
            parameter = parameters[parameter_index]
            if parameter.value is not None and int(parameter.value) <= 0:
                parameter.setErrorMessage("Value must be a positive integer.")
        if parameters[5].value is not None and float(parameters[5].value) < 0:
            parameters[5].setErrorMessage("Snap tolerance must be non-negative.")

    def execute(self, parameters: list[arcpy.Parameter], messages: Any) -> None:
        """Validate, run the eligibility workflow, and report the result location."""
        (
            aoi,
            network,
            output,
            h3_resolution,
            travel_mode,
            snap_tolerance,
            batch_size,
            part_limit,
            output_cap,
        ) = parameters
        network_path = network.valueAsText
        travel_modes = arcpy.na.GetTravelModes(network_path)
        if travel_mode.valueAsText not in travel_modes:
            raise ValueError(
                f"Travel mode '{travel_mode.valueAsText}' is unavailable in the network"
            )

        resolved_config = config.to_dict()
        resolved_config["spatial"].update(
            {
                "h3_resolution": int(h3_resolution.value),
                "intersection_policy": "inclusive",
                "representative_snap_tolerance_m": float(snap_tolerance.value),
            }
        )
        resolved_config["network"].update(
            {
                "travel_mode": travel_mode.valueAsText,
                "restrictions": json.loads(str(travel_modes[travel_mode.valueAsText]))[
                    "restrictionAttributeNames"
                ],
            }
        )
        summary = run_geometry_eligibility(
            aoi.valueAsText,
            network_path,
            output.valueAsText,
            ConfigNode(resolved_config),
            batch_size=self._limit_override(batch_size),
            part_row_limit=self._limit_override(part_limit),
            total_output_hard_cap=self._limit_override(output_cap),
        )
        self.logger.info(
            "Eligibility run %s completed with %s solvable cells; output: %s",
            summary.run_id,
            summary.solvable_cell_count,
            summary.run_directory,
        )
