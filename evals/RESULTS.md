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

- v4, 2026-10-26, after the P5 gated FAIL (H-R02) and the R3 blind-spot
  red team (q129-r3-blindspot-redteam.md in the shared notes): 9 new
  visible cases (76 in all; visible SHA-256 ea488c9d...), generator
  limits for parallel groups, ping and NaN read like the Code nodes,
  hold-out about 33 (owner, in the Q-129 session: "Pixel 9.",
  voice-to-text, read as "fix all 9"). No expected value of an existing
  visible case changed. The old hold-out is spent; a new one is written
  under v4. See `evals/eval_config.yaml` `changes`.
- v3, 2026-10-25, before any gated run: CASES.md 3.7, one retry on
  HubSpot's 404 `OBJECT_NOT_FOUND` for a contact upsert (owner, in the
  Q-129 session: "approved"). No visible expected value changed. See
  `evals/eval_config.yaml` `changes`.
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
- **2026-10-21 08:08-08:28 | DEVELOPMENT, not gated** | config v2 | workflows of 79176ee (runner at 62b631d;
  n8n match exit 0, workflow hash ca708c8b...; clean tree; reset) | visible set d4df6410... | `dev-4`: all 67
  visible cases | runner exit 0 | 67 of 67 passed | hard-rule breaks 0 | secret leaks 0 | real HubSpot
  errors 0 | stray alerts 0 | no misses | median 2.1 s and worst 19.1 s from request to log row for synced
  orders; 15 retries (simulated faults); 200 HubSpot requests through the fault proxy | n8n exclusive slot
  08:08-08:29 (n8n-usage.md) | cost $0. First full visible run on the R2-fixed build (P4 needs 3 in a row).
- **2026-10-21 08:41-09:42 | P4 VISIBLE RUNS, labelled not gated** | config v2 | workflows of 79176ee (runner at
  26f94bd; n8n match exit 0 at each start, one workflow hash ca708c8b... in all 3; clean tree; reset before each)
  | visible set d4df6410... | `vis-1`, `vis-2`, `vis-3`: all 67 visible cases each, one after the other |
  runner exit 0 three times | 67 of 67 passed in each run | hard-rule breaks 0 | secret leaks 0 | real
  HubSpot errors 0 | stray alerts 0 | cases that changed between runs: none | median 2.1 / 2.2 / 2.1 s and
  worst 19.1 / 19.3 / 19.2 s from request to log row for synced orders; 15 retries per run (simulated
  faults); 200 HubSpot requests per run through the fault proxy. `python tests/score.py` on the 3 files:
  exit 1, only for the hold-out checks (no hold-out in a visible run, as expected); every other gate check
  met. P4 item "3 full visible runs in a row meet the gate" met. n8n exclusive slot 08:41-09:42 | cost $0.

- **2026-10-22 01:10-01:20 | DEVELOPMENT, not gated (interaction sweep)** | workflows of 79176ee (hash ca708c8b..., n8n match exit 0) | sweep set e78351bd... (b6550b2) | `sweep-1`: runner exit 0, reset, tree clean | 14 of 17 (PASS 13, LIMIT 1, OBSERVE 1, MISS 2) | 0 stray alerts, 0 secret leaks | results `tests/results/sweep-1.json`
  - SW01 LIMIT: v2 then v1 1 s later; the deal shows v1 (stage, modified), ledger v2: the README limit (owner 2026-10-21).
  - SW02 MISS (H5): v1's deal write got 429 (5 s wait); the retry inside "HubSpot call" runs after the recheck, so v1 overwrote v2 about 5 s later; deal shows v1, ledger v2. Longer than the "about 2 seconds" README limit: owner decision.
  - SW03 MISS: v1 and v2 at the same moment; HubSpot answered 404 to one contact upsert (proxy real error at SW03:1), so v2 ended `needs_attention` `crm_bad_request` (row + alert); deal and ledger stay v1 until the next update. Not silent (H4 kept), but a real parallel-upsert answer the CASES retry rule does not cover.
  - SW19 OBSERVE: `HB-71190` and `hb-71190` became 2 deals, and a HubSpot search by `shop_order_id` finds both for either value (case-insensitive search): version 2 input.
  - Every other case passed: SW04 (one contact, 2 linked deals), SW05-SW09, SW11-SW14 (262144 bytes 200, 262145 bytes 413), SW18 (BOM -> not_json; raw UTF-8 synced exactly), SW20 (empty signature 401), SW21 (link failure -> needs-attention, resend closes the row). SW08 took 13.8 s (waits 0 s and 10 s, as CASES 3.7).

