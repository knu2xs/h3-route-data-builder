"""Portable directed OD candidate planning and Feature 003 ledger handoff."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace
import hashlib
import json
import math
from enum import Enum
from typing import Any

from h3.api.basic_int import get_resolution

from h3_route_data_builder.config import ConfigNode, config as project_config
from h3_route_data_builder.eligibility.cells import canonical_h3_ids
from h3_route_data_builder.eligibility.limits import (
    EXECUTION_LIMIT_POLICY_VERSION,
    ExecutionLimits,
)
from h3_route_data_builder.od.models import (
    CandidateDisposition,
    CandidateMode,
    CandidatePlan,
    CandidateReconciliation,
    CandidateScope,
    CandidateSummary,
    DirectedPair,
    LedgerEvidence,
    LedgerWorkUnit,
    SolvableCell,
)
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)
CANDIDATE_POLICY_VERSION = "1"


class _UseConfiguredErrorBound(Enum):
    """Internal sentinel that requests the value from project configuration."""

    VALUE = "configured"


_USE_CONFIGURED_ERROR_BOUND = _UseConfiguredErrorBound.VALUE

_DISTANCE_TO_METERS = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "km": 1000.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "mi": 1609.344,
    "mile": 1609.344,
    "miles": 1609.344,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
}
_TIME_TO_SECONDS = {
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
}
_RECOVERABLE_STATES = {
    "planned",
    "leased",
    "solving",
    "staged",
    "validated",
    "retryable",
    "retryable_failure",
}
_TERMINAL_STATES = {
    "terminal",
    "terminal_failure",
    "failed_terminal",
    "unlocated",
    "unreachable",
    "system_failure",
}


class CandidateBuildIncompleteError(RuntimeError):
    """Raised when candidate scope exceeds a resolved execution limit."""

    status = "failed_incomplete"


def cutoff_reach_m(
    cutoff: float,
    cutoff_unit: str,
    maximum_network_speed_mps: float | None = None,
) -> float:
    """Convert a finite cutoff into a conservative spatial reach in meters.

    Args:
        cutoff: Non-negative configured distance or time cutoff.
        cutoff_unit: Explicit supported distance or time unit.
        maximum_network_speed_mps: Proven permitted upper network speed for time cutoffs.

    Returns:
        Conservative reach in geodesic meters.

    Raises:
        ValueError: If cutoff, units, or the required maximum speed is invalid.
    """
    _require_finite_nonnegative(cutoff, "cutoff")
    unit = cutoff_unit.strip().casefold() if isinstance(cutoff_unit, str) else ""
    if unit in _DISTANCE_TO_METERS:
        reach_distance_m = float(cutoff) * _DISTANCE_TO_METERS[unit]
    elif unit in _TIME_TO_SECONDS:
        if maximum_network_speed_mps is None:
            raise ValueError(
                "A time cutoff requires maximum_network_speed_mps or another proven "
                "conservative spatial reach"
            )
        _require_finite_nonnegative(maximum_network_speed_mps, "maximum_network_speed_mps")
        if maximum_network_speed_mps <= 0:
            raise ValueError("maximum_network_speed_mps must be positive")
        reach_distance_m = float(cutoff) * _TIME_TO_SECONDS[unit] * maximum_network_speed_mps
    else:
        raise ValueError(f"Unsupported cutoff_unit: {cutoff_unit!r}")
    if not math.isfinite(reach_distance_m):
        raise ValueError("cutoff reach in meters must be finite")
    return reach_distance_m


def candidate_policy_manifest(
    cutoff: float,
    cutoff_unit: str,
    reach_distance_m: float,
    prefilter_distance_error_bound_m: float | None,
    limits: ExecutionLimits | None = None,
    mode: CandidateMode | str | None = None,
    maximum_network_speed_mps: float | None = None,
    maximum_origin_offset_m: float = 0.0,
) -> dict[str, Any]:
    """Build the serializable candidate policy passed to Feature 003.

    Args:
        cutoff: Configured network cutoff.
        cutoff_unit: Explicit cutoff cost unit.
        reach_distance_m: Derived conservative geodesic reach.
        prefilter_distance_error_bound_m: Optional caller-asserted measurement error bound.
        limits: Resolved shared execution limits, when available.
        mode: Candidate mode included in policy identity.
        maximum_network_speed_mps: Speed bound used for a time cutoff, if any.

    Returns:
        JSON-compatible policy values, including execution-limit provenance.
    """
    _require_finite_nonnegative(cutoff, "cutoff")
    if not isinstance(cutoff_unit, str) or not cutoff_unit.strip():
        raise ValueError("cutoff_unit must be a non-empty string")
    _require_finite_nonnegative(reach_distance_m, "reach_distance_m")
    required_reach_m = cutoff_reach_m(cutoff, cutoff_unit, maximum_network_speed_mps)
    if reach_distance_m < required_reach_m:
        raise ValueError("reach_distance_m is below the cutoff-derived reach")
    _require_finite_nonnegative(maximum_origin_offset_m, "maximum_origin_offset_m")
    _validate_error_bound(prefilter_distance_error_bound_m)
    if maximum_network_speed_mps is not None:
        _require_finite_nonnegative(maximum_network_speed_mps, "maximum_network_speed_mps")
    policy: dict[str, Any] = {
        "candidate_policy_version": CANDIDATE_POLICY_VERSION,
        "execution_limit_policy_version": EXECUTION_LIMIT_POLICY_VERSION,
        "mode": CandidateMode(mode).value if mode is not None else None,
        "cutoff": float(cutoff),
        "cutoff_unit": cutoff_unit.strip().casefold(),
        "reach_distance_m": float(reach_distance_m),
        "maximum_origin_offset_m": float(maximum_origin_offset_m),
        "maximum_network_speed_mps": maximum_network_speed_mps,
        "prefilter_distance_error_bound_m": prefilter_distance_error_bound_m,
        "limits": limits.to_manifest() if limits is not None else None,
    }
    return policy


def candidate_policy_fingerprint(
    cutoff: float,
    cutoff_unit: str,
    reach_distance_m: float,
    prefilter_distance_error_bound_m: float | None,
    limits: ExecutionLimits | None = None,
    mode: CandidateMode | str | None = None,
    maximum_network_speed_mps: float | None = None,
    maximum_origin_offset_m: float = 0.0,
) -> str:
    """Return a stable SHA-256 fingerprint for candidate-affecting policy."""
    policy = candidate_policy_manifest(
        cutoff,
        cutoff_unit,
        reach_distance_m,
        prefilter_distance_error_bound_m,
        limits,
        mode,
        maximum_network_speed_mps,
        maximum_origin_offset_m,
    )
    return _candidate_policy_hash(policy)


def _candidate_policy_hash(policy: Mapping[str, Any]) -> str:
    """Hash an already validated candidate policy without recalculating its reach."""
    encoded = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def restore_candidate_policy(
    saved_policy: Mapping[str, Any],
    explicit_overrides: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ExecutionLimits | None, str]:
    """Restore saved candidate policy without re-deriving cutoff reach or resource limits.

    Args:
        saved_policy: Candidate policy payload previously persisted by the run manifest.
        explicit_overrides: Optional same-run overrides to compare with saved values.

    Returns:
        Saved policy, restored shared limits, and its candidate-policy fingerprint.

    Raises:
        ValueError: If saved policy is unsupported or an override changes run behavior.
    """
    required_fields = {
        "candidate_policy_version",
        "execution_limit_policy_version",
        "mode",
        "cutoff",
        "cutoff_unit",
        "reach_distance_m",
        "maximum_origin_offset_m",
        "maximum_network_speed_mps",
        "prefilter_distance_error_bound_m",
        "limits",
    }
    missing = required_fields - saved_policy.keys()
    if missing:
        raise ValueError(f"Saved candidate policy is missing fields: {', '.join(sorted(missing))}")
    if saved_policy["candidate_policy_version"] != CANDIDATE_POLICY_VERSION:
        raise ValueError("Saved candidate policy version is unsupported")
    if saved_policy["execution_limit_policy_version"] != EXECUTION_LIMIT_POLICY_VERSION:
        raise ValueError("Saved execution limit policy version is unsupported")

    mode = CandidateMode(saved_policy["mode"])
    cutoff = saved_policy["cutoff"]
    cutoff_unit = saved_policy["cutoff_unit"]
    reach_distance_m = saved_policy["reach_distance_m"]
    maximum_origin_offset_m = saved_policy["maximum_origin_offset_m"]
    maximum_network_speed_mps = saved_policy["maximum_network_speed_mps"]
    error_bound = saved_policy["prefilter_distance_error_bound_m"]
    if not isinstance(cutoff_unit, str) or cutoff_unit.strip().casefold() not in (
        _DISTANCE_TO_METERS.keys() | _TIME_TO_SECONDS.keys()
    ):
        raise ValueError("Saved candidate policy has an unsupported cutoff unit")
    _require_finite_nonnegative(cutoff, "saved cutoff")
    _require_finite_nonnegative(reach_distance_m, "saved reach_distance_m")
    _require_finite_nonnegative(maximum_origin_offset_m, "saved maximum_origin_offset_m")
    _validate_error_bound(error_bound)
    if cutoff_unit.strip().casefold() in _TIME_TO_SECONDS:
        if maximum_network_speed_mps is None:
            raise ValueError("Saved time-cutoff policy has no maximum network speed")
        if not _valid_number(maximum_network_speed_mps) or float(maximum_network_speed_mps) <= 0:
            raise ValueError("Saved maximum_network_speed_mps must be positive and finite")

    raw_limits = saved_policy["limits"]
    limits = ExecutionLimits.from_manifest(raw_limits) if raw_limits is not None else None
    if explicit_overrides:
        allowed_overrides = {
            "mode",
            "cutoff",
            "cutoff_unit",
            "reach_distance_m",
            "maximum_origin_offset_m",
            "maximum_network_speed_mps",
            "prefilter_distance_error_bound_m",
            "limits",
        }
        unexpected = set(explicit_overrides) - allowed_overrides
        if unexpected:
            raise ValueError(
                f"Unsupported candidate policy overrides: {', '.join(sorted(unexpected))}"
            )
        saved_values = dict(saved_policy)
        saved_values["limits"] = limits.to_manifest() if limits is not None else None
        for name, value in explicit_overrides.items():
            if name == "mode":
                value = CandidateMode(value).value
            if name == "cutoff_unit" and isinstance(value, str):
                value = value.strip().casefold()
            if name == "limits" and isinstance(value, ExecutionLimits):
                value = value.to_manifest()
            if value != saved_values[name]:
                raise ValueError(
                    f"Candidate policy override {name!r} changes run behavior; "
                    "use a distinct run"
                )

    restored_policy = dict(saved_policy)
    restored_policy["limits"] = limits.to_manifest() if limits is not None else None
    return (
        restored_policy,
        limits,
        _candidate_policy_hash(restored_policy),
    )


def configured_prefilter_distance_error_bound_m(
    config_node: ConfigNode | None = None,
) -> float | None:
    """Read and validate the optional prefilter error bound from network config."""
    selected_config = config_node if config_node is not None else project_config
    network = selected_config.get("network")
    if network is None:
        return None
    value = network.get("prefilter_distance_error_bound_m")
    _validate_error_bound(value)
    return float(value) if value is not None else None


def build_candidate_plan(
    cells: Iterable[SolvableCell],
    scope: CandidateScope,
    cutoff: float,
    cutoff_unit: str,
    representative_distances_m: Mapping[tuple[int, int], float | None] | None = None,
    prefilter_distance_error_bound_m: float | None | _UseConfiguredErrorBound = (
        _USE_CONFIGURED_ERROR_BOUND
    ),
    maximum_network_speed_mps: float | None = None,
    limits: ExecutionLimits | None = None,
) -> CandidatePlan:
    """Enumerate directed candidate pairs and apply only a conservative prefilter.

    Args:
        cells: Feature 001 endpoint records.
        scope: Geometry-selected origin and destination IDs.
        cutoff: Actual network cutoff in ``cutoff_unit``.
        cutoff_unit: Explicit distance or time unit for actual solved costs.
        representative_distances_m: Optional geodesic measurements keyed by ordered pair.
        prefilter_distance_error_bound_m: Optional caller-asserted absolute measurement bound.
        maximum_network_speed_mps: Required proof bound for time-based cutoff reach.
        limits: Shared resolved resource limits and provenance.

    Returns:
        Complete deterministic plan, including self and prefilter-pruned dispositions.

    Raises:
        CandidateBuildIncompleteError: If the endpoint count exceeds the hard output cap.
        ValueError: If scope, endpoint, cutoff, or error-bound inputs are invalid.
    """
    mode = CandidateMode(scope.mode)
    reach_distance_m = cutoff_reach_m(cutoff, cutoff_unit, maximum_network_speed_mps)
    if prefilter_distance_error_bound_m is _USE_CONFIGURED_ERROR_BOUND:
        prefilter_distance_error_bound_m = configured_prefilter_distance_error_bound_m()
    _validate_error_bound(prefilter_distance_error_bound_m)
    _require_finite_nonnegative(scope.reach_distance_m, "scope.reach_distance_m")
    _require_finite_nonnegative(scope.maximum_origin_offset_m, "scope.maximum_origin_offset_m")
    if scope.reach_distance_m < reach_distance_m:
        raise ValueError("Candidate scope reach_distance_m is below the cutoff-derived reach")

    scope_origins = _canonical_scope_ids(scope.origin_ids, "origin_ids")
    scope_destinations = _canonical_scope_ids(scope.destination_ids, "destination_ids")
    if (
        isinstance(scope.resolution, bool)
        or not isinstance(scope.resolution, int)
        or not 0 <= scope.resolution <= 15
    ):
        raise ValueError("scope.resolution must be an H3 resolution between 0 and 15")
    origin_set = set(scope_origins)
    destination_set = set(scope_destinations)
    if mode == CandidateMode.AOI_ONLY and origin_set != destination_set:
        raise ValueError("AOI-only destination_ids must equal origin_ids")
    if mode == CandidateMode.AOI_TO_SURROUNDING and not origin_set.issubset(destination_set):
        raise ValueError("Surrounding destination_ids must include every origin ID")

    cell_by_id: dict[int, SolvableCell] = {}
    seen_cells: dict[int, SolvableCell] = {}
    duplicate_count = 0
    unique_solvable_ids: set[int] = set()
    rejected: dict[str, int] = defaultdict(int)
    rejected_cell_ids: dict[int, str] = {}
    for cell in cells:
        try:
            cell_id = _canonical_id(cell.h3_id)
        except (TypeError, ValueError):
            rejected["invalid_h3_id"] += 1
            continue
        previous = seen_cells.get(cell_id)
        if previous is not None:
            duplicate_count += 1
            if (
                previous.resolution != cell.resolution
                or previous.eligibility_status != cell.eligibility_status
                or previous.representative != cell.representative
            ):
                raise ValueError(f"Conflicting duplicate solvable-cell references for {cell_id!r}")
            continue
        seen_cells[cell_id] = cell
        if cell.eligibility_status == "solvable":
            unique_solvable_ids.add(cell_id)
        if isinstance(cell.resolution, bool) or not isinstance(cell.resolution, int):
            rejected_cell_ids[cell_id] = "invalid_resolution"
            continue
        if cell.resolution != _resolution(cell_id) or (cell.resolution != scope.resolution):
            rejected_cell_ids[cell_id] = "resolution_mismatch"
            continue
        if cell.eligibility_status != "solvable":
            rejected_cell_ids[cell_id] = "not_solvable"
            continue
        if not _valid_representative(cell.representative):
            rejected_cell_ids[cell_id] = "invalid_representative"
            continue
        cell_by_id[cell_id] = cell

    if limits is not None:
        _log_execution_limits(limits)
    if limits is not None and len(unique_solvable_ids) > limits.total_output_hard_cap:
        message = (
            "Candidate build failed incomplete: unique solvable cell count "
            f"{len(unique_solvable_ids)} exceeds total_output_hard_cap "
            f"{limits.total_output_hard_cap}"
        )
        logger.error(
            message,
            extra={
                "event_name": "od_candidate_limit_exceeded",
                "execution_limits": limits.to_manifest(),
                "solvable_cell_count": len(unique_solvable_ids),
                "status": "failed_incomplete",
            },
        )
        raise CandidateBuildIncompleteError(message)

    scoped_endpoint_ids = set(scope_origins).union(scope_destinations)
    for cell_id in sorted(scoped_endpoint_ids, key=_h3_order):
        if cell_id not in cell_by_id:
            rejected[rejected_cell_ids.get(cell_id, "missing_cell")] += 1
    valid_origins = tuple(cell_id for cell_id in scope_origins if cell_id in cell_by_id)
    valid_destinations = tuple(cell_id for cell_id in scope_destinations if cell_id in cell_by_id)
    if mode == CandidateMode.AOI_TO_SURROUNDING:
        valid_destinations = tuple(
            sorted(
                set(valid_destinations).union(valid_origins),
                key=_h3_order,
            )
        )

    distances = _canonical_distance_map(representative_distances_m or {})
    pairs: list[DirectedPair] = []
    self_count = 0
    input_count = 0
    pruned_count = 0
    retained_count = 0
    unbounded_count = 0
    valid_destination_set = set(valid_destinations)
    for origin_id in valid_origins:
        for destination_id in valid_destinations:
            if destination_id not in valid_destination_set:
                continue
            if origin_id == destination_id:
                self_count += 1
                pairs.append(
                    DirectedPair(
                        origin_id,
                        destination_id,
                        CandidateDisposition.SELF_RESOLVED,
                        straight_line_lower_bound_m=0.0,
                        solved_cost=0.0,
                    )
                )
                continue

            input_count += 1
            measured_distance = distances.get(
                (origin_id, destination_id),
                distances.get((destination_id, origin_id)),
            )
            valid_distance = _valid_distance(measured_distance)
            if prefilter_distance_error_bound_m is None or not valid_distance:
                unbounded_count += 1
                retained_count += 1
                pairs.append(DirectedPair(origin_id, destination_id, CandidateDisposition.RETAINED))
                continue

            lower_bound_m = max(
                0.0,
                float(measured_distance) - prefilter_distance_error_bound_m,
            )
            if lower_bound_m > reach_distance_m:
                pruned_count += 1
                disposition = CandidateDisposition.PREFILTER_PRUNED
            else:
                retained_count += 1
                disposition = CandidateDisposition.RETAINED
            pairs.append(
                DirectedPair(
                    origin_id,
                    destination_id,
                    disposition,
                    straight_line_lower_bound_m=lower_bound_m,
                )
            )

    summary = CandidateSummary(
        origin_count=len(valid_origins),
        destination_count=len(valid_destinations),
        scope_pair_count=len(valid_origins) * len(valid_destinations),
        self_pair_count=self_count,
        non_self_prefilter_input_count=input_count,
        prefilter_pruned_count=pruned_count,
        prefilter_retained_count=retained_count,
        prefilter_unbounded_retained_count=unbounded_count,
        duplicate_cell_input_count=duplicate_count,
        rejected_endpoint_reasons=dict(sorted(rejected.items())),
    )
    if self_count + input_count != summary.scope_pair_count:
        raise RuntimeError("Candidate scope counts do not reconcile")
    if pruned_count + retained_count != input_count:
        raise RuntimeError("Prefilter counts do not reconcile")

    policy = candidate_policy_manifest(
        cutoff,
        cutoff_unit,
        reach_distance_m,
        prefilter_distance_error_bound_m,
        limits,
        mode,
        maximum_network_speed_mps,
        scope.maximum_origin_offset_m,
    )
    fingerprint = candidate_policy_fingerprint(
        cutoff,
        cutoff_unit,
        reach_distance_m,
        prefilter_distance_error_bound_m,
        limits,
        mode,
        maximum_network_speed_mps,
        scope.maximum_origin_offset_m,
    )
    plan = CandidatePlan(
        scope=replace(
            scope,
            mode=mode,
            origin_ids=valid_origins,
            destination_ids=valid_destinations,
            resolution=scope.resolution,
        ),
        pairs=tuple(pairs),
        summary=summary,
        cutoff=float(cutoff),
        cutoff_unit=cutoff_unit.strip().casefold(),
        prefilter_distance_error_bound_m=prefilter_distance_error_bound_m,
        candidate_policy=policy,
        candidate_policy_fingerprint=fingerprint,
    )
    _log_candidate_plan(plan, limits)
    return plan


def classify_solved_costs(
    plan: CandidatePlan,
    actual_solved_costs: Mapping[tuple[int, int], float],
) -> CandidatePlan:
    """Classify completed retained pairs using actual network costs only.

    Args:
        plan: Candidate plan sent to the solver/ledger integration.
        actual_solved_costs: Solved costs keyed by ordered endpoint IDs, in plan cutoff units.

    Returns:
        Copy of the plan with solved pair dispositions and counts updated.

    Raises:
        ValueError: If a supplied key is not retained or an actual cost is invalid.
    """
    valid_pairs = {
        pair.logical_od_key: pair
        for pair in plan.pairs
        if pair.disposition == CandidateDisposition.RETAINED
    }
    normalized_costs: dict[tuple[int, int], float] = {}
    for raw_key, cost in actual_solved_costs.items():
        if cost is None or isinstance(cost, bool) or not isinstance(cost, (int, float)):
            raise ValueError("A finite actual solved cost is required")
        _require_finite_nonnegative(cost, "actual solved cost")
        key = (_canonical_id(raw_key[0]), _canonical_id(raw_key[1]))
        if key not in valid_pairs:
            raise ValueError(f"Solved cost supplied for a non-retained pair: {key!r}")
        normalized_costs[key] = float(cost)

    updated_pairs: list[DirectedPair] = []
    excluded_count = 0
    for pair in plan.pairs:
        actual_cost = normalized_costs.get(pair.logical_od_key)
        if actual_cost is None:
            updated_pairs.append(pair)
            continue
        if actual_cost <= plan.cutoff:
            disposition = CandidateDisposition.QUALIFYING
        else:
            disposition = CandidateDisposition.CUTOFF_EXCLUDED
            excluded_count += 1
        updated_pairs.append(replace(pair, disposition=disposition, solved_cost=actual_cost))
    summary = replace(
        plan.summary,
        solved_result_count=len(normalized_costs),
        cutoff_excluded_count=excluded_count,
    )
    logger.info(
        "od_solve_cutoff_classification",
        extra={
            "event_name": "od_solve_cutoff_classification",
            "solved_result_count": len(normalized_costs),
            "cutoff_excluded_count": excluded_count,
            "cutoff": plan.cutoff,
            "cutoff_unit": plan.cutoff_unit,
        },
    )
    return replace(plan, pairs=tuple(updated_pairs), summary=summary)


def reconcile_candidate_work(
    plan: CandidatePlan,
    ledger_evidence: Iterable[LedgerEvidence],
    dataset_fingerprint: str,
    destination_batch_size: int | None = None,
) -> CandidateReconciliation:
    """Partition retained non-self keys against Feature 003 evidence.

    Args:
        plan: Candidate plan to reconcile.
        ledger_evidence: Existing Feature 003 state observations.
        dataset_fingerprint: Current fingerprint used to select compatible evidence.
        destination_batch_size: Optional positive batch size override; otherwise use the
            candidate plan's resolved execution limits.

    Returns:
        Expected key partitions and deterministic work units for absent/invalidated keys.

    Raises:
        ValueError: If batch size, fingerprint, pair evidence, or ledger state is invalid.
    """
    if not dataset_fingerprint:
        raise ValueError("dataset_fingerprint must be non-empty")
    if destination_batch_size is None:
        limits_manifest = plan.candidate_policy.get("limits")
        if limits_manifest is None:
            raise ValueError(
                "destination_batch_size is required when no execution limits were resolved"
            )
        destination_batch_size = min(
            int(limits_manifest["batch_size"]["value"]),
            int(limits_manifest["part_row_limit"]["value"]),
        )
    elif plan.candidate_policy.get("limits") is not None:
        limits_manifest = plan.candidate_policy["limits"]
        maximum_batch_size = min(
            int(limits_manifest["batch_size"]["value"]),
            int(limits_manifest["part_row_limit"]["value"]),
        )
        if destination_batch_size > maximum_batch_size:
            raise ValueError(
                "destination_batch_size exceeds the resolved candidate batch/part row limit"
            )
    if (
        isinstance(destination_batch_size, bool)
        or not isinstance(destination_batch_size, int)
        or destination_batch_size <= 0
    ):
        raise ValueError("destination_batch_size must be a positive integer")

    expected_pairs = tuple(
        pair
        for pair in plan.pairs
        if pair.disposition == CandidateDisposition.RETAINED
        and pair.origin_h3_id != pair.destination_h3_id
    )
    expected_keys = tuple(pair.logical_od_key for pair in expected_pairs)
    if len(expected_keys) != len(set(expected_keys)):
        raise ValueError("Candidate plan contains duplicate logical OD keys")

    evidence_by_key: dict[tuple[int, int], list[LedgerEvidence]] = defaultdict(list)
    for evidence in ledger_evidence:
        key = (
            _canonical_id(evidence.logical_od_key[0]),
            _canonical_id(evidence.logical_od_key[1]),
        )
        evidence_by_key[key].append(evidence)

    reused: list[tuple[int, int]] = []
    resumed: list[tuple[int, int]] = []
    terminal: list[tuple[int, int]] = []
    planned: list[tuple[int, int]] = []
    compatible_state_by_key: dict[tuple[int, int], str] = {}
    for key in expected_keys:
        compatible = [
            item
            for item in evidence_by_key.get(key, ())
            if item.dataset_fingerprint == dataset_fingerprint
        ]
        if len(compatible) > 1:
            raise ValueError(f"duplicate compatible ledger evidence for {key!r}")
        if not compatible:
            planned.append(key)
            continue

        evidence = compatible[0]
        state = evidence.state.casefold()
        compatible_state_by_key[key] = state
        if evidence.invalidated or state == "invalidated":
            planned.append(key)
        elif state == "committed":
            reused.append(key)
        elif state in _RECOVERABLE_STATES:
            resumed.append(key)
        elif state in _TERMINAL_STATES:
            terminal.append(key)
        else:
            raise ValueError(f"Unsupported Feature 003 ledger state: {evidence.state!r}")

    retryable = [
        key for key in resumed if compatible_state_by_key[key] in {"retryable", "retryable_failure"}
    ]
    committed_set = set(reused)
    terminal_set = set(terminal)
    retryable_set = set(retryable)
    unresolved = [
        key for key in expected_keys if key not in committed_set | terminal_set | retryable_set
    ]
    if not unresolved and not terminal:
        completion_status = "all_success"
    elif not unresolved:
        completion_status = "complete_with_failures"
    else:
        completion_status = "in_progress"

    work_units: list[LedgerWorkUnit] = []
    expected_by_origin: dict[int, list[int]] = defaultdict(list)
    planned_key_set = set(planned)
    for origin_id, destination_id in expected_keys:
        expected_by_origin[origin_id].append(destination_id)
    for origin_id in sorted(expected_by_origin, key=_h3_order):
        ordered_destinations = sorted(set(expected_by_origin[origin_id]), key=_h3_order)
        for batch_index, start in enumerate(
            range(0, len(ordered_destinations), destination_batch_size)
        ):
            expected_batch = ordered_destinations[start : start + destination_batch_size]
            destination_batch = tuple(
                destination_id
                for destination_id in expected_batch
                if (origin_id, destination_id) in planned_key_set
            )
            if not destination_batch:
                continue
            keys = tuple((origin_id, destination_id) for destination_id in destination_batch)
            work_units.append(
                LedgerWorkUnit(
                    dataset_fingerprint=dataset_fingerprint,
                    origin_h3_id=origin_id,
                    batch_index=batch_index,
                    destination_ids=destination_batch,
                    logical_od_keys=keys,
                )
            )

    summary = {
        "expected_non_self_key_count": len(expected_keys),
        "ledger_reused_count": len(reused),
        "ledger_resumed_count": len(resumed),
        "ledger_terminal_count": len(terminal),
        "newly_planned_count": len(planned),
        "committed_count": len(reused),
        "retryable_failure_count": len(retryable),
        "terminal_failure_count": len(terminal),
        "unresolved_count": len(unresolved),
        "all_success": int(completion_status == "all_success"),
        "complete_with_failures": int(completion_status == "complete_with_failures"),
    }
    if sum(
        summary[name]
        for name in (
            "committed_count",
            "retryable_failure_count",
            "terminal_failure_count",
            "unresolved_count",
        )
    ) != len(expected_keys):
        raise RuntimeError("Ledger reconciliation counts do not partition expected keys")

    reconciliation = CandidateReconciliation(
        expected_keys=expected_keys,
        reused_keys=tuple(reused),
        resumed_keys=tuple(resumed),
        terminal_keys=tuple(terminal),
        planned_keys=tuple(planned),
        retryable_keys=tuple(retryable),
        unresolved_keys=tuple(unresolved),
        completion_status=completion_status,
        work_units=tuple(work_units),
        summary=summary,
    )
    logger.info(
        "od_candidate_ledger_reconciliation",
        extra={"event_name": "od_candidate_ledger_reconciliation", "metrics": summary},
    )
    return reconciliation


def _canonical_scope_ids(cell_ids: Iterable[int], field_name: str) -> tuple[int, ...]:
    try:
        return tuple(canonical_h3_ids(cell_ids))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} contains an invalid H3 identifier: {exc}") from exc


def _canonical_id(cell_id: int) -> int:
    return canonical_h3_ids((cell_id,))[0]


def _h3_order(cell_id: int) -> int:
    return cell_id


def _resolution(cell_id: int) -> int:
    return get_resolution(cell_id)


def _valid_representative(representative: tuple[float, float] | None) -> bool:
    if representative is None or not isinstance(representative, tuple) or len(representative) != 2:
        return False
    longitude, latitude = representative
    return (
        _valid_number(longitude)
        and _valid_number(latitude)
        and -180.0 <= float(longitude) <= 180.0
        and -90.0 <= float(latitude) <= 90.0
    )


def _canonical_distance_map(
    distances: Mapping[tuple[int, int], float | None],
) -> dict[tuple[int, int], float | None]:
    normalized: dict[tuple[int, int], float | None] = {}
    for key, value in distances.items():
        if len(key) != 2:
            continue
        try:
            normalized_key = (_canonical_id(key[0]), _canonical_id(key[1]))
        except (TypeError, ValueError):
            continue
        previous = normalized.get(normalized_key)
        if previous is not None and previous != value:
            raise ValueError(
                f"Conflicting representative distances supplied for {normalized_key!r}"
            )
        normalized[normalized_key] = value
    return normalized


def _valid_distance(value: float | None) -> bool:
    return _valid_number(value) and float(value) >= 0.0


def _valid_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _require_finite_nonnegative(value: Any, name: str) -> None:
    if not _valid_number(value) or float(value) < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")


def _validate_error_bound(value: float | None) -> None:
    if value is not None:
        _require_finite_nonnegative(value, "prefilter_distance_error_bound_m")


def _log_candidate_plan(plan: CandidatePlan, limits: ExecutionLimits | None) -> None:
    execution_limits = limits.to_manifest() if limits is not None else None
    metrics = plan.summary.to_dict()
    logger.info(
        "od_candidate_plan",
        extra={
            "event_name": "od_candidate_plan",
            "metrics": metrics,
            "execution_limits": execution_limits,
            "candidate_policy_fingerprint": plan.candidate_policy_fingerprint,
            "candidate_policy": plan.candidate_policy,
        },
    )


def _log_execution_limits(limits: ExecutionLimits) -> None:
    """Log each resolved limit value and source as structured provenance."""
    manifest = limits.to_manifest()
    logger.info(
        "od_candidate_execution_limits",
        extra={
            "event_name": "od_candidate_execution_limits",
            "execution_limits": manifest,
            "policy_version": manifest["policy_version"],
        },
    )
