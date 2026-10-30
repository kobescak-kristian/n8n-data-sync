# STATE — n8n-data-sync

n8n data sync with checks: a WooCommerce order webhook goes through field and duplicate checks to a HubSpot contact and deal; failed orders go to a needs-attention list with a Slack alert and a replay step; a daily summary goes to Slack. Portfolio demo with invented data.

**Classification:** PROJECT (portfolio demo)
**Status:** Complete v0.4 (2026-10-28). Private on GitHub until the publish gate passes. Next: the publish gate runs again, bound to the commit that will be public; then Kristian switches the repository to public by hand.
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
- 2026-10-30: publish-gate rulings (Change Log below).

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

- **2026-10-30 (process-noise sweep)**
  - Kristian's ruling: remove what does not help a reader; notes on booking the shared n8n go completely; his voice-to-text quotes become summaries; planning remarks go. History is not rewritten.
  - Removed: the n8n booking rule (with its notes on never restarting n8n and never touching other builds' workflows) and the v1.2.1 entry that added it, the "Shared n8n busy" risk row, the n8n-slot lines and the timebox line (BLUEPRINT.md); the slot times in the run entries and the booking note in the item 1 result (evals/RESULTS.md); the `shared_n8n` line (evals/eval_config.yaml); "the portfolio tells one story", "Loom if top 3-4" and the reason that pointed to another build (BLUEPRINT.md).
  - Rewritten: PREFLIGHT items 1 and 4 now say only what matters for a valid test (no other test series on the test tools, and no tool change during the series); quoted voice-to-text decisions in BLUEPRINT.md, evals/RESULTS.md, evals/eval_config.yaml and this file are summaries. The dated text-edit notes in those records say so.
  - Kept, because it helps a reader: the shared HubSpot demo account (it explains the `sync_source` marker and the safe reset), the winter and summer time marks (the runs crossed the clock change), and the credential fixes during development (they explain failed runs). `tests/cases/sweep.json` (its SHA-256 is recorded) keeps its SW16 note.
- **2026-10-30 (publish gate and label cleanup)**
  - Publish gate run on 2b05dbc: FAIL, 3 blockers. (1) The coverage canary `.githooks/.coverage-canary` was missing, so the publish scan of 2b05dbc stopped (exit 2); added, the same bytes as in the other public repositories. (2) 50 internal-label hits in tracked files. (3) The check that the system runs on 3 operating systems needed a ruling.
  - Kristian's rulings: remove every internal label and do not call him "the owner"; keep the `Q129` prefix; a short STATE; the 3-operating-system check is N/A.
  - Internal labels are removed from the tracked files (queue and failure numbers, private repository and note-file names, portfolio item numbers, job-post IDs, the private test procedure's name and section numbers, session names), records included (`evals/RESULTS.md`, the ADRs, BLUEPRINT.md); the original text stays in git history. Where a text means Kristian, it names him and does not call him "the owner"; where a quoted decision called him "the owner", it is now a summary, not a quote.
  - One exception, kept by Kristian's decision ("Keep control package", 2026-10-30): the control package (`.githooks/` hook and check scripts, `.github/workflows/kos-controls.yml`, the `.kos/` control files `controls.json` and `controls-manifest.sha256`, `.codex/`) is not edited by hand, because it is the same in every public repository and CI checks it against its hash list; these files still name the private control system and use the word "owner" (98 lines outside `.codex/` found by a case-insensitive search for "owner", "kos", "governance" and queue numbers, 56 of them in `.githooks/check_work.py`). The coverage canary `.githooks/.coverage-canary` holds one deliberate fake work-item label so that the publish scan can prove it reaches that folder.
  - The `Q129` prefix stays inside the product (workflow names, data tables, webhook path): renaming it would change the tested workflows. This short file replaces the long change log.
  - The 3-operating-system check is N/A: README advertises no keyless run path for the system; the keyed path (n8n, HubSpot, Slack) ran on local Windows only; `python workflows/build.py` (README going-live step 6) needs no keys and only rebuilds the workflow files, run on Windows only.
  - Code changed only in comments and docstrings: `python workflows/build.py` rebuilds `workflows/test/` and `workflows/live/` byte for byte unchanged; `python tests/make_cases.py` and `python tests/make_sweep.py` rewrite `tests/cases/visible.json` (SHA-256 ea488c9d...) and `tests/cases/sweep.json` (e78351bd...) unchanged.
  - Checks on Windows, all exit 0: the 3 unit tests (`tests/test_make_cases.py`, `tests/test_make_sweep.py`, `tests/test_sync_js.py`); `tests/score.py` on gated-4..6: GATE PASS; `tests/check_execute_once.py`: 0 findings; `tests/check_workflows_gate.py`: PASS; `.githooks/validate_artifacts.py` (the required-file check): PASS. Label scan of the staged files (publish scan, no allowlist file): PASS (exit 0); its only label hit is the canary decoy. A wider search for the removed label kinds outside the control package finds none, apart from Kristian's quoted words and a code variable named `owner`.
  - Secrets: 0 hits in history (the gate patterns, plus HubSpot, Slack, JWT, private-key and password checks); `.env` was never committed; Kristian checked every `.env` value against `git log -p --all`: only `N8N_URL` (a local address, not a secret) is in history.
  - `.kos/unit.json` status line updated (it said "scaffold only"). The other gate items PASS: eval (re-derived with `tests/score.py`), README, ADRs and LICENSE, anti-patterns, links.
