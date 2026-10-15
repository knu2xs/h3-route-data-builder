"""Acceptance tests for the durable OD work ledger."""

from pathlib import Path
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from h3_route_data_builder.od.ledger import ODLedger, WorkItem, WorkState, make_work_id
from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome


@pytest.mark.parametrize("version", [None, "1", "2"])
@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_legacy_or_inconsistent_ledger_is_rejected_without_mutation(
    tmp_path: Path,
    version: str | None,
    journal_mode: str,
) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA journal_mode = {journal_mode}")
        connection.execute(
            "CREATE TABLE ledger_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        if version is not None:
            connection.execute(
                "INSERT INTO ledger_metadata VALUES ('format_version', ?)", (version,)
            )
        connection.execute("CREATE TABLE work_items (origin_h3_id TEXT NOT NULL)")
        connection.execute("INSERT INTO work_items VALUES ('8928308280fffff')")
    connection.close()
    before = path.read_bytes()
    before_names = {item.name for item in tmp_path.iterdir()}

    with pytest.raises(ValueError, match="fresh|rebuild"):
        ODLedger(path)

    assert path.read_bytes() == before
    assert {item.name for item in tmp_path.iterdir()} == before_names


def test_integer_storage_and_json_restore_are_exact(tmp_path: Path) -> None:
    ledger, work_id, keys = _planned_ledger(tmp_path)
    lease = ledger.acquire_lease(work_id, "worker", 30, now=100)
    ledger.start_solving(work_id, lease, now=101)
    ledger.stage_results(work_id, lease, [_outcome()], now=102)
    ledger.validate_staged(work_id)
    ledger.commit(work_id)
    with sqlite3.connect(ledger.database_path) as connection:
        assert connection.execute(
            "SELECT typeof(origin_h3_id), typeof(destination_h3_id) FROM active_outcomes"
        ).fetchone() == ("integer", "integer")
        assert connection.execute("SELECT typeof(origin_h3_id) FROM work_items").fetchone() == (
            "integer",
        )
        assert connection.execute(
            "SELECT value FROM ledger_metadata WHERE key = 'format_version'"
        ).fetchone() == ("2",)
    assert ODLedger(ledger.database_path).get_work(work_id).expected_logical_od_keys == keys
    assert all(type(endpoint) is int and endpoint > 2**53 for endpoint in keys[0])


def test_greatest_valid_cells_round_trip_through_sqlite_at_every_resolution(
    tmp_path: Path,
    integer_h3_cells: tuple[int, ...],
) -> None:
    ledger = ODLedger(tmp_path / "all-resolutions.sqlite")
    expected = set()
    for resolution in range(16):
        destination, origin = integer_h3_cells[resolution * 4 + 2 : resolution * 4 + 4]
        item = ledger.plan_work("all-resolutions", origin, (destination,), 10, "m")
        lease = ledger.acquire_lease(item.work_id, "worker", 30, now=100)
        ledger.start_solving(item.work_id, lease, now=101)
        ledger.stage_results(item.work_id, lease, [_outcome(origin, destination)], now=102)
        ledger.validate_staged(item.work_id)
        ledger.commit(item.work_id)
        expected.add((origin, destination))
    reopened = ODLedger(ledger.database_path)
    assert {
        outcome.logical_od_key for outcome in reopened.committed_outcomes("all-resolutions")
    } == expected


def test_legacy_preflight_reads_durable_wal_without_changing_source_files(tmp_path: Path) -> None:
    path = tmp_path / "legacy-wal.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("CREATE TABLE ledger_metadata (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO ledger_metadata VALUES ('format_version', '1')")
        connection.commit()
        before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
        with pytest.raises(ValueError, match="format version is not 2"):
            ODLedger(path)
        assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


def test_work_id_uses_version_two_integer_encoding(integer_work_item: WorkItem) -> None:
    item = integer_work_item
    identity = {
        "version": 2,
        "compatibility_fingerprint": item.compatibility_fingerprint,
        "origin_h3_id": item.origin_h3_id,
        "destination_batch": item.destination_batch,
    }
    expected = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert (
        make_work_id(item.compatibility_fingerprint, item.origin_h3_id, item.destination_batch)
        == expected
    )
    identity["version"] = 1
    assert (
        expected
        != hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_restore_rejects_textual_json_endpoint_without_coercion(tmp_path: Path) -> None:
    ledger, work_id, keys = _planned_ledger(tmp_path)
    with sqlite3.connect(ledger.database_path) as connection:
        connection.execute(
            "UPDATE work_items SET expected_keys_json = ? WHERE work_id = ?",
            (json.dumps([[str(keys[0][0]), keys[0][1]]]), work_id),
        )
    with pytest.raises(ValueError, match="H3"):
        ledger.get_work(work_id)
    with pytest.raises(ValueError, match="H3"):
        ledger.evidence()


def _outcome(
    origin: int = 619056821839593471,
    destination: int = 619056559457304575,
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
) -> tuple[ODLedger, str, tuple[tuple[int, int], ...]]:
    ledger = ODLedger(tmp_path / "ledger.sqlite", max_attempts=max_attempts)
    keys = ((619056821839593471, 619056559457304575),)
    work = ledger.plan_work("fingerprint", 619056821839593471, (619056559457304575,), 10.0, "m")
    return ledger, work.work_id, keys


def test_work_id_is_deterministic_and_sensitive_to_identity_inputs() -> None:
    base = make_work_id("fingerprint", 619056821839593471, (619056559456780287, 619056559456255999))

    assert base == make_work_id(
        "fingerprint", 619056821839593471, (619056559456255999, 619056559456780287)
    )
    assert base != make_work_id(
        "other-fingerprint", 619056821839593471, (619056559456255999, 619056559456780287)
    )
    assert base != make_work_id(
        "fingerprint", 619056821839855615, (619056559456255999, 619056559456780287)
    )
    assert base != make_work_id(
        "fingerprint", 619056821839593471, (619056559456255999, 619056559457042431)
    )


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
    assert tuple(item.logical_od_key for item in reopened.committed_outcomes("fingerprint")) == keys


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
        619056821839593471,
        (619056559457828863, 619056559465168895, 619056821831991295),
        10.0,
        "m",
    )
    lease = ledger.acquire_lease(work.work_id, "worker", 30.0, now=100.0)
    ledger.start_solving(work.work_id, lease, now=101.0)
    outcomes = (
        _outcome(destination=619056559457828863),
        _outcome(
            destination=619056559465168895,
            cost=11.0,
            classification=OutcomeClass.CUTOFF_EXCLUDED,
        ),
        SolveOutcome(
            logical_od_key=(619056821839593471, 619056821831991295),
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
    first = ledger.plan_work("fp-1", 619056821839593471, (619056559457304575,), 10.0, "m")
    second = ledger.plan_work("fp-2", 619056821839593471, (619056559457304575,), 10.0, "m")
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
            _outcome(destination=619056559457304575),
        ],
        [_outcome(destination=617700169958293503)],
        [
            _outcome(
                cost=12.0,
                classification=OutcomeClass.QUALIFYING,
            )
        ],
    ],
)
def test_invalid_staged_results_never_commit(tmp_path: Path, outcomes: list[SolveOutcome]) -> None:
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
        work = ledger.plan_work("fingerprint", 619056821839593471, (619056559457304575,), 10.0, "m")
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
        if expected_state in {WorkState.PLANNED, WorkState.LEASED, WorkState.SOLVING}:
            lease = recovered.acquire_lease(work.work_id, "recovery-worker", 30, now=200)
            recovered.start_solving(work.work_id, lease, now=201)
            recovered.stage_results(work.work_id, lease, [_outcome()], now=202)
            recovered.recover_staged(work.work_id)
        elif expected_state is WorkState.STAGED:
            recovered.recover_staged(work.work_id)
        part_id = recovered.commit(work.work_id)
        assert recovered.commit(work.work_id) == part_id
        final = ODLedger(recovered.database_path)
        assert final.committed_outcomes("fingerprint") == (_outcome(),)
        assert (
            len({outcome.logical_od_key for outcome in final.committed_outcomes("fingerprint")})
            == 1
        )


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
