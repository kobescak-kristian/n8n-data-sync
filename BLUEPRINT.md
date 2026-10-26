# BLUEPRINT — n8n data sync with checks (Upwork item 4)

## 0. Header

- Version: v1.3, 2026-10-20
- Status: LOCKED 2026-10-20 by Kristian Kobescak (owner: "approved.", after v1.1)
- Owner: Kristian Kobescak
- Build type: portfolio
- Built by: Claude Code sessions, one phase per session; hold-out cases by a separate session that never builds; red teams by fresh sessions that never build.
- Trigger: UPWORK_LAUNCH_PLAN.md item 4 ("Data sync with checks", the old Make P2 idea reshaped: no duplicates, no missing fields, alerts; owner 2026-10-18; build order 7, 6, 4).
- Backlog: Q-129 (kristian-wiki 59405c2). All n8n names below use Q129.
- Repo: `n8n-data-sync` (owner, 2026-10-20), private until the publish gate (publish is the owner's decision).
- Timebox and budget: about 8-10 hours in 2 build sessions, plus 1 hold-out session and the red-team sessions. No fixed date: done when the quality bar (section 6, "Done") holds. Money: $0 (no AI step; HubSpot free, Slack free).

## 1. Problem

A small online shop sells through WooCommerce and keeps customers in a CRM (HubSpot). Orders are copied by hand, or by an automation that breaks quietly: the same customer appears twice, an order is missing its total or e-mail, an update overwrites good data, and when a sync fails nobody knows until a report or a customer is wrong. Client words from the research: "receive complete and accurate customer + order data" (B-009, WooCommerce to Customer.io); "check for missing information, prevent duplicate contacts" (U-024); "It should run automatically and reliably, with error handling and alerts." (U-011); "What do you normally do to prevent duplicate records or failed automations?" (P-18). Data family = 24 of 128 posts (19%); duplicate prevention named in 10 posts (career research 2026-10-18_upwork-n8n-demand-extended.md, F-06, F-08, F-19, F-27).

## 2. Scope

The demo shop is made up: **Harbour E-Bikes** (the same made-up company as item 6, so the portfolio tells one story). All names, e-mails (example.com domains), phones, addresses and orders are invented (F-112: no real business data).

What v1 does:
- **Takes shop orders in.** One webhook that receives WooCommerce order events (`order.created`, `order.updated`) in WooCommerce's real JSON format. It checks the WooCommerce signature; a request without a valid signature is rejected and nothing is written.
- **Checks every order before any write.** Required fields present (order number, e-mail, a name, total, currency, status, dates); formats valid (e-mail, total as a number with at most 2 decimals and not negative, currency in the allowed list, known status, valid dates). An order that fails a check is not written; it goes to the needs-attention list with the reason.
- **Cleans safe things only.** Trims spaces, lowercases the e-mail, joins double spaces in names, maps the shop status to a CRM deal stage. Nothing is guessed: no phone country guessing, no name case changes, no "fixing" of a total.
- **Syncs to HubSpot.** One contact per e-mail (created or updated) and one deal per order (created or updated), linked to the contact. Fields: name, e-mail, phone, company, address, city, postcode, country; deal name "Order #<number>", amount, currency, stage, order date.
- **Never creates a duplicate.** Same e-mail in another case or with spaces = the same contact. The same order sent again (WooCommerce resends on errors), or twice at the same moment, gives one deal. The key is the order number, checked in a sync ledger before the first write and enforced again by HubSpot (upsert by a unique order-number property).
- **Never overwrites good data with worse data.** An update with an empty field keeps the existing value. An older update that arrives after a newer one is skipped.
- **Retries the CRM safely.** HubSpot rate limit (429), server errors and timeouts are retried; every write is an upsert by its key, so a retry cannot create a duplicate.
- **Needs-attention list with replay.** Every order that is not synced gets one row (reason, payload, time) and one Slack alert in `#data-sync-alerts`. When the shop sends a fixed version of the order, the sync goes through and the row is closed by itself. After a CRM outage, a person presses replay in a small form; the order syncs once.
- **Daily summary.** One Slack message a day: orders synced, updated, skipped as duplicate or older, sent to needs-attention, still open. Extra alert when more than 5 orders fail in one day.
- **Log.** One row per event: time, order, result, reason, HubSpot record IDs, retries, seconds.

Out of scope (v1):
- Any AI step (nothing here needs judgement; see decision 1).
- Two-way sync (HubSpot changes never go back to the shop).
- A nightly comparison of shop and CRM to find orders whose webhook never arrived (needs the shop API; version 2 idea).
- Products and line items in HubSpot (the deal carries the total only).
- Other shops (Shopify), other CRMs (GoHighLevel, Pipedrive), Google Sheets.
- Merging duplicates that already exist in the CRM before go-live.
- A real WooCommerce shop: the test runner sends real-format, signed WooCommerce payloads to the webhook.
- n8n Cloud and other n8n versions than the local 2.43.7.

## 3. Architecture

```
WooCommerce (test runner in the demo) -- signed order event -->
  Q129 Entry (webhook /webhook/q129-order)
    1. Signature check (HMAC-SHA256 of the raw body) -> bad or missing: 401, log, stop
    2. Ping or other topic -> 200, log "ignored", stop
    3. Answer 200 at once (WooCommerce turns a webhook off after 5 failed deliveries in a row)
  -> Q129 Core (sub-workflow)
    4. Field checks + safe cleaning (code) -> fail: needs-attention row + Slack alert, stop
    5. Ledger check (data table q129_ledger, key = order number):
       same version already synced -> skip "duplicate"; older version -> skip "older"
    6. HubSpot contact upsert by e-mail (empty fields not sent)
    7. HubSpot deal upsert by order number (unique property), link to contact
       429 / 5xx / timeout -> retry; 400 / 401 / 403 or retries used up -> needs-attention + alert
    8. Ledger row + log row; close an open needs-attention row for this order
  Q129 Replay (form): needs-attention row ID -> Core with the stored payload
  Q129 Summary (every day 08:00): counts from the log -> Slack; over 5 failures today -> alert
  Q129 Error (error workflow): any crash -> Slack alert
Test tools: Python runner (signs and sends payloads, reads HubSpot and the tables back, scores),
  local fault proxy in front of HubSpot (port 8130; forwards, or returns 429/5xx/timeouts for
  cases marked simulated), reset script (archives only this build's demo records).
```

**Stack proposal:**
- **n8n:** local 2.43.7, shared with other builds. Names prefixed `Q129`, tag `q129`, data tables `q129_*`, webhooks `/webhook/q129-*`, fault proxy port 8130. Never restart, upgrade or reconfigure n8n; never touch other builds' workflows or credentials. Building in parallel is always fine. Before exclusive use (a full or gated test series, or anything that affects n8n as a whole): read `n8n-usage.md` in the shared notes; if another build has an open line (not DONE), wait for its "free" message; if not, add the line "IN USE Q-129 from HH:MM, expected end HH:MM, <what>" and send a one-line message to the other build sessions. When finished: mark the line DONE and send a one-line "n8n free" message. Messages only at start and end of exclusive use (owner rule, 2026-10-20). Session IDs of the other builds: in that shared notes folder or from the planning session.
- **HubSpot:** the existing free demo account "Portfolio Demo" (made for Q-116, separate from the owner's real HubSpot; owner, 2026-10-20). This build adds 2 custom deal properties (`shop_order_id`, unique; `shop_modified_at`) and 1 contact property (`sync_source`), plus a text deal property `shop_currency` if P2 finds that the free account has one currency (R1 finding 1; ADR). Its test records use only its own e-mail domains, and the reset touches only records with `sync_source = harbour-demo-shop`, so Q-116's contacts are never touched.
- **Slack:** the existing demo workspace; new channel `#data-sync-alerts`.
- **No AI provider, no Google, no new paid service.**

**New things the owner creates (no Q or item numbers in names, owner standard 2026-10-19):**

| What | Name | Where | Notes |
|---|---|---|---|
| HubSpot service key | `HubSpot n8n-data-sync` | HubSpot "Portfolio Demo" | scopes: contacts read/write, deals read/write, contact and deal schema write (the setup script creates the 3 properties) |
| n8n credential for it | `HubSpot n8n-data-sync` | local n8n | |
| Slack app | `n8n-data-sync` | demo workspace | chat:write; bot invited to `#data-sync-alerts` |
| n8n credential for it | `Slack n8n-data-sync` | local n8n | |
| Webhook secret | `WooCommerce n8n-data-sync` | n8n credential + `.env` (runner signs with it) | a long random string the owner generates |
| Replay form login | `Replay n8n-data-sync` | n8n Basic Auth credential + LastPass | protects the replay form |
| n8n API key | `n8n-data-sync` | local n8n | lets the build load workflows without a restart |

Values only in n8n, `.env` (git-ignored) and LastPass. No new account with any service.

Non-negotiables (build sessions may not change these):
- Nothing is written to HubSpot before all field checks pass.
- Every write is an upsert by its key (e-mail, order number); never a plain "create".
- An empty value never replaces a stored value; an older order version never replaces a newer one.
- Every order ends in exactly one place: synced, skipped (with the reason), or needs-attention with an alert. Never silent.
- The webhook answers WooCommerce with 200 for every signed request, including orders that fail a check.
- No secret in any log row, Slack message, file or result.

External actions:

| Action | Target | Human check before it |
|---|---|---|
| Contact and deal upsert | HubSpot (in client use: the client's CRM, which sales and reports rely on) | none by design; code checks before every write, failures to a person (Standard: records keep a history and can be undone, see 5.) |
| Replay | HubSpot | a person presses replay in the form |
| Alert, daily summary | own Slack channel | none needed (internal) |

AI and LLM steps: N/A because v1 has no AI step (decision 1).

Reliability and security defaults:

| Line (rows) | Default | This build |
|---|---|---|
| Entry points (S4, S5, P11, R5) | auth on every entry; schema check first; no test-only entry in the live copy; check_n8n_workflows.py exit 0 | order webhook: WooCommerce HMAC signature; replay form: n8n form with Basic Auth credential `Replay n8n-data-sync`; test helpers (reset, report) live only in the test copy and are left out of the live export; tests/check_n8n_workflows.py exit 0 before the frozen commit |
| Duplicate key (R8, L2) | key per trigger, checked before the first write | order number (ledger `q129_ledger`, then HubSpot unique property `shop_order_id`); e-mail for contacts (HubSpot upsert by e-mail) |
| Retries (R7, L4) | which errors, how many, wait; writes only with a key; no double retry | HubSpot 429: wait the time HubSpot gives, at most 10 s; 5xx, timeout, closed connection: 2 retries after 2 s and 8 s; 400/401/403/404: no retry. Node retry off; one own loop. All writes are upserts |
| Failure path (R6, R9, R12) | error workflow; every handled error alerts; one needs-attention place with replay | `Q129 Error` error workflow; table `q129_attention` + Slack alert per row; `Q129 Replay` form |
| Silent-failure check (R12) | alert on no success in X hours or more than N errors a day | daily summary always posts (a missing summary is itself visible); alert when more than 5 orders fail in one day. "No order in X hours" is N/A for the demo (no real order flow); the README tells a client to set X for their shop |
| Credentials (S2, S3, S10; F-112) | owner, scopes, expiry, store, demo accounts; revoke replaced ones | table above; demo accounts only; HubSpot service key has no expiry, so it is revoked by the owner when the build closes or goes public, and any replaced key is revoked at source in the same step |
| Limits (R10, S7, P12, L3) | timeouts, caps, payload size, rate limits | HubSpot call timeout 15 s; webhook body over 256 KB rejected; HubSpot free-account rate limit checked in P2 and the runner paced under it; no AI cost |
| Model (A4) | exact model ID, fallback, alert on drift | N/A because there is no AI step |
| Approval (A2, S11) | approval before every write; off only with the client's written yes | no approval per write (that removes the point of a sync); replaced by code checks + needs-attention (eval level Standard, 5.); replay is a person's action and the log records who pressed it |
| Data (S9, R13, L6) | LLM gets only needed fields; retention per place | no LLM; log keeps order number, result, reasons, IDs (no e-mail, no address); ledger keeps order number, version and a SHA-256 of the cleaned data, not the values (R1 finding 13); needs-attention keeps the payload until the row is closed + 30 days; n8n executions pruned by the n8n default; Slack alerts carry order number and reason, not the address |
| Test and live (R3, R14) | live copy with own credentials and data; rollback written | demo only; README "going live" section: own HubSpot key, own secret, live export without test helpers; rollback = deactivate, import the previous commit, replay the needs-attention rows |
| Hosting (S12, P10) | managed host or hardened self-hosting | N/A for the demo (local shared n8n, not exposed); README tells a client to use n8n Cloud or a managed host |
| Code track (P1, P2, P5, P8) | lock file, audits, pinned actions | test tools only: Python standard library plus `requests`, pinned in `requirements.txt` with hashes |
| LangGraph (L1, L2, L4, L6) | — | N/A because there is no LangGraph |

## 4. Risks and failure modes

| Risk or failure | Mitigation | Test kind (5.) |
|---|---|---|
| Same customer twice (e-mail case, spaces) | trim + lowercase, upsert by e-mail | E, M |
| Same order twice (resend, two at the same moment) | ledger key + HubSpot unique order number | D |
| Bad or missing field reaches the CRM | field checks in code before any write | F, V |
| Good value replaced by a blank or by an older update | empty fields not sent; `shop_modified_at` compared | U, E |
| Wrong amount (for example "1.234,50" read as 1.2345) | total must match the strict number rule, else needs-attention | V, M |
| Fake request writes data | HMAC signature check on the raw body | A |
| WooCommerce turns the webhook off after 5 failed deliveries | 200 for every signed request; checks run after the answer | A |
| HubSpot down, slow or rate-limited | retries; then needs-attention + alert + replay | T, R |
| Order lost without anyone knowing | every order ends synced, skipped or in needs-attention; error workflow; daily summary | all kinds; S |
| Test data mixes with Q-116 in the shared HubSpot account | own e-mail domains, `sync_source` marker, reset touches only those | setup check |
| HubSpot free account cannot do what the design needs (unique property, upsert by it, archived value reuse) | first-hour check P2; fallback: ledger + search before create, with a recorded ADR | P2 exit gate |
| n8n webhook cannot give the raw body for the signature check | first-hour check P2; fallback: the signature check in a Code node on the binary body | P2 exit gate |
| Shared n8n busy | runs only in a free slot, announced in n8n-usage.md | preflight |

## 5. Eval gate

Rules and tables: eval-gate skill (skills/eval-gate/SKILL.md) and kristian-os EVAL_STANDARD.md; not copied here.

Eval level: Proposed Critical (it writes customer and order records into the CRM with no person checking each write, and deal amounts feed sales reports that people rely on; the skill names "write numbers others rely on later" as Critical. Standard is arguable because HubSpot keeps property history, so most wrong writes can be undone; when unsure, the skill says one level up)
Eval level: Decided Standard, owner, 2026-10-20 (CRM records keep a history and can be undone; shop and accounting stay the money truth)

- **Five hard rules** (named so cases and red teams can point at them; at Standard they are ordinary gated checks, and since every check here is code, one break in any case of any run = FAIL):
  - H1 right values: every HubSpot field equals the expected cleaned value (amount, currency, stage, e-mail, name, phone, address, order date).
  - H2 no duplicates: one contact per e-mail, one deal per order number.
  - H3 nothing bad written: an order that must fail a check, or an unsigned request, changes nothing in HubSpot.
  - H4 nothing lost or silent: every order is synced, skipped with a reason, or in needs-attention with a Slack alert; a crash alerts.
  - H5 good data kept: no stored value is replaced by a blank or by an older order version.
- Approval per write: not part of Standard (records keep a history and can be undone); everything that fails a check goes to a person.
- README limit: if a client's HubSpot amounts feed invoicing or accounting, the level for that client is Critical (stricter test and review setup).
- **Code checks, 100%:** there is no AI step, so every case is a code check; a miss is a bug. PASS = every gated case gives its expected result in all 3 runs and 0 critical failures. No % claim (the rate table does not apply; eval-gate §3).
- **Repeat runs:** the full set (visible + hold-out) runs 3 times on one frozen workflow commit; results report the worst run and every case that changed between runs. (The skill asks one run for plain code; the owner's test standard asks 3, and real HubSpot timing can differ between runs.)
- **How a case is graded (code only):** after each case the runner reads back, through the HubSpot API and the n8n tables: number of contacts for the e-mail, number of deals for the order number, every expected field value (amount compared as an exact decimal), the link between deal and contact, the ledger row, the needs-attention row and its reason code, the Slack alert (message ID logged), the log row. Simulated failures are labelled "simulated" in the results.

**Case kinds** (visible = written now with the gate; hold-out = about 30%, written later by a separate session from tests/CASES.md only, sealed by SHA-256 before the build):

| Kind | What | Expected | Visible |
|---|---|---|---|
| N | clean order, new customer | contact + deal created, all fields exact | 5 |
| M | messy but valid: spaces, upper-case e-mail, accents and non-Latin names, phone formats, optional fields missing, guest checkout, total "1250.5" | synced with the cleaned values; nothing rejected | 8 |
| E | existing customer: second order, same e-mail in another case, update without phone | same contact, new deal; existing phone kept | 6 |
| U | order updates: status change, refund, edited total, an older update arriving late, e-mail corrected | deal updated; older update skipped | 7 |
| D | duplicate orders: resent, sent twice at the same moment, resent after an update | one deal; skip reason "duplicate" | 6 |
| F | missing required field (one case per field) | needs-attention + alert; nothing written | 7 |
| V | invalid format: bad e-mail, negative total, "12,50", unknown currency, unknown status, bad date | needs-attention + alert; nothing written | 7 |
| A | entry: no signature, wrong signature, body changed after signing, ping, other topic, not JSON, empty body | 401 or ignored; nothing written | 8 |
| T | HubSpot errors (simulated through the fault proxy): 429 then OK, 5xx then OK, timeout then OK, 5xx every time, 401, 400, closed connection, 403, 404 | retried and synced once; or needs-attention + alert, no retry on 4xx | 8 |
| R | replay and fix at source: replay after an outage, replay twice, replay of a closed row, fixed order sent by the shop, two open rows for one order, replay of a missing row | synced once; row closed | 9 |
| S | alerts and summary: summary counts match the log, over-5-failures alert, forced crash in an automatic run alerts | as written | 5 |

Visible total 76 (gate v4; 67 before). Hold-out about 33 (at least 2 per kind; it brings every kind to at least 7). Total about 109, hold-out share about 30%.

- Eval config: `evals/eval_config.yaml` + `tests/CASES.md` (rules and the case format) + generator `tests/make_cases.py` (deterministic; checks the whole set every run and stops on duplicate case IDs, a shared order number or e-mail between cases that are not marked related, a missing dependency, or an unknown expected result; a test plants each mistake) — committed before the first workflow. WooCommerce payload shapes copied from the current WooCommerce REST API docs, checked on the day.
- Results: `evals/RESULTS.md`, every run recorded, pass or fail. Hold-out opening: same procedure as item 3 (check the seal, extract to a new empty folder, stop on any shared case ID or order number).
- Build checks and red teams (eval-gate rule 7, Standard): 2 red teams, R1 of the gate before P3 and R2 of the build before the first gated run (with the interaction sweep); generator self-check and written preflight before the first gated run. Red-team findings that are not breaks of H1-H5 or real bugs go to the version 2 list in STATE.md (decision 4).
- Secondary, reported not gated: seconds per order (median, worst), HubSpot calls per order, retries per run.
- Claims: "on my test set of N made-up WooCommerce orders, 0 duplicates and 0 wrong values in 3 runs", worst run, from a committed RESULTS.md entry only. Not measured: real shops, high volume, webhooks that never arrive.

## 6. Phases

| Phase | Delivers | Accept when (checkable) |
|---|---|---|
| P0 | scaffold (new-project), this blueprint | done: ecf12bf, KOS-CONTROLS OK; LOCKED v1.2; Q-129 kristian-wiki 59405c2 |
| P1 | eval gate: CASES.md, generator, 67 visible cases, config; no workflow | gate commit hash in STATE; `python tests/make_cases.py` exit 0, same SHA-256 twice; planted-mistake test exit 0 |
| P1b | hold-out (separate session) + R1 red team of the gate (separate session) | `evals/holdout_commitment.json` committed, builder re-checks the archive SHA-256 without opening it; R1 report in the shared notes, every finding fixed or recorded |
| P2 | owner creates the keys and the Slack app; first-hour check in n8n (waits for a free n8n slot) | `tools/probe.py` exit 0 on: raw-body signature check in the webhook; HubSpot unique property, upsert by it, two upserts at the same moment give one deal, an archived deal's order number can be used again; rate limit read; the 4 custom properties (`shop_order_id`, `shop_modified_at`, `sync_source`, `shop_currency`) can be created on the free account; account currency read (`/settings/v3/currencies/company-currency` or the UI): one currency means `currency` maps to `shop_currency` (R1 finding 1); a 409 or 207 answer to two parallel upserts, two parallel contact upserts with the same new e-mail give one contact, two parallel ledger writes for one new order give one row (R1 finding 6); round-trip of every field (write, read back by ID, compare): phone stored raw (phone validation off), double spaces and non-Latin text unchanged, `closedate` unchanged when the stage moves to Closed Won or Closed Lost, `shop_modified_at` is a date-time property, an archived contact's e-mail can be used again (R1 finding 7). Or a fallback recorded in an ADR |
| P3 | entry, core, ledger, needs-attention, replay, summary, error workflow, fault proxy, runner, scorer, reset; first ADR | dry run on 2 cases, runner exit 0 (not a result); full visible run recorded in RESULTS.md, runner exit 0 |
| P4 | pre-gate readiness | R2 red team of the build (separate session) report in the shared notes, findings fixed or recorded; interaction sweep cases added; 3 full visible runs in a row meet the gate (labelled not gated); `evals/PREFLIGHT.md` done; checkpoint review of the frozen commit OK; 2-case dry run exit 0 |
| P5 | 3 gated runs (visible + hold-out, one frozen commit) | 3 entries in RESULTS.md, runner exit 0; PASS or FAIL recorded |
| P6 | README in client words + diagram + limits + "going live" steps, cover image, Loom if top 3-4 | eval-gate build-checks.md "Before go-live" items for every build done (forced failure in an automatic run alerts in `#data-sync-alerts`; frozen test PASS on the shipped commit); publish gate is a separate owner decision |

**Done (quality bar)** — all five hold:
1. End to end: a signed WooCommerce order event becomes one HubSpot contact and one linked deal with exact values; updates, resends and late older updates are handled; every failed order is in needs-attention with a Slack alert, and replay works.
2. Safety: 0 breaks of the five hard rules (H1-H5) in all 3 gated runs.
3. Every gated case gives its expected result in all 3 runs (code checks 100%), or the FAIL is recorded honestly and fixed in a new version.
4. Test standard met: 67 visible cases written before the build (9 more added with gate v4, after the first gated series), about 30% hold-out by a separate session, 3 runs, worst run reported, every run recorded.
5. README in client words with the diagram, the limits, "going live" steps and a cover image; numbers only from RESULTS.md.

## 7. Decisions

Locked (owner, 2026-10-20 plan approval; change only by a dated line in 8.):
1. No AI step in v1 (2026-10-20). Every check here is a fixed rule, and code is cheaper, faster and testable to 100%. The README says "AI only where it helps" as a selling point. Rejected: an AI step that cleans messy fields (adds cost, a rate claim, and a new way to write wrong values).
2. Upsert by key for every write, ledger plus HubSpot unique property (2026-10-20). Rejected: search before create (HubSpot search can lag a few seconds behind writes, so two quick events can still make a duplicate).
3. Fix at source, replay for outages (2026-10-20). A failed order is fixed in the shop, and the shop's update closes the row; replay is only for CRM outages. Rejected: an edit form for the payload (a second place where data is typed by hand, and more to test).
4. Red teams stay at the Standard two (2026-10-20); a finding that is not a break of H1-H5 or a real bug goes to the version 2 list, not into this build. Why: item 7 needed six fix rounds before a similar rule (its decision 16). Rejected: open-ended red teams.

Decided (owner, 2026-10-20):
5. Eval level Standard (see 5.). Rejected: Critical (it adds a red team after every build phase and a safeguard line, while the gate is already 100% because there is no AI step; the CRM records can be undone).
6. HubSpot: the existing "Portfolio Demo" account, separated from Q-116 as in 3. Rejected: a new HubSpot account.
7. Repo name `n8n-data-sync`. Rejected: `n8n-ai-data-sync` (there is no AI step).

Open:
- n8n slot for P2-P5: owner says when n8n is free (P1 and P1b need no n8n).
- Owner creates the keys, Slack app and secret in the table in 3. before P2.

## 8. Version log

- v1.4 2026-10-26: gate version 4 after the P5 gated FAIL (hold-out H-R02, evals/RESULTS.md 2026-10-26) and the R3 blind-spot red team (q129-r3-blindspot-redteam.md in the shared notes). Owner's words in the Q-129 session: "Pixel 9." (voice-to-text; read as "fix all 9"), answering the request to approve R3 findings 1-9, the H-R02 fix and gate v4. Section 5: 9 new visible cases (U 7, A 8, T 8, R 9; 76 in all), hold-out about 33. Details: evals/eval_config.yaml v4 and tests/CASES.md. No expected value of an existing visible case changed.
- v1.3 2026-10-20: R1 red team of the gate applied as gate version 2 (report q129-r1-gate-redteam.md in the planning session's shared notes). Owner decision: "Approved: R1 findings 2, 3, 4, 5 and 11 (test changes), owner, 2026-10-20." (owner's words in the R1 session: "yes, I agrove."; confirmed in the planning session: "I approve the changes in that session"). Test changes in tests/CASES.md sections 3.14 (H4), 5.2 and 6, evals/eval_config.yaml v2 and tests/make_cases.py checks. Build notes: P2 probe items in section 6 (R1 findings 1, 6, 7, and the 4 custom properties), the data line in section 3 (13), the `shop_currency` fallback in the stack line (1); clarifying sentences in CASES.md (6, 8, 9, 10, 14, 16, 17). No expected value of any visible case changed.
- v1.2.1 2026-10-20: shared n8n coordination rule added to the stack line (owner's words, relayed by the planning session: "when one need exclusively for itself the platform, it needs to send messages to others and when it stop, again send the messages that it's free"). No other change.
- v1.2 2026-10-20: owner approval ("approved."): decisions 1-4 locked; LOCKED; Q-129 registered (kristian-wiki 59405c2).
- v1.1 2026-10-20: owner decisions: eval level Standard (critical failures CF1-CF5 become the hard rules H1-H5; red teams 2 instead of one per build phase; no safeguard line), HubSpot "Portfolio Demo", repo name `n8n-data-sync`.
- v1.0 2026-10-20: first version, for owner review.
