# Runbook

Plain-English steps for the four things you'll actually need to do:
deploying, running a new migration, backing up the data, and restoring it.
Claude Code never does any of these itself — it writes the code/scripts;
you run them and do all `git`/deploy actions yourself.

---

## 1. Deploying

This app is one service on Render (`render.yaml`), backed by a managed
Postgres (e.g. Neon) in the `DATABASE_URL` environment variable. Render
builds with `pip install -r requirements.txt` and starts with
`gunicorn "app:create_app()"` (see `Procfile`).

**To ship a change:**
1. Review and commit the change yourself (Claude Code prepares diffs but
   never commits or pushes).
2. `git push` to the branch Render is watching. If Render's auto-deploy is
   on, that alone triggers a new build; otherwise trigger a manual deploy
   from the Render dashboard.
3. Watch the Render deploy log until it says the new version is live.
4. If the change included a new file under `migrations/`, run it now (see
   §2) — deploying the code does **not** run migrations for you.
5. Load the app in a browser and confirm the page you changed actually
   looks right. Render's free tier can cold-start slowly after idling —
   give it a few seconds on the first request.

**Environment variables** (set once in Render's dashboard, never in the
repo): `SECRET_KEY`, `DATABASE_URL`, `OWNER_EMAIL`, `PARTNER_EMAIL`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_COOKIE_SECURE=true`.
`.env.example` lists the same set for local dev.

**Changing `SECRET_KEY` signs everyone out immediately.** Sessions are
signed with it, so rotating the key invalidates every existing login the
instant the new value goes live — both of you will need to sign in again.
Sessions otherwise last 30 days of inactivity (`PERMANENT_SESSION_LIFETIME`,
refreshed on every request) before that happens on its own.

---

## 2. Running a migration

Every schema change lives as its own numbered file under `migrations/`
(`001_init.sql`, `002_goals.sql`, ...) — never edit an old one, only add a
new one. `scripts/apply_migrations.py` runs every file in that folder, in
filename order, against whatever `DATABASE_URL` points at. Every statement
in every migration is written to be safe to run twice (`CREATE TABLE IF NOT
EXISTS`, etc.), so re-running the whole set is harmless if you're ever
unsure whether the latest one already ran.

```
DATABASE_URL=<your real database URL> python3 scripts/apply_migrations.py
```

A successful run prints one `Applied migrations/<file>.` line per file and
exits 0. It never prints the database URL itself.

Run this against the real production database after deploying code that
added a new migration file — and always run it against a throwaway/test
database first if the migration is non-trivial, to see the error there
instead of in production.

---

## 3. Backing up the data

`scripts/export_data.py` dumps every row in every table — `users`, the full
`facts` history (not just the latest value per key — that's the point of
the append-only design), and Stage 1's `goals`, `goal_assignees`, `tasks`,
and `audit_log` — to a timestamped JSON file under `./exports/`.

```
DATABASE_URL=<your real database URL> python3 scripts/export_data.py
```

A successful run prints the output path and a row count per table, e.g.:
```
Wrote exports/financial-agent-v2-export-20261029T120000Z.json
users: 2 rows
facts: 312 rows
goals: 6 rows
goal_assignees: 4 rows
tasks: 9 rows
audit_log: 23 rows
```

Do this before any migration you're unsure about, before any manual
database surgery, and every so often anyway (there's no scheduled backup
today — this is a manual step you run yourself). Keep the exported file
somewhere other than the server (your laptop, a password manager's file
storage, wherever you keep sensitive files) — it contains the full household
financial history in plain JSON, unencrypted.

---

## 4. Restoring from a backup

`scripts/restore_data.py` takes an export file and restores it into the
database `DATABASE_URL` points at.

```
DATABASE_URL=<target database URL> python3 scripts/restore_data.py exports/financial-agent-v2-export-<timestamp>.json
```

**It only ever restores into an empty database.** Before writing a single
row, it checks all six tables and refuses immediately — no partial
changes — if even one of them already has any rows at all:
```
Refusing to restore: not empty — users has rows
```
This is deliberately a from-empty restore, not a merge and not an
overwrite. If you need to bring a backup back on top of a database that
already has data in it, that's a different (and more dangerous) operation
— stop and think about what you actually want before asking for it.

**When you'd do this:** setting up a fresh database after data loss, or
seeding a new environment (e.g. a staging database) with real history.

**Steps:**

1. Apply every migration to the target database first (§2) — the tables
   have to exist (and be empty) before anything can be restored into them.
2. Run the command above.
3. A successful run prints a row count per table restored, e.g.:
   ```
   Restored users: 2 rows
   Restored facts: 312 rows
   Restored goals: 6 rows
   Restored goal_assignees: 4 rows
   Restored tasks: 9 rows
   Restored audit_log: 23 rows
   ```
4. Spot-check: log in, confirm a few numbers on the Numbers page match what
   you expect, and check a fact's "as of" date against the original export
   to make sure history came back intact, not just the latest values.

The whole restore runs as one transaction — if anything fails partway
through, nothing is committed and the database is left exactly as empty as
it started.
