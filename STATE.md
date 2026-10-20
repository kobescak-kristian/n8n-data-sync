# STATE — n8n-data-sync

n8n data sync with checks (shop order webhook -> field and duplicate checks -> HubSpot contact + deal; failed orders to a needs-attention list with Slack alert and replay; daily summary); Upwork portfolio item 4 (Q-129 proposed) to support winning a first client.
**Classification:** PROJECT · T0
**Plan:** BLUEPRINT.md v1.1 DRAFT; eval level Standard, HubSpot "Portfolio Demo" and repo name decided by the owner 2026-10-20. Nothing is built; no n8n time used. Next: owner approves decisions 1-4 and LOCKs, then Q-129 backlog line, then P1 (eval gate before any workflow).
**Open decisions:** BLUEPRINT.md section 7 decisions 1-4 (no AI step; upsert by key; fix at source, replay for outages; red teams at the Standard two) and LOCK.

## Change Log
*(New entries on top. Phase closes require evidence: exit codes,
commit hashes, eval numbers.)*

- **2026-10-20** — Owner decisions (BLUEPRINT.md v1.1): eval level Standard ("Let's go with the standard"; Critical was proposed); HubSpot "Portfolio Demo" account; repo name `n8n-data-sync`. Hard rules H1-H5 replace the critical-failure list; red teams R1 (gate) and R2 (build).

- **2026-10-20** — Scaffold (new-project) and BLUEPRINT.md v1.0 draft for owner review. Q-129 proposed (next free in kristian-wiki BACKLOG.md on 2026-10-20; backlog line added at approval).
