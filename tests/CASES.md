# Test cases: the rules they encode and the case format

Written before the build (eval gate: `evals/eval_config.yaml`). The
workflow is built to these rules, never the reverse. A separate AI writer
writes the hold-out cases from this file alone (section 8).

Plan: `BLUEPRINT.md` v1.4 (locked 2026-10-20; v1.3 records the R1
changes, v1.4 gate v4), section 5. Where this file is more exact than the blueprint,
this file is the test rule.

Gate version 4, 2026-10-26 (`evals/eval_config.yaml` v4), after the P5
gated series failed on hold-out case H-R02 and the R3 blind-spot red
team: 9 new visible cases (U07, A07, A08, T07, T08, R06-R09; 76 in
all), two parallel-group limits (5.2), the generator reads a body like
the Code nodes (ping only without a final newline, NaN is not JSON),
clarifying sentences in 3.1 and 3.8, the hold-out size (section 8) and
letter-case order numbers out of scope (section 9). No expected value
of an existing visible case changed.

Gate version 3, 2026-10-25 (`evals/eval_config.yaml` v3): one retry on
HubSpot's 404 `OBJECT_NOT_FOUND` for a contact upsert (3.7). No expected
value of any visible case changed.

Gate version 2, 2026-10-20 (`evals/eval_config.yaml` v2): R1 red-team
test changes 2, 3, 4, 5 and 11 (section 6, H4, 5.2, the generator
checks) and R1 build notes 1, 6-10, 13, 14, 16, 17 (clarifying
sentences). No expected value of any visible case changed. Version 1 is
gate commit 849b93e.

## 1. Sources (checked 2026-10-20)

- Order JSON shape: WooCommerce REST API docs, v3, "Orders" (order,
  billing, shipping, line item, tax line, shipping line, coupon line and
  refund properties; "Retrieve an order" example):
  https://woocommerce.github.io/woocommerce-rest-api-docs/#orders .
  Source of that page: github.com/woocommerce/woocommerce-rest-api-docs,
  `source/includes/wp-api-v3/_orders.md`, last changed 2025-09-01
  (commit 9315664).
- Webhook delivery: same docs, "Webhooks" (`_webhooks.md`, same commit):
  topics `order.created`, `order.updated`, `order.deleted`; headers
  `X-WC-Webhook-Source`, `-Topic`, `-Resource`, `-Event`, `-Signature`
  (base64 HMAC-SHA256 of the body), `-ID`, `-Delivery-ID`; the body is
  the same JSON as the REST API; after 5 failed deliveries in a row the
  webhook is disabled.
- WooCommerce source, `plugins/woocommerce/includes/class-wc-webhook.php`
  (trunk, read 2026-10-20): body = `trim(wp_json_encode($payload))`
  with PHP default flags (so `/` is sent as `\/` and non-ASCII letters
  as `\uXXXX`); signature = `base64_encode(hash_hmac('sha256', body,
  secret, true))`; the ping sent when a webhook is saved has the body
  `webhook_id=<id>`, no `X-WC-Webhook-*` headers and no signature, and
  WooCommerce wants status 200 for it. `order.deleted` sends only
  `{"id":<order id>}`.
- Latest WooCommerce release on the day: 11.2.1 (2026-10-09); WordPress
  7.1.3. The cases use these in `version` and the User-Agent.

Fact vs. assumption: the HubSpot property names and deal stage labels in
3.4 are assumptions until the P2 probe confirms them in the "Portfolio
Demo" account (BLUEPRINT P2). If P2 finds a different name, only the
mapping table changes (by ADR); the expected values in the cases do not.
Known before P2 (R1 finding 1): HubSpot answers 400 for a
`deal_currency_code` that is not set up in the account, and a free
account has one currency. If P2 confirms this, the logical field
`currency` maps to a custom text deal property `shop_currency` (by ADR);
the cases still expect `EUR`, `GBP` and `USD`.

## 2. What is tested

The system under test is the set of n8n workflows in BLUEPRINT section 3
(`Q129 Entry`, `Q129 Core`, `Q129 Replay`, `Q129 Summary`, `Q129 Error`)
on the shared local n8n, writing to the HubSpot "Portfolio Demo" account
and posting to Slack `#data-sync-alerts`. The test runner:

- sends each webhook event as WooCommerce would (headers from 5.2, the
  exact `body` bytes, a signature it computes with the webhook secret).
  The runner adds the headers the case file does not hold:
  `X-WC-Webhook-Source: https://harbour-ebikes.example.com/`,
  `X-WC-Webhook-Resource` and `-Event` split from the topic (`order`,
  `created`), `User-Agent: WooCommerce/11.2.1 Hookshot (WordPress/7.1.3)`;
  for the ping (topic null) none of them;
- puts the local fault proxy (port 8130) between n8n and HubSpot and
  tells it the faults of the event (5.4);
- presses replay through the `Q129 Replay` form with its login;
- triggers the summary for the window of the case (3.11);
- reads back HubSpot (API), the n8n data tables (`q129_ledger`,
  `q129_attention`, `q129_log`, `q129_alerts`) and what the workflows
  recorded they sent to Slack (text and Slack message ID). Slack itself
  is not read.

