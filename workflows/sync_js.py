"""JavaScript of the Code nodes of the Q129 workflows (n8n-data-sync).

Rules: tests/CASES.md section 3 (the reference model is tests/make_cases.py, Model and
check_and_clean). tests/test_sync_js.py runs CHECK against that model in Node.
Placeholders filled by workflows/build.py: __BASE__ (HubSpot base URL: the fault proxy in the
test copy, https://api.hubapi.com in the live export), __TEST__ (true only in the test copy).
"""

# Shared helpers, pasted at the top of the Code nodes that need them.
HELPERS = r"""
const nowIso = () => new Date().toISOString();
const cut = (x, n) => { const a = [...String(x === undefined || x === null ? '' : x)]; return a.length > n ? a.slice(0, n).join('') : a.join(''); };
"""

# ------------------------------------------------------------------------------------------------ Entry

# Right after the webhook (v1, Binary File on; adr/003): the raw bytes are only readable here.
READ_REQUEST = r"""
const item = $input.first();
const raw = item.binary && item.binary.data ? await this.helpers.getBinaryDataBuffer(0, 'data') : Buffer.alloc(0);
const h = item.json.headers || {};
const one = (v) => (Array.isArray(v) ? v[0] : v);
return [{ json: {
  bytes: raw.length,
  text: raw.toString('utf8'),
  has_sig: one(h['x-wc-webhook-signature']) !== undefined,
  sig: String(one(h['x-wc-webhook-signature']) || ''),
  topic: one(h['x-wc-webhook-topic']) === undefined ? null : String(one(h['x-wc-webhook-topic'])),
  delivery_id: one(h['x-wc-webhook-delivery-id']) === undefined ? '' : String(one(h['x-wc-webhook-delivery-id'])),
  request_id: String(one(h['x-q129-request-id']) || ''),
  test_crash: __TEST__ && one(h['x-q129-test-crash']) === 'yes',
  received_ms: Date.now(),
}, binary: item.binary }];
"""

# After the Crypto node (HMAC SHA256, base64, credential "Crypto WooCommerce n8n-data-sync").
GATE = HELPERS + r"""
const it = $input.first().json;
const eq = (a, b) => { let d = a.length ^ b.length; for (let i = 0; i < Math.max(a.length, b.length); i++) d |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0); return d === 0; };
const want = typeof it.signature === 'string' ? it.signature : '';
let http = 200, result = 'accepted', reason = null;
if (it.bytes > 262144) { http = 413; result = 'rejected'; reason = 'too_large'; }
else if (/^webhook_id=[0-9]+$/.test(it.text)) { result = 'ignored'; reason = 'ping'; }
else if (!it.has_sig) { http = 401; result = 'rejected'; reason = 'no_signature'; }
else if (!want || !eq(it.sig, want)) { http = 401; result = 'rejected'; reason = 'bad_signature'; }
else if (it.topic !== 'order.created' && it.topic !== 'order.updated') { result = 'ignored'; reason = 'other_topic'; }
const request_id = it.request_id || it.delivery_id || ('exec-' + $execution.id);
return [{ json: { http, result, reason, request_id, delivery_id: it.delivery_id, topic: it.topic,
  received_ms: it.received_ms, body_text: result === 'accepted' ? it.text : '', test_crash: it.test_crash } }];
"""

ENTRY_LOG = r"""
const g = $('Gate').first().json;
return [{ json: { at: new Date().toISOString(), request_id: g.request_id, delivery_id: g.delivery_id || '',
  topic: g.topic || '', mode: 'webhook', order_number: '', result: g.result, reasons: JSON.stringify([g.reason]),
  contact_id: '', deal_id: '', attempts: '', seconds: Math.round((Date.now() - g.received_ms) / 100) / 10,
  row_id: '', user: '' } }];
"""

CORE_INPUT = r"""
const g = $('Gate').first().json;
return [{ json: { mode: 'webhook', body_text: g.body_text, request_id: g.request_id, delivery_id: g.delivery_id,
  topic: g.topic, received_ms: g.received_ms, replay: null, user: '', force_crash: g.test_crash === true } }];
"""

# ------------------------------------------------------------------------------------------------ Core

