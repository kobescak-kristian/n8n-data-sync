# AGENTS.md — n8n-data-sync

Agent-first context router. It points to where repository truth lives.
It is not itself evidence of project state: cite the source it routes
to, never this file.

## Repository purpose

An n8n workflow that syncs shop orders into a CRM (HubSpot): it checks every field, never creates a duplicate contact or order, never overwrites good data with blanks or older data, sends every failed order to a needs-attention list with a Slack alert and a replay step, and posts a daily summary. Human overview: `README.md`.

## Authority and conflict handling

| Question | Canonical source |
|---|---|
| What the system is and claims | `README.md` |
| Why a design decision was made | `adr/` |
| Build status, open decisions, change history | `STATE.md` |
| What the implementation actually does | source, tests and configuration inspected together |

When sources disagree: an adopted ADR outranks the text it amends;
documents state intent, implementation and tests state behaviour, and a
gap between them is a finding to surface, not something to silently
reconcile; `STATE.md` is the status surface; if canonical sources
conflict, stop and ask the owner.

## Task routing

Starting points, not exhaustive reading lists.

| Task class | Start here |
|---|---|
| Understand or explain the system | `README.md` |
| Current status or open decisions | `STATE.md` |
| Documentation / README / ADR work | the artifact itself; `.githooks/validate_artifacts.py` for enforced structure |

## Always-on constraints

- Tier 0 artifacts are README, ADRs, LICENSE, and AGENTS.md.
  STATE.md is separately required by the build-repo STATE rule.
  Do not create SYSTEM_WALKTHROUGH.md, CHANGELOG.md, RUNBOOK.md or
  other trigger-gated artifacts without an instruction citing the
  trigger. ADRs are for genuine material decisions only, with at least
  one required. Version log lives in README.
- Done means the acceptance condition is demonstrated, not that a file
  exists.
- No secrets or machine-local absolute paths in tracked files.
- Never rewrite git history.
- This file is an instruction surface, not a security boundary.

## Verification

- Tier 0 structure: `python .githooks/validate_artifacts.py .`
