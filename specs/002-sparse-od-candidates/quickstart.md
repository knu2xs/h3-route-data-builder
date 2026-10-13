# Quickstart: Sparse OD Candidate Validation

This guide is the acceptance path for Feature 002's portable candidate planner and ArcPy scope
adapter. Feature 003 remains the owner of durable solving and manifest persistence; the builder
candidate tests validate the typed handoff with synthetic ledger evidence and solved costs.

## Prerequisites

- Use the project's ArcGIS Pro `arcgispro-py3` environment for ArcPy geometry tests.
- Install the project development environment with `make env` when it is not already available.
- Use synthetic AOI, cell, representative, and network fixtures; do not modify source data.
- Configure a finite network cutoff with explicit units. For time cutoffs, provide a maximum
  permitted network speed or other proven conservative spatial reach.
- Set `network.prefilter_distance_error_bound_m` only when an auditable upper bound on absolute
  representative-distance measurement error is available. The default `null` safely retains
  pairs rather than applying an implicit measurement tolerance.

## Run portable candidate and ledger tests

From the repository root:

```powershell
pytest testing/test_od_candidates.py testing/test_od_candidate_ledger.py -q
```

Expected outcomes:

- Canonical ordered endpoint pairs are deterministic and direction-sensitive.
- AOI-only pairs match the in-AOI solvable directed product.
- Surrounding origins/destinations, self-pair scope, prefilter dispositions, and counts match the
  [candidate model](data-model.md).
- The prefilter subtracts the configured measurement-error bound from measured distance before
  comparing with reach; an absent bound or invalid individual measurement retains and counts the
  pair, while a present negative or non-finite configured value fails validation.
- No invalid endpoint enters a candidate or ledger work unit.
- Re-running reconciliation reuses committed pairs, resumes recoverable work, and schedules only
  missing or invalidated retained non-self keys.
- Candidate logs reconcile scope, prefilter, ledger, solve, cutoff, and resolved-limit counts;
  execution-limit values and sources are included in the candidate policy passed to Feature 003.

## Run ArcPy geometry tests

In the ArcGIS Pro environment:

```powershell
pytest testing/test_od_candidate_geometry.py -q
```

Expected outcomes:

- Polygon/AOI intersections follow the configured inclusive boundary policy.
- Expanded destination coverage includes origin representative offset plus cutoff reach.
- Distances and expansion use geodesic meters in WGS 84 / EPSG:4326; candidates at the reach
  boundary are retained.
- Origin offsets measure nearest distance to the AOI geometry, not distance to its centroid; an
  origin representative within the AOI has zero offset.
- Invalid CRS or absent conservative reach fails before candidate scheduling.

## Validate the Feature 003 solver handoff

Run the candidate/solver integration tests in the ArcGIS Pro environment:

```powershell
pytest testing/test_od_candidate_geometry.py testing/test_od_candidate_ledger.py -q
```

`testing/test_od_candidate_ledger.py` uses a synthetic solver-result fixture with costs below,
exactly at, and above the cutoff. Independently calculate the expected pair universe and assert:

- Zero routes at or under the cutoff are removed by the prefilter.
- The actual solved cost determines cutoff inclusion/exclusion.
- The solve-result handoff classifies actual costs before any qualifying fact is committed or
  published; an over-cutoff result is `cutoff-excluded`.
- Self-pairs produce zero cost without invoking the network solver.
- Pruned + retained counts equal all non-self prefilter inputs, and the pruning ratio matches the
  defined formula.
- Ledger work and all candidate dispositions reconcile without duplicate logical keys.
- Candidate-policy provenance includes the resolved execution limits and sources, inference-policy
  version, cutoff/reach inputs, and prefilter measurement-error bound; changed candidate policy
  changes the behavior fingerprint. Feature 003 persists and restores this payload in its manifest.

See the [ledger handoff contract](contracts/candidate-planning.md) for required identity and
reconciliation behavior.
