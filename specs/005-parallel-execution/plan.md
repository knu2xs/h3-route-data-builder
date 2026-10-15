# Implementation Plan: Parallel Execution

**Branch**: `005-parallel-execution` | **Date**: 2026-10-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-parallel-execution/spec.md`

## Summary

Add a coordinator-controlled execution layer that runs the existing bounded Feature 003 solve
work either in-process or in isolated ArcPy worker processes. Keep Feature 003 leases, fencing,
staging, validation, commits, and reconciliation authoritative in both modes. Before dispatching
parallel solves, probe the configured network and actual Network Analyst license configuration;
step down to the highest tested concurrency that succeeds, otherwise fall back observably to
serial. An explicit `parallel_solving.enabled: false` disables the probe and parallel solves; a
null or missing setting means enabled. Preserve the Feature 002 candidate plan and Feature 004
publication contract.

## Technical Context

**Language/Version**: Python 3.13 in ArcGIS Pro; project minimum Python 3.11.

**Primary Dependencies**: Existing ArcPy/Network Analyst adapter, Feature 002–004 OD models and
contracts, and Python standard-library process primitives. No package dependency addition is
planned. GeoPandas remains prohibited.

**Storage**: Existing Feature 003 SQLite-backed durable ledger and immutable result parts remain
authoritative. Child processes write only to per-assignment temporary scratch geodatabases; the
coordinator alone stages and commits results.

**Testing**: pytest. Coordinator policy, probe selection, result acceptance, cancellation,
fallback, and reconciliation tests remain ArcPy-free through injected process/solver boundaries.
ArcPy process initialization and actual network/license capability tests are optional integration
tests in the ArcGIS Pro environment.

**Target Platform**: ArcGIS Pro / `arcgispro-py3` on Windows. Spawned workers initialize ArcPy and
Network Analyst independently; the portable coordinator and ledger remain testable outside ArcGIS
Pro.

**Project Type**: Python package supporting an ArcGIS Pro geoprocessing pipeline.

**Performance Goals**: No fixed throughput target. Keep work assignments, queued results, probe
attempts, process count, and shutdown time bounded. ArcPy process concurrency cannot exceed
configured and CPU-resolved ceilings or successful probe evidence. Resolve the ArcPy process
worker ceiling as `min(max_workers, os.cpu_count() or 1)`; when CPU count is unavailable, use a
ceiling of one. Non-ArcPy preparation uses at most two active units and at most two prepared
payloads waiting for lease/dispatch, independent of the ArcPy process ceiling. Work items must be
streamed through this bounded window rather than fully materialized.

**Constraints**: Preserve existing public serial behavior and signatures. Candidate selection,
work identity and state transitions, and publication remain owned by Features 002, 003, and 004.
Processes receive serializable work only; scratch is unique per active worker/attempt; worker
output is non-authoritative. Probe and runtime fallback are observable. No change to result
compatibility fingerprint semantics and no GeoPandas use.

**Scale/Scope**: National-scale runs stream Feature 003's bounded work items through a preparation
window without materializing the full expected-key, preparation-payload, or result set in memory.
At most two prepared payloads may wait for lease/dispatch; the coordinator limits in-flight
assignments to effective worker capacity and reconciles every expected key through the durable
ledger.

**Execution configuration**: `parallel_solving.enabled` is disabled only by explicit `false`;
null or absent means enabled. `parallel_solving.max_workers` is a positive ceiling with a
conservative default of 2. Resolve the effective worker ceiling to the lesser of configured
`max_workers` and the logical CPU count returned by `os.cpu_count()`; use one when that API returns
`None`. This CPU-resolved limit applies to ArcPy worker processes. Probe timeout and
graceful-shutdown allowance are positive bounded settings with conservative implementation
defaults. Record configured and resolved ceilings as run provenance, not as result-compatibility
inputs. Eligible non-ArcPy preparation uses standard-library concurrency capped at two active units
and two prepared payloads waiting for lease/dispatch. With at least two eligible units, preparation
must execute concurrently, including during explicit serial solving, disabled parallel solving,
and capability/runtime fallback. This is unaffected by the ArcPy worker ceiling or parallel-solve
enablement.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Before Research

- **I. Explicit semantics**: PASS. Enablement, worker ceiling, probe step-down, fallback mode,
  solve identity, and durable authority are explicit; execution settings do not alter costs.
- **II. Builder ArcPy geometry boundary**: PASS. ArcPy remains inside network/geoprocessing
  worker code; coordination, lease acceptance, and tests are portable and ArcPy-free.
- **III. Sparse correctness**: PASS. Only Feature 002 retained keys and Feature 001 solvable
  representatives are dispatched.
- **IV. Immutable reproducibility**: PASS. Workers cannot modify authoritative parts; execution
  provenance is separate from compatibility identity.
- **V. Idempotent resumability**: PASS. Feature 003 leases, fencing, staging, validation, commit,
  retries, and reconciliation are unchanged and used in either mode.
- **VI. Approximation transparency**: PASS. Only existing actual network solve outcomes are sent
  for acceptance; probe output is discarded.
- **VII. Bounded execution**: PASS. Worker count, assignments, probing, and shutdown are bounded;
  Feature 002 batch sizes remain authoritative.
- **VIII. Builder interoperability**: PASS. Feature 004 publication and GeoParquet stay
  unchanged; no GeoPandas dependency or use is introduced.
- **IX. Observable operation**: PASS. Probe attempts, selected/effective mode, fallback causes,
  worker outcomes, and reconciled counts are reported.
- **X. Testable contracts**: PASS. Portable equivalence, isolation, fencing, probe, failure,
  and fallback behavior have measurable acceptance tests; real-network checks are environment
  gated.
- **XI. Serial reference path first**: PASS. The serial path remains the logical reference and
  shared acceptance path.
- **XII. Deterministic representatives**: PASS. Workers consume Feature 001's representative
  inputs without recalculating them.
- **XIII. Durable work lifecycle**: PASS. The coordinator alone owns leases, stage acceptance,
  commit, and reconciliation; the ledger remains outside worker scratch.
- **XIV. Isolated workers**: PASS. ArcPy solving uses isolated processes and unique scratch;
  parallel solving requires a bounded real-network/license probe and falls back to serial while
  eligible non-ArcPy preparation remains concurrent, including explicit serial mode.
- **XV. Publish atomically**: PASS. Feature 004 remains the only publication owner and receives
  only compatible committed outcomes.
- **XVI. Complete Pro tool documentation**: PASS. The plan adds internal execution policy and no
  new toolbox tool or user-visible toolbox parameter.
- **XVII. Resource-Aware Execution Limits**: PASS. The configured worker ceiling is further
  bounded by available resources and probe evidence; Feature 001/002 resolved limits are
  preserved and not recalculated or fingerprinted here.

No pre-research gate violations.

## Project Structure

### Documentation (this feature)

```text
specs/005-parallel-execution/
├── plan.md
├── research.md
├── data-model.md
├── contracts/
│   └── parallel-execution.md
├── quickstart.md
└── tasks.md             # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/h3_route_data_builder/
├── od/
│   ├── solving.py       # Existing serial lifecycle; preserve public behavior
│   ├── execution.py     # Coordinator, process policy, probe, fallback
│   ├── preparation.py  # Bounded deterministic non-ArcPy preparation
│   ├── ledger.py        # Existing Feature 003 authority; no worker access
│   ├── candidates.py    # Existing Feature 002 plan; unchanged
│   └── models.py        # Existing candidate/work records; extend only if needed
└── network/
    └── solver.py        # Existing ArcPy solve adapter; child-side initialization

