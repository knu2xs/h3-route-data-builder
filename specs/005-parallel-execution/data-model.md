# Data Model: Parallel Execution

This model describes the transient execution records for Feature 005. Feature 003 remains the
authority for durable work identity, states, leases, fencing, staged results, and commits.

## Execution Policy

| Field | Meaning | Validation |
|---|---|---|
| `parallel_solving.enabled` | Whether parallel network solving may be attempted | Explicit `false` disables it; null or absent means enabled |
| `max_workers` | Upper bound on requested concurrent ArcPy solve processes | Positive integer; further limited by CPU resources and probe evidence |
| `resource_worker_ceiling` | CPU-resolved upper bound on ArcPy worker processes | `min(max_workers, os.cpu_count() or 1)` |
| `effective_worker_ceiling` | Maximum ArcPy process count permitted for this run | No greater than configured and resource ceilings or successful probe evidence |
| `preparation_worker_ceiling` | Maximum concurrent non-ArcPy preparation units | `min(2, eligible_preparation_units)`; independent of parallel-solve enablement and CPU process ceiling |
| `prepared_payload_buffer_ceiling` | Maximum completed prepared payloads waiting for lease/dispatch | 2 units; apply backpressure when full |
| `shutdown_grace_s` | Maximum graceful-shutdown wait before forced worker termination | Positive bounded duration |
| `probe_timeout_s` | Maximum duration allowed for a probe attempt | Positive bounded duration |

If `os.cpu_count()` returns `None`, the ArcPy process worker ceiling is one and the system selects
serial network solving with an observable reason without probing. Resolved ceilings are execution
provenance and do not change Feature 003 result compatibility or logical OD identity. The
parallel-solve enablement setting does not disable eligible non-ArcPy preparation: that preparation
remains parallel when network solving runs serially.

## Prepared Solve Input

A prepared solve input is an immutable, serializable normalization of an existing bounded
Feature 003 work item and its Feature 001 representative inputs. Preparation MUST preserve the
work-item identity, expected logical OD keys, and canonical ordering. It MUST NOT select or remove
candidates, alter batch membership, acquire or modify leases, or write ledger state. Preparation
uses at most two concurrent non-ArcPy units. Work items are consumed incrementally; at most two
completed payloads may wait for lease/dispatch, and preparation pauses when that buffer is full.
With at least two eligible units, preparation runs concurrently even when network solving is
explicitly serial, disabled, or falls back after a failed probe.

## Execution Summary

One coordinator-owned summary describes one execution attempt.

| Field | Meaning |
|---|---|
| `requested_mode` | Operator or caller request: serial or parallel |
| `effective_mode` | Mode actually used after disablement, probing, or fallback |
| `probe_report` | Probe attempts, tested concurrency, outcomes, and failure reasons |
| `fallback_reason` | Structured reason or null if fallback did not occur |
| `work_counts` | Dispatched, completed, cancelled, failed, retried, and reconciled work counts |
| `preparation_counts` | Bounded non-ArcPy preparation items completed or failed |
| `key_counts` | Feature 003 logical outcome totals for the expected key set |

Counts are reconciled to coordinator-issued assignments and Feature 003 state. A process exit code
or worker-reported success is not a completion signal.

## Capability Probe

### Probe Attempt

Each attempt tests one concurrency level using isolated child processes and temporary work derived
from safe representative inputs in the current compatible plan.

| Field | Meaning | Validation |
|---|---|---|
| `worker_count` | Number of concurrent probe processes | Between two and the effective configured ceiling |
| `status` | Attempt result | Passed, failed, timed out, or inconclusive |
| `worker_evidence` | Initialization, network-access, license, and bounded-solve results | One result per probe worker |
| `failure_reason` | Structured cause, if not passed | Non-empty for failed/timed-out/inconclusive attempt |
| `elapsed_s` | Attempt duration | Finite and within the configured probe timeout |

### Probe Report

The report records attempts in descending order from the effective worker ceiling, selected
concurrency if any, and a reason for serial fallback when none succeeds. Probe scratch and outcomes
are temporary and never become committed solve results.

## Work Assignment

A coordinator-issued assignment wraps, but does not redefine, one Feature 003 work item.

| Field | Meaning | Validation |
|---|---|---|
| `work_id` | Feature 003 deterministic work-item ID | Matches the durable ledger item |
| `compatibility_fingerprint` | Feature 003 result compatibility identity | Matches the planned work |
| `lease_owner` | Coordinator-held Feature 003 owner identity | Current when assignment is dispatched |
| `fencing_value` | Current Feature 003 ownership generation | Rechecked before stage/commit |
| `attempt` | Durable attempt number | Matches ledger |
| `expected_logical_od_keys` | Ordered directed keys for this bounded batch | Exactly the ledger item's keys |
| `representatives` | Feature 001 deterministic network locations for endpoints | Serializable and validated against the keys |
| `network_inputs` | Network identity and solve-affecting settings | Compatible with the work fingerprint |
| `scratch_location` | Unique worker/attempt scratch root | Not shared with another active assignment or final output |

The coordinator acquires and renews the lease. The assignment only carries evidence required for
execution and coordinator-side acceptance.

## Worker Result

Worker output is transient until the coordinator submits it to Feature 003.

| Field | Meaning | Validation |
|---|---|---|
| `work_id` | Assignment identity | Exact match |
| `compatibility_fingerprint` | Result compatibility identity | Exact match |
| `attempt` / `fencing_value` | Ownership evidence | Must still be current when accepted |
| `logical_od_keys` | Keys represented in the output | Exact, duplicate-free match to expected keys |
| `outcomes` | Per-key classifications and actual costs | Valid under Feature 003 classification and units |
| `worker_diagnostics` | Non-authoritative execution evidence | Bounded and associated with the assignment |

Workers cannot update Feature 003 state, reconcile expected keys, or commit output. Invalid, stale,
missing, unexpected, or duplicate-key results are rejected by the coordinator's existing Feature
003 path.

## Worker Scratch Workspace

Each active worker assignment owns a unique temporary directory and geodatabase. Scratch contains
only that attempt's intermediates and is never authoritative. Cleanup occurs only after the worker
has stopped and cleanup is safe. A worker cannot write to the durable ledger, shared scratch, final
partition, publication reference, or completion marker.

## State and Relationships

- One execution summary covers the coordinator's requested and effective policy and all work it
  dispatches.
- One probe report contains zero or more probe attempts; zero attempts is valid when the run is
  serial, parallel solving is explicitly disabled, or the expected work set is empty.
- One work assignment refers to exactly one current Feature 003 work item and lease.
- One worker result reports exactly that assignment's expected logical-key set.
- Feature 003 owns all durable lifecycle state. Feature 004 consumes only compatible committed
  outcomes and owns dataset publication.
