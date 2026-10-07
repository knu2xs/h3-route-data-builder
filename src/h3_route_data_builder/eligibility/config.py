"""Validated configuration for one H3 eligibility run."""

from dataclasses import dataclass
from typing import Any

from h3_route_data_builder.config import ConfigNode
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


@dataclass(frozen=True)
class EligibilityConfig:
    """Required spatial, network, and execution settings for eligibility."""

    working_crs: str
    storage_crs: str
    datum_transformation: str | None
    h3_resolution: int
    intersection_policy: str
    representative_snap_tolerance_m: float
    travel_mode: str
    restrictions: tuple[str, ...]
    representative_policy: str
    batch_size: int
    part_row_limit: int
    total_output_hard_cap: int


def eligibility_config_from_node(config: ConfigNode) -> EligibilityConfig:
    """Validate and extract required eligibility settings from project configuration.

    Args:
        config: Resolved project configuration node.

    Returns:
        Validated configuration required to start an eligibility run.

    Raises:
        ValueError: If a required value is missing, malformed, or outside its valid range.
    """
    spatial: Any = config.get("spatial")
    network: Any = config.get("network")
    eligibility: Any = config.get("eligibility")
    if spatial is None or network is None or eligibility is None:
        logger.error(
            "Missing required spatial, network, or eligibility configuration sections"
        )
        raise ValueError(
            "spatial, network, and eligibility configuration sections are required"
        )

    working_crs = _required_nonempty_string(
        spatial.get("working_crs"), "spatial.working_crs"
    )
    storage_crs = _required_nonempty_string(
        spatial.get("storage_crs"), "spatial.storage_crs"
    )
    datum_transformation_value = spatial.get("datum_transformation")
    if datum_transformation_value is not None and (
        not isinstance(datum_transformation_value, str)
        or not datum_transformation_value.strip()
    ):
        raise ValueError(
            "spatial.datum_transformation must be null or a non-empty string"
        )
    h3_resolution = _required_integer(
        spatial.get("h3_resolution"), "spatial.h3_resolution"
    )
    if not 0 <= h3_resolution <= 15:
        raise ValueError("spatial.h3_resolution must be between 0 and 15")

    intersection_policy = _required_nonempty_string(
        spatial.get("intersection_policy"), "spatial.intersection_policy"
    )
    if intersection_policy != "inclusive":
        raise ValueError("spatial.intersection_policy must be 'inclusive'")

    snap_tolerance = _required_number(
        spatial.get("representative_snap_tolerance_m"),
        "spatial.representative_snap_tolerance_m",
    )
    if snap_tolerance < 0:
        raise ValueError("spatial.representative_snap_tolerance_m must be non-negative")

    travel_mode = _required_nonempty_string(
        network.get("travel_mode"), "network.travel_mode"
    )
    restrictions_value = network.get("restrictions")
    if not isinstance(restrictions_value, list) or any(
        not isinstance(value, str) or not value for value in restrictions_value
    ):
        raise ValueError("network.restrictions must be a list of non-empty strings")

    representative_policy = _required_nonempty_string(
        eligibility.get("representative_policy"), "eligibility.representative_policy"
    )
    if representative_policy != "nearest_centroid_then_source_id_oid_measure":
        raise ValueError("Unsupported eligibility.representative_policy")

    batch_size = _positive_integer(
        eligibility.get("batch_size"), "eligibility.batch_size"
    )
    part_row_limit = _positive_integer(
        eligibility.get("part_row_limit"), "eligibility.part_row_limit"
    )
    total_output_hard_cap = _positive_integer(
        eligibility.get("total_output_hard_cap"), "eligibility.total_output_hard_cap"
    )

    validated_config = EligibilityConfig(
        working_crs=working_crs,
        storage_crs=storage_crs,
        datum_transformation=(
            datum_transformation_value.strip() if datum_transformation_value else None
        ),
        h3_resolution=h3_resolution,
        intersection_policy=intersection_policy,
        representative_snap_tolerance_m=snap_tolerance,
        travel_mode=travel_mode,
        restrictions=tuple(sorted(set(restrictions_value))),
        representative_policy=representative_policy,
        batch_size=batch_size,
        part_row_limit=part_row_limit,
        total_output_hard_cap=total_output_hard_cap,
    )
    logger.info(
        "Validated eligibility configuration for %s at H3 resolution %s",
        validated_config.travel_mode,
        validated_config.h3_resolution,
    )
    return validated_config


def _required_nonempty_string(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _required_integer(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _positive_integer(value: Any, key: str) -> int:
    integer_value = _required_integer(value, key)
    if integer_value <= 0:
        raise ValueError(f"{key} must be positive")
    return integer_value


def _required_number(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)
