# Data Model: Sparse OD Candidates

This document defines the feature's logical records and validation invariants. It does not select
the durable ledger storage format.

## Solvable Cell Reference

| Field | Meaning | Validation |
|---|---|---|
| `h3_id_hex` | Canonical lowercase hexadecimal H3 cell identifier | Valid at the build resolution and unique after canonicalization |
| `resolution` | H3 resolution | Matches the build's configured resolution |
| `eligibility_status` | Feature 001 outcome | Must be `solvable` for either endpoint |
| `cell_geometry` | Canonical cell polygon | Valid geometry in a declared spatial reference |
| `representative` | Deterministic point on an eligible edge | Present, finite, in WGS 84 / EPSG:4326 |

The reference is supplied by Feature 001; candidate generation does not alter eligibility,
representative selection, or its evidence.

## Candidate Scope

| Field | Meaning | Validation |
|---|---|---|
| `mode` | `aoi_only` or `aoi_to_surrounding` | Required supported mode |
| `resolution` | Configured H3 resolution for this build | Integer from 0 through 15; every endpoint ID and Feature 001 cell record matches |
| `aoi_geometry` | Validated polygonal AOI | Non-empty, valid, WGS 84 / EPSG:4326 per Feature 001 |
| `origin_ids` | Ordered set of in-AOI solvable cells | Unique canonical IDs; each cell polygon intersects AOI under the configured policy |
| `destination_ids` | Ordered set of solvable destination cells | AOI-only: equals `origin_ids`; surrounding: polygon intersects expanded AOI |
| `reach_distance` | Cutoff-derived conservative spatial reach | Finite, nonnegative, geodesic meters |
| `maximum_origin_offset` | Greatest geodesic distance from any origin representative to the nearest point on the AOI geometry | Finite, nonnegative, geodesic meters; zero for a point within the AOI |
| `expanded_aoi` | AOI expanded by reach plus maximum origin offset | Includes the original AOI; surrounding destinations selected by polygon intersection |

AOI-only mode uses `origin_ids = destination_ids`. Surrounding mode forms `expanded_aoi` by
geodesically expanding the AOI by `reach_distance + maximum_origin_offset`. The maximum offset is
zero when there are no in-AOI origins; an empty origin set yields no candidates. Spatial geometry
uses Feature 001's WGS 84 / EPSG:4326 contract; no analysis CRS is configurable.

## Directed OD Candidate

| Field | Meaning | Validation |
|---|---|---|
| `origin_h3_id` | Ordered origin endpoint | Must reference a solvable cell in `origin_ids` |
| `destination_h3_id` | Ordered destination endpoint | Must reference a solvable cell in `destination_ids` |
| `logical_od_key` | Composite `(origin_h3_id, destination_h3_id)` | Deterministic and unique; endpoint order is significant |
| `disposition` | `self_resolved`, `prefilter_pruned`, `ledger_reused`, `ledger_resume`, `terminal_failure`, `planned`, or post-solve result | Must follow contract transitions |
| `straight_line_lower_bound` | Conservative geodesic representative-to-representative separation for non-self pairs | Meters; missing/invalid values cannot prune |
| `prefilter_distance_error_bound_m` | Caller-asserted upper bound on absolute measurement error for representative separation | If present, finite and nonnegative meters; absent means retain the pair |
| `network_result` | Actual solved network distance/time and solve classification | Present only after route solve; cutoff is evaluated against configured actual network cost |

The logical key excludes build fingerprint and destination batch. The ledger scopes key
compatibility by the build fingerprint and associates expected keys with Feature 003 work units.
An origin self-pair has zero cost and disposition `self_resolved`; it never enters network
solving. A pruned candidate remains part of the measured scoped pair universe but is excluded
from expected network work.

When both the configured error bound and distance measurement are valid, the conservative lower
bound used for pruning is
`max(0, measured_distance_m - prefilter_distance_error_bound_m)`. Prune only if that value is
strictly greater than the finite cutoff-derived reach. The caller is responsible for supplying a
defensible bound; software validates its form, not its accuracy. A present negative or non-finite
configured error bound fails validation. When the bound is absent or the distance measurement is
invalid, retain the pair and increment the unbounded-prefilter-retention count. The configured
bound and cutoff/reach inputs are candidate-policy provenance and behavior-fingerprint inputs.

## Ledger Work Reference

| Field | Meaning | Validation |
|---|---|---|
| `dataset_fingerprint` | Identity of network, policy, schema, and software inputs | Must match the compatible ledger evidence |
| `origin_h3_id` | Work-unit origin | Must match each expected pair's origin |
| `destination_batch` | Bounded deterministic batch of destination IDs | Order is deterministic; expected logical keys are explicit |
| `work_id` | Feature 003 durable work-unit identity | Derived under Feature 003's fingerprint/origin/batch rules |
| `state` | Planned/leased/solving/staged/validated/committed or failure state | Governed by Feature 003 lifecycle |
| `expected_logical_od_keys` | Retained non-self logical pairs represented by the work unit | No duplicate pair key; pruned and self-pairs are excluded |

Changes in destination scope may move a logical pair between batches. Compatible committed
evidence is reconciled by logical OD key, not by batch ID or filenames.

## Candidate Summary Metrics

For origin count `O` and destination count `D`, `scope_pair_count = O * D`. In AOI-to-surrounding
mode the origin set is contained in the destination set because the expanded AOI includes the
AOI; in AOI-only mode the sets are equal.

| Metric | Definition |
|---|---|
| `self_pair_count` | Number of origin IDs; zero in an empty scope |
| `non_self_prefilter_input_count` | `scope_pair_count - self_pair_count` |
| `prefilter_pruned_count` | Non-self pairs whose lower bound is strictly greater than conservative reach |
| `prefilter_retained_count` | Non-self prefilter input minus pruned count |
| `prefilter_unbounded_retained_count` | Retained non-self pairs for which no valid distance measurement or measurement-error bound was available |
| `prefilter_pruning_ratio` | Pruned count / non-self prefilter input count; zero for zero denominator |
| `ledger_reused_count` | Retained pairs with compatible committed evidence |
| `ledger_resumed_count` | Retained pairs already represented by recoverable, uncommitted work |
| `ledger_terminal_count` | Retained pairs left in a terminal failure state and not rescheduled |
| `newly_planned_count` | Retained pairs absent from compatible evidence or explicitly invalidated |
| `solved_result_count` | Pairs with a completed network result in this run |
| `cutoff_excluded_count` | Solved results whose actual configured network cost exceeds cutoff |
| `rejected_endpoint_reference_count` | Invalid/missing/non-solvable endpoint references, classified by reason |

Counts must reconcile to the corresponding scope, retained-work, and solve sets. The pruning ratio
is descriptive and has no target threshold. Actual network cutoff classification is performed on
the post-solve network cost before a result can be committed or published as qualifying output.