# Field checks and safe cleaning (CASES.md 3.2-3.4). Pure function body: tests/test_sync_js.py runs
# CHECK_FN in Node against the Python reference model.
CHECK_FN = r"""
function checkAndClean(bodyText) {
  const STAGE = { 'pending': 'Appointment Scheduled', 'on-hold': 'Qualified To Buy', 'processing': 'Closed Won',
    'completed': 'Closed Won', 'cancelled': 'Closed Lost', 'refunded': 'Closed Lost', 'failed': 'Closed Lost',
    'trash': 'Closed Lost' };
  const CURRENCIES = ['EUR', 'GBP', 'USD'];
  const EMAIL_RE = /^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;
  const TOTAL_RE = /^[0-9]+(\.[0-9]{1,2})?$/;
  const ORDER_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
  const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/;
  const isStr = (v) => typeof v === 'string';
  const absent = (v) => v === undefined || v === null;
  const trim = (s) => s.trim();
  const collapse = (s) => s.trim().replace(/\s+/g, ' ');
  const validDate = (s) => {
    const m = DATE_RE.exec(s);
    if (!m) return false;
    const [y, mo, d, h, mi, se] = m.slice(1).map(Number);
    if (y < 1 || mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || se > 59) return false;
    const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
    const dim = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1];
    return d <= dim;
  };
  const amount2 = (s) => {
    const [i, f = ''] = s.split('.');
    const ip = i.replace(/^0+(?=\d)/, '');
    return ip + '.' + (f + '00').slice(0, 2);
  };
  let p;
  try { p = JSON.parse(bodyText); } catch (e) { p = undefined; }
  if (!p || typeof p !== 'object' || Array.isArray(p)) {
    return { reasons: ['not_json'], order_number: null, modified: null };
  }
  const reasons = [];
  let badType = false;
  const rec = { order_number: null, modified: null };

  const num = p.number;
  if (absent(num) || (isStr(num) && trim(num) === '')) reasons.push('missing_order_number');
  else if (!isStr(num) || !ORDER_RE.test(trim(num))) reasons.push('invalid_order_number');
  else rec.order_number = trim(num);

  const billing = p.billing && typeof p.billing === 'object' && !Array.isArray(p.billing) ? p.billing : {};
  const text = (key, names) => {
    const v = billing[key];
    if (absent(v)) return '';
    if (!isStr(v)) { badType = true; return ''; }
    return names ? collapse(v) : trim(v);
  };

  const email = billing.email;
  let cleanEmail = null;
  if (absent(email) || (isStr(email) && trim(email) === '')) reasons.push('missing_email');
  else if (!isStr(email)) reasons.push('invalid_email');
  else {
    const e = trim(email).toLowerCase();
    if (e.length > 254 || !EMAIL_RE.test(e)) reasons.push('invalid_email');
    else cleanEmail = e;
  }

  const first = text('first_name', true), last = text('last_name', true);
  if (first === '' && last === '') reasons.push('missing_name');

  const total = p.total;
  let amount = null;
  if (absent(total) || (isStr(total) && trim(total) === '')) reasons.push('missing_total');
  else if (!isStr(total) || !TOTAL_RE.test(trim(total))) reasons.push('invalid_total');
  else amount = amount2(trim(total));

  const listed = (key, allowed, field) => {
    const v = p[key];
    if (absent(v) || (isStr(v) && trim(v) === '')) { reasons.push('missing_' + field); return null; }
    if (!isStr(v) || !allowed.includes(trim(v))) { reasons.push('invalid_' + field); return null; }
    return trim(v);
  };
  const currency = listed('currency', CURRENCIES, 'currency');
  const status = listed('status', Object.keys(STAGE), 'status');

  const date = (key, field) => {
    const v = p[key];
    if (absent(v) || (isStr(v) && trim(v) === '')) { reasons.push('missing_' + field); return null; }
    if (!isStr(v) || !validDate(trim(v))) { reasons.push('invalid_' + field); return null; }
    return trim(v) + 'Z';
  };
  const orderDate = date('date_created_gmt', 'date_created');
  rec.modified = date('date_modified_gmt', 'date_modified');

  const phone = text('phone'), company = text('company');
  const a1 = text('address_1'), a2 = text('address_2');
  const city = text('city'), postcode = text('postcode'), country = text('country');
  if (badType) reasons.push('invalid_text_field');
  if (reasons.length) return { reasons, order_number: rec.order_number, modified: rec.modified };

  const contact = { email: cleanEmail, first_name: first, last_name: last, phone, company,
    address: [a1, a2].filter((x) => x).join(', '), city, postcode, country };
  const deal = { order_number: rec.order_number, name: 'Order #' + rec.order_number, amount, currency,
    stage: STAGE[status], order_date: orderDate, modified: rec.modified };
  return { reasons: [], order_number: rec.order_number, modified: rec.modified, contact, deal };
}
"""

