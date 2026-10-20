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

No entries yet.