Cases run one at a time, in file order, the events of a case in step
order. Before each full run the reset script archives this build's
HubSpot records and empties the `q129_*` tables (BLUEPRINT section 3).

## 3. Behaviour rules

### 3.1 Entry (`Q129 Entry`), in this order

1. Body larger than 262144 bytes: HTTP 413, result `rejected`, reason
   `too_large`. Nothing else happens.
2. Body exactly `webhook_id=<digits>` (the WooCommerce ping): HTTP 200,
   result `ignored`, reason `ping`, signature or not.
3. No `X-WC-Webhook-Signature` header: HTTP 401, `rejected`,
   `no_signature`. A signature that does not equal base64(HMAC-SHA256 of
   the raw body bytes with the secret), compared in constant time:
   HTTP 401, `rejected`, `bad_signature`.
4. Signed, topic header not `order.created` or `order.updated` (for
   example `order.deleted`, `product.updated`): HTTP 200, `ignored`,
   `other_topic`. Deleting an order in the shop never changes HubSpot.
5. Every other signed request gets HTTP 200 at once; the work below
   runs after the answer. A signed body that is not a JSON object
   (also an empty body): `needs_attention`, reason `not_json` (row and
   alert, 3.8 and 3.10).
6. `rejected` and `ignored` requests get one log row and no alert.
   `order.created` and `order.updated` are handled the same way (both
   are upserts); their order is decided by the version time (3.5).

### 3.2 Field checks (before any write)

The checks run on the order JSON in this fixed order. Each field gives
at most one reason. All failing reasons are listed, in this order; the
first one is the row's main reason.

| # | Field (JSON path) | missing when | invalid when |
|---|---|---|---|
| 1 | `number` | absent, null, or empty after trim | not a string, or after trim not matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$` |
| 2 | `billing.email` | absent, null, or empty after trim | not a string, or after trim + lower case longer than 254 characters or not matching the e-mail pattern below |
| 3 | name: `billing.first_name`, `billing.last_name` | both empty after cleaning (3.3) | (no invalid case; a non-string counts as empty, see row 9) |
| 4 | `total` | absent, null, or empty after trim | not a JSON string, or after trim not matching `^[0-9]+(\.[0-9]{1,2})?$` (so no minus sign, no comma, no thousands separator, at most 2 decimals) |
| 5 | `currency` | absent, null, or empty after trim | not a string, or after trim not exactly one of `EUR`, `GBP`, `USD` (case matters) |
| 6 | `status` | absent, null, or empty after trim | not a string, or after trim not exactly one of the 8 statuses in 3.4 |
| 7 | `date_created_gmt` | absent, null, or empty after trim | not a string, or not `YYYY-MM-DDTHH:MM:SS` (no zone, no fraction), or not a real date and time: real calendar day (for example not 2026-09-31), hours 00-23, minutes 00-59, seconds 00-59 (so `24:00:00` and `:60` are invalid) |
| 8 | `date_modified_gmt` | as row 7 | as row 7 |
| 9 | text fields: `billing.first_name`, `last_name`, `phone`, `company`, `address_1`, `address_2`, `city`, `postcode`, `country` | | any of them is a JSON value that is not a string and not null: one reason `invalid_text_field` |

Reason codes: `missing_order_number`, `missing_email`, `missing_name`,
`missing_total`, `missing_currency`, `missing_status`,
`missing_date_created`, `missing_date_modified`, `invalid_order_number`,
`invalid_email`, `invalid_total`, `invalid_currency`, `invalid_status`,
`invalid_date_created`, `invalid_date_modified`, `invalid_text_field`.
If `billing` is not an object, it counts as empty (so `missing_email`
and `missing_name`).

E-mail pattern (after trim and lower case), one line:
`^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$`.
So: one `@`, no spaces, no comma, no `..`, at least one dot after the
`@`, ASCII only.

Amounts are never guessed: `1250.5` is 1250.50 (valid); `12,50`,
`1.234,50`, `1,234.50`, `-89.00`, `1250.505` and a JSON number are all
`invalid_total`.

### 3.3 Safe cleaning (the only changes to values)

- **Trim**: remove leading and trailing whitespace from every text value.
  Whitespace = the JavaScript `String.prototype.trim()` set: tab, line
  feed, vertical tab, form feed, carriage return, space, U+00A0,
  U+1680, U+2000 to U+200A, U+2028, U+2029, U+202F, U+205F, U+3000,
  U+FEFF.
- **E-mail**: trim, then lower case (the whole address).
- **Names** (`first_name`, `last_name` only): trim, then every run of
  whitespace inside becomes one space. Not for company, address or city
  (`Ilica  22` stays `Ilica  22`).
- **Address**: `address_1` and `address_2` trimmed and joined as
  `address_1, address_2`; if one is empty, the other alone.
- **Amount**: the valid `total` as an exact decimal with 2 places.
- **Nothing else**: no case change of names, no phone format or country
  guessing, no currency upper-casing, no fixing of totals, no date
  conversion except adding `Z` (the `_gmt` fields are UTC).
- Empty after cleaning = "not given". `state`, `shipping.*`, line items,
  taxes, coupons and refunds are not synced.

### 3.4 Mapping to HubSpot

Contact (one per cleaned e-mail; upsert by e-mail):

| logical field | from | HubSpot property (confirm in P2) |
|---|---|---|
| email | cleaned `billing.email` | `email` |
| first_name, last_name | cleaned names | `firstname`, `lastname` |
| phone, company | trimmed | `phone`, `company` |
| address | joined address (3.3) | `address` |
| city, postcode, country | trimmed | `city`, `zip`, `country` |
| sync_source | always `harbour-demo-shop` | `sync_source` (custom) |

Deal (one per order number; upsert by the unique property):

| logical field | value | HubSpot property (confirm in P2) |
|---|---|---|
| order_number | cleaned `number` | `shop_order_id` (custom, unique) |
| name | `Order #<number>` | `dealname` |
| amount | 2-place decimal of `total` (refunds are not subtracted) | `amount` |
| currency | `currency` | `deal_currency_code` |
| stage | label from the table below, default deal pipeline | `dealstage` (the runner maps label to stage ID) |
| order_date | `date_created_gmt` + `Z` | `closedate` |
| modified | `date_modified_gmt` + `Z` | `shop_modified_at` (custom) |

