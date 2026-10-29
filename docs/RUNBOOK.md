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

`scripts/export_data.py` dumps every row in `users` and `facts` (the full
history, not just the latest value per key — that's the point of the
append-only design) to a timestamped JSON file under `./exports/`.

```
DATABASE_URL=<your real database URL> python3 scripts/export_data.py
```

A successful run prints the output path and a row count per table, e.g.:
```
Wrote exports/financial-agent-v2-export-20261029T120000Z.json
users: 2 rows
facts: 312 rows
```

Do this before any migration you're unsure about, before any manual
database surgery, and every so often anyway (there's no scheduled backup
today — this is a manual step you run yourself). Keep the exported file
somewhere other than the server (your laptop, a password manager's file
storage, wherever you keep sensitive files) — it contains the full household
financial history in plain JSON, unencrypted.

---

## 4. Restoring from a backup

There's no restore *script* yet — only this documented procedure, run by
hand with the file `export_data.py` produced. If you end up doing this
often enough that it's worth automating, say so and it's a quick follow-up
to build (with its own tests, same as everything else).

**When you'd do this:** setting up a fresh database after data loss, or
seeding a new environment (e.g. a staging database) with real history.

**Steps:**

1. Make sure the target database is empty (a brand-new Neon/Postgres
   database, not the live one — restoring onto a database that already has
   rows will violate the `users.email`/`users.google_sub` uniqueness
   constraints and the facts table's append-only trigger will refuse any
   attempt to overwrite rather than append).
2. Apply every migration to it first (§2) — the tables have to exist before
   anything can be restored into them.
3. Run this short script, pointing `DATABASE_URL` at the *target* (empty)
   database and passing the export file as an argument:

   ```python
   # restore_from_export.py — run once, by hand, not part of the test suite.
   import json
   import sys

   import psycopg2

   with open(sys.argv[1]) as f:
       data = json.load(f)

   conn = psycopg2.connect()  # reads DATABASE_URL from the environment
   with conn.cursor() as cur:
       for u in data["users"]:
           cur.execute(
               """INSERT INTO users (id, google_sub, email, role, created_at)
                  VALUES (%(id)s, %(google_sub)s, %(email)s, %(role)s, %(created_at)s)""",
               u,
           )
       # Facts in entered_at order — preserves the real history, not just
       # the end state, which matters for freshness/audit correctness.
       for fact in sorted(data["facts"], key=lambda r: r["entered_at"]):
           cur.execute(
               """INSERT INTO facts
                  (key, value_text, value_type, unit, source, category, owner,
                   as_of, entered_at, note, entered_by_user_id)
                  VALUES (%(key)s, %(value_text)s, %(value_type)s, %(unit)s, %(source)s,
                          %(category)s, %(owner)s, %(as_of)s, %(entered_at)s, %(note)s,
                          %(entered_by_user_id)s)""",
               fact,
           )
       # Re-point the id sequences past the restored rows, since the
       # explicit ids above bypassed the normal SERIAL default.
       cur.execute("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))")
       cur.execute("SELECT setval('facts_id_seq', (SELECT MAX(id) FROM facts))")
   conn.commit()
   print(f"Restored {len(data['users'])} users, {len(data['facts'])} facts.")
   ```

   ```
   DATABASE_URL=<target database URL> python3 restore_from_export.py exports/financial-agent-v2-export-<timestamp>.json
   ```

4. Spot-check: log in, confirm a few numbers on the Numbers page match what
   you expect, and check a fact's "as of" date against the original export
   to make sure history came back intact, not just the latest values.

This restores `users` and `facts` only — `goals`, `tasks`, and `audit_log`
aren't in `export_data.py`'s output yet (it predates Stage 1). If you need
those backed up and restorable too, that's worth asking for as its own
small change rather than assuming the steps above cover them.
