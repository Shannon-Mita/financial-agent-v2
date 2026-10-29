# Changes

## Known issues (not being changed — reported, not fixed)

- **Child Benefit charge is assessed on the partner's income only, not the
  higher earner's.** `recap/builder.py`'s `build_recap()` (and the
  `calc_monthly_surplus()` extracted from it) always calls
  `calc_child_benefit(num_children, p_salary, ..., pension_contribution=p_pension)`
  — hardcoded to the partner's salary/pension, regardless of which of the two
  earners actually has the higher adjusted net income. Real HICBC rules
  assess the charge on whichever partner earns more. This is only correct for
  a household where the partner actually is the higher earner. Not changed as
  part of financial-agent-v2's Stage 1 build (no verified-error case supplied,
  per the standing rule that tax/scoring logic changes need a failing test
  first) — flagging so it's a conscious, known limitation rather than a
  silent assumption.
- **`calc_income_tax`'s NI calculation is reduced by ANY pension
  contribution, not just salary-sacrifice ones.** `engine.py` computes both
  income tax and employee NI on `adjusted = gross - pension_contribution`.
  Reducing the NI base this way is only correct for salary-sacrifice pension
  arrangements — relief-at-source and net-pay contributions should lower
  taxable income but not the NI base. The engine does not distinguish
  arrangement types, and does not read a `salary_sacrifice` fact at all (it
  only exists as an uncurated `legacy.pensions.*.salarySacrifice` key — no
  `.py` file in the repo references `salary_sacrifice`/`salarySacrifice`).
  Reported per Shannon's request while building Stage 1's feasibility check;
  not changed.

## 2026-10-29

### FIX: higher-rate band shrank when Gift Aid was present, overstating tax above ~£112,570 with a donation

The previous fix on this line (`higher_band = ty.higher_rate_limit - basic_band`,
below) reused `basic_band` — which already includes the Gift Aid extension
(`+ gift_aid_gross`) — to size the 40% band too. That made the 40% band
*narrower* by the exact amount of the Gift Aid extension, instead of staying
fixed at £87,440: Gift Aid is supposed to push every higher band's threshold
up by the grossed-up donation amount, not eat into the 40% band's width.
Fixed to size the 40% band off the basic band's *fixed* width only
(`ty.basic_rate_limit - ty.personal_allowance`, no Gift Aid term), so Gift Aid
correctly shifts the additional-rate threshold up without shrinking the 40%
band itself.

Example: £200,000 gross, £800 raw Gift Aid donation (£1,000 grossed-up), no
pension, 2025/26 or 2026/27 — was computed as £76,003 income tax; the
correct figure, hand-computed, is £75,953 (basic band £38,700 @ 20% =
£7,740; higher band stays the full £87,440 @ 40% = £34,976; remainder
£73,860 @ 45% = £33,237) — a £50 overstatement per £1,000 of grossed-up
Gift Aid. This also corrects the previous fix's changelog claim that it
"extends correctly with Gift Aid" — it did not.

Regression tests added: `test_golden_200000_salary_with_gift_aid` in both
`tax_engine/tests/test_engine.py` (2025/26) and
`tax_engine/tests/test_2026_27.py` (2026/27). Full suite re-run after this
fix with no skips (a throwaway local Postgres container, not the usual
skip-without-`TEST_DATABASE_URL` path): `vendor/wealth_core` 179 passed,
outer repo `tests/` 70 passed, 0 failed.

### REFACTOR: extracted `calc_monthly_surplus()` out of `build_recap()` — no formula change

`recap/builder.py`'s monthly-surplus computation (both earners' take-home
plus net Child Benefit, minus the four monthly spending facts) was inlined
inside `build_recap()`, with no way to call it on its own. financial-agent-v2
needs this exact formula for its Stage 1 goal feasibility check and was
told not to write a second implementation of it — so it's now a standalone
function, `calc_monthly_surplus(...)`, exported from `recap/__init__.py`.
`build_recap()` calls it instead of inlining the same four lines.

This is a pure extraction: same formula, same lines, zero behaviour change.
Verified by `test_build_recap_output_unchanged_by_extraction` (asserts
`build_recap()`'s `required_monthly`/`track_status` on a fixed scenario are
identical to their pre-extraction values) plus direct unit tests of the new
function, including two tests isolating the pension's effect on income tax
alone and on the Child Benefit charge alone (requested to confirm the
engine's actual pension handling — see Known Issues above for what that
revealed). All 170 pre-existing tests pass unchanged; 7 new tests added.

### FIX: higher-rate band width was sized off `basic_rate_limit` instead of the fixed basic-band width, understating tax above ~£112,570