The deal is linked to the contact of every synced version of the order;
links are never removed.

| shop status | deal stage label |
|---|---|
| `pending` | Appointment Scheduled |
| `on-hold` | Qualified To Buy |
| `processing` | Closed Won |
| `completed` | Closed Won |
| `cancelled` | Closed Lost |
| `refunded` | Closed Lost |
| `failed` | Closed Lost |
| `trash` | Closed Lost |

### 3.5 Versions, duplicates and older updates (ledger `q129_ledger`)

The version of an order is its cleaned `date_modified_gmt`. The ledger
keeps, per order number, the version and a SHA-256 of the cleaned data
(all logical fields of 3.4, empty ones included) of the last version
that was fully synced; not the values themselves. "Same cleaned data"
below means the same hash. After the checks pass:

| ledger has | incoming version is | result |
|---|---|---|
| no row | any | write; result `created` |
| a row | newer | write; result `updated` |
| a row | the same, same cleaned data | `skipped_duplicate`, nothing written |
| a row | the same, different cleaned data | `needs_attention`, reason `same_version_different_data`, nothing written (two versions with one time: not guessed) |
| a row | older | `skipped_older`, nothing written |

`created` or `updated` is decided by the ledger, not by HubSpot. The
ledger row is written only after the contact and the deal are both
written. Two copies at the same moment may both pass the ledger check;
the HubSpot upserts by key then still give one contact and one deal.

### 3.6 Good data kept

- A field that is empty after cleaning is not sent, so the stored
  HubSpot value stays (contact phone, company, address, city, postcode,
  country, names).
- A newer non-empty value replaces the stored one (a new phone in a
  later order is stored).
- An older version of an order is skipped (3.5), so it never replaces
  data from a newer version of the same order.
- Contacts take the values of the last order event that was synced for
  that e-mail (in processing order). Known limit: a later update of an
  older, different order of the same customer can bring back that
  order's billing values. Not an H5 break (H5 is about the same order).

### 3.7 HubSpot calls and retries

- Every write is an upsert by key: contacts by e-mail, deals by
  `shop_order_id`. Never a plain create. No search before create.
- Contact first, then deal, then the link. HubSpot call timeout 15 s.
- Retry: 429 (wait the `Retry-After` seconds, at most 10 s; without the
  header 2 s), 500, 502, 503, 504, timeout, closed connection. Waits
  for 5xx, timeout and closed connection: 2 s, then 8 s.
- No retry: 400, 401, 403, 404. One exception (gate v3): HubSpot's 404
  with category `OBJECT_NOT_FOUND` on a contact upsert is retried once
  after 1 s, like a 409. Two upserts of one new e-mail at the same
  moment can get this answer while HubSpot still saves the new contact
  (seen in D02 and sweep SW03, 2026-10-22 to 2026-10-25). Every other
  404, and the fault proxy's simulated `404` (it has another category),
  gets no retry.
- If `Retry-After` is above 10, wait 10 s and retry.
- At most 3 attempts per write (the first try + 2 retries). n8n node
  retry is off; one own retry loop, no double retry.
- Build note (two writes at the same moment): a 409 on an upsert is
  retried once as the same upsert; a 207 (batch answer with an error
  inside) is handled by the status of the error inside. Two parallel
  ledger writes for one new order must still leave one ledger row (H2);
  P2 probes this.
- After the contact or the deal write fails for good: `needs_attention`
  with reason `crm_retry_exhausted` (retries used up),
  `crm_auth_error` (401, 403) or `crm_bad_request` (400, 404). What was
  already written stays (a contact may exist without its deal); the
  ledger is not written.