STAGE_IDS = r"""{ 'Appointment Scheduled': 'appointmentscheduled', 'Qualified To Buy': 'qualifiedtobuy',
  'Closed Won': 'closedwon', 'Closed Lost': 'closedlost' }"""

CHECK = CHECK_FN + r"""
const S = Object.assign({}, $input.first().json);
S.t0 = S.received_ms || Date.now();
S.attempts = null;
S.contact_id = ''; S.deal_id = '';
const r = checkAndClean(S.body_text);
S.reasons = r.reasons;
S.order_number = r.order_number;
S.modified = r.modified;
S.ok = r.reasons.length === 0;
S.action = S.ok ? 'check_passed' : 'attention';
S.result = S.ok ? null : 'needs_attention';
if (S.ok) {
  const sortKeys = (o) => Object.keys(o).sort().reduce((a, k) => { a[k] = o[k]; return a; }, {});
  S.canonical = JSON.stringify([sortKeys(r.contact), sortKeys(r.deal)]);
  S.email = r.contact.email;
  const c = r.contact;
  const props = { firstname: c.first_name, lastname: c.last_name, phone: c.phone, company: c.company,
    address: c.address, city: c.city, zip: c.postcode, country: c.country };
  S.contact_props = {};
  for (const [k, v] of Object.entries(props)) if (v !== '') S.contact_props[k] = v;  // empty = not sent (CASES 3.6)
  S.contact_props.sync_source = 'harbour-demo-shop';
  const d = r.deal;
  const STAGE_ID = __STAGE_IDS__;
  // currency in shop_currency (adr/001); closedate in every deal upsert (adr/002)
  S.deal_props = { dealname: d.name, amount: d.amount, shop_currency: d.currency, pipeline: 'default',
    dealstage: STAGE_ID[d.stage], closedate: d.order_date, shop_modified_at: d.modified };
}
return [{ json: S }];
""".replace("__STAGE_IDS__", STAGE_IDS)

# Test copy only (CASES.md 3.13): after the field checks, before the ledger check. Not in the live export.
TEST_CRASH = r"""
if ($input.first().json.force_crash === true) {
  throw new Error('Forced crash for the test (CASES.md 3.13)');
}
return $input.all();
"""

DECIDE = r"""
const S = Object.assign({}, $('Data hash').first().json);
const rows = $input.all().map((i) => i.json).filter((j) => j && j.id !== undefined && j.id !== null);
const led = rows.length ? rows[0] : null;
S.ledger_found = !!led;
if (!led) { S.action = 'write'; S.result = 'created'; }
else if (S.modified < led.version) { S.action = 'skip'; S.result = 'skipped_older'; }
else if (S.modified === led.version) {
  if (led.data_hash !== S.data_hash) { S.action = 'attention'; S.result = 'needs_attention'; S.reasons = ['same_version_different_data']; }
  else { S.action = 'skip'; S.result = 'skipped_duplicate'; }
} else { S.action = 'write'; S.result = 'updated'; }
return [{ json: S }];
"""

CONTACT_REQUEST = r"""
const S = $input.first().json;
return [{ json: { base: '__BASE__', path: '/crm/v3/objects/contacts/batch/upsert',
  body: { inputs: [{ idProperty: 'email', id: S.email, properties: S.contact_props }] } } }];
"""

DEAL_REQUEST = r"""
const S = $input.first().json;
return [{ json: { base: '__BASE__', path: '/crm/v3/objects/deals/batch/upsert',
  body: { inputs: [{ idProperty: 'shop_order_id', id: S.order_number, properties: S.deal_props }] } } }];
"""

LINK_REQUEST = r"""
const S = $input.first().json;
return [{ json: { base: '__BASE__', path: '/crm/v4/associations/deals/contacts/batch/associate/default',
  body: { inputs: [{ from: { id: S.deal_id }, to: { id: S.contact_id } }] } } }];
"""


