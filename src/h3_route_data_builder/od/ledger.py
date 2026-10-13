"""Portable SQLite-backed durable lifecycle for directed OD solve work."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from typing import Any
from uuid import uuid4

from h3_route_data_builder.od.models import LedgerEvidence
from h3_route_data_builder.od.results import (
    OutcomeClass,
    SolveOutcome,
    validate_outcome,
)
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

LogicalODKey = tuple[str, str]


class WorkState(StrEnum):
    """Durable state for one deterministic bounded work item."""

    PLANNED = "planned"
    LEASED = "leased"
    SOLVING = "solving"
    STAGED = "staged"
    VALIDATED = "validated"
    COMMITTED = "committed"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class Lease:
    """Fenced, expiring ownership token."""

    owner_id: str
    expires_at: float
    fencing_value: int


@dataclass(frozen=True)
class FailureEvidence:
    """Durable failure reason associated with a work item."""

    classification: str
    message: str
    recorded_at: float


@dataclass(frozen=True)
class WorkItem:
    """Persisted work identity, expected keys, and lifecycle state."""

    work_id: str
    compatibility_fingerprint: str
    origin_h3_id: str
    destination_batch: tuple[str, ...]
    expected_logical_od_keys: tuple[LogicalODKey, ...]
    cutoff: float
    cost_unit: str
    state: WorkState
    attempt_count: int
    fencing_value: int
    lease: Lease | None
    committed_part_id: str | None
    failure_evidence: FailureEvidence | None


_ALLOWED_TRANSITIONS: dict[WorkState, set[WorkState]] = {
    WorkState.PLANNED: {
        WorkState.LEASED,
        WorkState.TERMINAL_FAILURE,
        WorkState.INVALIDATED,
    },
    WorkState.LEASED: {
        WorkState.SOLVING,
        WorkState.RETRYABLE_FAILURE,
        WorkState.TERMINAL_FAILURE,
        WorkState.INVALIDATED,
    },
    WorkState.SOLVING: {
        WorkState.STAGED,
        WorkState.RETRYABLE_FAILURE,
        WorkState.TERMINAL_FAILURE,
        WorkState.INVALIDATED,
    },
    WorkState.STAGED: {
        WorkState.VALIDATED,
        WorkState.RETRYABLE_FAILURE,
        WorkState.TERMINAL_FAILURE,
        WorkState.INVALIDATED,
    },
    WorkState.VALIDATED: {
        WorkState.COMMITTED,
        WorkState.RETRYABLE_FAILURE,
        WorkState.TERMINAL_FAILURE,
        WorkState.INVALIDATED,
    },
    WorkState.RETRYABLE_FAILURE: {
        WorkState.PLANNED,
        WorkState.TERMINAL_FAILURE,
        WorkState.INVALIDATED,
    },
    WorkState.TERMINAL_FAILURE: {WorkState.INVALIDATED},
    WorkState.COMMITTED: {WorkState.INVALIDATED},
    WorkState.INVALIDATED: {WorkState.PLANNED},
}


class ODLedger:
    """Persist work state and immutable committed outcomes in a SQLite database.

    The ledger keeps its behavior contract independent of SQLite. SQLite is the initial local
    backend and provides a transaction that atomically stores result content and unique active
    logical-key claims. Its bounded retry policy is persisted and must match on reopen.
    """

    def __init__(self, database_path: str | Path, max_attempts: int = 3) -> None:
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        self.database_path = Path(database_path)
        self.max_attempts = max_attempts
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def plan_work(
        self,
        compatibility_fingerprint: str,
        origin_h3_id: str,
        destination_batch: Sequence[str],
        cutoff: float,
        cost_unit: str,
    ) -> WorkItem:
        """Persist or idempotently retrieve a deterministic bounded work item."""
        _require_nonempty(compatibility_fingerprint, "compatibility_fingerprint")
        _require_nonempty(origin_h3_id, "origin_h3_id")
        _finite_nonnegative(cutoff, "cutoff")
        _require_nonempty(cost_unit, "cost_unit")
        cost_unit = cost_unit.strip()
        destinations = tuple(sorted(destination_batch))
        if not destinations:
            raise ValueError("destination_batch must not be empty")
        if any(
            not isinstance(destination, str) or not destination.strip()
            for destination in destinations
        ):
            raise ValueError("destination_batch identifiers must be non-empty strings")
        if len(destinations) != len(set(destinations)):
            raise ValueError(
                "destination_batch must not contain duplicate destinations"
            )
        if origin_h3_id in destinations:
            raise ValueError("self-pairs must not be included in solve work")
        work_id = make_work_id(compatibility_fingerprint, origin_h3_id, destinations)
        keys = tuple((origin_h3_id, destination) for destination in destinations)
        now = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_id = ?", (work_id,)
            ).fetchone()
            if row is not None:
                if (
                    row["expected_keys_json"] != _json(keys)
                    or row["cutoff"] != float(cutoff)
                    or row["cost_unit"] != cost_unit
                ):
                    raise ValueError(
                        "deterministic work ID already has conflicting definition"
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO work_items (
                        work_id, compatibility_fingerprint, origin_h3_id,
                        destination_batch_json, expected_keys_json, cutoff, cost_unit,
                        state, attempt_count, fencing_value
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                    """,
                    (
                        work_id,
                        compatibility_fingerprint,
                        origin_h3_id,
                        _json(destinations),
                        _json(keys),
                        float(cutoff),
                        cost_unit,
                        WorkState.PLANNED.value,
                    ),
                )
                self._event(
                    connection,
                    work_id,
                    None,
                    WorkState.PLANNED,
                    now,
                    {"expected_key_count": len(keys)},
                )
        return self.get_work(work_id)

    def get_work(self, work_id: str) -> WorkItem:
        """Return a durable work record by deterministic work ID."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_id = ?", (work_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown work item: {work_id}")
        return _work_item(row)

    def acquire_lease(
        self,
        work_id: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> Lease:
        """Acquire or reclaim a work lease, advancing fencing before ownership changes."""
        _require_nonempty(owner_id, "owner_id")
        _finite_positive(lease_seconds, "lease_seconds")
        instant = _now() if now is None else _finite_timestamp(now)
        failure: str | None = None
        lease: Lease | None = None
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            state = WorkState(row["state"])
            if state in {WorkState.LEASED, WorkState.SOLVING}:
                expiry = row["lease_expires_at"]
                if expiry is None:
                    raise RuntimeError("active work item has no lease expiry")
                if float(expiry) > instant:
                    raise RuntimeError("work item already has an active lease")
                self._record_failure(
                    connection,
                    row,
                    "lease_expired",
                    "lease expired before work was committed",
                    instant,
                )
                row = self._require_row(connection, work_id)
                state = WorkState(row["state"])
                if state is WorkState.TERMINAL_FAILURE:
                    failure = "work item is terminal after retry limit exhaustion"
            if state is WorkState.RETRYABLE_FAILURE:
                if int(row["attempt_count"]) >= self.max_attempts:
                    self._transition(
                        connection,
                        work_id,
                        state,
                        WorkState.TERMINAL_FAILURE,
                        instant,
                        {"reason": "retry limit exhausted"},
                    )
                    failure = "work item is terminal after retry limit exhaustion"
                    row = self._require_row(connection, work_id)
                    state = WorkState(row["state"])
                else:
                    self._transition(
                        connection,
                        work_id,
                        state,
                        WorkState.PLANNED,
                        instant,
                        {"reason": "retry scheduled"},
                    )
                    row = self._require_row(connection, work_id)
                    state = WorkState(row["state"])
            if state is WorkState.PLANNED:
                fencing_value = int(row["fencing_value"]) + 1
                expires_at = instant + float(lease_seconds)
                _finite_timestamp(expires_at)
                connection.execute(
                    """
                    UPDATE work_items
                    SET fencing_value = ?, attempt_count = attempt_count + 1,
                        lease_owner = ?, lease_expires_at = ?,
                        staged_payload_json = NULL, staged_fencing_value = NULL,
                        staged_digest = NULL
                    WHERE work_id = ?
                    """,
                    (fencing_value, owner_id, expires_at, work_id),
                )
                self._transition(
                    connection,
                    work_id,
                    WorkState.PLANNED,
                    WorkState.LEASED,
                    instant,
                    {
                        "owner_id": owner_id,
                        "expires_at": expires_at,
                        "fencing_value": fencing_value,
                    },
                )
                lease = Lease(owner_id, expires_at, fencing_value)
            elif failure is None:
                failure = f"cannot acquire lease for work in state {state.value}"
        if failure is not None:
            raise RuntimeError(failure)
        if lease is None:
            raise RuntimeError("lease acquisition failed without an error")
        return lease

    def start_solving(
        self, work_id: str, lease: Lease, now: float | None = None
    ) -> None:
        """Advance a currently leased item to solving."""
        instant = _now() if now is None else _finite_timestamp(now)
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            self._assert_current_lease(row, lease, instant)
            self._transition(
                connection,
                work_id,
                WorkState.LEASED,
                WorkState.SOLVING,
                instant,
                {"owner_id": lease.owner_id},
            )

    def renew_lease(
        self,
        work_id: str,
        lease: Lease,
        lease_seconds: float,
        now: float | None = None,
    ) -> Lease:
        """Extend the current lease without changing its fencing generation."""
        _finite_positive(lease_seconds, "lease_seconds")
        instant = _now() if now is None else _finite_timestamp(now)
        renewed: Lease | None = None
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            self._assert_current_lease(row, lease, instant)
            state = WorkState(row["state"])
            if state not in {WorkState.LEASED, WorkState.SOLVING}:
                raise RuntimeError("only leased or solving work can renew its lease")
            expires_at = instant + float(lease_seconds)
            _finite_timestamp(expires_at)
            connection.execute(
                "UPDATE work_items SET lease_expires_at = ? WHERE work_id = ?",
                (expires_at, work_id),
            )
            self._event(
                connection,
                work_id,
                state,
                state,
                instant,
                {
                    "owner_id": lease.owner_id,
                    "expires_at": expires_at,
                    "fencing_value": lease.fencing_value,
                    "renewal": True,
                },
            )
            renewed = Lease(lease.owner_id, expires_at, lease.fencing_value)
        if renewed is None:
            raise RuntimeError("lease renewal failed without an error")
        return renewed

    def stage_results(
        self,
        work_id: str,
        lease: Lease,
        outcomes: Iterable[SolveOutcome],
        now: float | None = None,
    ) -> None:
        """Persist isolated worker output as non-authoritative staged evidence."""
        instant = _now() if now is None else _finite_timestamp(now)
        outcome_list = tuple(outcomes)
        payload: dict[str, Any]
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            self._assert_current_lease(row, lease, instant)
            if WorkState(row["state"]) is not WorkState.SOLVING:
                raise RuntimeError("only solving work can stage output")
            payload = {
                "compatibility_fingerprint": row["compatibility_fingerprint"],
                "fencing_value": lease.fencing_value,
                "outcomes": [outcome.to_dict() for outcome in outcome_list],
            }
            serialized = _json(payload)
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            connection.execute(
                """
                UPDATE work_items
                SET staged_payload_json = ?, staged_fencing_value = ?, staged_digest = ?
                WHERE work_id = ?
                """,
                (serialized, lease.fencing_value, digest, work_id),
            )
            self._transition(
                connection,
                work_id,
                WorkState.SOLVING,
                WorkState.STAGED,
                instant,
                {"outcome_count": len(outcome_list), "staged_digest": digest},
            )

    def validate_staged(self, work_id: str) -> None:
        """Coordinator validation of staged identity and exact expected-key coverage."""
        failure: str | None = None
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            if WorkState(row["state"]) is not WorkState.STAGED:
                raise RuntimeError("only staged work can be validated")
            try:
                _, outcomes = self._validated_stage(row)
            except ValueError as exc:
                failure = str(exc)
                self._record_failure(
                    connection, row, "invalid_staged_output", failure, _now()
                )
            else:
                connection.execute(
                    "UPDATE work_items SET staged_digest = ? WHERE work_id = ?",
                    (
                        hashlib.sha256(
                            row["staged_payload_json"].encode("utf-8")
                        ).hexdigest(),
                        work_id,
                    ),
                )
                self._transition(
                    connection,
                    work_id,
                    WorkState.STAGED,
                    WorkState.VALIDATED,
                    _now(),
                    {"validated_key_count": len(outcomes)},
                )
        if failure is not None:
            raise ValueError(f"staged output rejected: {failure}")

    def recover_staged(self, work_id: str) -> None:
        """Revalidate durable staged evidence after restart before it can be committed."""
        self.validate_staged(work_id)

    def commit(self, work_id: str) -> str:
        """Atomically publish an immutable result part and unique active-key claims."""
        part_id: str | None = None
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            state = WorkState(row["state"])
            if state is WorkState.COMMITTED:
                return str(row["committed_part_id"])
            if state is not WorkState.VALIDATED:
                raise RuntimeError("only validated work can be committed")
            _, outcomes = self._validated_stage(row)
            for outcome in outcomes:
                origin, destination = outcome.logical_od_key
                existing = connection.execute(
                    """
                    SELECT part_id FROM active_outcomes
                    WHERE compatibility_fingerprint = ?
                        AND origin_h3_id = ? AND destination_h3_id = ?
                    """,
                    (row["compatibility_fingerprint"], origin, destination),
                ).fetchone()
                if existing is not None:
                    raise RuntimeError(
                        f"logical OD key already has an active committed outcome: "
                        f"{outcome.logical_od_key!r}"
                    )
            payload = _json([outcome.to_dict() for outcome in outcomes])
            part_id = uuid4().hex
            checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            connection.execute(
                """
                INSERT INTO committed_parts (
                    part_id, work_id, checksum, payload_json, committed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (part_id, work_id, checksum, payload, _now()),
            )
            for outcome in outcomes:
                origin, destination = outcome.logical_od_key
                connection.execute(
                    """
                    INSERT INTO active_outcomes (
                        compatibility_fingerprint, origin_h3_id,
                        destination_h3_id, part_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        row["compatibility_fingerprint"],
                        origin,
                        destination,
                        part_id,
                        _json(outcome.to_dict()),
                    ),
                )
            connection.execute(
                "UPDATE work_items SET committed_part_id = ? WHERE work_id = ?",
                (part_id, work_id),
            )
            self._transition(
                connection,
                work_id,
                WorkState.VALIDATED,
                WorkState.COMMITTED,
                _now(),
                {"part_id": part_id, "key_count": len(outcomes)},
            )
        if part_id is None:
            raise RuntimeError("commit did not produce a part reference")
        return part_id

    def invalidate(self, work_id: str, reason: str) -> None:
        """Withdraw an item's active outcomes without editing its immutable result part."""
        _require_nonempty(reason, "reason")
        instant = _now()
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            state = WorkState(row["state"])
            if state is WorkState.INVALIDATED:
                return
            self._transition(
                connection,
                work_id,
                state,
                WorkState.INVALIDATED,
                instant,
                {"reason": reason},
            )
            if row["committed_part_id"] is not None:
                connection.execute(
                    "DELETE FROM active_outcomes WHERE part_id = ?",
                    (row["committed_part_id"],),
                )
            connection.execute(
                """
                UPDATE work_items
                SET fencing_value = fencing_value + 1, lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE work_id = ?
                """,
                (work_id,),
            )

    def reschedule_invalidated(self, work_id: str, still_expected: bool) -> None:
        """Explicitly return invalidated work to planned when it remains expected."""
        if not still_expected:
            raise ValueError(
                "invalidated work can be rescheduled only if still expected"
            )
        with self._transaction() as connection:
            self._require_row(connection, work_id)
            self._transition(
                connection,
                work_id,
                WorkState.INVALIDATED,
                WorkState.PLANNED,
                _now(),
                {"reason": "explicit rescheduling"},
            )
            connection.execute(
                """
                UPDATE work_items SET lease_owner = NULL, lease_expires_at = NULL,
                    staged_payload_json = NULL, staged_fencing_value = NULL,
                    staged_digest = NULL, failure_class = NULL, failure_message = NULL,
                    failure_recorded_at = NULL, attempt_count = 0
                WHERE work_id = ?
                """,
                (work_id,),
            )

    def fail(
        self,
        work_id: str,
        lease: Lease,
        classification: str,
        message: str,
        now: float | None = None,
    ) -> WorkState:
        """Record a solve failure as retryable or terminal under the attempt bound."""
        _require_nonempty(classification, "classification")
        _require_nonempty(message, "message")
        instant = _now() if now is None else _finite_timestamp(now)
        with self._transaction() as connection:
            row = self._require_row(connection, work_id)
            self._assert_current_lease(row, lease, instant)
            state = WorkState(row["state"])
            if state not in {
                WorkState.LEASED,
                WorkState.SOLVING,
                WorkState.STAGED,
                WorkState.VALIDATED,
            }:
                raise RuntimeError(f"cannot fail work in state {state.value}")
            target = self._record_failure(
                connection, row, classification, message, instant
            )
        return target

    def committed_outcomes(
        self, compatibility_fingerprint: str
    ) -> tuple[SolveOutcome, ...]:
        """Return active committed outcomes for one compatibility identity."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT active_outcomes.payload_json
                FROM active_outcomes
                JOIN committed_parts USING (part_id)
                JOIN work_items USING (work_id)
                WHERE work_items.compatibility_fingerprint = ?
                ORDER BY active_outcomes.origin_h3_id,
                    active_outcomes.destination_h3_id
                """,
                (compatibility_fingerprint,),
            ).fetchall()
        return tuple(
            SolveOutcome.from_dict(json.loads(row["payload_json"])) for row in rows
        )

    def qualifying_outcomes(
        self, compatibility_fingerprint: str
    ) -> tuple[SolveOutcome, ...]:
        """Return only actual route facts suitable for the Feature 004 handoff."""
        return tuple(
            outcome
            for outcome in self.committed_outcomes(compatibility_fingerprint)
            if outcome.classification is OutcomeClass.QUALIFYING
        )

    def evidence(self) -> tuple[LedgerEvidence, ...]:
        """Return per-key durable state observations for candidate reconciliation."""
        observations: list[LedgerEvidence] = []
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM work_items ORDER BY work_id"
            ).fetchall()
            for row in rows:
                for origin, destination in json.loads(row["expected_keys_json"]):
                    observations.append(
                        LedgerEvidence(
                            logical_od_key=(origin, destination),
                            dataset_fingerprint=row["compatibility_fingerprint"],
                            state=row["state"],
                            invalidated=row["state"] == WorkState.INVALIDATED.value,
                        )
                    )
        return tuple(observations)

    def history(self, work_id: str) -> tuple[dict[str, Any], ...]:
        """Return ordered transition and failure evidence for one work item."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM work_events WHERE work_id = ? ORDER BY event_id",
                (work_id,),
            ).fetchall()
        return tuple(
            {
                "from_state": row["from_state"],
                "to_state": row["to_state"],
                "recorded_at": row["recorded_at"],
                "details": json.loads(row["details_json"]),
            }
            for row in rows
        )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    work_id TEXT PRIMARY KEY,
                    compatibility_fingerprint TEXT NOT NULL,
                    origin_h3_id TEXT NOT NULL,
                    destination_batch_json TEXT NOT NULL,
                    expected_keys_json TEXT NOT NULL,
                    cutoff REAL NOT NULL,
                    cost_unit TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    fencing_value INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    staged_payload_json TEXT,
                    staged_fencing_value INTEGER,
                    staged_digest TEXT,
                    committed_part_id TEXT,
                    failure_class TEXT,
                    failure_message TEXT,
                    failure_recorded_at REAL
                );
                CREATE TABLE IF NOT EXISTS ledger_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS committed_parts (
                    part_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    committed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active_outcomes (
                    compatibility_fingerprint TEXT NOT NULL,
                    origin_h3_id TEXT NOT NULL,
                    destination_h3_id TEXT NOT NULL,
                    part_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (
                        compatibility_fingerprint, origin_h3_id, destination_h3_id
                    )
                );
                CREATE TABLE IF NOT EXISTS work_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO ledger_metadata (key, value)
                VALUES ('max_attempts', ?)
                """,
                (str(self.max_attempts),),
            )
            policy = connection.execute(
                "SELECT value FROM ledger_metadata WHERE key = 'max_attempts'"
            ).fetchone()
            if int(policy["value"]) != self.max_attempts:
                raise ValueError(
                    "max_attempts differs from the retry policy persisted in the ledger"
                )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.database_path), timeout=30.0, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _require_row(connection: sqlite3.Connection, work_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM work_items WHERE work_id = ?", (work_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown work item: {work_id}")
        return row

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        work_id: str,
        from_state: WorkState | None,
        to_state: WorkState,
        recorded_at: float,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO work_events (
                work_id, from_state, to_state, recorded_at, details_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                work_id,
                from_state.value if from_state is not None else None,
                to_state.value,
                recorded_at,
                _json(details),
            ),
        )

    def _transition(
        self,
        connection: sqlite3.Connection,
        work_id: str,
        current: WorkState,
        target: WorkState,
        recorded_at: float,
        details: dict[str, Any],
    ) -> None:
        if current is target:
            return
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise ValueError(
                f"illegal work transition: {current.value} -> {target.value}"
            )
        connection.execute(
            "UPDATE work_items SET state = ? WHERE work_id = ?",
            (target.value, work_id),
        )
        self._event(connection, work_id, current, target, recorded_at, details)

    def _record_failure(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        classification: str,
        message: str,
        recorded_at: float,
    ) -> WorkState:
        current = WorkState(row["state"])
        target = (
            WorkState.TERMINAL_FAILURE
            if int(row["attempt_count"]) >= self.max_attempts
            else WorkState.RETRYABLE_FAILURE
        )
        connection.execute(
            """
            UPDATE work_items
            SET failure_class = ?, failure_message = ?, failure_recorded_at = ?,
                lease_owner = NULL, lease_expires_at = NULL
            WHERE work_id = ?
            """,
            (classification, message, recorded_at, row["work_id"]),
        )
        self._transition(
            connection,
            row["work_id"],
            current,
            target,
            recorded_at,
            {"classification": classification, "message": message},
        )
        return target

    @staticmethod
    def _assert_current_lease(row: sqlite3.Row, lease: Lease, now: float) -> None:
        if (
            row["lease_owner"] != lease.owner_id
            or int(row["fencing_value"]) != lease.fencing_value
            or int(row["staged_fencing_value"] or row["fencing_value"])
            != lease.fencing_value
            or row["lease_expires_at"] is None
            or float(row["lease_expires_at"]) <= now
        ):
            raise RuntimeError("lease is stale or expired")

    @staticmethod
    def _validated_stage(
        row: sqlite3.Row,
    ) -> tuple[dict[str, Any], tuple[SolveOutcome, ...]]:
        serialized = row["staged_payload_json"]
        if not serialized:
            raise ValueError("staged output is missing")
        payload = json.loads(serialized)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if digest != row["staged_digest"]:
            raise ValueError("staged output integrity check failed")
        if payload.get("compatibility_fingerprint") != row["compatibility_fingerprint"]:
            raise ValueError("staged output fingerprint is incompatible")
        if (
            payload.get("fencing_value") != row["fencing_value"]
            or row["staged_fencing_value"] != row["fencing_value"]
        ):
            raise ValueError("staged output fencing evidence is stale")
        outcomes = tuple(
            SolveOutcome.from_dict(value) for value in payload.get("outcomes", [])
        )
        actual_keys = tuple(outcome.logical_od_key for outcome in outcomes)
        expected_keys = tuple(
            tuple(key) for key in json.loads(row["expected_keys_json"])
        )
        if len(actual_keys) != len(set(actual_keys)):
            raise ValueError("staged output contains duplicate logical OD keys")
        if set(actual_keys) != set(expected_keys):
            raise ValueError(
                "staged output keys do not exactly match expected logical OD keys"
            )
        for outcome in outcomes:
            validate_outcome(outcome, float(row["cutoff"]), row["cost_unit"])
        return payload, outcomes