### 3.8 Needs-attention list (`q129_attention`)

- Every event or replay that ends in `needs_attention` is never silent.
  A webhook event opens one new row: order number (or null if it did
  not pass its check), version (or null), main reason, all reasons,
  the raw body, time, state `open`. One row per failing event, also for
  repeats.
- A failed replay opens no new row: the replayed row stays open, its
  replay count goes up by one, and a `replay_failed` alert is sent.
- A row closes by itself (closed by `sync`) when an event for the same
  order number ends `created` or `updated` with a version equal to or
  newer than the row's version (rows with no version also close). Every
  such row closes, also when one order has several open rows. Rows
  without an order number never close by themselves.
- A row closes by `replay` when its replay ends `created`, `updated`,
  `skipped_duplicate` or `skipped_older`.
- Rows keep the payload until closed + 30 days (not tested).

### 3.9 Replay (`Q129 Replay` form, Basic Auth)

- Input: a row ID. The stored raw body runs through Core again (checks,
  ledger, upserts; the signature was checked when it arrived). Faults
  of the replay step apply.
- Row closed: `replay_refused`, reason `row_closed`, nothing written,
  no alert. Row not found: `replay_refused`, `row_not_found`.
- A row that failed a field check fails again on replay (fix at source,
  BLUEPRINT decision 3).
- The log row of a replay records who pressed it (the form login user).

### 3.10 Slack alerts (`#data-sync-alerts`)

| alert type | when |
|---|---|
| `attention` | each new needs-attention row, at once |
| `replay_failed` | each replay that ends `needs_attention` |
| `over_5` | the summary of a window with more than 5 new needs-attention rows (once per summary) |
| `crash` | the error workflow, on any crash in an automatic run |

An attention or replay_failed alert contains the order number (or
`unknown`), the main reason code and the row ID. No alert text, log row
or summary contains the customer's e-mail, phone or address, or any
secret. `rejected`, `ignored`, skipped and `replay_refused` events send
no alert. The daily summary is a message, not an alert.

### 3.11 Daily summary (`Q129 Summary`)

- Live: every day 08:00, window = the 24 hours before. Test copy: the
  runner triggers it with the window = from the start of the case to
  the trigger.
- Always posts one message, also when every count is 0 (a missing
  summary is itself visible). Counts for the window:
  `synced` (results `created`), `updated`, `skipped_duplicate`,
  `skipped_older`, `needs_attention` (new rows), `still_open` (of those
  rows, the ones still open). Replays count by their result: a failed
  replay opens no row, so it adds nothing to `needs_attention`; a replay
  that ends `created`, `updated`, `skipped_duplicate` or `skipped_older`
  counts in that result's count.
- More than 5 new rows in the window: also one `over_5` alert.

### 3.12 Log (`q129_log`)

One row per request and per replay: time, delivery ID, topic, order
number, result, reasons, HubSpot contact and deal IDs, attempts per
write, seconds, and for replays the row ID and the user. Results:
`created`, `updated`, `skipped_duplicate`, `skipped_older`,
`needs_attention`, `ignored`, `rejected`, `replay_refused`. A crash may
leave no log row; its alert is the record.

Sent Slack messages (`q129_alerts`, build note): every workflow that
posts to Slack (Core, Replay, Summary, Error) writes one row per
message: time, type (`attention`, `replay_failed`, `over_5`, `crash`,
`summary`), order number, reason, row ID, delivery ID or execution ID,
Slack message ID, text. The runner grades alerts and summaries from
this table.

### 3.13 Forced crash (test copy only)

An event with `force_crash: true` makes Core fail after the field
checks and before the ledger check. How the switch works is a build
choice; it must not exist in the live export. Expected: HTTP 200, a
`crash` alert from `Q129 Error` with the execution ID, nothing written.

### 3.14 Hard rules (BLUEPRINT section 5) and how a break is named

Every check here is code, so every expected value must match in every
run; one break in any case of any run = FAIL.

- **H1 right values**: every expected HubSpot field equals the cleaned
  value (amount as an exact decimal), and the deal is linked to the
  expected contact.
- **H2 no duplicates**: at most one contact per e-mail, one deal per
  order number, one ledger row per order number.
- **H3 nothing bad written**: an event with `hubspot_unchanged: true`
  (failed check, unsigned or bad signature, ignored, skipped, refused,
  crash) leaves this case's HubSpot records exactly as before; a record
  expected with count 0 does not exist.
- **H4 nothing lost or silent**: every event has its log row (except a
  crash, whose alert is the record) and its expected result; every `needs_attention` has its row (or replay
  count) and its alert; a crash has its alert; every summary posts.
- **H5 good data kept**: no stored value is replaced by a blank or by a
  value of an older version of the same order.

The scorer names the rule for each miss: a wrong field value is H1; it
is also H5 when the actual value is empty or equals the value of a
skipped or older event of the case. A count above 1 is H2. A change
where `hubspot_unchanged` is true, or a record that should not exist,
is H3. A missing log row, row, alert or summary is H4. A miss that fits
none (for example a wrong HTTP code or attempt count) is still a miss.

