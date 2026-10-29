# Changes

## 2026-10-29

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
