"""Typed records for directed OD candidate planning and ledger handoff."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


class CandidateMode(StrEnum):
    """Supported origin/destination scopes."""

    AOI_ONLY = "aoi_only"
    AOI_TO_SURROUNDING = "aoi_to_surrounding"


class CandidateDisposition(StrEnum):
    """Planning or actual-solve result for one logical pair."""

    SELF_RESOLVED = "self_resolved"
    PREFILTER_PRUNED = "prefilter_pruned"
    RETAINED = "retained"
    QUALIFYING = "qualifying"
    CUTOFF_EXCLUDED = "cutoff_excluded"


@dataclass(frozen=True)
class SolvableCell:
    """Feature 001 cell reference used by portable candidate logic.

    Args:
        h3_id: Exact integer H3 cell identity.
        resolution: Cell resolution.
        eligibility_status: Feature 001 eligibility outcome.
        representative: Deterministic WGS 84 representative as (longitude, latitude).
        cell_geometry: Optional ArcPy geometry, only consumed by network geometry functions.
    """

    h3_id: int
    resolution: int
    eligibility_status: str
    representative: tuple[float, float] | None
    cell_geometry: Any | None = None


@dataclass(frozen=True)
class CandidateScope:
    """AOI-derived ordered endpoint sets and conservative surrounding extent."""

    mode: CandidateMode | str
    origin_ids: tuple[int, ...]
    destination_ids: tuple[int, ...]
    reach_distance_m: float
    resolution: int
    maximum_origin_offset_m: float = 0.0
    aoi_geometry: Any | None = None
    expanded_aoi: Any | None = None


@dataclass(frozen=True)
class DirectedPair:
    """One ordered origin/destination candidate and its current disposition."""

    origin_h3_id: int
    destination_h3_id: int
    disposition: CandidateDisposition
    straight_line_lower_bound_m: float | None = None
    solved_cost: float | None = None

    @property
    def logical_od_key(self) -> tuple[int, int]:
        """Return the deterministic ordered pair identity."""
        return (self.origin_h3_id, self.destination_h3_id)


@dataclass(frozen=True)
class CandidateSummary:
    """Reconciliable counts for endpoint scope, prefilter, ledger, and solves."""

    origin_count: int
    destination_count: int
    scope_pair_count: int
    self_pair_count: int
    non_self_prefilter_input_count: int
    prefilter_pruned_count: int
    prefilter_retained_count: int
    prefilter_unbounded_retained_count: int
    duplicate_cell_input_count: int
    rejected_endpoint_reasons: dict[str, int] = field(default_factory=dict)
    ledger_reused_count: int = 0
    ledger_resumed_count: int = 0
    ledger_terminal_count: int = 0
    newly_planned_count: int = 0
    solved_result_count: int = 0
    cutoff_excluded_count: int = 0

    @property
    def rejected_endpoint_reference_count(self) -> int:
        """Return the total rejected endpoint reference count."""
        return sum(self.rejected_endpoint_reasons.values())

    @property
    def prefilter_pruning_ratio(self) -> float:
        """Return the pruning share, defined as zero for an empty input set."""
        if self.non_self_prefilter_input_count == 0:
            return 0.0
        return self.prefilter_pruned_count / self.non_self_prefilter_input_count

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible reconciliation metrics."""
        return {
            "origin_count": self.origin_count,
            "destination_count": self.destination_count,
            "scope_pair_count": self.scope_pair_count,
            "self_pair_count": self.self_pair_count,
            "non_self_prefilter_input_count": self.non_self_prefilter_input_count,
            "prefilter_pruned_count": self.prefilter_pruned_count,
            "prefilter_retained_count": self.prefilter_retained_count,
            "prefilter_unbounded_retained_count": self.prefilter_unbounded_retained_count,
            "prefilter_pruning_ratio": self.prefilter_pruning_ratio,
            "duplicate_cell_input_count": self.duplicate_cell_input_count,
            "rejected_endpoint_reasons": dict(self.rejected_endpoint_reasons),
            "rejected_endpoint_reference_count": self.rejected_endpoint_reference_count,
            "ledger_reused_count": self.ledger_reused_count,
            "ledger_resumed_count": self.ledger_resumed_count,
            "ledger_terminal_count": self.ledger_terminal_count,
            "newly_planned_count": self.newly_planned_count,
            "solved_result_count": self.solved_result_count,
            "cutoff_excluded_count": self.cutoff_excluded_count,
        }


@dataclass(frozen=True)
class CandidatePlan:
    """Candidate records plus the exact policy inputs used to build them."""

    scope: CandidateScope
    pairs: tuple[DirectedPair, ...]
    summary: CandidateSummary
    cutoff: float
    cutoff_unit: str
    prefilter_distance_error_bound_m: float | None
    candidate_policy: dict[str, Any]
    candidate_policy_fingerprint: str


@dataclass(frozen=True)
class LedgerEvidence:
    """One Feature 003 ledger observation for a logical pair key."""

    logical_od_key: tuple[int, int]
    dataset_fingerprint: str
    state: str
    invalidated: bool = False


@dataclass(frozen=True)
class LedgerWorkUnit:
    """Deterministic per-origin destination batch to be newly scheduled."""

    dataset_fingerprint: str
    origin_h3_id: int
    batch_index: int
    destination_ids: tuple[int, ...]
    logical_od_keys: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class CandidateReconciliation:
    """Expected retained keys partitioned by Feature 003 ledger disposition."""

    expected_keys: tuple[tuple[int, int], ...]
    reused_keys: tuple[tuple[int, int], ...]
    resumed_keys: tuple[tuple[int, int], ...]
    terminal_keys: tuple[tuple[int, int], ...]
    planned_keys: tuple[tuple[int, int], ...]
    retryable_keys: tuple[tuple[int, int], ...]
    unresolved_keys: tuple[tuple[int, int], ...]
    completion_status: str
    work_units: tuple[LedgerWorkUnit, ...]
    summary: dict[str, int]
