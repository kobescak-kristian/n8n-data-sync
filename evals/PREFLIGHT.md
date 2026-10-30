# PREFLIGHT — before each gated series

The written preflight (build check c): 7 items (1b added by gate v4), checked by hand before each gated series
(P5) and again when a series restarts. Not a code guard. "Preflight done <date time>" and any item that
needed action go into the first run's entry in `evals/RESULTS.md`.

Prepared 2026-10-21 (P4). Items 2, 3 and 6 are checked below on the current build. Items 1, 4 and 5 can
only be checked right before the series: fill them in then, with the time.

| # | Item | How to check | Status |
|---|---|---|---|
| 1 | The test tools are ours for the whole series | no other test series is planned on this n8n or on the HubSpot demo account in the series window; Slack `#data-sync-alerts` is used only by this system | before the series |
| 1b | No fault proxy left running (R3 finding 9) and no executeOnce trap (H-R02) | nothing answers on port 8130 before the series (the runner starts its own proxy from the current `tests/proxy.py`); `python tests/check_execute_once.py` exit 0 on the frozen commit (H-R02) | before the series |
| 2 | Every credential works and does not expire before the series ends | see "Credentials" below | checked 2026-10-21 |
| 3 | Every rate or daily limit on the test path, for 3 runs + 1 rerun | see "Limits" below | checked 2026-10-21 |
| 4 | No tooling change or tool upgrade during the series | n8n stays 2.43.7 and is not restarted; no change to the build tooling or to n8n is planned during the series; no Python or Node upgrade on this machine during the series | before the series |
| 5 | One dry case through the full path, runner exit 0 (not a result) | the P4 2-case dry run on the frozen commit: `python tests/runner.py --label dry-<n> --only N01,T01` exit 0 | before the series |
| 6 | Every line of BLUEPRINT section 3 "Reliability and security defaults" is built as written | see "Defaults" below | checked 2026-10-21 |

## Credentials (item 2)

All checked by use in the visible runs `vis-1`..`vis-3` and the replay run `dev-r4` (2026-10-21, `evals/RESULTS.md`):

- n8n credential `HubSpot n8n-data-sync` (HubSpot service key, Portfolio Demo): every sync case wrote and
  read back. A HubSpot service key has no expiry date (BLUEPRINT section 3, Credentials row).
- n8n credential `Slack n8n-data-sync`: every alert and summary row had a Slack `ts` (the grader counts an
  alert only with a `ts` and no `slack_error`). Slack bot tokens do not expire unless rotation is on.
- n8n credential `Crypto WooCommerce n8n-data-sync` and `.env` `Q129_WEBHOOK_SECRET`: signed cases 200,
  A01-A03 401 (same secret on both sides).
- n8n credential `Replay n8n-data-sync` and `.env` `REPLAY_PASSWORD`: R01-R05 5 of 5 in `dev-r4`.
- n8n API key `n8n-data-sync` (`.env` `N8N_API_KEY`): used by the runner and `tests/n8n_match.py`. Before
  the series: one `python tests/n8n_match.py` (exit 0) shows it still works; if the key was made with an
  expiry date, the date must be after the series end (n8n Settings > n8n API).
- `.env` `HUBSPOT_TOKEN` (the runner's own reads): used in every run.

## Limits (item 3)

Numbers from `vis-1`..`vis-3` (67 cases each, about 20 minutes each). A gated run has 67 + 29 = 96 cases,
so about 1.45 times a visible run: about 30 minutes. 3 runs + 1 rerun = 4 runs, about 2 hours.

| Limit | Per gated run (estimate) | 4 runs | Limit (source) | OK |
|---|---|---|---|---|
| HubSpot burst: 100 requests per 10 s | the runner paces its own reads to at most 6 per second; the workflow adds about 3 per synced order | — | P2 probe `tools/probe.py` (100 per 10 s, 10 per second) | yes, no 429 from HubSpot itself in `vis-1`..`vis-3` (`proxy_real_errors` empty) |
| HubSpot daily: 250,000 requests | about 290 workflow requests (200 per visible run x 1.45) + a few thousand runner reads | under 20,000 | P2 probe | yes |
| Slack `chat.postMessage` (about 1 per second per channel) | about 57 alerts + about 6 summaries (39 alerts and 4 summaries in the visible set, x 1.45) | about 250 | Slack API rate limits | yes, the posts are seconds apart |
| n8n | one execution per event (about 165 per run) on the local n8n | — | none | yes |
| E-mail | none (this build sends no e-mail) | — | — | n/a |

## Defaults (item 6, BLUEPRINT section 3)

| Line | Built as written? | Evidence |
|---|---|---|
| Entry points | yes | order webhook: HMAC check in the workflow (adr/003); A01 (no signature) and A02/A03 (bad signature) give 401 in every visible run. Replay form: Basic Auth; `dev-r2`/`dev-r3` got 401 with a wrong login (proof that the form rejects a request without the right auth). Test hooks only in the test copy (R2 finding 7). `python tests/check_workflows_gate.py` exit 0: `check_n8n_workflows.py` reports only the 4 accepted items of adr/003 (Kristian's decision 2026-10-21); run it again on the frozen commit |
| Duplicate key | yes | ledger `q129_ledger` by order number, HubSpot upsert by `shop_order_id` and by e-mail; D01-D06 pass |
| Retries | yes | workflows/build.py "HubSpot call": 429 waits Retry-After, at most 10 s; 5xx, timeout, closed connection: 2 retries after 2 s and 8 s; 400/401/403/404 no retry; T01-T06 pass |
| Failure path | yes | `Q129 Error` error workflow (S04); `q129_attention` + Slack alert per row; `Q129 Replay` form (R01-R05) |
| Silent-failure check | yes | summary always posts (S05: all zero still posts); over-5 alert (S02) |
| Credentials | yes | names as in the BLUEPRINT table (above); the HubSpot service key is revoked by Kristian when the build closes or goes public (P6 to-do) |
| Limits | yes | HubSpot call timeout 15 s; body over 262,144 bytes gets 413 (sweep SW14 checks the exact edge); runner paced |
| Model | n/a | no AI step |
| Approval | yes | no approval per write by design; replay is a person's action (form login) |
| Data | yes | log keeps order number, result, reasons, IDs; ledger keeps version + SHA-256; alerts carry order number and reason; secret-leak check 0 in every run |
| Test and live | yes | `workflows/live/` export without test hooks; "going live" text is a P6 README item |
| Hosting | n/a | demo only, local n8n not exposed |
| Code track | yes | test tools use the Python standard library only (`requirements.txt` says so): nothing to install, so no lock file is needed |
| LangGraph | n/a | no LangGraph |
