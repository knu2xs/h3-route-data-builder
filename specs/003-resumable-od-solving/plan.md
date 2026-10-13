# Implementation Plan: Resumable OD Solving

**Branch**: `003-resumable-od-solving` | **Date**: 2026-10-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-resumable-od-solving/spec.md`

## Summary

Implement the durable lifecycle for Feature 002's directed, retained, non-self candidate pairs.
Keep logical OD identity independent from bounded work-item identity, protect work ownership with
expiring fenced leases, and make the coordinator the only authority that can validate and commit
isolated worker output. Resume and AOI expansion reconcile expected logical keys against
result-compatible committed evidence, not batch names, files, or worker status.

Use the existing portable OD candidate models/reconciliation and eligibility atomic-staging
patterns where their contracts fit. Separate result compatibility from run provenance: route
outcomes are reusable when their result-affecting inputs are compatible, while candidate limits,
batch assignment, and other run-specific settings remain auditable without alone preventing reuse.
The behavior contract remains storage-engine-neutral; the initial local implementation uses the
Python standard-library SQLite backend to provide transactional key claims and atomic commit
without adding a dependency. Do not prescribe the publication format, alter candidate generation,
or redefine parallel worker policy.

## Technical Context

**Language/Version**: Python 3.13 in ArcGIS Pro; project minimum Python 3.11.

**Primary Dependencies**: ArcPy / Network Analyst for route solving; H3 v4 and existing package
models for cell identity; existing project utilities; pytest. No dependency addition is planned.

**Storage**: The ledger behavior and serialization contract remain storage-engine-neutral. The
initial implementation uses SQLite transactions for durable work records, immutable result-part
payloads, and unique active logical-key claims. Worker scratch is isolated and non-authoritative.
The ledger provides one atomic, durable commit point for publishing a result-part reference and
claiming its expected logical keys.

**Testing**: pytest. Lifecycle, identity, fingerprint compatibility, lease fencing, and
reconciliation tests must run without ArcPy. Network solve tests use synthetic ArcPy/Network
Analyst fixtures and are marked/skipped when ArcPy is unavailable.

**Target Platform**: ArcGIS Pro / `arcgispro-py3`; portable non-spatial state and ledger logic is
testable outside ArcGIS Pro.

**Project Type**: Python package supporting an ArcGIS Pro geoprocessing pipeline.

**Performance Goals**: Process candidate pairs in Feature 002's bounded per-origin destination
batches; do not introduce an unbounded in-memory expected-key/result set. No fixed throughput or
runtime target is specified.

**Constraints**: Ledger is durable and outside worker scratch. Only the coordinator commits.
Actual network costs and cutoff classification govern qualifying outcomes. No ArcPy imports in
portable ledger, identity, or reconciliation code. Preserve Features 002, 004, and 005 boundaries.

**Scale/Scope**: National-scale candidate plans may be interrupted and resumed. Work item size is
bounded by Feature 002; test datasets are small, synthetic, and cover each lifecycle boundary.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Before Research

- **I. Explicit semantics**: PASS. Directed key identity, result-affecting compatibility,
  explicit actual-cost cutoff classification, units, retry state, and run provenance are defined.
- **II. Builder ArcPy geometry boundary**: PASS. Feature 003 consumes Feature 001 representatives.
  Non-spatial lifecycle, ledger, fingerprint, and reconciliation logic remains ArcPy-free; ArcPy
  is confined to network solving.
- **III. Sparse correctness**: PASS. Only Feature 002 retained non-self keys can enter solve work;
  endpoints must be Feature 001 solvable cells.
- **IV. Immutable reproducibility**: PASS. Committed solve parts are immutable and identified by
  compatibility/provenance; incompatible result inputs cannot reuse prior outcomes.
- **V. Idempotent resumability**: PASS. Deterministic work IDs, durable states, fenced leases,
  validated staging, atomic commit, and expected-key reconciliation are required.
- **VI. Approximation transparency**: PASS. Only actual network costs can qualify; unlocated,
  unreachable, and cutoff-excluded cases are not qualifying route facts.
- **VII. Bounded execution**: PASS. Solve work uses the bounded batches from Feature 002 and a
  bounded retry policy; no new unbounded candidate expansion is introduced.
- **VIII. Interoperability**: PASS. Feature 003 hands validated solve outcomes downstream and does
  not change Feature 004's output contract or format.
- **IX. Observable operation**: PASS. Durable transition, retry, lease, invalidation,
  classification, validation, commit, and reconciled-count evidence is required.
- **X. Testable contracts**: PASS. The data model, internal ledger handoff, and quickstart define
  portable and ArcPy-dependent acceptance coverage, including crash/restart fault injection.
- **XI. Serial reference path first**: PASS. A serial coordinator/solver path is the reference;
  parallel execution remains governed by Feature 005.
- **XII. Deterministic representatives**: PASS. Solver inputs are the existing validated Feature
  001 representatives; no representative selection is added here.
- **XIII. Durable work lifecycle**: PASS. States, lease expiry/reclaim, coordinator ownership,
  failure classes, reconciliation, and durable ledger ownership are central requirements.
- **XIV. Isolated workers**: PASS. Worker scratch is isolated; capability probing and fallback
  behavior remain Feature 005 responsibilities.
- **XV. Publish atomically**: PASS. Feature 003 atomically commits immutable solve parts to its
  durable ledger; Feature 004 remains responsible for published dataset staging and `_SUCCESS`.
- **XVI. Complete Pro tool documentation**: PASS. No new exposed toolbox class or parameter is
  required by this internal lifecycle feature.
- **XVII. Resource-aware execution limits**: PASS. Feature 002's resolved limits and provenance
  remain recorded for each run but, as clarified, do not alone prevent reuse of result-compatible
  route outcomes. Feature 003 introduces no competing execution-limit resolver.

No pre-research gate violations.

## Project Structure

### Documentation (this feature)

```text
specs/003-resumable-od-solving/
├── plan.md
├── research.md
├── data-model.md
├── contracts/
│   └── solver-ledger.md
├── quickstart.md
└── tasks.md             # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/h3_route_data_builder/
├── od/
│   ├── candidates.py    # Existing Feature 002 candidate and ledger handoff
│   ├── models.py       # Existing portable candidate records
│   ├── ledger.py       # Durable lifecycle, work identity, lease and reconciliation
│   ├── results.py      # Outcome validation and compatibility identity
│   └── solving.py      # Serial coordinator and isolated solve orchestration
└── network/
    └── solver.py       # ArcPy/Network Analyst solve adapter

