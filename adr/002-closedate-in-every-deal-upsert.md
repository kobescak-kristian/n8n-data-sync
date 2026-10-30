# ADR-002: Every deal upsert sends `closedate`, so HubSpot never sets it to "now" on a stage move

**Status:** Accepted (2026-10-28). Proposed 2026-10-20 (P2 probe) with the condition: the P3 build sends `closedate` in every deal upsert and the first full visible run reads U02's `closedate` back as sent. Verified 2026-10-28: the one place that builds the deal properties (`workflows/sync_js.py`, in `workflows/live/core.json`) always sets `closedate: d.order_date`; U02 passed in `tests/results/vis-10.json` to `vis-12.json` and `gated-4.json` to `gated-6.json`.
Date: 2026-10-20
Author: Kristian Kobescak; drafted with Claude Code (P2)
Text edit 2026-10-30, for publication: wording tidied; no decision, number or result changed. The original text is in git history.

## Context

The logical field `order_date` (`date_created_gmt` + `Z`) maps to the deal's
`closedate` (tests/CASES.md 3.4), and H1 requires it to be exact. Case U02
moves an order from `pending` (Appointment Scheduled) to Closed Won and then
Closed Lost; the expected `closedate` stays the order date. R1 finding 7(c)
asked P2 to prove that `closedate` stays as sent when the stage moves to
Closed Won or Closed Lost.

P2 probe, check H-CLOSEDATE:
- First run (1020065557): an upsert that sends `dealstage` = `closedwon`
  without `closedate` makes HubSpot set `closedate` to the current time
  (`2026-10-20T06:58:02.142Z`); the same for `closedlost`. Check FAIL.
- Second run (1020065904, exit 0): an upsert that sends the new stage
  together with `closedate` keeps `closedate` exactly as sent
  (`2026-10-08T08:00:00Z`) for both moves; a deal created directly in Closed
  Won with `closedate` also keeps it (H-RT-DEAL). Stage-only evidence again:
  `closedate` set to now (`2026-10-20T07:01:06.209Z`).

## Decision

Every deal upsert, create or update, sends `closedate` (the order's
`date_created_gmt` + `Z`) together with any `dealstage` it sends.

## Alternatives rejected

- **Send only changed fields on an update.** Rejected: a status-only update
  (U02) would let HubSpot overwrite `closedate` with the sync time; that is
  an H1 break in a field sales reports use.
- **Write `closedate` again in a second call after the stage move.**
  Rejected: two calls per update, and a short window where the wrong date is
  stored; one upsert with both fields is atomic.
- **Map `order_date` to a custom property and leave `closedate` to HubSpot.**
  Rejected: client reports filter deals by close date; the real order date
  belongs there.

## Consequences

- No conflict with "an empty value never replaces a stored value":
  `date_created_gmt` is a required field (CASES.md 3.2 row 7), so it is
  never empty when the deal is written.
- An older update is skipped by the ledger before any write (3.5), so an old
  `closedate` cannot come back through this rule.
- Not a change to any case or expected value.

## Review

Reopen if a HubSpot change makes `closedate` sent with a closed stage differ
from the value read back (the probe's H-CLOSEDATE check shows it), or if a
client wants the close date to be the payment or completion date instead of
the order date.
