# Financial Agent V2 — Stage 2 Spec (Goals, Milestones, Strategies)

**For:** Claude Code
**From:** Shannon (product owner). Shannon does all git, PRs, merges and deploys.
Claude Code never commits or pushes and has no GitHub access.
**Status:** APPROVED by Shannon, 1 Nov 2026. Claude Code produces a build plan
for Shannon's approval before writing any code.

---

## 0. Scope rule (unchanged)

V1 and V2 failed by growing broad before anything was used. If a change adds a
capability not listed here, stop and ask. Claude must not fill gaps with its own
assumptions: anything not stated by Shannon or Asha is recorded as `?` and
surfaced, never guessed.

---

## 1. The two goals (replace the single "FIRE £3M at 4%" goal)

1. **Net worth — £1,000,000 by 5 Oct 2030.**
   All assets minus all debts, including home value and mortgage. Excluded: the
   Junior ISA, Shannon's pension pots, Asha's pension pots. The only debt counted
   anywhere in this household's facts is the mortgage (Shannon, 1 Nov 2026) — if
   another debt is ever recorded, it is not counted until Shannon explicitly says
   so. Target is fact-backed (`goals.net_worth.target_amount`, already exists).
2. **Passive income — £12,000 per month by 5 Oct 2030.**
   After tax, **entered** after tax by Shannon/Asha — the app does not calculate
   tax on passive income streams. In 2030 money. The sum of all passive income
   streams (interest from holdings, rental, business, automated investing, and
   any other strategy). Not a fixed percentage of one fund. Target is fact-backed
   (new key, `goals.passive_income.target_amount`).
   Interest and dividends are **not** new boxes (Shannon, 1 Nov 2026): they
   reuse the existing `income.shannon.savings_interest`, `income.partner.savings_interest`,
   `income.shannon.dividends`, `income.partner.dividends` facts, so nothing is
   entered twice — see §6.

The two goals are linked: a strategy can move one, both, or move them in opposite
directions.

**Remove from the app:** the "FIRE target number" and "FIRE safe withdrawal
rate" boxes. Facts are append-only, so "remove" means they are no longer shown or
used; their history stays. If drawing down investments later becomes a passive
income stream, its rate is recorded on that stream, not as a top-level setting.

Shannon confirmed (1 Nov 2026): **all five** old FIRE boxes are hidden from the
Numbers page — `goals.fire.target_number`, `goals.fire.swr`,
`goals.fire.target_age`, `goals.fire.target_years`, `goals.fire.target_monthly_income`.
Shannon deletes the old FIRE goal row himself; no migration/cleanup script needed.

### Net worth: fact-key classification (proposed by Claude Code, pending Shannon's sign-off)

Every curated fact key that exists today, classified for `calc_net_worth()`.
Legacy/uncurated keys are not applicable — the calculation only ever reads
curated keys.

**Assets (9):**
`cashflow.emergency_savings`, `isa.shannon.stocks_shares.value`,
`isa.shannon.cash.value`, `isa.partner.stocks_shares.value`,
`isa.partner.cash.value`, `investments.shannon.crypto_value`,
`investments.partner.stocks_gia_value`, `savings.house_deposit.balance`,
`property.main.value`.

**Debt (1):** `property.main.mortgage_balance`.

**Excluded (explicit, per §1) (3):** `isa.junior.value`,
`pensions.shannon.current_value`, `pensions.partner.current_value`.

**Not counted — income/spending flows, dates, metadata, booleans, and goal/
target settings (36):** every `income.*` key, every `cashflow.monthly_*` key,
`pensions.*.monthly_employee`, `pensions.*.monthly_employer`,
`pensions.*.has_pension`, `pensions.partner.expression_of_wishes_updated`,
`property.main.mortgage_rate`, `property.main.fixed_rate_end`, every
`goals.fire.*` key, `goals.net_worth.target_amount` (it is the target, not an
asset), `children.0.child_benefit_claiming`, `children.0.dob`,
`people.shannon.dob`, `people.partner.dob`.

