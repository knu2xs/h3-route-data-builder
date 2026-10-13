"""Portable result compatibility and OD outcome classification."""

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

_RUN_PROVENANCE_KEYS = {
    "aoi",
    "aoi_geometry",
    "aoi_scope",
    "batch",
    "batch_index",
    "batch_size",
    "candidate_policy_fingerprint",
    "candidate_provenance",
    "destination_batch",
    "execution_limit_policy_version",
    "execution_limits",
    "resolved_execution_limits",
    "resolved_limits",
    "run_id",
    "run_provenance",
}


class OutcomeClass(StrEnum):
    """Durable per-key result classifications."""

    QUALIFYING = "qualifying"
    UNLOCATED = "unlocated"
    UNREACHABLE = "unreachable"
    CUTOFF_EXCLUDED = "cutoff_excluded"


@dataclass(frozen=True)
class SolveOutcome:
    """One classified outcome for a directed logical OD key."""

    logical_od_key: tuple[str, str]
    classification: OutcomeClass
    actual_cost: float | None
    cost_unit: str | None
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible outcome record."""
        return {
            "logical_od_key": list(self.logical_od_key),
            "classification": self.classification.value,
            "actual_cost": self.actual_cost,
            "cost_unit": self.cost_unit,
            "diagnostic": self.diagnostic,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolveOutcome":
        """Construct an outcome from persisted JSON data."""
        key = value.get("logical_od_key")
        if not isinstance(key, list) or len(key) != 2:
            raise ValueError("logical_od_key must contain two endpoint identifiers")
        return cls(
            logical_od_key=(str(key[0]), str(key[1])),
            classification=OutcomeClass(value["classification"]),
            actual_cost=value.get("actual_cost"),
            cost_unit=value.get("cost_unit"),
            diagnostic=value.get("diagnostic"),
        )


def compatibility_fingerprint(
    result_inputs: Mapping[str, Any], version: str = "1"
) -> str:
    """Hash result-affecting values while excluding run-only provenance.

    Args:
        result_inputs: Nested identity values for network, endpoint, cost, schema, and software.
        version: Compatibility identity version.

    Returns:
        A stable SHA-256 fingerprint.

    Raises:
        ValueError: If the version or canonical JSON inputs are invalid.
    """
    if not isinstance(version, str) or not version.strip():
        raise ValueError("fingerprint version must be non-empty")
    if not isinstance(result_inputs, Mapping):
        raise ValueError("result_inputs must be a mapping")

    canonical_inputs = _without_run_provenance(result_inputs)
    if not canonical_inputs:
        raise ValueError("result_inputs must contain result-affecting identity")
    payload = {"version": version, "inputs": canonical_inputs}
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"result inputs are not canonical JSON values: {exc}") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def classify_actual_cost(
    logical_od_key: tuple[str, str],
    actual_cost: float,
    cutoff: float,
    cost_unit: str,
) -> SolveOutcome:
    """Classify a solved pair using the actual network cost and configured cutoff."""
    _validate_key(logical_od_key)
    _finite_nonnegative(actual_cost, "actual_cost")
    _finite_nonnegative(cutoff, "cutoff")
    if not isinstance(cost_unit, str) or not cost_unit.strip():
        raise ValueError("cost_unit must be non-empty")
    classification = (
        OutcomeClass.QUALIFYING
        if actual_cost <= cutoff
        else OutcomeClass.CUTOFF_EXCLUDED
    )
    return SolveOutcome(
        logical_od_key=logical_od_key,
        classification=classification,
        actual_cost=float(actual_cost),
        cost_unit=cost_unit.strip(),
    )


def validate_outcome(outcome: SolveOutcome, cutoff: float, cost_unit: str) -> None:
    """Validate one staged outcome against configured cutoff and cost units."""
    if not isinstance(outcome, SolveOutcome):
        raise ValueError("staged outcomes must be SolveOutcome records")
    _validate_key(outcome.logical_od_key)
    if not isinstance(outcome.classification, OutcomeClass):
        raise ValueError("outcome classification is invalid")
    if outcome.classification in {
        OutcomeClass.QUALIFYING,
        OutcomeClass.CUTOFF_EXCLUDED,
    }:
        if outcome.actual_cost is None:
            raise ValueError("route outcome requires an actual cost")
        _finite_nonnegative(outcome.actual_cost, "actual_cost")
        if outcome.cost_unit != cost_unit:
            raise ValueError("outcome cost unit is incompatible with the work item")
        if outcome.classification is OutcomeClass.QUALIFYING:
            if outcome.actual_cost > cutoff:
                raise ValueError("qualifying outcome exceeds the actual-cost cutoff")
        elif outcome.actual_cost <= cutoff:
            raise ValueError("cutoff-excluded outcome does not exceed the cutoff")
    elif outcome.actual_cost is not None or outcome.cost_unit is not None:
        raise ValueError("unlocated or unreachable outcomes cannot contain route costs")


def _without_run_provenance(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_name = str(key).casefold()
            if key_name in _RUN_PROVENANCE_KEYS:
                continue
            if key_name == "candidate_policy":
                candidate_result_inputs = _candidate_result_inputs(item)
                if candidate_result_inputs:
                    normalized[key] = candidate_result_inputs
                continue
            normalized[key] = _without_run_provenance(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_without_run_provenance(item) for item in value]
    return value


def _candidate_result_inputs(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("candidate_policy must be a mapping when supplied")
    result_keys = {"cutoff", "cutoff_unit", "outcome_classification_policy"}
    return {
        key: _without_run_provenance(item)
        for key, item in value.items()
        if str(key).casefold() in result_keys
    }


def _validate_key(logical_od_key: tuple[str, str]) -> None:
    if (
        not isinstance(logical_od_key, tuple)
        or len(logical_od_key) != 2
        or any(
            not isinstance(value, str) or not value.strip() for value in logical_od_key
        )
    ):
        raise ValueError(
            "logical_od_key must be an ordered pair of non-empty identifiers"
        )


def _finite_nonnegative(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite non-negative")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite non-negative")
