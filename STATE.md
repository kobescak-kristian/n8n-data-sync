# STATE — n8n-data-sync

n8n data sync with checks (shop order webhook -> field and duplicate checks -> HubSpot contact + deal; failed orders to a needs-attention list with Slack alert and replay; daily summary); Upwork portfolio item 4 (Q-129) to support winning a first client.
**Classification:** PROJECT · T0
**Plan:** BLUEPRINT.md v1.2 LOCKED 2026-10-20 (Standard; decisions 1-7). Done = the five quality-bar items in BLUEPRINT.md section 6. P1 eval gate committed (849b93e); no workflow, no n8n time used. Next: P1b, both from tests/CASES.md only: hold-out by a separate session that never builds, and the R1 red team of the gate. No remote yet (`gh repo create` private is an owner step).
**Open decisions:** none. Owner steps before P2: keys, Slack app, webhook secret, replay login (BLUEPRINT.md section 3 table); a free n8n slot.

## Change Log
*(New entries on top. Phase closes require evidence: exit codes,
commit hashes, eval numbers.)*

- **2026-10-20** — P1 closed: eval gate committed before any workflow, gate commit **849b93e**. `tests/CASES.md` (rules 3.1-3.14, closed lists, case format, visible list, hold-out instructions), `tests/make_cases.py` (reference model + whole-set check, `--check` for the hold-out writer), `tests/test_make_cases.py`, `evals/eval_config.yaml` v1 (Standard, Decided owner 2026-10-20; gate = every gated case in all 3 runs, 0 H1-H5 breaks, 0 secret leaks), `evals/RESULTS.md` (no entries). Evidence: `python tests/make_cases.py` exit 0 twice, 67 cases (N5 M8 E6 U6 D6 F7 V7 A6 T6 R5 S5), 114 events, SHA-256 of `tests/cases/visible.json` d4df64103d3d36bea17c57c67aac88e7cb48c4f738ff47e70855d041fc6e9b9d on both runs; `python tests/test_make_cases.py` exit 0, 27 of 27 checks (22 planted mistakes stop with the right message, unchanged set accepted, hold-out id rule, set moved to hold-out ranges accepted, same bytes twice, nothing written on a stop). Sources checked on the day: WooCommerce REST API v3 docs (orders, webhooks; docs source commit 9315664), class-wc-webhook.php (signature, ping, body encoding), WooCommerce 11.2.1. `.gitattributes` keeps the case file bytes exact. HubSpot property names and stage labels (CASES.md 3.4) wait for the P2 probe. `python .githooks/validate_artifacts.py .` exit 1 only because adr/ has no record yet (first ADR is due in P3).

- **2026-10-20** — P0 closed: BLUEPRINT.md v1.2 LOCKED by the owner ("approved."; decisions 1-4 locked). Backlog line Q-129 in kristian-wiki 59405c2 (pushed). Scaffold ecf12bf, KOS-CONTROLS OK.

- **2026-10-20** — Owner decisions (BLUEPRINT.md v1.1): eval level Standard ("Let's go with the standard"; Critical was proposed); HubSpot "Portfolio Demo" account; repo name `n8n-data-sync`. Hard rules H1-H5 replace the critical-failure list; red teams R1 (gate) and R2 (build).

- **2026-10-20** — Scaffold (new-project) and BLUEPRINT.md v1.0 draft for owner review. Q-129 proposed (next free in kristian-wiki BACKLOG.md on 2026-10-20; backlog line added at approval).
