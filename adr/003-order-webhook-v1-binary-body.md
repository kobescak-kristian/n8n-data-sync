# ADR-003: The order webhook is an n8n Webhook node v1 with "Binary File" on; signature check and JSON parse run on the raw bytes

**Status:** Proposed (2026-10-20, P2 probe). Becomes Accepted when `Q129 Entry` is built this way and the first full visible run passes the A cases (A01-A06).
Date: 2026-10-20
Author: Kristian Kobescak (owner); drafted by a Claude Code build session (P2)

## Context

WooCommerce signs the exact body bytes: base64 HMAC-SHA256 with the webhook
secret, and the body uses PHP escaping (`\/`, `\uXXXX`) (tests/CASES.md
section 1). The entry must check the signature on those exact bytes and
compare in constant time (CASES.md 3.1 step 3). A signed body that is not
JSON must still get HTTP 200 and go to needs-attention with reason
`not_json` (CASES.md 3.1 step 5; visible case A06 sends it with
`Content-Type: application/json`). BLUEPRINT section 4 names the P2 risk "n8n
webhook cannot give the raw body for the signature check" with the fallback
"the signature check in a Code node on the binary body".

P2 probe, check N-SIG (`python tools/probe.py --only n8n`, n8n 2.43.7):
- Run 1020181826, Webhook node v2.1 with the option "Raw Body": a signed
  body that is not JSON got HTTP 422 from n8n itself before any node ran. n8n
  parses every `application/json` body first
  (`dist/webhooks/webhook-helpers.js` `parseRequestBody`, then
  `middlewares/body-parser.js`, "Failed to parse request body"). So A06
  cannot get its 200, row and alert with a v2 webhook. (The other answers in
  that run were 500 from a mistake in the probe's own Code node.)
- `parseRequestBody` returns before parsing when the start node is version 1
  with the option `binaryData` ("Binary File") on; the node then writes the
  request stream unchanged into the binary field `data`.
- Run 1020182242 and the full run 1020182301 (exit 0, 15 of 15), Webhook v1
  with "Binary File" on, then a Code node that reads the bytes with
  `this.helpers.getBinaryDataBuffer(0, 'data')` (n8n keeps them in its binary
  store, so only the node that gets the binary as its own input can read
  them), then the Crypto node (HMAC SHA256, base64, credential
  `Crypto WooCommerce n8n-data-sync`) on the same binary, then a constant-time
  compare: signed 200; wrong signature, body changed after signing and no
  signature 401; signed body that is not JSON 200 with `JSON.parse` failing
  in the Code node (so `not_json` can be raised); ping body 200. The bytes in
  n8n equal the bytes sent, and the n8n credential gives the same signature
  as `Q129_WEBHOOK_SECRET` in `.env`.

## Decision

`Q129 Entry` starts with a Webhook node of version 1 with "Binary File" on.
The size check, ping check, signature check (Crypto node on the binary, then
a constant-time compare in code) and the JSON parse all run on the raw bytes
in the workflow.

## Alternatives rejected

- **Webhook v2 with "Raw Body".** Rejected: n8n answers 422 for a signed body
  that is not JSON before the workflow runs, so A06 (200 + `not_json` row +
  alert) cannot pass, and a real shop sending a broken body would get no
  needs-attention row (H4 "never silent").
- **Re-create the bytes with `JSON.stringify` of the parsed body.** Rejected:
  PHP escapes `/` and non-ASCII letters, JavaScript does not, so the HMAC
  would differ for most real orders.
- **A small proxy in front of n8n that signs off the body.** Rejected: one
  more service for a client to run, and the check would no longer live in the
  workflow the client sees.

## Consequences

- The workflow parses the JSON itself (a Code node with `try`/`catch`); n8n
  gives no `body` object. This is the place where `not_json` is decided.
- The 256 KB limit (CASES.md 3.1 step 1) is checked on the binary length in
  the same Code node; n8n's own limit is far higher.
- Version 1 of the Webhook node is an older node version. n8n still ships it
  in 2.43.7; a later n8n upgrade must re-run `python tools/probe.py --only n8n`
  (README "going live" note).
- The Code node that reads the bytes must come right after the webhook (the
  Crypto node drops the binary from its output).

## Review

Reopen when n8n changes webhook body parsing (a v2+ option that skips
parsing), or when an n8n upgrade removes Webhook v1. Trigger: the N-SIG check
in `tools/probe.py` fails on the new n8n version.