- **2026-10-25 01:40-02:58 (summer time) | DEVELOPMENT, not gated** | config v2 | workflows of 4d9fc57 (SW02 fix; pushed by `python workflows/build.py --push`, hash dccb95f5..., n8n match exit 0) | runner exit 0 on all 4 runs, reset, tree clean, 0 stray alerts, 0 secret leaks
  - `sweep-2` (sweep set e78351bd...): 15 of 17. SW02 now PASS (the fix works). SW01 LIMIT (README limit). SW03 MISS again (HubSpot 404 on one of two parallel contact upserts; owner option A). SW19 OBSERVE.
  - `vis-4` 66 of 67, `vis-5` 67 of 67, `vis-6` 66 of 67 (visible set d4df6410...), 0 hard-rule breaks. D02 ("Same event sent twice at the same moment", gated) missed in vis-4 (step 1) and vis-6 (step 2): one of the two parallel contact upserts for the new e-mail got a real HubSpot 404 (proxy real error at D02:1), so that event ended `needs_attention` `crm_bad_request` with a row and an alert; the other event synced, so contact, deal and ledger are right (no H break). HubSpot's answer, read from the n8n execution of "Q129 HubSpot call" (vis-6): category `OBJECT_NOT_FOUND`, "Cannot update contact that doesn't exist". The same race as SW03. Not seen in any run before 2026-10-22 (vis-1..3, dev-2..4: 0 real errors).
  - P4 item "3 full visible runs in a row meet the gate" is NOT met on 4d9fc57.

- **2026-10-25 02:06-03:28 (winter time, after 01:40-02:58 summer time) | DEVELOPMENT, not gated** | config v2 (gate v3 written after these runs; it adds only the retry these runs tested) | workflows of 8973aff (trial: one retry after 1 s on a HubSpot 404 `OBJECT_NOT_FOUND` for a contact upsert; owner 2026-10-25: "can be test your recommendation and if we see there is not working, then we proceed with third option. Before the official run."), hash 40a6c889..., n8n match exit 0 | runner exit 0 on every run, tree clean, 0 stray alerts, 0 secret leaks
  - Stress test (each run with a reset): `st-d02-1`..`st-d02-10` (`--only D02`): 10 of 10 PASS; a real HubSpot 404 came in `st-d02-2` and `st-d02-10`, and the retry fixed both. `st-sw-1`..`st-sw-5` (`--sweep --only SW03,SW04`): SW04 5 of 5 PASS; SW03 2 PASS, 2 LIMIT (one with a 404), 1 MISS (`st-sw-1`, no 404: deal and ledger kept v1, so not the `limit_final` end state, which keeps the ledger at v2; a same-moment arrival inside the "about 2 seconds" README limit; the next update corrects it).
  - `sweep-3`: 16 of 17 (SW01 LIMIT; SW19 OBSERVE; SW02, SW03 PASS; SW04 had a 404 and passed).
  - `vis-7`, `vis-8`, `vis-9`: 67 of 67 each, 0 hard-rule breaks (a 404 race in vis-7 D02, fixed by the retry). Median sync 2.2-2.9 s, worst 19.3-19.9 s.
  - P4 item "3 full visible runs in a row meet the gate (labelled not gated)" is met on 8973aff.

