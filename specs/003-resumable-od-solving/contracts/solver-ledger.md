# Solver and Ledger Handoff Contract

This is an internal contract between Feature 002 candidate planning, Feature 003 solve
coordination, and Feature 004 publication. It does not prescribe an external API or storage
engine.

## Inputs

- Feature 002's expected retained non-self directed logical OD keys, per-origin deterministic
  bounded destination batches, candidate policy, and run provenance.
- Feature 001's solvable-cell records and deterministic network representatives with compatible
  network-location identity.
- Result-affecting network, travel mode/restrictions, cost attribute and units, cutoff and
  classification policy, schema compatibility, and software compatibility inputs.
- A bounded retry policy and lease policy. Their exact limits are implementation choices and are
  recorded with the run.

## Identity and compatibility

```text
logical_od_key = (origin_h3_id, destination_h3_id)
work_id = deterministic_id(compatibility_fingerprint, origin_h3_id, canonical_destination_batch)
```

- Logical OD key order is significant and independent of work identity.
- Work ID is deterministic for the same result-compatibility fingerprint, origin, and bounded
  batch.
- Batch/execution policy and AOI scope remain run provenance and do not alone prevent reuse.
- Compare every expected logical key with compatible authoritative outcomes, even when prior
  work used different batches. The expected key set limits the candidate set; compatible outcomes
  outside the current expected set are not current-run results.
- A changed result-affecting input prevents reuse unless compatibility is explicitly established.

## Lifecycle

```text
planned -> leased -> solving -> staged -> validated -> committed
                 \-> retryable_failure -> planned
                 \-> terminal_failure
any nonterminal state -> invalidated
committed or terminal_failure -> invalidated
invalidated -> planned only by explicit rescheduling
```

The full legal transition matrix is in the [data model](../data-model.md). Each lease carries an
owner, expiry, and fencing value. Reclaim changes the fencing value before accepting a new owner.
Every worker state change and output submission checks the current fencing value. Only the
coordinator may validate and commit.

## Solve and stage

- Solve each retained non-self expected key using only its Feature 001 deterministic origin and
  destination representatives.
- Isolate each worker's temporary solve output. Scratch artifacts are never authoritative.
- Stage a complete bounded result set, then validate the exact expected-key set and each row's
  endpoint identity, compatibility, classification, cost, and units.
- Reject staged output with any missing, duplicate, unexpected, invalid, or stale-fenced key.
- Classify actual-cost cutoff outcomes only after solving.
- Record unlocated/unreachable diagnostics distinctly if available, but exclude both from final
  output. Exclude cutoff-excluded outcomes and system failures from qualifying route facts.

## Commit and recovery

- The coordinator commits only validated staged results.
- Immutable result content becomes authoritative only through one durable commit point that
  records its part reference and unique logical-key ownership atomically.
- An interruption before that point leaves no active committed result. A retry or restart may
  verify/adopt durable staged content only after rechecking its fingerprint, fence, complete key
  set, integrity, and outcome validity.
- Repeating the same commit is idempotent. A conflicting active result for the same key is
  rejected unless the prior result was explicitly invalidated and atomically superseded.
- A worker exit, result filename, or unreferenced part never establishes completion.

## Reconciliation and counts

For the expected key set, report compatible committed outcomes, recoverable states, retryable
failures, terminal failures, unresolved keys, and newly scheduled keys separately. Each expected
key appears once in the effective disposition. Complete-with-failures is distinct from
all-success completion. Feature 004 receives only validated authoritative solve results and owns
the final published schema, layout, manifests, and `_SUCCESS` marker.

## Ownership boundaries

- **Feature 001**: eligibility and deterministic network representatives.
- **Feature 002**: candidate scope, prefilter, expected logical keys, and deterministic bounded
  batches.
- **Feature 003**: durable solve ledger, work IDs, leases/fencing, solve outcomes, result staging,
  commit, and reconciliation.
- **Feature 004**: final dataset publication format and publication completion.
- **Feature 005**: concurrency capability probe, parallel-worker policy, and fallback.
