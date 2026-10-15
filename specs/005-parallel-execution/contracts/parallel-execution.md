# Parallel Execution Contract

This internal contract connects the Feature 005 coordinator to Feature 003's durable work
lifecycle and the builder's ArcPy network-solve boundary. It does not define a public API or alter
candidate, ledger, or publication contracts.

## Coordinator Inputs

- Feature 002's bounded plan and expected directed logical OD keys.
- Feature 001's solvable-cell records and deterministic representative locations.
- Feature 003's durable ledger, work items, lease operations, fencing, validation, and commit
  operations.
- Feature 003-compatible network, travel mode, restrictions, cost, cutoff, and result settings.
- Feature 005 execution policy, including the effective worker ceiling and bounded probe and
  shutdown timeouts.
- Deterministic bounded non-ArcPy preparation inputs for solve assignments.

The coordinator owns work scheduling, lease acquisition/renewal, result acceptance, failure
handling, reconciliation, and handoff to Feature 004.

## Shared Serial and Parallel Lifecycle

Both execution modes use the same ordered lifecycle:

1. Obtain Feature 003's existing bounded work items and Feature 001 representative inputs
   incrementally; do not materialize the full work plan.
2. Normalize those existing inputs into immutable, serializable solve payloads using bounded
   non-ArcPy concurrency of at most two units; do not change candidates, keys, batch membership, or
   ledger state. Preserve canonical ordering and report preparation failures to the coordinator.
   Hold at most two completed payloads while awaiting lease/dispatch, and apply backpressure when
   that buffer is full. When at least two units are eligible, preparation runs concurrently in all
   solve modes.
3. Acquire the next prepared item's lease and current fencing value through the coordinator.
4. Execute only the network solve for that bounded assignment.
5. Return bounded outcome records to the coordinator.
6. Check work identity, compatibility, exact expected logical keys, and current fencing evidence.
7. Use the existing Feature 003 staging, validation, classification, and atomic commit path.
8. Reconcile expected logical keys through Feature 003; hand only authoritative committed
   outcomes to Feature 004.

Serial mode invokes the solve operation in the coordinator process. Parallel mode invokes it in an
isolated process. The independent non-ArcPy preparation remains parallel in both modes, including
explicit serial mode, explicit parallel-solve disablement, and capability/runtime fallback. The
result acceptance path and Feature 003 state transitions do not vary by execution mode. Existing
public serial entry points retain their signatures and semantics.

## Worker Assignment and Result

Each assignment contains one Feature 003 work item, the current lease/fencing evidence, its exact
expected logical keys, compatible network settings, serializable deterministic representatives,
and a unique assignment scratch location. A worker must not receive live ArcPy objects, ledger
handles, publication handles, or authority to renew leases.

A worker is launched using the explicit Python `spawn` process context and an importable
module-level entry point. It initializes ArcPy and Network Analyst in its own process, exercises
license access there, executes the bounded solve using the supplied representatives, and returns
bounded per-key outcomes tagged with work ID, compatibility fingerprint, attempt, and fencing
value. Worker results remain non-authoritative.

The coordinator rejects a result if its assignment is no longer current, any key is missing,
unexpected, or duplicated, or any outcome fails Feature 003 validation. Only the coordinator
stages and commits accepted results. A worker cannot write the ledger, shared scratch, final
partitions, publication references, or completion markers.

## Capability Probe

When parallel solving is enabled and expected work exists:

1. Select safe representative inputs from the current compatible work plan.
2. Resolve the ArcPy resource worker ceiling as `min(max_workers, os.cpu_count() or 1)`; if the
   resulting ceiling is below two, skip probing and record serial selection.
3. For the resolved worker ceiling, start that many isolated probe workers with unique scratch
   workspaces and run a small non-authoritative solve against the configured network and actual
   Network Analyst license environment.
4. Require each worker to initialize, access the network, acquire the required license, complete
   the bounded solve, and return a valid result for its expected probe key.
5. On failure, record a structured reason and try the next lower worker count, stopping at the
   first passing count or after testing two workers.
6. Use the highest passing concurrency. If no count of at least two passes, or safe probe inputs
   are unavailable, record the reason and use serial execution when available.

Probe inputs and output are temporary; they never enter Feature 003 or Feature 004. The probe is
skipped when parallel solving is explicitly disabled or no work is expected. A null or absent
`parallel_solving.enabled` setting means enabled. Skipping or failing the probe only disables
parallel network solving; eligible independent non-ArcPy preparation remains parallel.

## Runtime Failure and Cancellation

On cancellation or a runtime failure that disables parallel solving, the coordinator stops new
dispatch and requests worker shutdown. It waits only for the configured grace period before
terminating an unresponsive worker. Results already returned are still accepted only when
Feature 003's current lease and fencing checks permit them.

Incomplete in-flight work is fenced or allowed to expire through Feature 003 and retried serially
when eligible. Failure of the serial retry remains visible as a Feature 003 retryable or terminal
failure; fallback cannot turn it into success. Worker scratch is cleaned only after the owning
process stops and cleanup is safe.

## Resource and Isolation Invariants

- Active solve concurrency never exceeds the configured ceiling, the resource-resolved ceiling,
  or the highest concurrency established by the probe.
- The resource-resolved ceiling is the minimum of configured `max_workers` and the logical CPU
  count returned by `os.cpu_count()`; an unavailable count resolves to one and prevents probing.
- Independent non-ArcPy preparation runs at most two units concurrently, preserves canonical
  ordering, and remains available for every serial network-solve mode regardless of the ArcPy
  process ceiling or `parallel_solving.enabled`.
- Each worker/attempt has a collision-safe unique scratch directory and geodatabase.
- The network source is read-only to workers.
- Work dispatch and returned outcomes are bounded by Feature 003 work-item limits.
- Any independent non-ArcPy preparation or local immutable-artifact check may run concurrently
  only when deterministic and isolated. Candidate scope, ledger lifecycle, full-key
  reconciliation, aggregate publication validation, and publication remain coordinator-owned.

## Observable Completion

The execution summary records requested/effective mode, probe attempts and result, selected worker
count, fallback reason, assignment counts, cancellation/failure counts, and Feature 003
reconciliation totals. Counts must reconcile to coordinator-issued work and expected logical keys.
Process exit status, filenames, scratch output, and worker-reported success are never completion
evidence.