`tax_engine/engine.py`'s `calc_income_tax` sized the 40% band as
`higher_rate_limit - basic_rate_limit` (£125,140 - £50,270 = £74,870). The
real UK rule is that the 40% band runs from £37,700 to £125,140 of *taxable*
income — a width of £87,440 — because the additional-rate threshold
(£125,140) is itself expressed in taxable-income terms, not gross-income
terms. Using `basic_rate_limit` undercounted the band by exactly the full
Personal Allowance (£12,570), pushing income into the 45% band too early.
Fixed to `ty.higher_rate_limit - basic_band`, reusing the same fixed-width
`basic_band` already computed above it (so it also extends correctly with
Gift Aid).

Example: a £120,000 salary (no pension, no gift aid, 2025/26 or 2026/27)
was computed as £39,675 income tax; the correct figure, hand-computed
against GOV.UK, is £39,432 — a £243/year overstatement. Also verified at
£130,000 (£45,332 -> £44,703) and £200,000 (£76,832 -> £76,203).

Regression tests added: `test_golden_120000_salary`,
`test_golden_130000_salary`, `test_golden_200000_salary` in both
`tax_engine/tests/test_engine.py` (2025/26) and
`tax_engine/tests/test_2026_27.py` (2026/27). The existing £45,600 and
£105,000 golden cases were unaffected by this bug (their taxable income
never reaches the old, too-narrow £74,870 higher-band cap) and already
passed before this fix.

### FIX: basic-rate band width was shrunk by the personal-allowance taper, understating tax between £100,000-£125,140

`tax_engine/engine.py`'s `calc_income_tax` sized the 20% band as
`basic_rate_limit - pa`, using the *already-tapered* personal allowance. The
real UK rule fixes that band's width at its full-PA value (£37,700) —
exactly where the documented ~60% marginal rate in that band comes from, and
the taper bug produced only a ~50% marginal effect instead. Fixed to use
`ty.personal_allowance` (the full, untapered figure) in that one line only.

This was not specific to 2026/27 — it affected every tax year, including
2025/26 calculations already running live. Example: a £105,000 salary (no
pension, no other income) was computed as £29,932 income tax / £70,957
take-home; the correct figures, verified by hand against GOV.UK, are
£30,432 income tax / £70,457.40 take-home — a £500/year understatement.
This matches Partner's actual current salary in the household's data.

Regression tests added to `tax_engine/tests/test_engine.py` (the £105,000
case, the 60%-marginal-effect check, and gift-aid/pension interactions with
the now-fixed band width). All 47 pre-existing 2025/26 golden tests pass
unchanged — none of them asserted an exact income-tax value inside the
£100,000-£125,140 taper zone, so none had encoded the wrong figure.

### FIX: added the 2026/27 TaxYear entry

Added `TaxYear("2026/27")` to `tax_engine/facts.py` and bumped
`DEFAULT_TAX_YEAR` to `"2026/27"`. The 2025/26 entry is untouched.

Verified against GOV.UK, fetched 2026-10-29 (England) — unchanged from
2025/26 (frozen thresholds):
- Personal Allowance £12,570, tapered £1 per £2 of adjusted net income over
  £100,000, zero at £125,140+.
  https://www.gov.uk/income-tax-rates
- Income tax: 20% up to £37,700 taxable; 40% £37,701-£125,140; 45% above.
  https://www.gov.uk/income-tax-rates
- Employee Class 1 NI: primary threshold £12,570 (£242/wk), upper earnings
  limit £50,270 (£967/wk), 8% between, 2% above.
  https://www.gov.uk/national-insurance/how-much-you-pay
- Child Benefit: £27.05/wk eldest or only child, £17.90/wk each additional
  child. Annual figures use the same 52-week convention as 2025/26
  (`engine.py`: `annual = weekly * 52`), unchanged.
  https://www.gov.uk/child-benefit-rates
- HICBC: taper £60,000-£80,000, 1% of the benefit clawed back per £200 of
  income over £60,000.
  https://www.gov.uk/child-benefit-tax-charge

NOT verified for 2026/27 — left as `NotVerified` placeholders (see
`facts.py`) rather than copied from 2025/26, so any calculation needing one
raises `NotVerifiedForYear` instead of silently reusing a stale figure:
CGT exemption/rates, savings allowances, dividend allowance, ISA/JISA
allowances, pension annual allowance, trading allowance, IHT (nil-rate
band/RNRB/rate/gift exemption), SDLT additional-property surcharge.

Tests in `tax_engine/tests/test_2026_27.py`: golden £45,600 and £105,000
salary scenarios, HICBC at £70,000 (50% clawback) and £80,000+ (100%), the
52-week Child Benefit convention, every unverified field raising
`NotVerifiedForYear` on use, `calc_iht`/`calc_sdlt_surcharge` raising for
2026/27, `DEFAULT_TAX_YEAR` tracking the tax year containing today's date
(fails loudly after 5 April 2027), and 2025/26 unaffected by the addition.