**Not counted — new passive-income stream boxes (§6):** the three new stream
facts (rental, business, investment income) are monthly *income flows*, not
asset balances — same treatment as the existing `income.*` keys already in
the 36 above. They feed the passive income goal only and are never summed
into net worth, even though they are "financial" numbers — flagging this
explicitly since it would be an easy mistake.

---

## 2. Year-adjusted figures (inflation and tax)

Every figure is adjusted to the year it applies to.

- **Inflation:** use the Office for Budget Responsibility's latest published CPI
  forecast for each year to 2030, replaced by ONS actuals as they are published.
  Note: inflation is published by the ONS/OBR, not HMRC. A secondary source
  reports the OBR's March 2026 forecast as 2.3% (2026) then 2.0% (2027–2030);
  Claude Code must fetch the OBR primary source before using any figure, and the
  figures must be updated after each fiscal event.
- **Tax:** use HMRC/GOV.UK rates and thresholds per tax year. Income tax and
  equivalent NI thresholds are frozen until 5 April 2031 (GOV.UK policy paper).
  Any rate not yet published for a future year is marked unverified, using the
  existing NotVerified mechanism, never guessed.
- **Tax years 2027/28–2030/31** (Shannon, 1 Nov 2026): added to `facts.py` in
  Step 1, now, not deferred — the goals run to 5 Oct 2030, which spans these
  four tax years beyond 2026/27. Income tax and NI thresholds for each are
  fetched and verified from the GOV.UK freeze policy paper (the same source
  already cited above). Every other field (CGT, dividend/savings allowances,
  IHT, SDLT, pension annual allowance, etc.) is `NotVerified` for all four
  years, exactly like 2026/27's own unverified fields today — not guessed, not
  copied from 2026/27. This includes the Child Benefit/HICBC fields
  (`cb_weekly_first_child`, `cb_weekly_additional_child`, `hicbc_taper_start`,
  `hicbc_taper_end`) — `NotVerified` for all four years too (Shannon, 1 Nov
  2026), even though this household no longer uses them (§3): never carried
  forward unverified, no exception for fields that happen to be unused.
- **UK only:** the tax engine models UK tax only. Strategies involving another
  country are recorded but not calculated until that country's rules are added.
- **Passive income is entered after tax by Shannon/Asha** (1 Nov 2026) — the
  app does not calculate tax on passive income streams. "After tax, in 2030
  money" in §1 describes what the household *enters*, not something the engine
  derives from a gross figure.