def after_call(prev_node, target, id_field):
    """After a HubSpot write: carry the state on, or turn it into needs-attention (CASES.md 3.7)."""
    return r"""
const S = Object.assign({}, $('__PREV__').first().json);
const r = $input.first().json || {};
S.attempts = Object.assign({ contacts: 0, deals: 0 }, S.attempts || {});
if ('__TARGET__' !== 'link') S.attempts['__TARGET__'] = r.attempts || 0;
if (!r.ok) {
  S.action = 'attention'; S.result = 'needs_attention';
  S.reasons = [r.reason || 'crm_retry_exhausted'];
  S.crm_error = String(r.error || '').slice(0, 300);
  return [{ json: S }];
}
const res = ((r.body || {}).results || [])[0] || {};
if ('__FIELD__') S['__FIELD__'] = String(res.id || '');
return [{ json: S }];
""".replace("__PREV__", prev_node).replace("__TARGET__", target).replace("__FIELD__", id_field)


LEDGER_ROW = r"""
const S = $input.first().json;
return [{ json: { order_number: S.order_number, version: S.modified, data_hash: S.data_hash, updated_at: new Date().toISOString() } }];
"""

# Which open rows this step closes (CASES.md 3.8): on created/updated every open row of the order with no
# version or a version <= this one (by sync) and the replayed row (by replay); on a skip only the replayed row.
ROWS_TO_CLOSE = r"""
const S = $('__STATE__').first().json;
const open = $input.all().map((i) => i.json).filter((j) => j && j.id !== undefined && j.id !== null && j.state === 'open');
const replayId = S.replay ? String(S.replay.row_id) : null;
const out = [];
const at = new Date().toISOString();
for (const r of open) {
  const mine = replayId !== null && String(r.id) === replayId;
  const bySync = S.action === 'write' && r.order_number === S.order_number && (!r.version || r.version <= S.modified);
  if (mine || bySync) out.push({ json: { row_id: r.id, state: 'closed', closed_by: mine ? 'replay' : 'sync', closed_at: at, closed_request: S.request_id } });
}
if (!out.length) out.push({ json: { row_id: -1, state: 'closed', closed_by: '', closed_at: at, closed_request: '' } });
return out;
"""

STEP_DONE = r"""
const S = Object.assign({}, $('__STATE__').first().json);
const closed = $('Rows to close__SUFFIX__').all().map((i) => i.json).filter((j) => j.row_id !== -1).map((j) => j.row_id);
S.closed_rows = closed;
return [{ json: S }];
"""

# ---- needs-attention (CASES.md 3.8, 3.10)
ATTENTION = r"""
const S = Object.assign({}, $input.first().json);
S.result = 'needs_attention';
S.main_reason = S.reasons[0];
return [{ json: S }];
"""

NEW_ROW = r"""
const S = $input.first().json;
return [{ json: { order_number: S.order_number || '', version: S.modified || '', reason: S.main_reason,
  reasons: JSON.stringify(S.reasons), body: S.body_text, state: 'open', created_at: new Date().toISOString(),
  request_id: S.request_id, delivery_id: S.delivery_id || '', replays: 0, closed_by: '', closed_at: '',
  closed_request: '' } }];
"""

NEW_ROW_ALERT = r"""
const S = Object.assign({}, $('Attention').first().json);
const row = $input.first().json || {};
S.row_id = row.id === undefined ? '' : String(row.id);
S.alert = { type: 'attention', order: S.order_number || 'unknown', reason: S.main_reason, row_id: S.row_id };
S.alert.text = `Order ${S.alert.order} needs attention: ${S.alert.reason} (row ${S.row_id}). Fix it in the shop, or press replay after a HubSpot outage.`;
return [{ json: S }];
"""

REPLAY_ROW_UPDATE = r"""
const S = $input.first().json;
return [{ json: { row_id: S.replay.row_id, replays: Number(S.replay.replays || 0) + 1 } }];
"""

REPLAY_ALERT = r"""
const S = Object.assign({}, $('Attention').first().json);
S.row_id = String(S.replay.row_id);
S.alert = { type: 'replay_failed', order: S.replay.order || 'unknown', reason: S.main_reason, row_id: S.row_id };
S.alert.text = `Replay of row ${S.row_id} (order ${S.alert.order}) failed: ${S.alert.reason}. The row stays open.`;
return [{ json: S }];
"""

