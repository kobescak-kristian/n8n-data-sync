# STATE — n8n-data-sync

- STATUS: DORMANT
  No work in progress; true as of 2026-11-12; updated when work resumes.

## Status

v0.5. Changes: README.md, Version Log.

## Latest result

Second gated series (gate v4): PASS, 2026-10-26. Results: `evals/RESULTS.md`.

## Open

- Next: none scheduled.
- Deferred (version 2): README.md, "Limits": ledger proof on SQLite only, letter-case order numbers, retention rule.
- Deferred (version 2): README.md, "Limits": crash after the HubSpot writes, Slack failure, n8n restart.
- Deferred (version 2): live summary time zone, README.md, "Going live" step 9.
- Deferred (version 2): the crash alert after the HubSpot writes carries no order number.
- Deferred (version 2): a Slack failure in live: no fallback channel, no failed-post count in the summary.
- Deferred (version 2): `crm_error` is not stored.
- Deferred (version 2): two replays of one row at the same moment can both count n+1 (sweep SW10).
- Deferred (version 2): check once that the crash alert text carries no e-mail (sweep SW15).
- Deferred (next test-case version): after 3 x `timeout_after_forward` on the deal, the ledger has no row
  while HubSpot holds the newer version, so a later older event is `created` (tests/CASES.md 3.5, 3.7).
