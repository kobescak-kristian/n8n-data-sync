# STATE — n8n-data-sync

n8n data sync with checks (shop order webhook -> field and duplicate checks -> HubSpot contact + deal; failed orders to a needs-attention list with Slack alert and replay; daily summary); Upwork portfolio item 4 (Q-129) to support winning a first client.
**Classification:** PROJECT · T0
**Plan:** BLUEPRINT.md v1.2 LOCKED 2026-10-20 (Standard; decisions 1-7). Done = the five quality-bar items in BLUEPRINT.md section 6. Nothing is built; no n8n time used. Next: P1 eval gate (CASES.md, generator, 67 visible cases, config; no workflow), then P1b hold-out + R1 red team in separate sessions. No remote yet (`gh repo create` private is an owner step).
**Open decisions:** none. Owner steps before P2: keys, Slack app, webhook secret, replay login (BLUEPRINT.md section 3 table); a free n8n slot.

## Change Log
*(New entries on top. Phase closes require evidence: exit codes,
commit hashes, eval numbers.)*

- **2026-10-20** — P0 closed: BLUEPRINT.md v1.2 LOCKED by the owner ("approved."; decisions 1-4 locked). Backlog line Q-129 in kristian-wiki 59405c2 (pushed). Scaffold ecf12bf, KOS-CONTROLS OK.

- **2026-10-20** — Owner decisions (BLUEPRINT.md v1.1): eval level Standard ("Let's go with the standard"; Critical was proposed); HubSpot "Portfolio Demo" account; repo name `n8n-data-sync`. Hard rules H1-H5 replace the critical-failure list; red teams R1 (gate) and R2 (build).

- **2026-10-20** — Scaffold (new-project) and BLUEPRINT.md v1.0 draft for owner review. Q-129 proposed (next free in kristian-wiki BACKLOG.md on 2026-10-20; backlog line added at approval).