testing/
├── test_od_candidate_ledger.py  # Existing Feature 002 handoff tests
├── test_od_ledger.py            # Portable lifecycle and recovery tests
└── test_od_solver.py            # ArcPy-marked solve adapter tests
```

**Structure Decision**: Extend the existing `od` package, keeping ledger and reconciliation
portable and placing ArcPy-specific route execution under `network`. The coordinator bridges the
candidate handoff, solver adapter, durable ledger, and immutable staged result parts. Exact module
splits may be adjusted during implementation without changing these contracts. SQLite is an
initial backend choice, not part of the feature's storage-engine-neutral contract.

## Constitution Check

### Post-Design

- **Principles I-XVII**: PASS. The data model separates compatibility identity from run
  provenance, the internal contract defines atomic commit and fencing without naming a storage
  engine, and the quickstart requires portable lifecycle tests plus ArcPy-gated network checks.
- **Ownership boundaries**: PASS. Feature 002 retains candidate scope and batching; Feature 003
  owns durable solve work and classifications; Feature 004 owns publication; Feature 005 owns
  parallel capability and fallback policy.
- **Complexity**: PASS. The design uses one coordinator/ledger contract and a solver boundary; no
  storage abstraction hierarchy, parallel executor, or new dependency is specified.

No post-design gate violations.

## Complexity Tracking

No constitution violations or unjustified complexity.
