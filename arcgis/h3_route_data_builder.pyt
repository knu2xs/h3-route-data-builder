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
from h3_route_data_builder.network.workflow import run_geometry_eligibility

# initialize logger for the toolbox
logger = get_logger("h3_route_data_builder", level="INFO", add_arcpy_handler=True)

class Toolbox:
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "h3-route-data-builder"
        self.alias = "h3_route_data_builder"

        # List of tool classes associated with this toolbox
        self.tools = [
            GeometryEligibilityTool,
        ]


class GeometryEligibilityTool:
    """Create an auditable H3 eligibility dataset without generating OD pairs."""

    def __init__(self) -> None:
        self.label = "Build H3 Geometry Eligibility"
        self.description = "Validate an AOI and create reconciled H3 cell eligibility results from a network dataset."
        self.category = "H3 Route Data Builder"
        self.logger = get_logger(
            f"h3_route_data_builder.Toolbox.{self.__class__.__name__}",
            level="INFO",
            add_arcpy_handler=False
        )

    def getParameterInfo(self) -> list[arcpy.Parameter]:
        """Define AOI, network, CRS, and bounded-run parameters."""
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
        working_crs = arcpy.Parameter(
            displayName="Working Projected Coordinate System",
            name="working_crs",
            datatype="GPCoordinateSystem",
            parameterType="Required",
            direction="Input",
        )
        storage_crs = arcpy.Parameter(
            displayName="GeoParquet Storage Coordinate System",
            name="storage_crs",
            datatype="GPCoordinateSystem",
            parameterType="Required",
            direction="Input",
        )
        storage_crs.value = arcpy.SpatialReference("GCS_WGS_1984")

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
        batch_size = arcpy.Parameter(
            displayName="Input Batch Size",
            name="batch_size",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        part_limit = arcpy.Parameter(
            displayName="Staged Part Row Limit",
            name="part_row_limit",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        output_cap = arcpy.Parameter(
            displayName="Total Solvable Cell Hard Cap",
            name="total_output_hard_cap",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        datum_transformation = arcpy.Parameter(
            displayName="Datum Transformation",
            name="datum_transformation",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )

        return [
            aoi,
            network,
            output,
            working_crs,
            storage_crs,
            h3_resolution,
            travel_mode,
            snap_tolerance,
            batch_size,
            part_limit,
            output_cap,
            datum_transformation,
        ]

    def isLicensed(self) -> bool:
        """Require the Network Analyst extension to be licensed."""
        return arcpy.CheckExtension("Network") in {"Available", "CheckedOut"}

    def updateParameters(self, parameters: list[arcpy.Parameter]) -> None:
        """Populate travel-mode choices from the selected network dataset."""
        network, travel_mode = parameters[1], parameters[6]
        if network.valueAsText and network.altered:
            try:
                modes = arcpy.na.GetTravelModes(network.valueAsText)
                travel_mode.filter.list = sorted(modes)
                default_mode = arcpy.Describe(network.valueAsText).defaultTravelModeName
                if default_mode in modes and not travel_mode.altered:
                    travel_mode.value = default_mode
            except Exception as exc:
                self.logger.warning(f"Could not load network travel modes: {exc}")

    def updateMessages(self, parameters: list[arcpy.Parameter]) -> None:
        """Validate input layer shape and configured positive processing values."""
        aoi, network = parameters[0], parameters[1]
        if aoi.valueAsText:
            try:
                if arcpy.Describe(aoi.valueAsText).shapeType.casefold() != "polygon":
                    aoi.setErrorMessage("Area of Interest must be polygon geometry.")
            except Exception as exc:
                aoi.setErrorMessage(f"Could not inspect AOI: {exc}")
        if network.valueAsText:
            try:
                if arcpy.Describe(network.valueAsText).dataType != "NetworkDataset":
                    network.setErrorMessage("Input must be a Network Dataset.")
            except Exception as exc:
                network.setErrorMessage(f"Could not inspect network dataset: {exc}")
        for parameter_index in (8, 9, 10):
            parameter = parameters[parameter_index]
            if parameter.value is not None and int(parameter.value) <= 0:
                parameter.setErrorMessage("Value must be a positive integer.")
        if parameters[7].value is not None and float(parameters[7].value) < 0:
            parameters[7].setErrorMessage("Snap tolerance must be non-negative.")

    def execute(self, parameters: list[arcpy.Parameter], messages: Any) -> None:
        """Validate, run the eligibility workflow, and report the result location."""
        (
            aoi,
            network,
            output,
            working_crs,
            storage_crs,
            h3_resolution,
            travel_mode,
            snap_tolerance,
            batch_size,
            part_limit,
            output_cap,
            datum_transformation,
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
                "working_crs": _spatial_reference_text(working_crs.value),
                "storage_crs": _spatial_reference_text(storage_crs.value),
                "h3_resolution": int(h3_resolution.value),
                "intersection_policy": "inclusive",
                "representative_snap_tolerance_m": float(snap_tolerance.value),
                "datum_transformation": datum_transformation.valueAsText or None,
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
        resolved_config["eligibility"].update(
            {
                "batch_size": int(batch_size.value),
                "part_row_limit": int(part_limit.value),
                "total_output_hard_cap": int(output_cap.value),
            }
        )
        summary = run_geometry_eligibility(
            aoi.valueAsText,
            network_path,
            output.valueAsText,
            ConfigNode(resolved_config),
        )
        self.logger.info(
            "Eligibility run %s completed with %s solvable cells; output: %s",
            summary.run_id,
            summary.solvable_cell_count,
            summary.run_directory,
        )


def _spatial_reference_text(spatial_reference: arcpy.SpatialReference) -> str:
    """Return a canonical spatial-reference WKT string from a toolbox parameter."""
    if spatial_reference is None or spatial_reference.name == "Unknown":
        raise ValueError("A known spatial reference is required")
    return spatial_reference.exportToString()