## 4. Closed lists

A case may use only these values; the generator check stops on any
other.

- Kinds and visible counts: N 5, M 8, E 6, U 7, D 6, F 7, V 7, A 8,
  T 8, R 9, S 5 (76).
- HTTP codes: 200, 401, 413.
- Results: `created`, `updated`, `skipped_duplicate`, `skipped_older`,
  `needs_attention`, `ignored`, `rejected`, `replay_refused`, `crash`.
- Reasons: the 16 field codes of 3.2; `not_json`,
  `same_version_different_data`, `crm_retry_exhausted`,
  `crm_auth_error`, `crm_bad_request` (needs_attention); `ping`,
  `other_topic` (ignored); `no_signature`, `bad_signature`, `too_large`
  (rejected); `row_closed`, `row_not_found` (replay_refused).
- Alert types: `attention`, `replay_failed`, `over_5`, `crash`.
- Row effect of an event: `opens`, `stays_open`, `none`. Row state:
  `open`, `closed`; closed by: `sync`, `replay`.
- Event types: `webhook`, `replay`, `summary`. Sign modes: `valid`,
  `none`, `wrong_secret`, `tampered`.
- Fault targets: `contacts`, `deals`. Fault responses: `pass`, `429`,
  `429:<seconds>` (with `Retry-After`), `500`, `502`, `503`, `504`,
  `timeout`, `timeout_after_forward`, `close`, `400`, `401`, `403`, `404`.

## 5. Case format

A case file is one JSON document:
`{"format_version": 1, "set": "visible" | "holdout", "case_count": n, "cases": [...]}`.
The visible file is `tests/cases/visible.json`, written only by
`tests/make_cases.py`.

### 5.1 Case

| key | meaning |
|---|---|
| `id` | visible `N01`; hold-out `H-N01` (kind letter, 2 digits) |
| `kind` | the kind letter (must match the id) |
| `title` | one line, plain words |
| `related_to` | case IDs that may share an order number or e-mail with this one (either side may list it) |
| `depends_on` | case IDs that must run before this one (must come earlier in the file) |
| `hard_rules` | the H rules the case is about (for reading; every rule is checked on every case) |
| `simulated` | true when an event has faults or `force_crash` (labelled "simulated" in results) |
| `gated` | true for every case in this build |
| `events` | the steps, in order (5.2) |
| `expected_final` | the state after the last step (5.5) |

### 5.2 Events

Webhook event:

| key | meaning |
|---|---|
| `step` | 1, 2, 3 ... |
| `type` | `webhook` |
| `topic` | `X-WC-Webhook-Topic`; null = no `X-WC-Webhook-*` headers (ping) |
| `webhook_id`, `delivery_id` | header values (null for the ping); a resend has a new delivery ID |
| `content_type` | `application/json`, or null for none |
| `body` | the exact body text to send |
| `sign` | `valid` (secret), `none` (no header), `wrong_secret` (another secret), `tampered` (sign `body`, then send it with `tamper.find` replaced once by `tamper.replace`) |
| `parallel` | null, or a group name: events with the same name are sent at the same moment. Events in one group have the same `body` bytes (the topic may differ), `faults` null and `force_crash` false; the generator stops on any other group. Gate v4 (R3 finding 4): no summary event after a parallel group, and no parallel group while its order has an open needs-attention row (which copy closes the row, and the counts, would be chance) |
| `faults` | null, or `{"contacts": [...], "deals": [...]}` (5.4) |
| `force_crash` | true only for the crash test (3.13) |
| `expect` | 5.3 |

Replay event: `step`, `type: "replay"`, `row_from_step` (the step whose
row is replayed), `faults`, `expect`. Summary event: `step`,
`type: "summary"`, `expect` (with `summary`).

### 5.3 Expected result of an event (`expect`)

| key | meaning |
|---|---|
| `http` | HTTP status of the webhook (200 for replay and summary) |
| `result` | list of allowed results (one value, or more only for `parallel` events); `[]` for a summary |
| `reasons` | all reasons, in check order (3.2); `[]` when none |
| `alerts` | alerts this step sends: `{"type", "order", "reason"}` (`over_5` and `crash`: type only) |
| `attention_row` | `opens`, `stays_open` (failed replay) or `none` |
| `closes_rows_from_steps` | steps whose rows this step closes |
| `hubspot_unchanged` | true: this case's HubSpot records must be exactly as before the step (H3); null: not checked at this step |
| `crm_write_attempts` | with faults only: `{"contacts": n, "deals": n}` upsert requests seen by the proxy; else null |
| `summary` | summary events only: the 6 counts of 3.11 |

### 5.4 Faults (fault proxy, simulated)