testing/
├── test_od_execution.py         # Portable coordinator and equivalence tests
├── test_od_execution_preparation.py # Parallel preparation equivalence and failure tests
├── test_od_execution_probe.py   # Probe selection, failure, and fallback tests
├── test_od_ledger.py            # Existing Feature 003 lifecycle and fencing tests
├── test_od_solver.py            # Existing solver adapter tests
├── test_publication_validation.py # Parallel local immutable-part validation tests
└── test_real_network_dataset.py # Optional configured network/license integration
```

**Structure Decision**: Add the execution coordinator to the existing `od` package and reuse the
existing solver adapter in `network`. Put deterministic bounded non-ArcPy preparation in its own
portable `od/preparation.py` module so it can run concurrently in serial-solve fallback without
sharing edits or state with the solve coordinator. Stream existing bounded work items through a
two-unit preparation window; apply backpressure when two prepared payloads await lease/dispatch.
Keep the worker entry point in the ArcPy boundary and pass only serializable work records into
spawned processes. Preserve existing serial function signatures by routing both execution modes
through the same coordinator acceptance and commit logic. Keep Feature 002 planning, Feature 003
ledger semantics, and Feature 004 publication unchanged.

## Phase 0: Research

Research decisions and alternatives are recorded in [research.md](research.md). The architecture
uses the repository's existing solver/ledger boundaries and Python's process facilities; no
dependency additions are required.

## Phase 1: Design

- [data-model.md](data-model.md) defines execution policy, probe evidence, work assignments,
  transient worker output, scratch ownership, and coordinator summary.
- [contracts/parallel-execution.md](contracts/parallel-execution.md) defines the internal
  coordinator/worker protocol, probe step-down, validation, fallback, and authority boundaries.
- [quickstart.md](quickstart.md) provides focused portable and ArcPy integration validation.

## Constitution Check (Post-Design)

- **Principles I–X**: PASS. Configuration and units remain explicit, ArcPy is isolated to
  network work, candidate sparsity is unchanged, results remain immutable and resumable, execution
  is bounded and observable, GeoParquet interoperability is preserved, and tests cover the
  coordinator/worker contract without requiring ArcPy.
- **Principles XI–XVII**: PASS. Serial remains the correctness reference; deterministic
  representatives and Feature 003 durable lifecycle remain authoritative; worker isolation and
  probe/fallback are mandatory; serial-solve modes retain parallel non-ArcPy preparation per
  Principle XIV; Feature 004 publication remains atomic; no toolbox interface is added; and process
  capacity is bounded by configured, CPU-resolved, and probe limits.

No post-design constitution violations.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations.