# One row per Slack message (CASES.md 3.12, q129_alerts). Input: the Slack node's answer; state from __STATE__.
def alert_row(state_node, kind_expr="S.alert.type"):
    return r"""
const S = $('__STATE__').first().json;
const s = $input.first().json || {};
const a = S.alert;
const ts = s.ts || (s.message && s.message.ts) || '';
return [{ json: { at: new Date().toISOString(), type: __KIND__, order_number: a.order || '', reason: a.reason || '',
  row_id: a.row_id || '', request_id: S.request_id || '', execution_id: String(a.execution_id || $execution.id), slack_ts: String(ts),
  slack_error: ts ? '' : String((s.error && (s.error.message || s.error)) || 'no message ts').slice(0, 300),
  text: a.text, data: a.data ? JSON.stringify(a.data) : '' } }];
""".replace("__STATE__", state_node).replace("__KIND__", kind_expr)


ATTENTION_DONE = r"""
return [{ json: $('__STATE__').first().json }];
"""

LOG_ROW = r"""
const S = $input.first().json;
const rowId = S.mode === 'replay' ? String(S.replay.row_id) : (S.row_id || '');
return [{ json: { at: new Date().toISOString(), request_id: S.request_id, delivery_id: S.delivery_id || '',
  topic: S.topic || '', mode: S.mode, order_number: S.order_number || '', result: S.result,
  reasons: JSON.stringify(S.result === 'needs_attention' ? S.reasons : []),
  contact_id: S.contact_id || '', deal_id: S.deal_id || '', attempts: S.attempts ? JSON.stringify(S.attempts) : '',
  seconds: Math.round((Date.now() - S.t0) / 100) / 10, row_id: rowId, user: S.user || '' } }];
"""

# ------------------------------------------------------------------------------------------------ HubSpot call

# One HubSpot write with the retry rules of CASES.md 3.7 (at most 3 attempts; unrolled, no loop).
def check_try(n):
    return r"""
const R = $('Start').first().json;
const r = $input.first().json || {};
const n = __N__;
const code = typeof r.statusCode === 'number' ? r.statusCode : null;
let status = code;
if (code === 207) {
  const e = ((r.body || {}).errors || [])[0] || {};
  status = Number(e.status) || (e.category === 'CONFLICT' ? 409 : 400);
}
const out = { done: true, ok: false, attempts: n, status, reason: null, wait: 0, body: r.body || null,
  error: code === null ? String((r.error && (r.error.message || r.error.code || JSON.stringify(r.error))) || 'no answer').slice(0, 300) : '' };
const hdr = (r.headers || {});
if (code !== null && status >= 200 && status < 300) { out.ok = true; return [{ json: out }]; }
let retry = false;
if (status === 429) {
  const ra = Number(hdr['retry-after']);
  out.wait = Number.isFinite(ra) && ra >= 0 ? Math.min(ra, 10) : 2;
  retry = true;
} else if (status === 409) { retry = n === 1; out.wait = 1; }
else if (code === null || [500, 502, 503, 504].includes(status) || status >= 500) { retry = true; out.wait = n === 1 ? 2 : 8; }
else if (status === 401 || status === 403) { out.reason = 'crm_auth_error'; return [{ json: out }]; }
else { out.reason = 'crm_bad_request'; return [{ json: out }]; }
if (retry && n < 3) { out.done = false; return [{ json: out }]; }
out.reason = 'crm_retry_exhausted';
return [{ json: out }];
""".replace("__N__", str(n))


# ------------------------------------------------------------------------------------------------ Replay

REPLAY_REQUEST = r"""
const f = $input.first().json;
const id = Number(f.row_id);
return [{ json: { row_id: Number.isFinite(id) ? id : -1, request_id: String(f.request_id || '') || ('replay-' + $execution.id),
  received_ms: Date.now() } }];
"""