The proxy counts, per event or replay step, the upsert requests to
HubSpot: `POST /crm/v3/objects/contacts/batch/upsert` (`contacts`) and
`POST /crm/v3/objects/deals/batch/upsert` (`deals`). The n-th request
of a target gets the n-th response of its list; after the list, every
request passes. `pass` = forward and return HubSpot's answer; a code =
return that code without forwarding (`429:2` adds `Retry-After: 2`);
`timeout` = do not forward, never answer; `timeout_after_forward` =
forward, then hold the answer past the 15 s timeout; `close` = close
the connection without forwarding. Other HubSpot requests (reads, the
link) always pass. If P2 needs other upsert paths, the ADR updates
this list; the cases stay. The proxy logs every real non-2xx answer from
HubSpot (time, path, status), so a miss caused by HubSpot itself can be
explained in `evals/RESULTS.md`; it is still a miss.

### 5.5 End state (`expected_final`)

| key | meaning |
|---|---|
| `contacts` | for every e-mail of the case that passes the e-mail check: `{"email", "count": 0 or 1, "fields"}`; `fields` has the 9 contact fields + `sync_source`, `""` = not set |
| `deals` | for every order number of the case that passes its check: `{"order_number", "count", "fields", "contacts"}`; `fields` has the 7 deal fields; `contacts` = linked e-mails |
| `ledger` | `{"order_number", "modified"}` (null = no row) |
| `attention_rows` | rows opened by this case: `from_step`, `order`, `reason`, `reasons`, `state`, `closed_by`, `closed_at_step`, `replays` |
| `alerts` | every alert of the case with its `step` |
| `summary_posts` | number of summary messages |

Comparison: amounts as exact decimals (`1250.5` = `1250.50`); dates as
the same UTC second; text exactly, byte for byte, except that HubSpot's
empty and null are equal to `""`; e-mails in lower case. State carries
over between cases only through `depends_on` (for example E06 uses the
contact of N01).

### 5.6 Example (shortened body)

```json
{"id": "D01", "kind": "D", "title": "Same event delivered twice",
 "related_to": [], "depends_on": [], "hard_rules": ["H2", "H5"],
 "simulated": false, "gated": true,
 "events": [
  {"step": 1, "type": "webhook", "topic": "order.created", "sign": "valid",
   "tamper": null, "content_type": "application/json", "parallel": null,
   "faults": null, "force_crash": false, "webhook_id": 14,
   "delivery_id": "…", "body": "{\"id\":41401,\"parent_id\":0,\"number\":\"41401\",…}",
   "expect": {"http": 200, "result": ["created"], "reasons": [], "alerts": [],
              "attention_row": "none", "closes_rows_from_steps": [],
              "hubspot_unchanged": null, "crm_write_attempts": null}},
  {"step": 2, "type": "webhook", "topic": "order.created", "…": "…",
   "expect": {"http": 200, "result": ["skipped_duplicate"], "reasons": [],
              "alerts": [], "attention_row": "none", "closes_rows_from_steps": [],
              "hubspot_unchanged": true, "crm_write_attempts": null}}],
 "expected_final": {
  "contacts": [{"email": "marko.juric@mail.harbour-sync.example.com", "count": 1,
                "fields": {"email": "marko.juric@mail.harbour-sync.example.com",
                           "first_name": "Marko", "last_name": "Jurić",
                           "phone": "+385 91 234 5678", "company": "",
                           "address": "Obala Lazareta 14", "city": "Split",
                           "postcode": "21000", "country": "HR",
                           "sync_source": "harbour-demo-shop"}}],
  "deals": [{"order_number": "41401", "count": 1,
             "fields": {"order_number": "41401", "name": "Order #41401",
                        "amount": "690.00", "currency": "EUR", "stage": "Closed Won",
                        "order_date": "2026-10-09T07:00:00Z",
                        "modified": "2026-10-09T07:00:06Z"},
             "contacts": ["marko.juric@mail.harbour-sync.example.com"]}],
  "ledger": [{"order_number": "41401", "modified": "2026-10-09T07:00:06Z"}],
  "attention_rows": [], "alerts": [], "summary_posts": 0}}
```

Bodies are in the real WooCommerce order shape (section 1): every
property of the docs example, in its order, with string amounts. To
make the exact bytes WooCommerce sends from a JSON object in Python:
`json.dumps(obj, ensure_ascii=True, separators=(",", ":")).replace("/", "\\/")`.

## 6. How a case is graded