- **Inflation adjustment** (Shannon, 1 Nov 2026): both targets — net worth
  £1,000,000 and passive income £12,000/month — are in 2030 money, treated
  identically. A new pure function in `vendor/wealth_core` (OBR CPI forecasts
  fetched from the primary source, replaced by ONS actuals as published)
  deflates both targets to today's money before comparing them against the
  household's today's-money entered figures — not the reverse (projecting
  entered figures forward would be a growth projection, out of scope per
  `goal_progress.py`'s existing maths-only rule). Built in Step 1, applied in
  Step 3 (§7).

---

## 3. Child Benefit fix and 30 hours funded childcare

### Child Benefit (FIX)
- Shannon confirmed (1 Nov 2026): this household does not receive Child
  Benefit. Removing it from the surplus calculation is a **FIX**, not a new
  capability — written with a failing test first, per the project's bug-fix
  discipline.
- Because Child Benefit is not received, the High Income Child Benefit Charge
  (HICBC) does not apply to this household either. It is removed alongside
  Child Benefit, not calculated separately — there is nothing to charge against
  income that was never claimed.
- Once the fix lands, Claude Code reports how much the household's **current
  live** `calc_monthly_surplus()` figure changes as a result, using this
  household's real facts, not a hypothetical. This report is a Step 1
  build-time deliverable, not something computed now.
- **Fix design (approved, Shannon 1 Nov 2026):** do not force `num_children=0`
  — the household still has a child for every other calculation. Instead,
  `calc_child_benefit()` (and `calc_monthly_surplus()`/`build_recap()` above
  it) gain a new `claiming: bool = True` parameter; when `False` it
  short-circuits to the same zero result already used for `num_children<=0`,
  without touching `num_children` itself. `app/goal_progress.py` reads the
  existing `children.0.child_benefit_claiming` fact (set to `false` for this
  household) and passes it through as `claiming=`; that key is added to the
  required-facts list so a missing value refuses the calculation rather than
  silently assuming either way.

### 30 hours funded childcare (new household constraint)
- Shannon confirmed (1 Nov 2026): this household receives the 30-hours funded
  childcare entitlement.
- Claude Code fetches the current eligibility rules from GOV.UK before this is
  built, including the **per-parent** income limits (each parent is assessed
  individually, not the household combined) and records them with the
  existing `NotVerified` mechanism until fetched and confirmed — exactly like
  tax figures, never guessed.
- The entitlement is recorded as a household constraint fact, separate from
  any goal or strategy.
- Every strategy or idea that could change either parent's income (e.g. a new
  role, more consulting, business income) must state whether it risks
  breaching the per-parent income limit and losing eligibility. This is a new
  required field on the strategy data model (§5) and worksheet.

### Childcare-eligibility flagging (resolved, Shannon 1 Nov 2026)
- **Manual field — in scope for Step 4:** each strategy has a
  `risks_childcare_eligibility` (yes / no / unknown) field, filled in by
  Shannon or Asha. This ships with Steps 1–4 regardless of anything below.
- **Automatic warning — deferred to Step 6, alongside lever recalculation:**
  when a strategy's lever changes a dimension that is an `income.*` fact key
  for either parent, the app could project that parent's new income and
  compare it against the stored per-parent childcare income limit fact,
  showing a visible warning badge ("risks childcare eligibility") without
  blocking saving. This depends on lever recalculation existing (§8.3), which
  lands with Step 6's AI idea generation, its only identified consumer in this
  spec — so the automatic version lands there too, not in Steps 1–4.
- **Policy module (approved, Shannon 1 Nov 2026):** a new, non-tax-year-scoped
  module in `vendor/wealth_core` (e.g. `tax_engine/childcare_policy.py`) holds
  the 30-hours entitlement's per-parent income limits, fetched from GOV.UK
  with source and date logged, same citation discipline as `TaxYear`/
  `CHANGES.md`. A new household fact, `children.0.funded_childcare_30hrs_claiming`
  (boolean), mirrors the existing `child_benefit_claiming` key.

---

## 4. Milestones

- Each goal can be broken into milestones (sub-goals via `parent_id`).
- Milestones stay **owner-only** (Shannon), the same as the two apex goals
  (Shannon, 1 Nov 2026, resolving 3.4): the strategy permission model (both
  Shannon and Asha can add/edit) is a flat, row-independent rule — every
  strategy row is editable by both, with no exceptions based on which strategy
  it is. Milestones share the same `goals` table and the same uniformly
  owner-only CRUD routes as the two protected apex goals; giving Asha edit
  rights on milestones specifically (but not on the apex goals in that same
  table) would need new, row-conditional permission logic branching on
  `parent_id` inside routes that are otherwise unconditionally owner-only.
  That is not a clean reuse of the strategy pattern, so milestones remain
  owner-only.
- Milestone figures and dates are entered by Shannon once the Goals page shows
  the new structure.

---

## 5. Strategies