REPLAY_DECIDE = r"""
const q = $('Replay request').first().json;
const rows = $input.all().map((i) => i.json).filter((j) => j && j.id !== undefined && j.id !== null);
const row = rows.find((r) => Number(r.id) === q.row_id) || null;
let go = false, reason = null;
if (!row) reason = 'row_not_found';
else if (row.state !== 'open') reason = 'row_closed';
else go = true;
return [{ json: { go, reason, row_id: q.row_id, request_id: q.request_id, received_ms: q.received_ms,
  core: go ? { mode: 'replay', body_text: row.body, request_id: q.request_id, delivery_id: '', topic: '',
    received_ms: q.received_ms, replay: { row_id: row.id, order: row.order_number || '', replays: Number(row.replays || 0) },
    user: 'replay', force_crash: false } : null } }];
"""

REPLAY_REFUSED_LOG = r"""
const d = $('Replay decide').first().json;
return [{ json: { at: new Date().toISOString(), request_id: d.request_id, delivery_id: '', topic: '', mode: 'replay',
  order_number: '', result: 'replay_refused', reasons: JSON.stringify([d.reason]), contact_id: '', deal_id: '',
  attempts: '', seconds: Math.round((Date.now() - d.received_ms) / 100) / 10, row_id: String(d.row_id), user: 'replay' } }];
"""

# ------------------------------------------------------------------------------------------------ Summary

SUMMARY_GATE = r"""
const it = $input.first().json;
const eq = (a, b) => { let d = a.length ^ b.length; for (let i = 0; i < Math.max(a.length, b.length); i++) d |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0); return d === 0; };
const want = typeof it.signature === 'string' ? it.signature : '';
let ok = it.has_sig && !!want && eq(it.sig, want), body = {};
if (ok) { try { body = JSON.parse(it.text); } catch (e) { ok = false; } }
const start = ok && typeof body.window_start === 'string' ? body.window_start : null;
return [{ json: { ok: ok && !!start, window_start: start, request_id: String(body.request_id || it.request_id || ''), http: ok && start ? 200 : 401 } }];
"""

SUMMARY_WINDOW_LIVE = r"""
return [{ json: { window_start: new Date(Date.now() - 24 * 3600 * 1000).toISOString(), request_id: 'daily-' + $execution.id } }];
"""

SUMMARY_COUNT = r"""
const W = $('__WINDOW__').first().json;
const end = new Date().toISOString();
const inWin = (t) => typeof t === 'string' && t >= W.window_start && t <= end;
const log = $('Log rows').all().map((i) => i.json).filter((j) => j && j.id !== undefined && inWin(j.at));
const rows = $('Attention rows').all().map((i) => i.json).filter((j) => j && j.id !== undefined && inWin(j.created_at));
const count = (r) => log.filter((j) => j.result === r).length;
const c = { synced: count('created'), updated: count('updated'), skipped_duplicate: count('skipped_duplicate'),
  skipped_older: count('skipped_older'), needs_attention: rows.length, still_open: rows.filter((r) => r.state === 'open').length };
const text = `Data sync summary (${W.window_start} to ${end}): ${c.synced} new, ${c.updated} updated, `
  + `${c.skipped_duplicate} duplicates skipped, ${c.skipped_older} older updates skipped, `
  + `${c.needs_attention} need attention (${c.still_open} still open).`;
return [{ json: { request_id: W.request_id, alert: { type: 'summary', order: '', reason: '', row_id: '', text, data: c },
  over5: c.needs_attention > 5, counts: c } }];
"""

OVER5_STATE = r"""
const S = Object.assign({}, $('Count').first().json);
S.alert = { type: 'over_5', order: '', reason: '', row_id: '', data: S.counts,
  text: `Alert: ${S.counts.needs_attention} orders needed attention in this window (more than 5). Check the needs-attention list.` };
return [{ json: S }];
"""

# ------------------------------------------------------------------------------------------------ Error

CRASH_STATE = r"""
const e = $input.first().json || {};
const ex = e.execution || {};
const wf = e.workflow || {};
const msg = String((ex.error && ex.error.message) || 'unknown error').slice(0, 200);
return [{ json: { request_id: '', alert: { type: 'crash', order: '', reason: '', row_id: '', execution_id: String(ex.id || ''),
  text: `Crash in ${wf.name || 'a Q129 workflow'} (execution ${ex.id || '?'}): ${msg}`,
  data: { execution_id: String(ex.id || ''), workflow: wf.name || '', last_node: ex.lastNodeExecuted || '' } } } }];
"""
