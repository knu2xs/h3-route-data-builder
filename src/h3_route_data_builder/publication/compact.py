"""Immutable logical-preserving physical compaction."""

import json
from pathlib import Path
import uuid

from h3_route_data_builder.od.results import SolveOutcome
from h3_route_data_builder.publication.models import PublicationResult
from h3_route_data_builder.publication.publish import (
    _load_version,
    publish_dataset,
)


def compact_publication(
    output_root: str | Path,
    source_version_id: str,
) -> PublicationResult:
    """Create and atomically expose a new physical version without modifying its source."""
    root = Path(output_root).resolve()
    source_path = root / "versions" / source_version_id
    source = _load_version(source_path)
    reconciliation = json.loads(
        (source_path / "reconciliation.json").read_text(encoding="utf-8")
    )
    outcomes = [SolveOutcome.from_dict(value) for value in reconciliation["outcomes"]]
    solve_states = {
        tuple(value["logical_od_key"]): value["state"]
        for value in reconciliation.get("solve_states", [])
    }
    manifest = source.manifest
    return publish_dataset(
        output_root=root,
        dimension=source.dimension,
        facts=source.facts,
        expected_keys=[tuple(key) for key in reconciliation["expected_keys"]],
        outcomes=outcomes,
        self_pairs=[tuple(key) for key in reconciliation["self_pairs"]],
        dataset_fingerprint=manifest["dataset_fingerprint"],
        result_compatibility_fingerprint=manifest["result_compatibility_fingerprint"],
        eligibility_fingerprint=manifest["eligibility_fingerprint"],
        candidate_provenance=manifest["candidate_provenance"],
        solve_provenance=manifest["solve_provenance"],
        prefilter_pruned_count=manifest["prefilter_pruned_count"],
        solve_states=solve_states or None,
        version_id=f"compact-{uuid.uuid4().hex}",
    )