### Data model
- **`strategies`**: id, title, detail, **area** (added 3 Nov 2026 — this
  section's own grouping-by-area requirement below has no column to
  render from without it; the worksheet's six section headings, stored
  verbatim), status (idea / in progress / active / parked / archived),
  "work lives in" (project or repo, or "here"), effect on net worth (£ by
  5 Oct 2030, numeric), effect on passive income (£/month after tax by 5
  Oct 2030, numeric), risks childcare eligibility (yes / no / unknown —
  see §3), archived reason, archived date, last reviewed date, source
  (shannon / asha), created/updated/by whom.
  - Dropped from the original draft: "the number" (redundant with the two
    numeric effect fields, Shannon 1 Nov 2026) and "confidence" (dropped
    entirely, Shannon 1 Nov 2026).
  - `detail` and `status` are also nullable, same NULL="?" rule as the two
    numeric effect fields (added 3 Nov 2026) — the worksheet has "Status: ?"
    (2 entries) and "Detail: ?" (5 entries); forcing either into a
    fabricated default would misrepresent a genuine unknown as a decision.
  - Numeric fields are stored as numbers or `NULL`. `NULL` displays as `?` and
    is never defaulted to zero. A genuine, known zero effect (e.g. strategy 8,
    "not operating to produce profit") is stored as the number `0`, not `?`
    (Shannon, 1 Nov 2026).
- **Links:** a strategy can link to one or more goals or milestones
  (many-to-many link table, `strategy_goal_links`) — both apex goals and
  milestones live in the same `goals` table, so one link table covers both.
- **`strategy_levers`**: the numeric assumptions the engine reads. Each
  lever's `dimension` is an existing fact key (Shannon, 1 Nov 2026), not a
  free-text label, so the engine applies `{dimension, delta, from_date}`
  directly to that fact's current value. Step 4 only stores this data —
  **lever recalculation** (actually computing a projected position from it,
  §8.3) is deferred to Step 6, approved by Shannon 1 Nov 2026, since AI idea
  generation is its only identified consumer in this spec.
- **`strategy_steps`**: checklist items under a strategy, mirroring `tasks`
  structurally. Either Shannon or Asha can add or edit a step; only the
  assignee can tick it (Shannon, 1 Nov 2026) — the same tick-only-your-own
  rule as `tasks`, but add/edit is open to both here, unlike `tasks` where
  add/edit is creator+assignee gated.

### Permissions
- Shannon and Asha can both add and edit strategies, including each other's
  (Shannon, 1 Nov 2026) — the first object in this app where edit rights are
  not owner-only or creator/assignee-gated.
- **Archive** (status = archived, with a required reason and archived date)
  and **delete**: Shannon only, consistent with the existing rule that the
  partner cannot delete. Archived strategies drop off the active list and stay
  in history.
- Either person can add or edit a strategy's steps; only the step's assignee
  can tick it.
- The goals and milestones themselves stay owner-only (Shannon) — see §4.

### Keeping it updated
- **Progress** comes from the Numbers page. Balances and income are updated
  there and the goals and milestones recalculate. Nothing is entered twice.
- **Strategy details** are edited on the strategy using the same fields as the
  worksheet template.
- **Review:** each strategy goes stale after a **fixed 90-day review period**
  (Shannon, 1 Nov 2026). A settings screen to change this period is explicitly
  deferred, not built in Steps 1–4.

### Seed data
Seed from `docs/STRATEGY_WORKSHEET.md` (15 strategies, after strategy 11 —
bots/manual investment — was deleted and the rest renumbered). Every `?` stays
`?`.

---

## 6. New boxes on the Numbers page

- **Passive income streams — three new boxes, jointly owned** (Shannon, 1 Nov
  2026, revised): rental income, business income, investment income.
  Additional streams are added manually as new boxes when needed; these three
  are a starting set, not a hard limit.
- **Interest and dividends are NOT new boxes** (Shannon, 1 Nov 2026): passive
  interest is the existing `income.shannon.savings_interest` +
  `income.partner.savings_interest` facts; passive dividends is the existing
  `income.shannon.dividends` + `income.partner.dividends` facts — so nothing
  is entered twice. These four existing facts are `GBP_PER_YEAR` (confirmed
  in `vendor/wealth_core/migrate/from_v1.py`), while the passive income goal
  is monthly, so they are divided by 12 when summed into the goal's progress
  — see §8.2.
