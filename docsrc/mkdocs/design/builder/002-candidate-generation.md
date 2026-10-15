# Feature 002: Sparse OD Candidates

With Feature 006, origin/destination IDs and directed keys are integers ordered numerically.
Invalid identity types and resolution mismatches cannot enter scheduled work.
This versioned representation cutover does not redefine the candidate policies below.

AOI-only mode uses intersecting solvable cells as both origins and destinations. AOI-to-surrounding mode uses solvable origins inside the AOI and solvable destinations inside a conservatively expanded area.

## Requirements

- Both endpoints must exist in the solvable-cell table.
- Preserve directionality and deterministic keys.
- Materialize self-pairs without a network solve.
- Apply straight-line prefiltering before solving.
- Require a conservative spatial radius or documented speed bound for time-cutoff builds.
- Apply the actual network cutoff after solving.
- Partition work by solvable origin and bounded destination batches.
- Schedule only missing or invalidated pairs.
- Report measured sparsity and pruning ratios without assuming a fixed reduction.

## Acceptance

No unsolvable H3 appears in work; validation fixtures show no in-cutoff route was improperly prefiltered; all planned states reconcile.