- **2026-10-25 06:05 (winter time) | DRY RUN, not a result** | config v3 | workflows of frozen commit 83225a3 (hash 40a6c889..., n8n match exit 0, clean tree, reset) | visible set d4df6410... | `dry-2` (`--only N01,T01`): runner exit 0 | 2 of 2 passed | hard-rule breaks 0 | secret leaks 0 | stray alerts 0.

- **2026-10-26 01:25-03:07 (winter time) | P5 GATED SERIES | FAIL** | config v3 | frozen workflow commit 83225a3 (hash 40a6c889... in all 3 runs; n8n match exit 0 at each start; clean tree; reset before each; no `--only`) | visible set d4df6410... (generator 891c1d2), hold-out SHA-256 936a9e82... (archive aa35b829... matched the commitment; extracted to a new empty folder; no shared case ID or order number with the visible set; `python tests/make_cases.py --check <hold-out> --set holdout` exit 0) | 3 runs: `gated-1`, `gated-2`, `gated-3`, 96 cases each (67 visible + 29 hold-out) | runner exit 0 three times | 95 of 96 passed in each run | hard-rule breaks 0 (H1-H5) | secret leaks 0 | stray alerts 0 | `python tests/score.py tests/results/gated-1.json tests/results/gated-2.json tests/results/gated-3.json`: exit 1, "GATE FAIL: a case missed".
  - Miss analysis: the only miss is hold-out case H-R02 (kind R, replay), the same in all 3 runs. Order 68903 has two open needs-attention rows (from step 1 and step 2, both `crm_retry_exhausted`). At step 3 both must close; only the first closed, the second stayed open (misses "step 3 closed rows" expected [1, 2], actual [1]; "final attention rows"). Root cause, read from the n8n execution data (Core execution 48458): "Find open rows" returns both rows, but the Code node "Rows to close" runs with `executeOnce: true`, so its `$input.all()` sees only the first item. Its twin "Rows to close (skip)" has the same setting. The other 7 nodes with `executeOnce` and `$input.all()` read at most one row, so they are safe. No visible case and no sweep case has two open rows for one order, so no development run could catch it. A real v1 bug, not a grader or timing fault.
  - Cases that changed between runs: none. Newly broken cases: H-R02 is a hold-out case, first run here.
  - Real HubSpot errors: gated-1 0, gated-2 0, gated-3 2 (U04 step 1: network, "Remote end closed connection without response"; H-D01 step 1: 404 on a contact upsert, the gate v3 race). Both cases passed: the retry rules (CASES 3.7) handled them.
  - Secondary: median 3.0 / 2.3 / 3.2 s and worst 21.5 / 21.5 / 33.8 s from request to log row for synced orders; 26 / 26 / 28 retries; 286 / 286 / 288 HubSpot requests through the fault proxy.
  - Changed variables vs the previous entry: hold-out cases added (first gated series); workflows unchanged since vis-7..9 (same hash 40a6c889...).
  - The hold-out is now seen, so it cannot be used again for a gated result. Next (BLUEPRINT section 6 quality bar: "a FAIL recorded honestly and fixed in a new version"): see STATE.md.
  - n8n exclusive slot until 03:08 (n8n-usage.md) | cost $0.

