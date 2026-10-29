"""
Job execution substrate (architecture v0.3, Layer 4 / §8.4).

The reviewers were clear: before any scheduled/agentic behaviour, the system
needs to be able to answer "when the system says it did X, X actually happened
exactly once, using the intended code and data." An in-process APScheduler that
dies with the web container cannot answer that.

This module makes job execution state a first-class, persisted thing:
  - every run is recorded (status, attempt, timing, code version, error)
  - idempotency keys prevent the same logical job running twice
  - an external heartbeat ping fires on success, so a dead scheduler is visible
    (the dead-man's switch — e.g. Healthchecks.io)
  - last-success timestamps and failure counts are queryable, so the UI can
    surface "last ran 9 days ago" instead of pretending all is well

Scheduling itself is expected to be host cron calling a CLI that uses this
runner — NOT in-process APScheduler.
"""
from __future__ import annotations

import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional


class JobStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"      # idempotency key already completed


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class JobRecord:
    id: int
    job_type: str
    idempotency_key: str
    status: JobStatus
    attempt: int
    code_version: str
    started_at: datetime
    finished_at: Optional[datetime]
    error: str
    output_ref: str


class JobStore:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type        TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status          TEXT NOT NULL,
                attempt         INTEGER NOT NULL DEFAULT 1,
                code_version    TEXT NOT NULL DEFAULT 'unknown',
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                error           TEXT NOT NULL DEFAULT '',
                output_ref      TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_key ON jobs(idempotency_key)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_type_started ON jobs(job_type, started_at)"
        )
        self.conn.commit()

    def _row(self, r: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=r["id"], job_type=r["job_type"], idempotency_key=r["idempotency_key"],
            status=JobStatus(r["status"]), attempt=r["attempt"],
            code_version=r["code_version"],
            started_at=datetime.fromisoformat(r["started_at"]),
            finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
            error=r["error"], output_ref=r["output_ref"],
        )

    def already_succeeded(self, idempotency_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM jobs WHERE idempotency_key = ? AND status = 'success' LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        return row is not None

    def _start(self, job_type: str, key: str, attempt: int, code_version: str) -> int:
        cur = self.conn.execute(
            """INSERT INTO jobs (job_type, idempotency_key, status, attempt,
               code_version, started_at) VALUES (?, ?, 'running', ?, ?, ?)""",
            (job_type, key, attempt, code_version, _utcnow().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def _finish(self, job_id: int, status: JobStatus, error: str = "", output_ref: str = ""):
        self.conn.execute(
            "UPDATE jobs SET status = ?, finished_at = ?, error = ?, output_ref = ? WHERE id = ?",
            (status.value, _utcnow().isoformat(), error, output_ref, job_id),
        )
        self.conn.commit()

    def last_success(self, job_type: str) -> Optional[datetime]:
        row = self.conn.execute(
            "SELECT MAX(finished_at) AS t FROM jobs WHERE job_type = ? AND status = 'success'",
            (job_type,),
        ).fetchone()
        return datetime.fromisoformat(row["t"]) if row and row["t"] else None

    def consecutive_failures(self, job_type: str) -> int:
        """How many failures since the last success — drives 'alert on repeated failure'."""
        rows = self.conn.execute(
            "SELECT status FROM jobs WHERE job_type = ? AND status IN ('success','failed') "
            "ORDER BY started_at DESC",
            (job_type,),
        ).fetchall()
        count = 0
        for r in rows:
            if r["status"] == "failed":
                count += 1
            else:
                break
        return count

    def history(self, job_type: str, limit: int = 50) -> list[JobRecord]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE job_type = ? ORDER BY started_at DESC LIMIT ?",
            (job_type, limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    def close(self):
        self.conn.close()


# Heartbeat sender is injected so we can test without network and swap providers.
HeartbeatFn = Callable[[str], None]


def _noop_heartbeat(url: str) -> None:
    pass


@dataclass(frozen=True)
class JobOutcome:
    status: JobStatus
    job_id: Optional[int]
    result: object = None
    error: str = ""


def run_job(
    store: JobStore,
    job_type: str,
    idempotency_key: str,
    fn: Callable[[], object],
    *,
    code_version: str = "unknown",
    max_attempts: int = 1,
    heartbeat_url: str = "",
    heartbeat: HeartbeatFn = _noop_heartbeat,
    output_ref: str = "",
) -> JobOutcome:
    """Run `fn` as a recorded, idempotent job.

    - If this idempotency_key already succeeded, returns SKIPPED without running.
    - Records RUNNING -> SUCCESS/FAILED with timing and error.
    - Retries up to max_attempts on exception.
    - On success, pings the heartbeat URL (dead-man's switch).

    `fn` takes no args and returns any result; wrap your real work in a closure.
    """
    if store.already_succeeded(idempotency_key):
        return JobOutcome(JobStatus.SKIPPED, None)

    last_error = ""
    job_id = None
    for attempt in range(1, max_attempts + 1):
        job_id = store._start(job_type, idempotency_key, attempt, code_version)
        try:
            result = fn()
            store._finish(job_id, JobStatus.SUCCESS, output_ref=output_ref)
            if heartbeat_url:
                try:
                    heartbeat(heartbeat_url)
                except Exception:
                    # A failed heartbeat must not fail the job; monitoring will
                    # notice the missing ping on its own.
                    pass
            return JobOutcome(JobStatus.SUCCESS, job_id, result=result)
        except Exception as e:  # noqa: BLE001 — we deliberately capture all
            last_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            store._finish(job_id, JobStatus.FAILED, error=last_error)

    return JobOutcome(JobStatus.FAILED, job_id, error=last_error)