**Waiting.** After each step the runner waits for the log row of the
step (by delivery ID; for replay and summary by the runner's request),
then checks `expect`. The longest wait for a step is 60 s, plus, for
every response in that step's fault lists: 17 s per `timeout` or
`timeout_after_forward`, 10 s per `429` or `429:<seconds>`, 8 s per
`500`, `502`, `503`, `504` or `close`. For a step whose expected result
is `crash`, the runner waits for the recorded `crash` alert instead of
the log row (same longest wait, matched by time after the step was
sent); a log row is allowed but not required. A step that exceeds its
wait is a miss (H4), unless the test machinery failed (INVALID RUN).

**Reading HubSpot.** Field values and the before/after reads for
`hubspot_unchanged` use GET by `idProperty` (`email` for contacts,
`shop_order_id` for deals), which shows a write at once. Counts for H2
use the search API, only after the record read by `idProperty` also
appears in search (poll, at most 60 s); deals are counted both by
`shop_order_id` and by `dealname` = `Order #<number>`, so a deal
written without the key is still seen. For a step with
`hubspot_unchanged: true`, "nothing written" also means the fault proxy
forwarded 0 upsert requests to HubSpot in that step (requests the proxy
answered itself without forwarding do not count).

**Passing.** After the last step the runner checks `expected_final`
through the HubSpot API and the n8n tables. A case passes only when
every check passes; then the next case starts. Each full run is
repeated 3 times on one frozen workflow commit (eval config).

## 7. The visible cases

Written by `tests/make_cases.py`; the generator stops if a case is
missing here with its title. Expected results per step, in order.

| ID | Title | Expected per step |
|---|---|---|
| N01 | Clean paid order, new customer, card payment | created |
| N02 | Clean order waiting for bank transfer (pending) | created |
| N03 | Completed order for a company customer, two items | created |
| N04 | Order on hold, paid in GBP, UK customer | created |
| N05 | Paid order in USD with a coupon, US customer | created |
| M01 | E-mail in upper case with spaces around it, names with spaces | created |
| M02 | Double spaces and non-breaking spaces in names, newline after city | created |
| M03 | Accented names, city and company | created |
| M04 | Name and address in Japanese script | created |
| M05 | Phone with brackets and dashes, plus sign in e-mail, spaces in postcode | created |
| M06 | Optional fields empty: phone, company, postcode, country | created |
| M07 | Guest checkout with last name only, cash on delivery | created |
| M08 | Total written as 1250.5, second address line | created |
| E01 | Second order from the same customer | created then created |
| E02 | Same e-mail written in another letter case | created then created |
| E03 | Second order without a phone keeps the stored phone | created then created |
| E04 | Second order with a new phone and address updates the contact | created then created |
| E05 | Second order without company, e-mail with spaces, keeps the company | created then created |
| E06 | Returning customer from case N01 places a new order without phone | created |
| U01 | Status change from pending to processing after payment | created then updated |
| U02 | Full refund: stage changes, amount stays the order total | created then updated |
| U03 | Shop staff add an item: total changes from 2490.00 to 2579.00 | created then updated |
| U04 | Older update (on-hold) arrives after the newer one (completed) | created then updated then skipped_older |
| U05 | Update with empty phone and company keeps both stored values | created then updated |
| U06 | Update event arrives before the create event | created then skipped_older |
| U07 | Customer corrects the e-mail in an update: deal linked to both contacts | created then updated |
| D01 | Same event delivered twice | created then skipped_duplicate |
| D02 | Same event sent twice at the same moment | created/updated/skipped_duplicate then created/updated/skipped_duplicate |
| D03 | Update delivered again after it was synced | created then updated then skipped_duplicate |
| D04 | Create and update events for the same order version | created then skipped_duplicate |
| D05 | Same version time but a different phone: not guessed, needs attention | created then needs_attention (same_version_different_data) |
| D06 | Three copies of the same update at the same moment | created then updated/skipped_duplicate then updated/skipped_duplicate then updated/skipped_duplicate |
| F01 | Order number missing (empty) | needs_attention (missing_order_number) |
| F02 | E-mail missing (empty) | needs_attention (missing_email) |
| F03 | Both name fields empty or spaces only | needs_attention (missing_name) |
| F04 | Total missing (null) | needs_attention (missing_total) |
| F05 | Currency key missing | needs_attention (missing_currency) |
| F06 | Status missing (null) | needs_attention (missing_status) |
| F07 | Last-modified date missing (null) | needs_attention (missing_date_modified) |
| V01 | E-mail with a comma instead of a dot | needs_attention (invalid_email) |
| V02 | Negative total | needs_attention (invalid_total) |
| V03 | Total written with a decimal comma (12,50) | needs_attention (invalid_total) |
| V04 | Update with total 1.187,00 (German style) keeps the stored deal | created then needs_attention (invalid_total) |
| V05 | Old currency code HRK (not in the allowed list) | needs_attention (invalid_currency) |
| V06 | Custom plugin status 'shipped' (not a known status) | needs_attention (invalid_status) |
| V07 | Order date that does not exist (31 September) | needs_attention (invalid_date_created) |
| A01 | No signature header | rejected (no_signature) |
| A02 | Signature made with another secret | rejected (bad_signature) |
| A03 | Body changed after signing (total 2490.00 to 24.90) | rejected (bad_signature) |
| A04 | WooCommerce ping when the webhook is saved | ignored (ping) |
| A05 | Order deleted in the shop: event ignored, deal stays | created then ignored (other_topic) |
| A06 | Signed body that is cut off (not valid JSON) | needs_attention (not_json) |
| A07 | Signed empty body (not valid JSON) | needs_attention (not_json) |
| A08 | Empty body without a signature | rejected (no_signature) |
| T01 | HubSpot rate limit (429, wait 2 s) then OK | created |
| T02 | HubSpot server error (503) on the deal, then OK | created |
| T03 | Deal write reaches HubSpot but the answer times out, retry | created |
| T04 | HubSpot server errors every time: retries used up | needs_attention (crm_retry_exhausted) |
| T05 | HubSpot says 401 (key problem): no retry | needs_attention (crm_auth_error) |
| T06 | HubSpot says 400 on the deal: no retry, contact already written | needs_attention (crm_bad_request) |
| T07 | Contact connection closed then OK, deal 403: no retry | needs_attention (crm_auth_error) |
| T08 | Contact answer times out after HubSpot saved it, deal 404: no retry | needs_attention (crm_bad_request) |
| R01 | Replay after a HubSpot outage | needs_attention (crm_retry_exhausted) then created |
| R02 | Replay pressed twice | needs_attention (crm_retry_exhausted) then created then replay_refused (row_closed) |
| R03 | Shop resends the order after an outage, then replay of the closed row | needs_attention (crm_retry_exhausted) then created then replay_refused (row_closed) |
| R04 | Order fixed in the shop (e-mail added) closes the row by itself | needs_attention (missing_email) then created |
| R05 | Replay during the outage fails, second replay works | needs_attention (crm_retry_exhausted) then needs_attention (crm_retry_exhausted) then created |
| R06 | Two open rows for one order, the shop resends: both close by sync | needs_attention (crm_retry_exhausted) then needs_attention (crm_retry_exhausted) then created |
| R07 | Two open rows, replay of the second: it closes by replay, the first by sync | needs_attention (crm_retry_exhausted) then needs_attention (crm_retry_exhausted) then created |
| R08 | Two open rows, the older version is resent first: only its row closes | needs_attention (crm_retry_exhausted) then needs_attention (crm_retry_exhausted) then created then updated |
| R09 | Replay of a step that opened no row | created then replay_refused (row_not_found) |
| S01 | Summary counts match the log | created then updated then skipped_duplicate then skipped_older then needs_attention (missing_email) then summary |
| S02 | Six failed orders in the window: summary and the over-5 alert | needs_attention (missing_email) then needs_attention (invalid_total) then needs_attention (invalid_currency) then needs_attention (invalid_status) then needs_attention (missing_name) then needs_attention (invalid_email) then summary |
| S03 | Exactly five failed orders: summary, no over-5 alert | needs_attention (missing_total) then needs_attention (invalid_currency) then needs_attention (invalid_date_modified) then needs_attention (invalid_total) then needs_attention (invalid_email) then summary |
| S04 | Forced crash in an automatic run alerts | crash |
| S05 | Summary with no events in the window still posts, all zero | summary |

## 8. Writing the hold-out cases (separate AI writer)

The hold-out writer never builds, never opens `tests/cases/visible.json`
or `tests/make_cases.py` (it may run the checker), and works from this
file only.

1. About 33 cases (about 30% of all cases with the 76 visible), at
   least 2 per kind (every kind then has at least 7 with the visible
   ones). IDs `H-<kind><2 digits>`.
2. Order numbers 61001 to 69999 (an optional letter prefix such as
   `HB-61001` is allowed); valid e-mails only on subdomains of
   `harbour-sync-h.example.com`. Made-up people only. No case may
   share an order number or e-mail with another unless marked related.
3. Test the rules of section 3 in ways the visible list in section 7
   does not: other fields, other formats, two problems in one order,
   other orders of events, rules not covered visibly (for example
   `too_large`, `invalid_text_field`, `invalid_order_number`,
   `missing_date_created`, `timeout`, `429` with no wait header, `500`,
   `504`). A replay cannot end `skipped_older` one step after another
   (a newer sync closes the row first), so do not write that case.
4. Write every expected value by hand from this file, in the format of
   section 5 (`"set": "holdout"`).
5. Check: `python tests/make_cases.py --check <file> --set holdout`
   (writes nothing; exit 0 = the set is consistent with these rules).
   If the checker disagrees, decide from this file. If this file and
   the checker disagree, do not change either: record the case as a
   finding for Kristian.
6. Seal as in item 3: zip the file (with a README.txt) outside every
   repository, write `evals/holdout_commitment.json` (date, case count,
   count per kind, count per result, archive SHA-256, where it is kept,
   how to open). Only that file is committed here.
7. Opening (gate v2, Kristian 2026-10-20): at the first gated run, after
   the seal check and before any scoring, run the current checker on
   the extracted file: `python tests/make_cases.py --check <file> --set
   holdout`. Any case the current checker refuses (for example a hold-out
   sealed under an older gate version) is a wrong case for Kristian
   to decide, never a silent fix, and the refusal is
   recorded in `evals/RESULTS.md`.

## 9. Not tested here

Real shops and real customer data, volumes above the test set,
webhooks that never arrive (version 2 idea), HubSpot UI behaviour,
Slack delivery itself (we check what the workflow recorded it sent),
n8n Cloud and other n8n versions, the 30-day row retention, order
numbers that differ only in letter case (`HB-61001` and `hb-61001`:
version 2 list; HubSpot's search does not tell them apart).
