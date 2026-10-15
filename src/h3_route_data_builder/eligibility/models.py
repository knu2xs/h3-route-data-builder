"""Portable records and eligibility invariants for H3 cells."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from h3_route_data_builder.utils import get_logger
from h3.api import basic_int as h3
from .cells import canonical_h3_ids

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


class EligibilityStatus(StrEnum):
    """Eligibility state recorded for an H3 cell."""

    SOLVABLE = "solvable"
    INELIGIBLE = "ineligible"


class PartitionStatus(StrEnum):
    """Processing state of one expected input partition."""

    PENDING = "pending"
    PROCESSING = "processing"
    STAGED = "staged"
    RECONCILED = "reconciled"
    FAILED = "failed"


class RunStatus(StrEnum):
    """Completion state of one eligibility run."""

    PROCESSING = "processing"
    FAILED_INCOMPLETE = "failed_incomplete"
    COMPLETE = "complete"


@dataclass(frozen=True)
class NetworkLocation:
    """A representative point and its Network Analyst location fields."""

    x: float
    y: float
    source_id: int
    source_oid: int
    pos_along: float
    side_of_edge: int
    snap_distance_m: float


@dataclass(frozen=True)
class EdgeEvidence:
    """Eligibility decision for one transportation edge."""

    source_id: int
    source_oid: int
    eligibility_status: str
    reason: str
    travel_direction: str | None = None


@dataclass(frozen=True)
class CellEligibilityResult:
    """Auditable eligibility result for one canonical H3 cell."""

    h3_id: int
    resolution: int
    eligibility_status: EligibilityStatus
    eligibility_reason: str
    intersecting_edge_count: int
    representative: NetworkLocation | None = None
    edge_evidence: tuple[EdgeEvidence, ...] = ()
    policy_evidence: dict[str, Any] = field(default_factory=dict)
    build_fingerprint: str = ""
    cell_geometry: Any | None = None
    centroid_geometry: Any | None = None

    def __post_init__(self) -> None:
        """Validate integer identity and its declared resolution."""
        canonical_h3_ids([self.h3_id])
        if type(self.resolution) is not int or self.resolution != h3.get_resolution(self.h3_id):
            message = "Cell resolution does not match H3 cell identity"
            logger.error(message)
            raise ValueError(message)


@dataclass(frozen=True)
class EdgeIntersectionEvidence:
    """One eligible network edge that intersects an H3 cell within the AOI."""

    source_id: int
    source_oid: int
    network_edge_geometry: Any
    in_aoi_intersection_geometry: Any
    allowed_directions: tuple[str, ...] = ()
    eligibility_reason: str = "eligible edge intersects cell within AOI"


@dataclass(frozen=True)
class CellGeometryCandidate:
    """Geometry-stage result awaiting representative/location validation."""

    h3_id: int
    resolution: int
    cell_geometry: Any
    centroid_geometry: Any
    intersecting_edges: tuple[EdgeIntersectionEvidence, ...]
    eligibility_reason: str

    def __post_init__(self) -> None:
        """Validate integer identity and its declared resolution."""
        canonical_h3_ids([self.h3_id])
        if type(self.resolution) is not int or self.resolution != h3.get_resolution(self.h3_id):
            message = "Cell resolution does not match H3 cell identity"
            logger.error(message)
            raise ValueError(message)

    @property
    def has_eligible_intersection(self) -> bool:
        """Whether at least one eligible edge intersects this cell in the AOI."""
        return bool(self.intersecting_edges)


@dataclass
class EligibilityRunState:
    """Persistable lifecycle state for one AOI eligibility evaluation."""

    run_id: str
    expected_partition_keys: tuple[str, ...]
    total_output_hard_cap: int
    partition_status: dict[str, PartitionStatus]
    status: RunStatus = RunStatus.PROCESSING
    unique_solvable_cell_count: int = 0


def validated_solvable_results(
    results: list[CellEligibilityResult],
    snap_tolerance_m: float,
) -> list[CellEligibilityResult]:
    """Return only solvable results with eligible edges and valid network locations.

    Args:
        results: Eligibility results to filter for OD handoff.
        snap_tolerance_m: Maximum accepted representative snap distance in meters.

    Returns:
        Results safe to hand to later OD planning.

    Raises:
        ValueError: If the configured tolerance is negative or a result marked solvable
            violates the edge, location, or snap-distance invariant.
    """
    if snap_tolerance_m < 0:
        logger.error("Invalid negative snap tolerance: %s", snap_tolerance_m)
        raise ValueError("snap_tolerance_m must be non-negative")

    handoff: list[CellEligibilityResult] = []
    for result in results:
        if result.eligibility_status != EligibilityStatus.SOLVABLE:
            continue
        if result.intersecting_edge_count < 1:
            logger.error("Solvable cell %s has no eligible intersecting edge", result.h3_id)
            raise ValueError(f"Solvable cell {result.h3_id} has no eligible intersecting edge")
        if result.representative is None:
            logger.error("Solvable cell %s has no representative", result.h3_id)
            raise ValueError(f"Solvable cell {result.h3_id} has no representative")
        if result.representative.snap_distance_m > snap_tolerance_m:
            logger.error("Solvable cell %s exceeds snap tolerance", result.h3_id)
            raise ValueError(f"Solvable cell {result.h3_id} exceeds snap tolerance")
        handoff.append(result)
    logger.info("Validated %s solvable cell(s) for downstream handoff", len(handoff))
    return handoff
