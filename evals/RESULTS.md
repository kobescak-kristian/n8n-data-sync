# Eval results: n8n data sync with checks (Q-129)

Gate and metric definitions: `evals/eval_config.yaml`; rules and case
format: `tests/CASES.md`. Every run is appended here, pass or fail;
entries are never edited or deleted. A run counts only when its results
artifact is committed and the runner exited with code 0.

Entry format: date | config version | workflow commit | dataset version
(generator commit, visible SHA-256, hold-out SHA-256) | runs | cases
passed per run | hard-rule breaks per rule | secret leaks | result (PASS
/ FAIL / INVALID RUN / NOT ENOUGH CASES) | miss analysis | cases that
changed between runs | newly broken cases | changed variables vs the
previous entry | secondary metrics | cost.

## Gate versions (not results)

- v2, 2026-10-20, before any run: R1 red-team test changes 2, 3, 4, 5
  and 11 ("Approved: R1 findings 2, 3, 4, 5 and 11 (test changes),
  owner, 2026-10-20."). No visible expected value changed. See
  `evals/eval_config.yaml` `changes`.
- v1, 2026-10-20: gate commit 849b93e.

## Entries

- **2026-10-20 23:15-23:33 | DEVELOPMENT, not gated** | config v2 | workflow commit a07d777 (pushed to
  local n8n 2.43.7 by `python workflows/build.py --push`) | visible set d4df6410... (generator 891c1d2) |
  - `dry-1` (N01, A04; dry run, not a result): runner exit 0, 2 of 2 passed, 0 hard-rule breaks, 0 secret
    leaks.
  - `dev-1` (22 visible cases, one or more per kind except R: M02 M04 E03 U04 U06 D02 D06 F01 V04 A01 A03
    A05 A06 T01 T03 T04 T05 T06 S01 S02 S04 S05): runner exit 0, 22 of 22 passed, 0 hard-rule breaks,
    0 secret leaks, 0 real HubSpot errors; median 2.8 s and worst 19.7 s from request to log row for
    synced orders; 4 retries (simulated faults); 65 HubSpot requests through the fault proxy.
  - `neg-1` (grader check): M04 sent again without the reset; the grader reported the miss (step 1
    result skipped_duplicate, expected created). Shows that a pass is not automatic.
  - Not run yet: R01-R05 (the runner needs the replay form password in `.env`). Cost: $0 (no AI step).
- **2026-10-21 00:02-00:11 | DEVELOPMENT, not gated** | config v2 | workflow commit a07d777 (as pushed; later
  commits changed no workflow) | visible set d4df6410... | `dev-2`: all visible cases except R01-R05 (62 of 67;
  the replay cases wait for the replay password in `.env`) | runner exit 0 | 62 of 62 passed | hard-rule
  breaks 0 | secret leaks 0 | real HubSpot errors 0 | no misses | median 2.4 s and worst
  19.3 s from request to log row for synced orders; 5 retries (simulated faults);
  168 HubSpot requests through the fault proxy | n8n exclusive slot 00:02-00:11
  (n8n-usage.md) | cost $0.
- **2026-10-21 02:34-03:04 | DEVELOPMENT, not gated** | config v2 | workflows of commit 362f3e1 (R2 fixes;
  pushed 02:25; `tests/n8n_match.py` exit 0, workflow hash 4e9a7829...; later commits changed only
  tests/runner.py) | visible set d4df6410... |
  - `dev-3` (62 of 67 visible cases, all except R01-R05; runner commit 23cca44, clean tree, reset): runner
    exit 0 | 61 of 62 passed | hard-rule breaks 2 (both H4, both S02) | secret leaks 0 | real HubSpot
    errors 0 | stray alerts after the last case 0. Miss analysis: S02 step 7 alerts and final alerts
    missed the `over_5` alert, and the new stray-alert check found it in the same case: the workflow sent
    and saved it, but after the summary row, and the runner read the step's alerts before it was saved.
    A runner timing hole, not a workflow fault (dev-2 passed S02 by timing). Fix 57f50f8: the runner waits
    for the over-5 alert of a summary step that expects one. Secondary: median 4.5 s (dev-2 2.4 s; the 3
    ledger rechecks add data-table reads) and worst 19.6 s from request to log row for synced orders;
    5 retries (simulated faults); 168 HubSpot requests through the fault proxy.
  - `dev-3b` (S02 again): INVALID RUN, the runner crashed on an SSL error in its own HubSpot read
    (`SSLV3_ALERT_BAD_RECORD_MAC`). Fix bf6e15d: the runner retries its own HubSpot calls after a
    network error.
  - `dev-3c` (S02 again, runner bf6e15d): runner exit 0 | 1 of 1 passed | hard-rule breaks 0 | secret
    leaks 0.
  - `dev-r1` (R01-R05): INVALID RUN twice (02:26 and 03:04), `REPLAY_PASSWORD` not found in `.env`; no
    case sent.
  - n8n exclusive slot 02:34-03:05 (n8n-usage.md) | cost $0.
- **2026-10-21 03:13-03:35 | DEVELOPMENT, not gated** | config v2 | visible set d4df6410... | R01-R05 only |
  - `dev-r1` (workflows of 362f3e1, runner bf6e15d+23cca44): runner exit 0 | 1 of 5 passed (R04, which has
    no replay step) | every replay request got HTTP 404 | hard-rule breaks 23 (all follow from the 404: no
    log row, no result) | secret leaks 0. Miss analysis: real bug (R2 finding 5, "the replay path has never
    run"): Form Trigger 2.4 reads its path from `options.path`; the build put it at the top level, so n8n
    registered the form under its random webhook ID (n8n 2.43.7 FormTriggerV2, `webhook_entity`). Fix
    79176ee, pushed; n8n now lists `q129-replay` (GET, POST); `tests/n8n_match.py` exit 0.
  - `dev-r2` (workflows of 79176ee): runner exit 0 | 1 of 5 passed (R04) | every replay request got HTTP
    401 | hard-rule breaks 23 (all follow from the 401) | secret leaks 0. Miss analysis: the form is found;
    its Basic Auth login refuses user `replay` with `REPLAY_PASSWORD` from `.env`, so the n8n credential
    `Replay n8n-data-sync` has another user name or password. Owner step.
  - n8n exclusive slot 03:13-03:35 (n8n-usage.md) | cost $0.
- **2026-10-21 06:07-06:16 | DEVELOPMENT, not gated** | config v2 | workflows of 79176ee | `dev-r3` (R01-R05):
  runner exit 0 | 1 of 5 passed (R04) | every replay request got HTTP 401 again | hard-rule breaks 23 (all
  follow from the 401) | secret leaks 0. The owner edited the credential at 04:05; n8n now shows its name as
  `replay n8n-data-sync` (the form still uses it by ID). Next: owner checks the credential's User and Password
  fields and puts the name back. n8n exclusive slot 06:07-06:16 | cost $0.
- **2026-10-21 08:02-08:05 | DEVELOPMENT, not gated** | config v2 | workflows of 79176ee (n8n match exit 0 at
  the runner start) | visible set d4df6410... | `dev-r4` (R01-R05; owner fixed the credential `Replay
  n8n-data-sync`: name, User `replay`, Password = `REPLAY_PASSWORD`): runner exit 0 | 5 of 5 passed |
  hard-rule breaks 0 | secret leaks 0 | real HubSpot errors 0 | no misses. With dev-3 (61 of 62) and dev-3c
  (S02) every visible case has now passed once on the R2-fixed build, in 3 separate runs (not one full
  run). n8n exclusive slot 08:02-08:05 | cost $0.
