"""Acceptance tests for the durable OD work ledger."""

from pathlib import Path
import sqlite3

import pytest

from h3_route_data_builder.od.ledger import ODLedger, WorkState, make_work_id
from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome


def _outcome(
    origin: str = "origin",
    destination: str = "destination",
    cost: float = 8.0,
    unit: str = "m",
    classification: OutcomeClass = OutcomeClass.QUALIFYING,
) -> SolveOutcome:
    return SolveOutcome(
        logical_od_key=(origin, destination),
        classification=classification,
        actual_cost=cost,
        cost_unit=unit,
    )


def _planned_ledger(
    tmp_path: Path, max_attempts: int = 3
) -> tuple[ODLedger, str, tuple[tuple[str, str], ...]]:
    ledger = ODLedger(tmp_path / "ledger.sqlite", max_attempts=max_attempts)
    keys = (("origin", "destination"),)
    work = ledger.plan_work("fingerprint", "origin", ("destination",), 10.0, "m")
    return ledger, work.work_id, keys


def test_work_id_is_deterministic_and_sensitive_to_identity_inputs() -> None:
    base = make_work_id("fingerprint", "origin", ("b", "a"))

    assert base == make_work_id("fingerprint", "origin", ("a", "b"))
    assert base != make_work_id("other-fingerprint", "origin", ("a", "b"))
    assert base != make_work_id("fingerprint", "other-origin", ("a", "b"))
    assert base != make_work_id("fingerprint", "origin", ("a", "c"))


def test_ledger_commit_survives_restart_and_is_idempotent(tmp_path: Path) -> None:
    ledger, work_id, keys = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker-1", 30.0, now=100.0)
    ledger.start_solving(work_id, lease, now=101.0)
    ledger.stage_results(work_id, lease, [_outcome()], now=102.0)
    ledger.validate_staged(work_id)

    part_id = ledger.commit(work_id)
    reopened = ODLedger(tmp_path / "ledger.sqlite")

    assert reopened.get_work(work_id).state is WorkState.COMMITTED
    assert reopened.commit(work_id) == part_id
    assert reopened.committed_outcomes("fingerprint") == (_outcome(),)
    assert (
        tuple(
            item.logical_od_key for item in reopened.committed_outcomes("fingerprint")
        )
        == keys
    )


def test_commit_transaction_rolls_back_part_and_key_claim_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker-1", 30.0, now=100.0)
    ledger.start_solving(work_id, lease, now=101.0)
    ledger.stage_results(work_id, lease, [_outcome()], now=102.0)
    ledger.validate_staged(work_id)
    original_transition = ledger._transition

    def interrupt_after_commit_transition(*args, **kwargs):
        original_transition(*args, **kwargs)
        if args[3] is WorkState.COMMITTED:
            raise OSError("simulated process failure inside commit transaction")

    monkeypatch.setattr(ledger, "_transition", interrupt_after_commit_transition)
    with pytest.raises(OSError, match="simulated process failure"):
        ledger.commit(work_id)

    recovered = ODLedger(tmp_path / "ledger.sqlite")
    assert recovered.get_work(work_id).state is WorkState.VALIDATED
    assert recovered.committed_outcomes("fingerprint") == ()
    assert recovered.commit(work_id)
    assert recovered.committed_outcomes("fingerprint") == (_outcome(),)


def test_nonqualifying_committed_outcomes_are_not_route_facts(tmp_path: Path) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    work = ledger.plan_work(
        "fingerprint",
        "origin",
        ("destination-1", "destination-2", "destination-3"),
        10.0,
        "m",
    )
    lease = ledger.acquire_lease(work.work_id, "worker", 30.0, now=100.0)
    ledger.start_solving(work.work_id, lease, now=101.0)
    outcomes = (
        _outcome(destination="destination-1"),
        _outcome(
            destination="destination-2",
            cost=11.0,
            classification=OutcomeClass.CUTOFF_EXCLUDED,
        ),
        SolveOutcome(
            logical_od_key=("origin", "destination-3"),
            classification=OutcomeClass.UNREACHABLE,
            actual_cost=None,
            cost_unit=None,
        ),
    )
    ledger.stage_results(work.work_id, lease, outcomes, now=102.0)
    ledger.validate_staged(work.work_id)
    ledger.commit(work.work_id)

    assert len(ledger.committed_outcomes("fingerprint")) == 3
    assert len(ledger.qualifying_outcomes("fingerprint")) == 1


def test_expired_lease_is_reclaimed_and_stale_worker_cannot_stage(
    tmp_path: Path,
) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path)
    stale = ledger.acquire_lease(work_id, "worker-1", 5.0, now=100.0)
    ledger.start_solving(work_id, stale, now=101.0)
    with pytest.raises(RuntimeError, match="stale or expired"):
        ledger.fail(work_id, stale, "system_failure", "late failure", now=106.0)
    assert ledger.get_work(work_id).state is WorkState.SOLVING

    current = ledger.acquire_lease(work_id, "worker-2", 10.0, now=106.0)

    assert current.fencing_value > stale.fencing_value
    with pytest.raises(RuntimeError, match="stale"):
        ledger.stage_results(work_id, stale, [_outcome()], now=107.0)


def test_lease_renewal_extends_expiry_without_weakening_fencing(tmp_path: Path) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker-1", 5.0, now=100.0)

    renewed = ledger.renew_lease(work_id, lease, 20.0, now=103.0)

    assert renewed.fencing_value == lease.fencing_value
    assert renewed.expires_at == 123.0
    assert ledger.get_work(work_id).lease == renewed


