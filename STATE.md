# STATE — n8n-data-sync

n8n data sync with checks: a WooCommerce order webhook goes through field and duplicate checks to a HubSpot contact and deal; failed orders go to a needs-attention list with a Slack alert and a replay step; a daily summary goes to Slack. Portfolio demo with invented data.

**Classification:** PROJECT (portfolio demo)
**Status:** Complete v0.5 (2026-10-30). Public on GitHub since 2026-10-30 (publish gate PASS on f7dee9b). Keyless checks run in CI on Linux, macOS and Windows.
**Plan:** BLUEPRINT.md v1.4, LOCKED 2026-10-20 (eval level Standard; decisions 1-7). Done = the five quality-bar items in BLUEPRINT.md section 6.
**Limits:** README.md, section "Limits".
**Open decisions:** none.

## Phases

| Phase | Result | Evidence |
|---|---|---|
| P0 scaffold and blueprint | done 2026-10-20 | ecf12bf; BLUEPRINT.md v1.2 LOCKED |
| P1, P1b eval gate and sealed hold-out | done | gate v1 849b93e, v2 891c1d2, v3 d0b0245, v4 39b5c7d (2026-10-26); `evals/holdout_commitment.json` |
| P2 first-hour probe | done 2026-10-20 | f815621; `python tools/probe.py` exit 0, 15 of 15 checks |
| P3, P4 build, red teams R1-R3, interaction sweep, pre-gate checks | done 2026-10-20 to 2026-10-26 | development runs in `evals/RESULTS.md`; `evals/PREFLIGHT.md` |
| P5 first gated series | FAIL 2026-10-26 | 95 of 96 in each of 3 runs (hold-out case H-R02); `evals/RESULTS.md` |
| P5 second gated series (gate v4) | PASS 2026-10-26 | 110 of 110 in each of 3 runs, `tests/results/gated-4.json` to `gated-6.json`, workflows of a156178; `python tests/score.py tests/results/gated-4.json tests/results/gated-5.json tests/results/gated-6.json`: GATE PASS |
| P6 README, diagram, cover image | done 2026-10-28 | a428139; ADRs 001-003 Accepted in a5a8c38 |

## Decisions on record

- 2026-10-21: the window of about 2 seconds for two updates of one order is a README limit for v1; the checker exception for 4 items is recorded in adr/003 (`python tests/check_workflows_gate.py` is the check before a frozen commit).
- 2026-10-22: the SW02 fix (the ledger is read again after each retry wait).
- 2026-10-25: SW03 option A (keep `needs_attention`) and gate v3: one retry on HubSpot's 404 `OBJECT_NOT_FOUND` for a contact upsert (CASES.md 3.7).
- 2026-10-28: adr/001 (currency in `shop_currency`), adr/002 (`closedate` in every deal upsert) and adr/003 (order webhook v1 with "Binary File" on) Accepted.
- 2026-10-30: the keyless checks run in CI on Linux, macOS and Windows; the full test series stays local (it needs n8n, HubSpot and Slack).

## Version 2 list

Not breaks of the hard rules H1-H5 and not v1 bugs (decision 4):
- A crash after the HubSpot writes leaves no needs-attention row, and the crash alert has no order number (fix: read the order number from the failed execution, or write a "started" mark before the first write).
- A Slack failure is silent in live (no fallback channel, no failed-post count in the summary).
- The live summary runs at 08:00 in n8n's time zone (set the client's time zone at go-live).
- No retention rule for needs-attention and log rows; `crm_error` is not stored.
- Two replays of one row at the same moment can both count n+1.
- "One ledger row for two parallel writes" was proven on SQLite only (re-run the N-LEDGER probe on a Postgres n8n).
- Order numbers that differ only in letter case are two orders (sweep SW19).
- An n8n restart while Core runs can lose an order without an alert.
- Check once that the crash alert text carries no e-mail (sweep SW15).
- For the next CASES version: after 3 x `timeout_after_forward` on the deal, the ledger has no row while HubSpot holds the newer version, so a later older event is `created` by the rules (CASES 3.5, 3.7).

## Change Log
*(New entries on top. Phase closes require evidence: exit codes, commit hashes, eval numbers. Entries before 2026-10-30 are in the git history of this file.)*

- **2026-10-30 (public release and CI)**
  - Repository made public on 2026-10-30. Checked without login: page and API answer 200, a fresh clone is at f7dee9b, and the keyless checks pass in that clone.
  - CI workflow `tests` (9c8f3da): the keyless checks on Linux, macOS and Windows with Python 3.12 and Node 24. Run 41019469286 green on all three at the first attempt: 76 visible and 17 sweep cases OK; 12 workflow files, 0 findings; `tests/score.py` GATE PASS (110 of 110 in each of gated-4..6); the rebuild gives the committed files (visible SHA-256 ea488c9d..., sweep e78351bd...). The publish scan of 9c8f3da exited with code 0.
- **2026-10-30 (publication preparation)**
  - Documents tidied for publication (wording tidied, process-only notes removed); this file is now a short status file. No workflow, test case, number or result changed: `python workflows/build.py` rebuilds `workflows/test/` and `workflows/live/` byte for byte unchanged, and `python tests/make_cases.py` and `python tests/make_sweep.py` rewrite `tests/cases/visible.json` (SHA-256 ea488c9d...) and `tests/cases/sweep.json` (e78351bd...) unchanged. The earlier text is in git history.
  - Checks on Windows, all exit 0: the 3 unit tests (`tests/test_make_cases.py`, `tests/test_make_sweep.py`, `tests/test_sync_js.py`); `tests/score.py` on gated-4..6: GATE PASS; `tests/check_execute_once.py`: 0 findings; `tests/check_workflows_gate.py`: PASS; `.githooks/validate_artifacts.py`: PASS.
  - Publish gate on f98bad5: PASS. The publish scan of f98bad5 exited with code 0 (coverage canary found in the files and in history, zero blocking hits, secret patterns checked over all history); eval (`tests/score.py` GATE PASS), ADRs and LICENSE, links and the workflow audit PASS. Secrets at f98bad5: HubSpot, Slack, JWT and private-key checks over all history found 0 hits, and `.env` was never committed. Kristian checked every `.env` value against the history up to 2b05dbc: no key or token is in the history; the later commits change only text. The check that the system runs on 3 operating systems is N/A: README advertises no keyless run path; the keyed path (n8n, HubSpot, Slack) ran on local Windows only.
  - `.kos/unit.json` status line updated (it said "scaffold only").
