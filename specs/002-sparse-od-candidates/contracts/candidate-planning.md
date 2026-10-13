# Candidate Planning and Ledger Handoff Contract

This is an internal boundary between Feature 002 candidate planning and Feature 003 resumable OD
solving. It does not add a public endpoint or change the shared OD fact schema.

## Inputs

- Build mode: AOI-only or AOI-to-surrounding.
- Validated AOI geometry in WGS 84 / EPSG:4326 and configured inclusive intersection policy.
- Unique Feature 001 solvable-cell references with canonical H3 polygon and deterministic network
  representative.
- Finite network cutoff and explicit cost units. Spatial distances and AOI expansion use geodesic
  meters under Feature 001's fixed WGS 84 / EPSG:4326 contract.
- Optional `network.prefilter_distance_error_bound_m`, a finite nonnegative upper bound on the
  absolute measurement error of representative-point geodesic separation. It covers coordinate
  precision, geodesic calculation, and unit conversion. The caller asserts that a configured
  value is defensible; the planner validates its form, not its accuracy. If absent, all otherwise
  eligible non-self pairs are retained and the fallback count is reported.
- For time cutoffs, a documented maximum permitted network speed or another proven conservative
  spatial reach bound.
- Resolved execution limits and compatible dataset fingerprint.
- Feature 003 ledger view/reconciliation capability for expected logical OD keys.

## Scope and ordering

1. Canonicalize and deduplicate H3 identifiers; reject malformed or non-solvable endpoint
   references before work is scheduled.
2. Determine origins by canonical H3 polygon intersection with the AOI.
3. AOI-only destinations are exactly the origin set.
4. For surrounding mode, compute the greatest geodesic distance in meters from each origin
   representative to the nearest point on the AOI geometry (zero when inside). Geodesically
   expand AOI by that offset plus conservative cutoff reach, then include every solvable cell
   whose canonical polygon intersects the expansion.
5. Order endpoint IDs by canonical H3 integer order. Enumerate each origin against bounded,
   deterministic destination batches. A pair's logical key is the ordered endpoint tuple and is
   independent of the batch.

## Prefilter

- Self-pairs are resolved to zero network cost and are not submitted to the solver.
- For non-self pairs, use only a conservative geodesic lower bound in meters between deterministic
  network representatives.
- When a valid configured error bound and distance measurement exist, compute the conservative
  lower bound as `max(0, measured_distance_m - prefilter_distance_error_bound_m)`. Prune only when
  the bound is strictly greater than a conservative cutoff-derived spatial reach. Equality is
  retained.
- If coordinates, units, spatial reference, or distance measurement are invalid or unavailable,
  retain the pair; do not substitute an unsafe estimate or implicit tolerance. If the configured
  error bound is absent, retain all otherwise eligible pairs. A present configured error bound
  that is negative or non-finite fails validation before scheduling. Report the number retained
  due to an unavailable error bound or distance measurement.
- Apply the configured cutoff only after a network solve, against the actual network cost. An
  over-cutoff result is classified `cutoff-excluded` and is not a qualifying published OD fact.
  Feature 003 owns solving and must classify actual cost before validating, committing, or
  publishing a qualifying OD fact; candidate estimates and prefilter distances are not solved
  costs.

## Ledger handoff

For each retained non-self pair, provide the ledger the following expected logical identity:

```text
logical_od_key = (origin_h3_id, destination_h3_id)
work_unit = (dataset_fingerprint, origin_h3_id, deterministic_destination_batch)
```

- Reuse compatible committed logical keys.
- Resume an existing recoverable logical key under its existing work lifecycle.
- Plan a new key only when compatible evidence is absent or the key is invalidated.
- Leave terminal failures unscheduled unless they are explicitly invalidated.
- Associate duplicate/recovered candidates by logical key, never by output filename.
- Do not schedule self-pairs or prefilter-pruned pairs as route-solving work.

## Reconciliation and metrics

Report scope and candidate dispositions from the [data model](../data-model.md). Expected retained
non-self keys must partition into compatible committed reuse, recoverable existing work, terminal
failures left unscheduled, and newly planned/invalidated work, with each key appearing once.
Solved results then partition by actual cutoff outcome and other Feature 003 solve classifications.
Counts and pruning ratio must match the contract formulas; no target pruning ratio is defined.

Any configured scope or batch limit that is exceeded must end the build explicitly incomplete.
The planner must not silently drop cells or expected pair keys.

Resolved candidate limits and their source, inference-policy version, cutoff/reach inputs, and
prefilter error bound are part of run provenance and the behavior fingerprint. Feature 003 must
restore the saved values on resume rather than infer them again; changed explicit overrides must
create a distinct run or fail clearly.