- Current total interest is ~£11/month, inside the Personal Savings
  Allowance, so it is treated as after-tax for now (Shannon, 1 Nov 2026).
  Flag this in `vendor/wealth_core/CHANGES.md`: needs a tax check if interest
  grows past the allowance — not built now, just recorded as a known gap.
- Each of the three new boxes is entered **after tax, monthly** (Shannon, 1
  Nov 2026) — the household enters the amount that actually lands in the
  account each month; the app performs no tax calculation on these figures.
  The section heading and every box label must say "after tax — what lands in
  your account" so this is never mistaken for a gross figure.
- Without these, the passive income goal shows zero progress.
- Home value and mortgage balance already exist and feed the net worth goal.

---

## 7. Goals page layout

One page, top to bottom:
1. **Current monthly surplus** (Shannon, 2 Nov 2026) — shown plainly on the
   Goals page itself, not only buried inside a goal's own feasibility card,
   so it's visible without needing a goal that happens to surface it.
   Built in Step 3.
2. The two goals, each with progress against its target.
3. Their milestones, nested beneath.
4. Strategies grouped by area (work and income, relocation, business, investing,
   property, spending), each showing its effect on net worth and on passive
   income, its status, and any `?` gaps.

Not on the Numbers page, which stays focused on confirming figures.

---

## 8. Engine (wealth-core)

Reuse; do not rewrite tax logic. Additions, each pure and tested:
1. **Net worth calculation** using the definition in §1.
2. **Passive income calculation:** sum of the three new monthly boxes plus
   the four existing `income.*.savings_interest`/`income.*.dividends` facts
   divided by 12 (see §6) — not a flat sum over a single list of keys, so
   this needs its own small calculation, same reasoning as net worth
   (neither fits the generic sum-only `progress_fact_keys` mechanism).
3. **Lever recalculation:** current facts plus a strategy's levers gives a new
   position against both goals, by adjusting inputs and calling existing
   calculations. Deferred to Step 6 (approved, Shannon 1 Nov 2026) — see §5.
4. **Inflation adjustment** per §2: deflates both 2030-money targets to
   today's money before comparison.

Fix before feeding Stage 2 (as FIXes with failing tests): `build_recap` silently
defaults the target to £4.5M and 10 years when facts are missing; it must
refuse instead. Remove Child Benefit (and the HICBC it triggers) from the
surplus calculation, per §3 — this household does not receive Child Benefit,
so the calculation's current assumption is wrong for this household's real
facts, not merely unconfirmed.

---

## 9. Learning layer (this project only)

- **Decision log:** append-only record of what was decided, when, why, and what
  it assumed.
- **Assumption vs actual:** when real figures arrive, compare them against each
  strategy's assumptions and record the difference, so future projections can be
  corrected.
- Everything relevant from the other projects (job hunt, crypto, investing,
  Ramsgate, business ideas) is entered here manually. No live integrations.

---

## 10. Build order

1. Engine changes and fixes (§8), including removing the old FIRE target/rate
   and the Child Benefit/HICBC fix (§3).
2. Numbers page: passive income stream boxes (§6).
3. Goals page: two goals and milestones (§1, §4, §7).
4. Strategies: data model, permissions, seed from worksheet, add/edit/archive/
   delete (§5).
5. Learning layer (§9).
6. AI idea generation, last and only after the above are in use. AI proposes
   strategies as structured levers; the engine calculates their effect; nothing
   is applied without Shannon or Asha accepting it. AI never edits facts, goals,
   tax constants or engine logic.

---

## 11. Still deferred

- Live integrations with other agents or projects.
- Annual budgets / budget-vs-actual.
- Quarterly tax review, law-change watch, grant discovery.
- A general in-app chat assistant.
- Tax models for countries other than the UK.
