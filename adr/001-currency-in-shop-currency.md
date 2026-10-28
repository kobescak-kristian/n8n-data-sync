# ADR-001: The order currency goes into the custom deal property `shop_currency`, not `deal_currency_code`

**Status:** Accepted (2026-10-28). Proposed 2026-10-20 (P2 probe) with the condition: the P3 build writes `shop_currency` and the first full visible run reads EUR, GBP and USD back exactly. Verified 2026-10-28: `workflows/live/core.json` writes `shop_currency` and no workflow sends `deal_currency_code`; N04 (GBP), N05 and M04 (USD) and the EUR cases passed in `tests/results/vis-10.json` to `vis-12.json` and `gated-4.json` to `gated-6.json`. Owner's words 2026-10-28, answering "Mark the 3 ADRs Accepted and add the 2 register entries?" (the second part is the kristian-os failure register): "Yes to both".
Date: 2026-10-20
Author: Kristian Kobescak (owner); drafted by a Claude Code build session (P2)

## Context

The test cases expect the deal currency exactly as the shop sends it: `EUR`,
`GBP` or `USD` (tests/CASES.md 3.2 row 5 and 3.4; visible cases N04 GBP, N05
and M04 USD). CASES.md 3.4 mapped it to HubSpot's own `deal_currency_code`,
"confirm in P2". R1 finding 1 warned that HubSpot rejects a
`deal_currency_code` the account has not set up, and that a free account has
one currency. BLUEPRINT v1.3 (stack line and P2 row) and CASES.md section 1
already say: if P2 confirms one currency, `currency` maps to a custom text deal
property `shop_currency`, by ADR; the expected values in the cases do not
change.

P2 probe (`python tools/probe.py --only hubspot`, run 1020065904, exit 0,
check H-CURRENCY) on the "Portfolio Demo" account:
- `/account-info/v3/details`: company currency `USD`, no additional
  currencies (one currency). The service key has no currency scope, so
  `/settings/v3/currencies/company-currency` answers 403; the account
  details call gives the same fact.
- Deal upsert with `deal_currency_code` = `EUR` and `GBP`: HTTP 400
  VALIDATION_ERROR. `USD`: 200.
- `shop_currency` (custom text deal property, created by the probe) stores
  `EUR`, `GBP` and `USD` and reads them back exactly.

## Decision

The logical field `currency` is written to the custom text deal property
`shop_currency`; the build does not send `deal_currency_code`.

## Alternatives rejected

- **Keep `deal_currency_code`.** Rejected: every GBP and EUR order gets a 400
  and ends `crm_bad_request` in needs-attention; a correct build would fail
  N04 (GBP) and every EUR case, which is most of the set.
- **Add EUR and GBP as currencies in the account.** Rejected: more than one
  currency needs a paid HubSpot tier; the build budget is $0 (BLUEPRINT
  section 0) and the demo account is shared with Q-116.
- **Convert amounts to the account currency.** Rejected: guessing an exchange
  rate changes money values; CASES.md 3.3 forbids any change of totals.
- **Send both (`deal_currency_code` only when it is USD).** Rejected: two
  places for one fact, and the stored value would depend on the account
  setup; one rule is easier to test and to explain.

## Consequences

- The tests' mapping table changes only in the HubSpot property name
  (CASES.md section 1 allows this by ADR); no case or expected value changes.
  The runner reads `shop_currency` for the logical field `currency`.
- In the HubSpot UI the deal amount shows in the account currency format
  (USD); the real currency is in `shop_currency`. README limit (STATE.md P6
  to-do already names it).
- The setup step creates `shop_currency` (done by the probe on 2026-10-20;
  the property stays as build setup).
- For a client with a paid multi-currency HubSpot, `deal_currency_code` with
  the currencies set up is the better field; the README "going live" section
  says so.

## Review

Reopen when the demo account (or a client account) has more than one
currency set up, or when HubSpot changes `deal_currency_code` validation.