def make_work_id(
    compatibility_fingerprint: str,
    origin_h3_id: str,
    destination_batch: Sequence[str],
) -> str:
    """Return a stable work ID from compatibility identity and canonical batch identity."""
    _require_nonempty(compatibility_fingerprint, "compatibility_fingerprint")
    _require_nonempty(origin_h3_id, "origin_h3_id")
    destinations = tuple(sorted(destination_batch))
    if not destinations or len(destinations) != len(set(destinations)):
        raise ValueError("destination_batch must be non-empty and unique")
    identity = {
        "version": 1,
        "compatibility_fingerprint": compatibility_fingerprint,
        "origin_h3_id": origin_h3_id,
        "destination_batch": destinations,
    }
    return hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()


def _work_item(row: sqlite3.Row) -> WorkItem:
    lease = None
    if row["lease_owner"] is not None and row["lease_expires_at"] is not None:
        lease = Lease(
            row["lease_owner"],
            float(row["lease_expires_at"]),
            int(row["fencing_value"]),
        )
    failure = None
    if row["failure_class"] is not None:
        failure = FailureEvidence(
            row["failure_class"],
            row["failure_message"],
            float(row["failure_recorded_at"]),
        )
    return WorkItem(
        work_id=row["work_id"],
        compatibility_fingerprint=row["compatibility_fingerprint"],
        origin_h3_id=row["origin_h3_id"],
        destination_batch=tuple(json.loads(row["destination_batch_json"])),
        expected_logical_od_keys=tuple(
            tuple(key) for key in json.loads(row["expected_keys_json"])
        ),
        cutoff=float(row["cutoff"]),
        cost_unit=row["cost_unit"],
        state=WorkState(row["state"]),
        attempt_count=int(row["attempt_count"]),
        fencing_value=int(row["fencing_value"]),
        lease=lease,
        committed_part_id=row["committed_part_id"],
        failure_evidence=failure,
    )


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _finite_timestamp(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("timestamp must be finite")
    return float(value)


def _finite_nonnegative(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and non-negative")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _finite_positive(value: float, name: str) -> None:
    _finite_nonnegative(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
