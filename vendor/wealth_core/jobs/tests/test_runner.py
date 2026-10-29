"""
Tests for the job execution substrate. The behaviours that matter: a job runs
exactly once per idempotency key, failures are recorded and retried, the
heartbeat fires only on success, and the store can tell us when something last
succeeded and how many times it has failed since — the visibility that stops a
dead scheduler from going unnoticed.
"""
import pytest
from jobs import JobStore, JobStatus, run_job


def test_successful_job_records_success():
    store = JobStore()
    out = run_job(store, "monthly_recap", "recap-2026-06", lambda: 42)
    assert out.status == JobStatus.SUCCESS
    assert out.result == 42
    assert store.last_success("monthly_recap") is not None

def test_idempotency_key_prevents_rerun():
    store = JobStore()
    calls = []
    def work():
        calls.append(1)
        return "done"
    run_job(store, "recap", "june", work)
    out2 = run_job(store, "recap", "june", work)   # same key
    assert out2.status == JobStatus.SKIPPED
    assert len(calls) == 1                          # ran only once

def test_different_keys_both_run():
    store = JobStore()
    calls = []
    run_job(store, "recap", "june", lambda: calls.append(1))
    run_job(store, "recap", "july", lambda: calls.append(1))
    assert len(calls) == 2

def test_failure_is_recorded():
    store = JobStore()
    def boom():
        raise ValueError("kaboom")
    out = run_job(store, "recap", "june", boom)
    assert out.status == JobStatus.FAILED
    assert "kaboom" in out.error
    assert store.last_success("recap") is None

def test_retry_then_succeed():
    store = JobStore()
    attempts = {"n": 0}
    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "ok"
    out = run_job(store, "recap", "june", flaky, max_attempts=3)
    assert out.status == JobStatus.SUCCESS
    assert attempts["n"] == 3

def test_retry_exhausted_fails():
    store = JobStore()
    def always():
        raise RuntimeError("nope")
    out = run_job(store, "recap", "june", always, max_attempts=2)
    assert out.status == JobStatus.FAILED
    assert store.consecutive_failures("recap") == 2

def test_heartbeat_fires_only_on_success():
    store = JobStore()
    pings = []
    def hb(url):
        pings.append(url)
    run_job(store, "recap", "s", lambda: 1,
            heartbeat_url="https://hc.example/abc", heartbeat=hb)
    assert pings == ["https://hc.example/abc"]

def test_heartbeat_not_fired_on_failure():
    store = JobStore()
    pings = []
    def hb(url):
        pings.append(url)
    def boom():
        raise ValueError("x")
    run_job(store, "recap", "f", boom,
            heartbeat_url="https://hc.example/abc", heartbeat=hb)
    assert pings == []

def test_failed_heartbeat_does_not_fail_job():
    store = JobStore()
    def bad_hb(url):
        raise ConnectionError("monitoring down")
    out = run_job(store, "recap", "s", lambda: "result",
                  heartbeat_url="https://hc.example/abc", heartbeat=bad_hb)
    assert out.status == JobStatus.SUCCESS   # job still succeeds

def test_consecutive_failures_resets_on_success():
    store = JobStore()
    run_job(store, "recap", "a", lambda: (_ for _ in ()).throw(ValueError()))
    run_job(store, "recap", "b", lambda: (_ for _ in ()).throw(ValueError()))
    assert store.consecutive_failures("recap") == 2
    run_job(store, "recap", "c", lambda: "ok")
    assert store.consecutive_failures("recap") == 0

def test_history_records_all_runs():
    store = JobStore()
    run_job(store, "recap", "a", lambda: 1)
    run_job(store, "recap", "b", lambda: 2)
    hist = store.history("recap")
    assert len(hist) == 2
    assert all(h.status == JobStatus.SUCCESS for h in hist)
