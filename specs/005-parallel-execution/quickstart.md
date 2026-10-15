# Quickstart: Parallel Execution Validation

This guide validates Feature 005 against the Feature 002–004 contracts. It does not require a
production network for portable coordinator and lifecycle tests.

## Prerequisites

- Use the project Conda environment with Python 3.11 or later and pytest.
- ArcPy and Network Analyst are required only for real network/probe integration tests.
- Provide the same candidate plan, representative inputs, and result-affecting solve settings when
  comparing serial and parallel outputs.
- Ensure tests write only to temporary test directories and geodatabases.

## Portable Test Scenarios

From the repository root, run the focused execution and lifecycle tests:

```powershell
pytest testing/test_od_execution_config.py testing/test_od_execution.py testing/test_od_execution_preparation.py testing/test_od_execution_workers.py testing/test_od_execution_probe.py testing/test_od_ledger.py testing/test_od_solver.py testing/test_publication_validation.py
```

Expected results:

- Serial and parallel fixtures reconcile to identical directed logical-key sets, classifications,
  units, and canonical costs.
- Non-ArcPy preparation normalizes existing bounded work items and representative inputs without
  changing candidate scope, key identity, batch membership, or ledger state; concurrent preparation
  preserves canonical output order, uses no more than two active units, buffers no more than two
  prepared payloads awaiting lease/dispatch, applies backpressure, and reports failures explicitly.
- The coordinator alone leases, stages, validates, commits, reconciles, and hands results to
  publication.
- Workers receive bounded serializable assignments and isolated scratch locations.
- Spawned ArcPy workers receive only their bounded assignment and cannot access the ledger or
  publication API. The coordinator accepts each response under current fencing evidence.
- Lease expiry, stale worker results, cancellation, crashes, invalid output, and runtime fallback
  cannot produce duplicate or missing committed logical keys.
- Probe levels descend to a passing lower count, or produce an observable serial fallback when no
  level of at least two succeeds.
- The resolved ArcPy process ceiling is `min(max_workers, os.cpu_count() or 1)`; tests cover
  CPU-count limits and unavailable CPU-count fallback. Non-ArcPy preparation remains bounded to
  two concurrent units regardless of this process ceiling.
- Explicit serial mode, `parallel_solving.enabled: false`, or a CPU-resolved process ceiling below
  two skips the probe and concurrent ArcPy workers but retains eligible parallel non-ArcPy
  preparation, with tests verifying concurrency when at least two units are eligible. Null or
  absent configuration is treated as enabled and runs the probe when work exists and the process
  ceiling is at least two.
- Failed probe fallback uses serial network solves while non-ArcPy preparation remains concurrent;
  tests verify this when at least two units are eligible, preparation failures remain explicit, and
  the bounded payload buffer is respected.
- Compatible committed work is reused without starting a probe when no new solve work remains.
- Per-part integrity checks run with at most two concurrent workers by default, retain deterministic
  diagnostic ordering, and return failures to the publication owner so atomic publication is
  blocked.

## ArcPy Capability and Network Tests

In an ArcGIS Pro environment with the configured network dataset and Network Analyst available:

```powershell
pytest testing/test_real_network_dataset.py
```

The real-network integration test includes the configured capability probe and a small bounded
solve in isolated child processes. Probe outputs remain temporary and do not appear in the Feature
003 ledger or Feature 004 publication. If ArcPy, the network, representative locations, or the
required license is unavailable, the integration test reports/skips that environmental prerequisite
rather than treating it as successful probe evidence.

## Full Regression

```powershell
pytest
```

Expected results: Features 002–004 retain their candidate selection, durable lifecycle, and
publication behavior. Parallel execution introduces no GeoPandas dependency/use, no worker writes
to final partitions or the ledger, and no changes to the Feature 003 compatibility fingerprint.

For record field ownership and validation, see [data-model.md](data-model.md). For coordinator and
worker boundaries, see [contracts/parallel-execution.md](contracts/parallel-execution.md).