def test_persisted_staged_result_is_revalidated_after_restart(tmp_path: Path) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker-1", 30.0, now=100.0)
    ledger.start_solving(work_id, lease, now=101.0)
    ledger.stage_results(work_id, lease, [_outcome()], now=102.0)

    reopened = ODLedger(tmp_path / "ledger.sqlite")
    reopened.recover_staged(work_id)

    assert reopened.get_work(work_id).state is WorkState.VALIDATED
    assert reopened.commit(work_id)


def test_staged_result_with_stale_fencing_evidence_returns_to_retry(
    tmp_path: Path,
) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker-1", 30.0, now=100.0)
    ledger.start_solving(work_id, lease, now=101.0)
    ledger.stage_results(work_id, lease, [_outcome()], now=102.0)
    with sqlite3.connect(ledger.database_path) as connection:
        connection.execute(
            """
            UPDATE work_items SET staged_fencing_value = staged_fencing_value + 1
            WHERE work_id = ?
            """,
            (work_id,),
        )

    with pytest.raises(ValueError, match="fencing"):
        ledger.recover_staged(work_id)

    assert ledger.get_work(work_id).state is WorkState.RETRYABLE_FAILURE
    assert ledger.committed_outcomes("fingerprint") == ()


def test_invalidation_withdraws_only_its_fingerprint_and_allows_reschedule(
    tmp_path: Path,
) -> None:
    ledger = ODLedger(tmp_path / "ledger.sqlite")
    first = ledger.plan_work("fp-1", "origin", ("destination",), 10.0, "m")
    second = ledger.plan_work("fp-2", "origin", ("destination",), 10.0, "m")
    for item in (first, second):
        lease = ledger.acquire_lease(item.work_id, "worker", 30.0, now=100.0)
        ledger.start_solving(item.work_id, lease, now=101.0)
        ledger.stage_results(item.work_id, lease, [_outcome()], now=102.0)
        ledger.validate_staged(item.work_id)
        ledger.commit(item.work_id)

    ledger.invalidate(first.work_id, "network source was corrected")

    assert ledger.committed_outcomes("fp-1") == ()
    assert ledger.committed_outcomes("fp-2") == (_outcome(),)
    assert ledger.get_work(first.work_id).state is WorkState.INVALIDATED
    ledger.reschedule_invalidated(first.work_id, still_expected=True)
    assert ledger.acquire_lease(first.work_id, "worker-2", 30.0, now=200.0)


@pytest.mark.parametrize(
    "outcomes",
    [
        [],
        [_outcome(classification=OutcomeClass.UNREACHABLE, cost=None)],
        [_outcome(unit="s")],
        [
            _outcome(),
            _outcome(destination="destination"),
        ],
        [_outcome(destination="unexpected")],
        [
            _outcome(
                cost=12.0,
                classification=OutcomeClass.QUALIFYING,
            )
        ],
    ],
)
def test_invalid_staged_results_never_commit(
    tmp_path: Path, outcomes: list[SolveOutcome]
) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker-1", 30.0, now=100.0)
    ledger.start_solving(work_id, lease, now=101.0)
    ledger.stage_results(work_id, lease, outcomes, now=102.0)

    with pytest.raises(ValueError):
        ledger.validate_staged(work_id)

    assert ledger.get_work(work_id).state is WorkState.RETRYABLE_FAILURE
    assert ledger.committed_outcomes("fingerprint") == ()


def test_every_restart_boundary_has_durable_state_evidence(tmp_path: Path) -> None:
    states = (
        (WorkState.PLANNED, None),
        (WorkState.LEASED, "lease"),
        (WorkState.SOLVING, "solve"),
        (WorkState.STAGED, "stage"),
        (WorkState.VALIDATED, "validate"),
        (WorkState.COMMITTED, "commit"),
    )
    for index, (expected_state, action) in enumerate(states):
        ledger = ODLedger(tmp_path / f"boundary-{index}.sqlite")
        work = ledger.plan_work("fingerprint", "origin", ("destination",), 10.0, "m")
        lease = None
        if action:
            lease = ledger.acquire_lease(work.work_id, "worker", 30.0, now=100.0)
        if action in {"solve", "stage", "validate", "commit"}:
            ledger.start_solving(work.work_id, lease, now=101.0)
        if action in {"stage", "validate", "commit"}:
            ledger.stage_results(work.work_id, lease, [_outcome()], now=102.0)
        if action in {"validate", "commit"}:
            ledger.validate_staged(work.work_id)
        if action == "commit":
            ledger.commit(work.work_id)

        recovered = ODLedger(tmp_path / f"boundary-{index}.sqlite")
        assert recovered.get_work(work.work_id).state is expected_state


def test_retry_limit_turns_expired_work_into_terminal_failure(tmp_path: Path) -> None:
    ledger, work_id, _ = _planned_ledger(tmp_path, max_attempts=1)
    ledger.acquire_lease(work_id, "worker-1", 1.0, now=100.0)

    with pytest.raises(RuntimeError, match="terminal"):
        ledger.acquire_lease(work_id, "worker-2", 1.0, now=102.0)

    assert ledger.get_work(work_id).state is WorkState.TERMINAL_FAILURE


def test_retry_policy_is_persisted_and_cannot_change_on_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "ledger.sqlite"
    ODLedger(database_path, max_attempts=2)

    with pytest.raises(ValueError, match="retry policy persisted"):
        ODLedger(database_path, max_attempts=3)

    assert ODLedger(database_path, max_attempts=2).max_attempts == 2
