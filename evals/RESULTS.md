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

