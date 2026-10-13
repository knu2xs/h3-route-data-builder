# Quickstart: Resumable OD Solving

This guide is the acceptance path for Feature 003's durable solve lifecycle. It validates the
portable ledger and mocked adapter contracts independently from ArcPy, then optionally exercises
the actual solve adapter against a configured read-only network dataset.

## Prerequisites

- Use the project development environment; use ArcGIS Pro `arcgispro-py3` for the optional real
  Network Analyst solve test.
- The real-network tests default to the Feature 001 StreetMap Premium 2025 dataset at
  `D:\data\ba_data\usa_2025\Data\StreetMap Premium Data\northamerica.geodatabase\main.Routing\main.Routing_ND`.
  Set `H3_RDB_TEST_NETWORK` only to override that local path. Tests create and remove temporary
  in-memory points and write solve scratch only under a pytest temporary directory; they do not
  modify the source network dataset.
- Use the Feature 002 expected-key and bounded-batch contract.
- See the [data model](data-model.md) and [solver-ledger contract](contracts/solver-ledger.md).

## Run portable lifecycle and recovery tests

From the repository root:

```powershell
.\env\python.exe -m pytest testing/test_od_ledger.py testing/test_od_solver.py testing/test_od_candidate_ledger.py -q
```

Expected outcomes:

- Logical OD keys are direction-sensitive and independent of work IDs.
- Work IDs are deterministic from compatibility identity, origin, and bounded destination batch.
- Legal transitions are enforced; expiry and retry move work through recoverable or terminal
  failure without recording a fabricated route result.
- Reclaim changes fencing evidence; stale owners cannot stage, validate, or commit.
- Incomplete, duplicate, unexpected, invalid-cost, invalid-unit, and incompatible staged results
  are rejected without changing committed outcomes.
- Compatible committed keys are reused across AOI coverage and batch changes; missing keys are
  scheduled once; incompatible results are not reused.
- Reconciliation uses expected logical keys and durable state; worker status and stray files never
  count as completion.

## Verify restart safety at every lifecycle boundary

Use fault injection to terminate and recreate the process after each durable boundary:

1. Work item and expected keys persisted as planned.
2. Lease acquired.
3. Solving state persisted.
4. Solve output staged.
5. Stage validated.
6. Immutable result part written but before authoritative ledger commit.
7. Commit persisted but before caller acknowledgement.

For each restart, compare the reconciled logical outcomes to an uninterrupted reference run.
Expected: no expected result is lost, no logical key has duplicate active outcomes, pre-commit
orphan parts remain non-authoritative, and a repeated acknowledged commit is idempotent.

## Run Network Analyst adapter tests

The same `test_od_solver.py` command above includes portable mocked-ArcPy adapter tests for
representative fields, time units, all-destination solving, cutoff classification, location
statuses, and isolated scratch coordination. Run it with the project interpreter for the portable
checks. In ArcGIS Pro, the real-network adapter smoke test uses the Feature 001 default path above.
If ArcPy cannot resolve the dataset, pytest reports the unavailable path as the skip reason.

```powershell
.\env\python.exe -m pytest testing/test_od_solver.py testing/test_od_candidate_geometry.py -q
```

Expected outcomes:

- Only Feature 001 solvable endpoints and their deterministic representatives reach Network
  Analyst.
- Network Analyst location status distinguishes unlocated endpoints from reachable no-route
  outcomes. The adapter solves without applying its own impedance cutoff, sets output units from
  the configured cost unit, and classifies returned actual costs against the configured cutoff.
- Unlocated and unreachable outcomes are retained as diagnostics but excluded from the final
  result dataset. Cutoff-excluded outcomes and system failures are not qualifying route facts.
- Serial solve results and portable expected-key reconciliation agree on the complete fixture.

## Verify Feature 004 publication handoff

After solve reconciliation:

- Provide only authoritative, validated committed outcomes to publication.
- Confirm each expected key is represented by one durable outcome and qualifying results contain
  actual network costs only.
- Run Feature 004's publication and format validation separately; Feature 003 does not own the
  published file layout, manifest schema, or `_SUCCESS` behavior.
