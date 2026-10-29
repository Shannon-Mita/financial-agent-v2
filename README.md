# Financial Agent V2 — Stage 0

Hosted, two-login, permission-enforced facts dashboard. Built per
`financial-agent-v2-build-spec.md` §5. Stage 1 (goals, feasibility) is not
built yet — see spec §7 for what's deliberately deferred.

## Layout

- `vendor/wealth_core/` — wealth-core, copied in verbatim (untouched; see
  `app/vendor_path.py` for how it's put on `sys.path`).
- `app/` — the Flask app: `store.py` (Postgres fact store, same contract as
  wealth-core's own sqlite `FactStore`), `permissions.py`, `auth.py` (Google
  OAuth + email allowlist), `routes.py`.
- `migrations/001_init.sql` — schema, including the append-only trigger.
- `scripts/export_data.py`, `scripts/load_placeholder_facts.py` — see each
  script's own docstring before running.
- `tests/` — `pytest -q` from the repo root also runs wealth-core's own 133
  tests (they live under `vendor/wealth_core/*/tests/`), unmodified.

## Local setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values, never commit this file
```

## Running tests

Most tests (permissions, allowlist rejection, CSRF-missing-token, all of
wealth-core's own suite) need no database:

```
pytest -q
```

The store-contract, append-only, and full-login-flow tests need a real
Postgres and are skipped without one. Point `TEST_DATABASE_URL` at a
throwaway database (never your real one) to run them too:

```
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest -q
```

A successful full run (DB included) prints something like
`160 passed in Xs` with no skips.

## Running locally

```
flask --app run.py run
```
