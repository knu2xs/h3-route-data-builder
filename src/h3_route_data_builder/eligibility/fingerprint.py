"""Deterministic fingerprints for eligibility run inputs and policies."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


_REQUIRED_SOFTWARE_VERSIONS = {"python", "arcgis_pro", "h3", "package"}
ELIGIBILITY_SCHEMA_VERSION = "2"


def build_input_fingerprint(
    aoi_fingerprint: str,
    network_fingerprint: str,
    travel_mode: str,
    restrictions: Sequence[str],
    h3_resolution: int,
    eligibility_policy: Mapping[str, Any],
    schema_version: str,
    software_versions: Mapping[str, str],
) -> str:
    """Return a stable SHA-256 fingerprint for eligibility inputs and policy.

    Args:
        aoi_fingerprint: Stable identity for the validated AOI geometry.
        network_fingerprint: Stable identity for the network dataset/build.
        travel_mode: Selected network travel mode.
        restrictions: Restriction names applied to edge eligibility.
        h3_resolution: Canonical H3 resolution for the run.
        eligibility_policy: JSON-compatible intersection and representative policy values.
        schema_version: Eligibility result/staging schema version.
        software_versions: Versions for Python, ArcGIS Pro, H3, and this package.

    Returns:
        Lowercase hexadecimal SHA-256 digest.

    Raises:
        ValueError: If a required identity or version is empty or invalid.
        TypeError: If policy values cannot be encoded as canonical JSON.
    """
    required_values = {
        "aoi_fingerprint": aoi_fingerprint,
        "network_fingerprint": network_fingerprint,
        "travel_mode": travel_mode,
        "schema_version": schema_version,
    }
    missing_values = [name for name, value in required_values.items() if not value]
    if missing_values:
        raise ValueError(f"Required fingerprint values are empty: {', '.join(missing_values)}")
    if h3_resolution < 0:
        raise ValueError("h3_resolution must be non-negative")
    missing_versions = sorted(_REQUIRED_SOFTWARE_VERSIONS - software_versions.keys())
    if missing_versions:
        raise ValueError(f"Missing software versions: {', '.join(missing_versions)}")
    if any(not software_versions[name] for name in _REQUIRED_SOFTWARE_VERSIONS):
        raise ValueError("Required software versions must be non-empty")

    payload = {
        "identity_encoding_version": 2,
        "aoi_fingerprint": aoi_fingerprint,
        "network_fingerprint": network_fingerprint,
        "travel_mode": travel_mode,
        "restrictions": sorted(set(restrictions)),
        "h3_resolution": h3_resolution,
        "eligibility_policy": eligibility_policy,
        "schema_version": schema_version,
        "software_versions": software_versions,
    }
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    fingerprint = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    logger.debug("Built eligibility fingerprint %s", fingerprint)
    return fingerprint
