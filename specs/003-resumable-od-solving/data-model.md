# Data Model: Resumable OD Solving

This document defines the durable identity, lifecycle, and reconciliation records for Feature 003.
It does not select a storage engine, serialization format, or publication format.

## Result Compatibility Identity

The compatibility identity is a versioned canonical identity over values that change whether a
solved pair outcome is meaningful or valid.

| Input | Compatibility requirement |
|---|---|
| Network dataset identity and version | Must match |
| Travel mode and restrictions | Must match |
| Network cost attribute, units, and cost semantics | Must match |
| Actual-cost cutoff and outcome-classification policy | Must match |
| H3 resolution and endpoint eligibility | Must match |
| Deterministic endpoint representatives and their network-location identity | Must match |
| Result schema compatibility version | Must match |
| Relevant software compatibility versions | Must match |
| AOI geometry and derived coverage | Provenance only; do not alone prevent reuse |
| Feature 002 candidate policy/provenance | Provenance only; expected keys govern reuse |
| Destination batch boundaries | Work identity input; not a logical result identity |
| Resolved execution limits and inference-policy provenance | Per-run provenance; do not alone prevent reuse |

An implementation may reject reuse when it cannot prove compatibility. It must not claim
compatibility merely because the logical key matches.

## Logical OD Key

| Field | Meaning | Validation |
|---|---|---|
| `origin_h3_id` | Directed origin endpoint | Canonical H3 identity; Feature 001 status is solvable |
| `destination_h3_id` | Directed destination endpoint | Canonical H3 identity; Feature 001 status is solvable |
| `logical_od_key` | Ordered `(origin_h3_id, destination_h3_id)` pair | Direction-sensitive; unique per active result |

The logical key excludes compatibility fingerprint, work ID, batch, attempt, lease, and output
location. Self-pairs and prefilter-pruned pairs are resolved/excluded by Feature 002 and are not
network solve work.

## Work Item

| Field | Meaning | Validation |
|---|---|---|
| `work_id` | Deterministic durable work identity | Fingerprint + origin + canonical bounded batch |
| `compatibility_fingerprint` | Identity of result-affecting inputs | Versioned; excludes AOI and execution limits |
| `origin_h3_id` | Single origin for this unit | Must match each expected key's origin |
| `destination_batch` | Feature 002 bounded, deterministic batch | Canonical H3 order; determines work ID |
| `expected_logical_od_keys` | Retained non-self pair keys to resolve | Unique; endpoints match the work item |
| `state` | Current durable lifecycle state | One legal state and transition |
| `attempt_count` | Number of lease attempts | Monotonic; subject to bounded retry policy |
| `fencing_value` | Current ownership generation | Changes on reclaim/invalidation; stale values fail |
| `lease` | Optional current owner and expiry | Required while leased/solving; checked on mutations |
| `staged_reference` | Optional isolated output reference | Non-authoritative until validated and committed |
| `committed_reference` | Optional immutable part referenced by ledger | Present only after atomic commit |
| `failure_evidence` | Failure class and diagnostic provenance | Preserved across attempts; not a route outcome |

Retrying retains the deterministic work ID while advancing attempt and fencing evidence.
Invalidation makes prior committed evidence non-authoritative without modifying its immutable
content. An explicitly rescheduled invalidated item can enter `planned` again.

## Work State and Legal Transitions

| Current state | Allowed next state(s) |
|---|---|
| `planned` | `leased`, `terminal_failure`, `invalidated` |
| `leased` | `solving`, `retryable_failure`, `terminal_failure`, `invalidated` |
| `solving` | `staged`, `retryable_failure`, `terminal_failure`, `invalidated` |
| `staged` | `validated`, `retryable_failure`, `terminal_failure`, `invalidated` |
| `validated` | `committed`, `retryable_failure`, `terminal_failure`, `invalidated` |
| `retryable_failure` | `planned`, `terminal_failure`, `invalidated` |
| `committed` | `invalidated` |
| `terminal_failure` | `invalidated` |
| `invalidated` | `planned` only when explicitly rescheduled and still expected |

An expired lease in `leased` or `solving` is recorded as a retryable failure, then returned to
`planned` if attempts remain or marked terminal when the bounded retry policy is exhausted.
Lease expiry invalidates the old fencing value before another owner is accepted.

## Lease

| Field | Meaning | Validation |
|---|---|---|
| `owner_id` | Worker or coordinator identity holding the lease | Non-empty |
| `expires_at` | Lease expiration instant | Finite and durable |
| `fencing_value` | Ownership generation | Must be current for mutations and stage acceptance |

Lease renewal may extend the expiration only when the submitted owner and fencing value are
current. Reclaim advances the fencing value. Workers cannot validate or commit their own output.

## Staged Result

| Field | Meaning | Validation |
|---|---|---|
| `logical_od_key` | Pair represented by this outcome | Must be exactly one expected key |
| `classification` | Outcome classification | One of the allowed values listed below |
| `actual_cost` | Actual network cost, when applicable | Finite, nonnegative, configured units; cutoff checked first |
| `attempt/fencing evidence` | Ownership at solve/stage time | Current or coordinator-verified on recovery |
| `result provenance` | Compatibility and stage integrity evidence | Must match and validate against the work |

Allowed classifications are `qualifying`, `unlocated`, `unreachable`, and `cutoff_excluded`.

For each work item, staged keys must equal the complete expected-key set: no missing,
unexpected, or duplicate logical keys. `unlocated` and `unreachable` may be retained separately
for diagnostics, but are equivalent unroutable outcomes and are excluded from the final dataset.
`cutoff_excluded` is computed from actual cost and is not a qualifying route fact. A system
failure is a work failure, not a fabricated per-key successful result.

## Committed Result Part

A committed part contains immutable validated outcome rows. The ledger records the authoritative
reference to the part and the logical keys it resolves at one atomic commit point. Unreferenced
staged content is not authoritative. The active compatible result set has no duplicate logical
keys; a conflicting commit is rejected unless an earlier result was explicitly invalidated and
atomically superseded.

## Run Provenance and Reconciliation

Run provenance records the AOI/candidate scope, candidate policy, batch assignment, resolved
execution limits and their sources, retry policy, and software details needed to explain how work
was performed. These values do not alone prevent pair-result reuse.

For the Feature 002 expected key set, reconciliation places every key into exactly one effective
disposition:

- Compatible committed outcome (including qualifying, unroutable, or cutoff-excluded).
- Existing recoverable work (planned, leased, solving, staged, validated, or retryable).
- Durable terminal failure.
- Missing or explicitly invalidated work to schedule once.
- Unresolved work awaiting state recovery.

Only the coordinator's durable references and states count. File names, orphan staged artifacts,
and process status do not establish completion. Reconciliation distinguishes all-success from
complete-with-terminal-failures.
