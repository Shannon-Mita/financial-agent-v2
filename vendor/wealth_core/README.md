# Wealth Core — Phase 0 complete, Phase 1 substantially built

Deterministic, tested foundation + intelligence layer for the wealth agent
(architecture v0.3). **117 tests, all passing.** No network, no LLM in this core.

## Run everything
    pip install pytest
    python -m pytest -q        # 117 tests
    python demo.py             # watch the whole stack work end to end

## Packages

| Package        | Layer | What it does | Tests |
|----------------|-------|--------------|-------|
| `tax_engine/`  | 2 & 3 | Versioned UK tax facts + pure calculations. `tax_year` mandatory; unknown year raises; inputs coerced; IHT relationship-aware. | 47 |
| `facts_layer/` | 1     | Typed, sourced, timestamped facts. Append-only store with history + `as_of()` audit. Freshness gate. | 16 |
| `jobs/`        | 4     | Persistent, idempotent job records; retry; heartbeat (dead-man's switch). | 11 |
| `ops/`         | —     | Backup/restore with integrity check (round-trip tested); deploy smoke test. | 7 |
| `strategy/`    | 4     | Machine-readable FIRE objective + honest projection bands; strategy assumptions monitored for breach; opportunities scored against the goal, not raw £. | 16 |
| `recap/`       | 1     | Deterministic monthly recap: freshness-gated, materiality-filtered, track-status aware. | 11 |
| `delivery/`    | 7     | Render recap → Telegram HTML; injectable sender (offline-testable). | 9 |

## What the intelligence layer does (Phase 1 highlights)
- **Objective projection** is honest about uncertainty: a growth band
  (pessimistic/central/optimistic) yields ON_TRACK / AT_RISK / OFF_TRACK, not a
  fake precise probability.
- **Strategy monitoring** stores each strategy as assumptions with expected
  ranges; when an assumption breaks (e.g. mortgage rate reverts above the range),
  it flags "re-evaluate" — deterministically, no LLM, no prose regeneration.
- **Opportunity scoring** ranks by contribution to the goal adjusted for
  confidence and effort, so a £6k/yr low-effort certain move beats a £12k/yr
  high-effort speculative one. "Does this move the goal?", not "is it interesting?"

## Rules this core enforces (from the reviews)
- No tax number lives outside `tax_engine/facts.py`, versioned by tax year + source.
- Unknown tax year raises; every calc coerces inputs; IHT is rule-by-rule.
- Facts append-only → freshness + full audit.
- Freshness gate REFUSES stale advice, naming exactly what to refresh.
- Recap SUPPRESSES immaterial items; surfaces £-impact or deadline triggers only.
- Scheduled work runs through recorded, idempotent jobs with a heartbeat.
- LLM appears NOWHERE in this core. It enters only at later phases, subordinate.

## Phase status
- [x] **Phase 0** — tax engine, facts layer, jobs, ops (backup + smoke test)
- [x] **Phase 1 core** — wealth objective + strategy graph, monthly recap, delivery
- [ ] **Phase 1 integration** — wire live Flask app to facts layer; host-cron the
      recap job; back up current droplet SQLite first
- [ ] **Phase 2** — on-demand stress-tester (scenario maths + LLM assumption-attack)
- [ ] **Phase 3+** — discovery catalogue, quarterly tax review, external discovery
      behind the qualification firewall

## Integration note
Standalone by design — NOT yet bolted onto the live droplet. The migration is its
own careful step: back up the droplet DB (the `ops` module does this with
verification), migrate the Flask app to read/write via `facts_layer`, and run the
recap as a host-cron job through the `jobs` runner with a Healthchecks.io heartbeat.

## After a Budget
Add a new `TaxYear(...)` in `tax_engine/facts.py` (never edit an old one),
register it in `TAX_YEARS`, re-run the suite. Golden tests flag any drift.

## Migration from the v1 JSON-blob profile
`migrate/` maps every field the calculation engine reads from the old blob into
typed facts — fixing the empty-string/zero inconsistency permanently, and
flagging (never silently resolving) any internal contradictions in the old data,
such as a FIRE target that doesn't match the stated net-worth goal.

Run on the droplet, non-destructively (the old file is never modified):

    python3 scripts/migrate_v1_db.py \
        --old ~/financial-agent/data/financial_agent.db \
        --new ~/financial-agent/data/wealth_facts.db

Add `--dry-run` to see the report without writing anything. Review the report —
especially any discrepancies — before wiring the new database into anything live.