- **2026-10-26 07:47-09:14 (winter time) | DEVELOPMENT, not gated (gate v4 build)** | config v4 | workflows of a156178 (pushed by `python workflows/build.py --push`; `tests/n8n_match.py` exit 0, workflow hash b50f0ef2... in every run; clean tree; reset before each run) | visible set ea488c9d... (76 cases), sweep set e78351bd... | runner exit 0 on all 5 runs, 0 stray alerts, 0 secret leaks
  - `dev-5` (`--only` the 9 gate v4 cases U07, A07, A08, T07, T08, R06-R09): 9 of 9 passed, 0 hard-rule breaks. The two-open-rows cases R06, R07, R08 and the empty-body cases A07, A08 pass on the fixed build.
  - `vis-10`, `vis-11`, `vis-12`: all 76 visible cases each, one after the other | 76 of 76 passed in each run | hard-rule breaks 0 | cases that changed between runs: none | real HubSpot errors: vis-10 1, vis-11 1 (both D02 step 1, the contact 404 race; the gate v3 retry fixed both), vis-12 0 | median 3.8 / 2.2 / 2.2 s and worst 20.0 / 19.4 / 19.2 s from request to log row for synced orders; 30 / 30 / 29 retries; 246 / 246 / 245 HubSpot requests through the fault proxy. `python tests/score.py` on the 3 files: exit 1 only for the hold-out checks (no hold-out in a visible run, as expected); every other gate check met. P4 item "3 full visible runs in a row meet the gate (labelled not gated)" met on the gate v4 build.
  - `sweep-4`: 16 of 17 (SW01 LIMIT, the README limit; SW19 OBSERVE, letter-case order numbers, version 2 list; its 2 H2 counts are that known observation). Same as sweep-3.
  - n8n exclusive slot 07:47-09:15 (n8n-usage.md) | cost $0.

- **2026-10-26 21:19 (winter time) | DRY RUN, not a result** | config v4 | workflows of a156178 (runner recorded HEAD febf097; later commits changed no workflow; hash b50f0ef2..., n8n match exit 0, clean tree, reset) | visible set ea488c9d... | `dry-3` (`--only N01,T01`): runner exit 0 | 2 of 2 passed | hard-rule breaks 0 | secret leaks 0 | stray alerts 0.

- **2026-10-26 21:21-23:03 (winter time) | SECOND GATED SERIES (gate v4) | PASS** | config v4 | frozen workflows of a156178 (runner recorded HEAD febf097: febf097 only added the hold-out commitment and STATE; workflow hash b50f0ef2... in all 3 runs; n8n match exit 0 at each start; clean tree; reset before each; no `--only`) | visible set ea488c9d... (76 cases), hold-out v4 SHA-256 8a227a4e... (34 cases; archive c294796d... matched the commitment; extracted into a new empty folder; holdout.json SHA-256 matched; no shared case ID or order number with the visible set; `python tests/make_cases.py --check <hold-out> --set holdout` exit 0) | PREFLIGHT before the series: item 1 n8n booked 21:20 (n8n-usage.md) and Q-117 told; item 1b nothing on port 8130, `python tests/check_execute_once.py` 0 findings; item 4 the planning session answered "None planned" (no KOS rule deploy, no n8n change, no Python or Node upgrade; its answer came after the series had started), n8n 2.43.7, Python 3.12.0, Node v24.20.0; item 5 `dry-3` above | 3 runs: `gated-4`, `gated-5`, `gated-6`, 110 cases each (76 visible + 34 hold-out) | runner exit 0 three times | 110 of 110 passed in each run | hard-rule breaks 0 (H1-H5) | secret leaks 0 | stray alerts 0 | `python tests/score.py tests/results/gated-4.json tests/results/gated-5.json tests/results/gated-6.json`: exit 0, "GATE PASS".
  - Miss analysis: no misses. Cases that changed between runs: none. Newly broken cases: none.
  - Real HubSpot errors: 1 per run, each the contact 404 race on a "same moment" case (gated-4 H-D02 step 1, gated-5 and gated-6 D02 step 1); the gate v3 retry fixed every one and the cases passed.
  - Secondary: median 2.4 / 2.2 / 2.1 s and worst 24.6 / 19.6 / 19.4 s from request to log row for synced orders; 37 retries per run (simulated faults); 365 HubSpot requests per run through the fault proxy.
  - Changed variables vs the first gated series (FAIL, 2026-10-26 01:25): workflows (gate v4 fixes: executeOnce off 9 Code nodes, empty-body signing), visible set 67 -> 76 cases, new hold-out (34 cases, written under gate v4 by a separate session).
  - n8n exclusive slot 21:20-23:05 (n8n-usage.md) | cost $0.
