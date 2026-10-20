"""Test runner of the data sync (Q-129): sends every case to the Q129 workflows and grades it.

    python tests/runner.py --label visible-1                 # all visible cases (resets first)
    python tests/runner.py --label dry-1 --only N01,T01      # some cases (resets first)
    python tests/runner.py --label gated-1 --data <folder>   # visible + the hold-out file in <folder>

Grading follows tests/CASES.md sections 5-6 and evals/eval_config.yaml; the gate verdict over 3 runs is
tests/score.py. Results: tests/results/<label>.json (and a short text summary on screen).
Exit 0 = the run completed (misses are results, not errors); 2 = test machinery failed (INVALID RUN).

Needs: local n8n with the Q129 test copy pushed (python workflows/build.py --push), the fault proxy
(tests/proxy.py; started here when it is not running), and in the git-ignored .env: N8N_URL, N8N_API_KEY,
HUBSPOT_TOKEN, Q129_WEBHOOK_SECRET, Q129_REPLAY_PASSWORD. Secrets are never printed or written.
Shared-account rules: HubSpot records are archived only when they are this build's (sync_source
harbour-demo-shop and an e-mail on harbour-sync(-h).example.com; deals with a shop_order_id); n8n tables
q129_* only.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from n8n_api import load_env  # noqa: E402

HS = "https://api.hubapi.com"
PROXY = "http://127.0.0.1:8130"
SOURCE = "harbour-demo-shop"
DOMAINS = ("harbour-sync.example.com", "harbour-sync-h.example.com")
TABLES = ("q129_ledger", "q129_attention", "q129_log", "q129_alerts")
STAGE_LABEL = {"appointmentscheduled": "Appointment Scheduled", "qualifiedtobuy": "Qualified To Buy",
               "closedwon": "Closed Won", "closedlost": "Closed Lost"}
CONTACT_MAP = {"email": "email", "first_name": "firstname", "last_name": "lastname", "phone": "phone",
               "company": "company", "address": "address", "city": "city", "postcode": "zip", "country": "country",
               "sync_source": "sync_source"}
DEAL_MAP = {"order_number": "shop_order_id", "name": "dealname", "amount": "amount", "currency": "shop_currency",
            "stage": "dealstage", "order_date": "closedate", "modified": "shop_modified_at"}
USER_AGENT = "WooCommerce/11.2.1 Hookshot (WordPress/7.1.3)"
SHOP = "https://harbour-ebikes.example.com/"
ALERT_TYPES = ("attention", "replay_failed", "over_5", "crash")

ENV = load_env()


class Invalid(Exception):
    """The test machinery failed (INVALID RUN, eval-gate section 6)."""


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ------------------------------------------------------------------------------------------------ HTTP helpers

_pace_lock = threading.Lock()
_calls = []


def _pace():
    with _pace_lock:
        now = time.monotonic()
        while len(_calls) >= 6 and now - _calls[-6] < 1.0:
            time.sleep(1.0 - (now - _calls[-6]) + 0.01)
            now = time.monotonic()
        _calls.append(now)
        del _calls[:-10]


def http(method, url, body=None, headers=None, timeout=60):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def hs(method, path, body=None, params=None):
    url = HS + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    for attempt in range(5):
        _pace()
        s, raw = http(method, url, body, {"Authorization": "Bearer " + ENV["HUBSPOT_TOKEN"],
                                          "Content-Type": "application/json", "Accept": "application/json"})
        if s == 429 or s >= 500:
            time.sleep(2 + attempt * 2)
            continue
        try:
            return s, json.loads(raw) if raw else None
        except ValueError:
            return s, raw[:300].decode("utf-8", "replace")
    raise Invalid(f"HubSpot {method} {path}: HTTP {s} after retries")


def n8n(method, path, body=None, params=None):
    url = ENV["N8N_URL"].rstrip("/") + "/api/v1" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    s, raw = http(method, url, body, {"X-N8N-API-KEY": ENV["N8N_API_KEY"], "Accept": "application/json",
                                      "Content-Type": "application/json"})
    if s >= 300:
        raise Invalid(f"n8n API {method} {path}: HTTP {s} {raw[:200]!r}")
    return json.loads(raw) if raw else {}


# ------------------------------------------------------------------------------------------------ n8n tables

class Tables:
    def __init__(self):
        self.ids = {}
        for t in self._all("/data-tables"):
            if t.get("name") in TABLES:
                self.ids[t["name"]] = t["id"]
        missing = [t for t in TABLES if t not in self.ids]
        if missing:
            raise Invalid("data tables missing in n8n (python workflows/build.py --push): " + ", ".join(missing))

    @staticmethod
    def _all(path, params=None):
        items, cursor = [], None
        while True:
            p = dict(params or {}, limit=100)
            if cursor:
                p["cursor"] = cursor
            page = n8n("GET", path, params=p)
            items.extend(page.get("data", []))
            cursor = page.get("nextCursor")
            if not cursor:
                return items

    def rows(self, table, **eq):
        params = {}
        if eq:
            params["filter"] = json.dumps({"type": "and", "filters": [
                {"columnName": k, "condition": "eq", "value": v} for k, v in eq.items()]})
        return self._all(f"/data-tables/{self.ids[table]}/rows", params)

    def clear(self):
        for t in TABLES:
            n8n("DELETE", f"/data-tables/{self.ids[t]}/rows/clear")


# ------------------------------------------------------------------------------------------------ HubSpot reads

def get_contact(email):
    s, b = hs("GET", f"/crm/v3/objects/contacts/{urllib.parse.quote(email, safe='')}",
              params={"idProperty": "email", "properties": ",".join(CONTACT_MAP.values())})
    return b if s == 200 else None


def get_deal(order):
    s, b = hs("GET", f"/crm/v3/objects/deals/{urllib.parse.quote(order, safe='')}",
              params={"idProperty": "shop_order_id", "properties": ",".join(DEAL_MAP.values())})
    return b if s == 200 else None


def search_records(obj, prop, value, op="EQ", props=()):
    f = {"propertyName": prop, "operator": op}
    if value is not None:
        f["value"] = value
    out, after = [], None
    while True:
        body = {"filterGroups": [{"filters": [f]}], "properties": [prop, *props], "limit": 100}
        if after:
            body["after"] = after
        s, b = hs("POST", f"/crm/v3/objects/{obj}/search", body)
        if s != 200:
            raise Invalid(f"HubSpot search {obj} {prop}: HTTP {s}")
        out += b.get("results", [])
        after = ((b.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            return out


def search_ids(obj, prop, value, op="EQ"):
    return [r["id"] for r in search_records(obj, prop, value, op)]


def count_after_visible(obj, record_id, searches):
    """H2 count: union of the searches, once the record read by idProperty shows in search (<= 60 s)."""
    end = time.time() + 60
    ids = set()
    while True:
        ids = set()
        for prop, value in searches:
            ids |= set(search_ids(obj, prop, value))
        if record_id is None or record_id in ids or time.time() > end:
            return ids
        time.sleep(3)


def linked_emails(deal_id):
    s, b = hs("GET", f"/crm/v4/objects/deals/{deal_id}/associations/contacts")
    if s != 200:
        return []
    cids = [str(r["toObjectId"]) for r in b.get("results", [])]
    if not cids:
        return []
    s, b = hs("POST", "/crm/v3/objects/contacts/batch/read",
              {"properties": ["email"], "inputs": [{"id": c} for c in cids]})
    return sorted(str((r.get("properties") or {}).get("email") or "").lower() for r in (b or {}).get("results", []))


def snapshot(orders, emails):
    out = {}
    for e in sorted(emails):
        c = get_contact(e)
        out["c:" + e] = None if c is None else {k: (c.get("properties") or {}).get(k) for k in CONTACT_MAP.values()}
    for o in sorted(orders):
        d = get_deal(o)
        out["d:" + o] = None if d is None else {k: (d.get("properties") or {}).get(k) for k in DEAL_MAP.values()}
    return out


def reset_hubspot():
    """Archive this build's records only (see module docstring); wait until search shows none."""
    def mine_contacts():
        out = []
        for r in search_records("contacts", "sync_source", SOURCE, props=("email",)):
            em = str((r.get("properties") or {}).get("email") or "").lower()
            if any(em.endswith("." + d) or em.endswith("@" + d) for d in DOMAINS):
                out.append(r["id"])
        return out

    archived = 0
    for _ in range(3):
        cids = mine_contacts()
        dids = search_ids("deals", "shop_order_id", None, op="HAS_PROPERTY")
        if not cids and not dids:
            break
        for obj, ids in (("contacts", cids), ("deals", dids)):
            for k in range(0, len(ids), 100):
                s, _ = hs("POST", f"/crm/v3/objects/{obj}/batch/archive", {"inputs": [{"id": i} for i in ids[k:k + 100]]})
                if s not in (200, 204):
                    raise Invalid(f"HubSpot archive {obj}: HTTP {s}")
                archived += len(ids[k:k + 100])
        time.sleep(5)
    end = time.time() + 180
    while time.time() < end:
        if not search_ids("deals", "shop_order_id", None, op="HAS_PROPERTY") and not mine_contacts():
            return archived
        time.sleep(5)
    raise Invalid("HubSpot search still shows this build's records 180 s after the reset")


# ------------------------------------------------------------------------------------------------ sending

def wc_sign(body, secret):
    return base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode()


def send_webhook(ev, rid):
    body = ev["body"].encode("utf-8")
    secret = ENV["Q129_WEBHOOK_SECRET"]
    h = {"X-Q129-Request-Id": rid}
    if ev.get("content_type"):
        h["Content-Type"] = ev["content_type"]
    if ev.get("topic"):
        res, _, act = ev["topic"].partition(".")
        h.update({"User-Agent": USER_AGENT, "X-WC-Webhook-Source": SHOP, "X-WC-Webhook-Topic": ev["topic"],
                  "X-WC-Webhook-Resource": res, "X-WC-Webhook-Event": act,
                  "X-WC-Webhook-ID": str(ev.get("webhook_id") or ""),
                  "X-WC-Webhook-Delivery-ID": str(ev.get("delivery_id") or "")})
    sign = ev.get("sign")
    if sign == "valid":
        h["X-WC-Webhook-Signature"] = wc_sign(body, secret)
    elif sign == "wrong_secret":
        h["X-WC-Webhook-Signature"] = wc_sign(body, "another-secret-" + secret[:4])
    elif sign == "tampered":
        h["X-WC-Webhook-Signature"] = wc_sign(body, secret)
        t = ev["tamper"]
        body = ev["body"].replace(t["find"], t["replace"], 1).encode("utf-8")
    if ev.get("force_crash"):
        h["X-Q129-Test-Crash"] = "yes"
    s, _ = http("POST", ENV["N8N_URL"].rstrip("/") + "/webhook/q129-order", body, h, timeout=90)
    return s


def send_replay(row_id, rid):
    pw = ENV.get("Q129_REPLAY_PASSWORD")
    if not pw:
        raise Invalid("Q129_REPLAY_PASSWORD missing in .env (the replay form login, user replay)")
    boundary = "q129" + uuid.uuid4().hex
    parts = []
    for name, value in (("field-0", str(row_id)), ("field-1", rid)):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
    body = ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8")
    auth = base64.b64encode(f"replay:{pw}".encode("utf-8")).decode()
    s, raw = http("POST", ENV["N8N_URL"].rstrip("/") + "/form/q129-replay", body,
                  {"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": "Basic " + auth},
                  timeout=90)
    return s


def send_summary(window_start, rid):
    body = json.dumps({"window_start": window_start, "request_id": rid}).encode("utf-8")
    h = {"Content-Type": "application/json", "X-Q129-Request-Id": rid,
         "X-WC-Webhook-Signature": wc_sign(body, ENV["Q129_WEBHOOK_SECRET"])}
    s, _ = http("POST", ENV["N8N_URL"].rstrip("/") + "/webhook/q129-test-summary", body, h, timeout=90)
    return s


def proxy_control(step, faults):
    s, _ = http("POST", PROXY + "/__control", {"step": step, "faults": faults}, {"Content-Type": "application/json"})
    if s != 200:
        raise Invalid("fault proxy control failed")


def proxy_counts():
    s, raw = http("GET", PROXY + "/__counts")
    if s != 200:
        raise Invalid("fault proxy counts failed")
    return json.loads(raw)


def ensure_proxy():
    try:
        proxy_counts()
        return None
    except (Invalid, OSError, urllib.error.URLError):
        pass
    p = subprocess.Popen([sys.executable, "-I", str(ROOT / "tests" / "proxy.py")], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.3)
        try:
            proxy_counts()
            return p
        except (Invalid, OSError, urllib.error.URLError):
            continue
    raise Invalid("fault proxy did not start on port 8130")


# ------------------------------------------------------------------------------------------------ grading

def step_wait(ev):
    extra = 0
    for seq in ((ev.get("faults") or {}).values()):
        for r in seq:
            if r in ("timeout", "timeout_after_forward"):
                extra += 17
            elif r.startswith("429"):
                extra += 10
            elif r in ("500", "502", "503", "504", "close"):
                extra += 8
    return 60 + extra


def norm_order(v):
    return "" if v in (None, "", "unknown") else str(v)


def same_amount(a, b):
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return False


def same_second(a, b):
    def p(v):
        if v in (None, ""):
            return None
        if str(v).isdigit():
            return datetime.fromtimestamp(int(v) / 1000, timezone.utc).replace(microsecond=0)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)
    try:
        return p(a) == p(b)
    except ValueError:
        return False


class CaseRun:
    def __init__(self, runner, case):
        self.r, self.case = runner, case
        self.misses = []
        self.rids = {}          # step -> request id
        self.sent_at = {}       # step -> iso time sent
        self.seconds = {}
        self.orders, self.emails = case_keys(case)

    def miss(self, where, rule, expected, actual):
        self.misses.append({"where": where, "rule": rule, "expected": expected, "actual": actual})

    def wait_log(self, rid, limit):
        end = time.time() + limit
        while time.time() < end:
            rows = self.r.t.rows("q129_log", request_id=rid)
            if rows:
                return rows
            time.sleep(1)
        return []

    def wait_alert(self, typ, limit, rid=None, after=None):
        end = time.time() + limit
        while time.time() < end:
            rows = self.r.t.rows("q129_alerts", type=typ) if rid is None else self.r.t.rows("q129_alerts", request_id=rid)
            rows = [a for a in rows if a.get("type") == typ and (after is None or str(a.get("at")) >= after)
                    and a["id"] not in self.r.claimed_alerts]
            if rows:
                return rows
            time.sleep(1)
        return []


def case_keys(case):
    sys.path.insert(0, str(ROOT / "tests"))
    import make_cases as M
    orders, emails = M.case_keys(case)
    valid_e = {e for e in emails if M.EMAIL_RE.match(e) and len(e) <= 254}
    valid_o = {o for o in orders if M.ORDER_RE.match(o)}
    return valid_o, valid_e


class Runner:
    def __init__(self, label):
        self.label = label
        self.t = Tables()
        self.claimed_alerts = set()

    def rid(self, cid, step):
        return f"{self.label}:{cid}:{step}"

    def run_case(self, case):
        cr = CaseRun(self, case)
        cid = case["id"]
        case_start = iso_now()
        time.sleep(0.05)
        events = case["events"]
        i = 0
        while i < len(events):
            ev = events[i]
            group = [ev]
            if ev.get("type") == "webhook" and ev.get("parallel"):
                while i + len(group) < len(events) and events[i + len(group)].get("parallel") == ev["parallel"]:
                    group.append(events[i + len(group)])
            self.run_group(cr, group, case_start)
            i += len(group)
        self.check_final(cr)
        return cr

    def run_group(self, cr, group, case_start):
        cid = cr.case["id"]
        first = group[0]
        label = f"{cid}:{first['step']}"
        proxy_control(label, first.get("faults") if len(group) == 1 else None)
        want_unchanged = any(ev["expect"].get("hubspot_unchanged") for ev in group)
        before = snapshot(cr.orders, cr.emails) if want_unchanged else None
        rows_before = {r["id"]: r for r in self.t.rows("q129_attention")}
        statuses = {}
        t0 = time.time()

        def send(ev):
            rid = self.rid(cid, ev["step"])
            cr.rids[ev["step"]] = rid
            cr.sent_at[ev["step"]] = iso_now()
            if ev["type"] == "webhook":
                statuses[ev["step"]] = send_webhook(ev, rid)
            elif ev["type"] == "replay":
                src = cr.rids.get(ev["row_from_step"])
                rows = self.t.rows("q129_attention", request_id=src) if src else []
                row_id = rows[0]["id"] if rows else 999999999
                statuses[ev["step"]] = send_replay(row_id, rid)
            else:
                statuses[ev["step"]] = send_summary(case_start, rid)

        if len(group) == 1:
            send(first)
        else:
            barrier = threading.Barrier(len(group))

            def go(ev):
                barrier.wait()
                send(ev)
            ts = [threading.Thread(target=go, args=(ev,)) for ev in group]
            for t in ts:
                t.start()
            for t in ts:
                t.join()

        for ev in group:
            self.check_step(cr, ev, statuses.get(ev["step"]), rows_before, t0)
        counts = proxy_counts()
        for ev in group:
            exp = ev["expect"]
            where = f"step {ev['step']}"
            if exp.get("crm_write_attempts") is not None and counts["seen"] != exp["crm_write_attempts"]:
                cr.miss(where + " crm_write_attempts", "miss", exp["crm_write_attempts"], counts["seen"])
        if want_unchanged:
            after = snapshot(cr.orders, cr.emails)
            fwd = sum(counts["forwarded"].values())
            if after != before or fwd:
                cr.miss(f"step {first['step']} hubspot_unchanged", "H3", "no change, 0 forwarded upserts",
                        {"changed": [k for k in after if after[k] != before.get(k)], "forwarded": counts["forwarded"]})

    def check_step(self, cr, ev, status, rows_before, t0):
        exp = ev["expect"]
        step = ev["step"]
        where = f"step {step}"
        rid = cr.rids[step]
        limit = step_wait(ev)
        result, reasons = None, None
        if exp["http"] != status:
            cr.miss(where + " http", "miss", exp["http"], status)
        if ev["type"] == "summary":
            rows = cr.wait_alert("summary", limit, rid=rid)
            if not rows:
                cr.miss(where + " summary", "H4", "summary message", "none recorded")
            else:
                data = json.loads(rows[0].get("data") or "{}")
                if data != exp.get("summary"):
                    cr.miss(where + " summary counts", "miss", exp.get("summary"), data)
        elif "crash" in exp["result"]:
            rows = cr.wait_alert("crash", limit, after=cr.sent_at[step])
            if not rows:
                cr.miss(where + " crash alert", "H4", "crash alert", "none")
            else:
                result, reasons = "crash", []
        else:
            rows = cr.wait_log(rid, limit)
            if not rows:
                cr.miss(where + " log row", "H4", "log row", f"none within {limit} s")
            else:
                if len(rows) > 1:
                    cr.miss(where + " log rows", "miss", 1, len(rows))
                result = rows[0].get("result")
                reasons = json.loads(rows[0].get("reasons") or "[]")
        cr.seconds[step] = round(time.time() - t0, 1)
        if ev["type"] != "summary":
            if result not in exp["result"]:
                cr.miss(where + " result", "H4" if result is None else "miss", exp["result"], result)
            if result is not None and reasons != exp["reasons"]:
                cr.miss(where + " reasons", "miss", exp["reasons"], reasons)
        # alerts of this step
        got = []
        for a in self.t.rows("q129_alerts", request_id=rid):
            if a.get("type") in ALERT_TYPES:
                got.append(a)
        if "crash" in exp["result"]:
            got += cr.wait_alert("crash", 0.5, after=cr.sent_at[step])
        for a in got:
            self.claimed_alerts.add(a["id"])
        got_n = sorted(self.alert_key(a["type"], a.get("order_number"), a.get("reason")) for a in got)
        exp_n = sorted(self.alert_key(a["type"], a.get("order"), a.get("reason")) for a in exp["alerts"])
        if got_n != exp_n:
            cr.miss(where + " alerts", "H4" if len(got_n) < len(exp_n) else "miss", exp_n, got_n)
        cr.step_alerts = getattr(cr, "step_alerts", {})
        cr.step_alerts[step] = got_n
        # attention row effect and closed rows
        rows_now = {r["id"]: r for r in self.t.rows("q129_attention")}
        new = [r for r in rows_now.values() if r.get("request_id") == rid]
        if exp["attention_row"] == "opens" and len(new) != 1:
            cr.miss(where + " attention row", "H4" if not new else "miss", "one new row", len(new))
        if exp["attention_row"] in ("none", "stays_open") and new:
            cr.miss(where + " attention row", "miss", "no new row", len(new))
        if exp["attention_row"] == "stays_open":
            src = cr.rids.get(ev.get("row_from_step"))
            row = next((r for r in rows_now.values() if r.get("request_id") == src), None)
            old = rows_before.get(row["id"]) if row else None
            if not row or row.get("state") != "open" or not old or \
                    int(row.get("replays") or 0) != int(old.get("replays") or 0) + 1:
                cr.miss(where + " replayed row", "H4", "open, replays +1",
                        None if not row else {"state": row.get("state"), "replays": row.get("replays")})
        closed_now = sorted(self.step_of(cr, r.get("request_id")) for r in rows_now.values()
                            if r.get("closed_request") == rid)
        if closed_now != sorted(exp["closes_rows_from_steps"]):
            cr.miss(where + " closed rows", "miss", sorted(exp["closes_rows_from_steps"]), closed_now)

    @staticmethod
    def alert_key(typ, order, reason):
        if typ in ("over_5", "crash"):
            return [typ, "", ""]
        return [typ, norm_order(order), reason or ""]

    @staticmethod
    def step_of(cr, rid):
        for s, r in cr.rids.items():
            if r == rid:
                return s
        return rid

    def check_final(self, cr):
        fin = cr.case["expected_final"]
        older = self.older_values(cr)
        for c in fin["contacts"]:
            where = f"final contact {c['email']}"
            rec = get_contact(c["email"])
            if c["count"] == 0:
                ids = count_after_visible("contacts", None, [("email", c["email"])])
                if rec is not None or ids:
                    cr.miss(where, "H3", "no contact", "exists")
                continue
            if rec is None:
                cr.miss(where, "H1", "contact", "missing")
                continue
            ids = count_after_visible("contacts", rec["id"], [("email", c["email"])])
            if len(ids) > 1:
                cr.miss(where + " count", "H2", 1, len(ids))
            props = rec.get("properties") or {}
            for k, hk in CONTACT_MAP.items():
                want = (c["fields"] or {}).get(k, "")
                got = props.get(hk) or ""
                if k == "email":
                    got = got.lower()
                if got != want:
                    rule = "H1+H5" if (got == "" and want != "") or got in older.get(hk, set()) else "H1"
                    cr.miss(f"{where} {k}", rule, want, got)
        for d in fin["deals"]:
            where = f"final deal {d['order_number']}"
            rec = get_deal(d["order_number"])
            searches = [("shop_order_id", d["order_number"]), ("dealname", "Order #" + d["order_number"])]
            if d["count"] == 0:
                ids = count_after_visible("deals", None, searches)
                if rec is not None or ids:
                    cr.miss(where, "H3", "no deal", "exists")
                continue
            if rec is None:
                cr.miss(where, "H1", "deal", "missing")
                continue
            ids = count_after_visible("deals", rec["id"], searches)
            if len(ids) > 1:
                cr.miss(where + " count", "H2", 1, len(ids))
            props = rec.get("properties") or {}
            for k, hk in DEAL_MAP.items():
                want = d["fields"][k]
                got = props.get(hk) or ""
                if k == "amount":
                    ok = same_amount(got, want)
                elif k in ("order_date", "modified"):
                    ok = same_second(got, want)
                elif k == "stage":
                    got = STAGE_LABEL.get(got, got)
                    ok = got == want
                else:
                    ok = got == want
                if not ok:
                    rule = "H1+H5" if got == "" or got in older.get(hk, set()) else "H1"
                    cr.miss(f"{where} {k}", rule, want, got)
            links = linked_emails(rec["id"])
            if links != sorted(d["contacts"]):
                cr.miss(where + " links", "H1", sorted(d["contacts"]), links)
        for l_ in fin["ledger"]:
            rows = self.t.rows("q129_ledger", order_number=l_["order_number"])
            where = f"final ledger {l_['order_number']}"
            if l_["modified"] is None:
                if rows:
                    cr.miss(where, "miss", "no row", len(rows))
            elif len(rows) != 1:
                cr.miss(where, "H2" if len(rows) > 1 else "H4", 1, len(rows))
            elif rows[0].get("version") != l_["modified"]:
                cr.miss(where + " version", "miss", l_["modified"], rows[0].get("version"))
        rids = set(cr.rids.values())
        rows = [r for r in self.t.rows("q129_attention") if r.get("request_id") in rids]
        got_rows = sorted(({"from_step": self.step_of(cr, r["request_id"]), "order": norm_order(r.get("order_number")),
                            "reason": r.get("reason"), "reasons": json.loads(r.get("reasons") or "[]"),
                            "state": r.get("state"), "closed_by": r.get("closed_by") or None,
                            "closed_at_step": self.step_of(cr, r.get("closed_request")) if r.get("closed_request") else None,
                            "replays": int(r.get("replays") or 0)} for r in rows), key=lambda x: x["from_step"])
        exp_rows = sorted((dict(r, order=norm_order(r["order"])) for r in fin["attention_rows"]),
                          key=lambda x: x["from_step"])
        if got_rows != exp_rows:
            cr.miss("final attention rows", "H4" if len(got_rows) < len(exp_rows) else "miss", exp_rows, got_rows)
        got_alerts = sorted([s] + a for s, al in getattr(cr, "step_alerts", {}).items() for a in al)
        exp_alerts = sorted([a["step"]] + self.alert_key(a["type"], a.get("order"), a.get("reason"))
                            for a in fin["alerts"])
        if got_alerts != exp_alerts:
            cr.miss("final alerts", "H4" if len(got_alerts) < len(exp_alerts) else "miss", exp_alerts, got_alerts)
        posts = sum(1 for a in self.t.rows("q129_alerts", type="summary") if a.get("request_id") in rids)
        if posts != fin["summary_posts"]:
            cr.miss("final summary posts", "H4" if posts < fin["summary_posts"] else "miss", fin["summary_posts"], posts)

    @staticmethod
    def older_values(cr):
        """HubSpot values that only skipped or older events of the case carry (for naming H5)."""
        sys.path.insert(0, str(ROOT / "tests"))
        import make_cases as M
        out = {}
        for ev in cr.case["events"]:
            if ev.get("type") != "webhook" or not set(ev["expect"]["result"]) <= {"skipped_older", "skipped_duplicate"}:
                continue
            reasons, rec = M.check_and_clean(M.parse_body(ev["body"]))
            if reasons:
                continue
            for k, hk in CONTACT_MAP.items():
                if rec["contact"].get(k):
                    out.setdefault(hk, set()).add(rec["contact"][k])
            for k, hk in DEAL_MAP.items():
                if k != "order_number":
                    out.setdefault(hk, set()).add(str(rec["deal"][k]))
        return out


# ------------------------------------------------------------------------------------------------ main

def load_cases(data):
    doc = json.loads((ROOT / "tests" / "cases" / "visible.json").read_text(encoding="utf-8"))
    cases = doc["cases"]
    if data:
        hdoc = json.loads((Path(data) / "holdout.json").read_text(encoding="utf-8"))
        vis_ids = {c["id"] for c in cases}
        vis_orders = set().union(*(case_keys(c)[0] for c in cases))
        for c in hdoc["cases"]:
            if c["id"] in vis_ids or case_keys(c)[0] & vis_orders:
                raise Invalid(f"hold-out case {c['id']} shares an ID or order number with the visible set")
        cases = cases + hdoc["cases"]
    return cases


def secret_leaks(t, text):
    secrets = [ENV.get(k) for k in ("Q129_WEBHOOK_SECRET", "HUBSPOT_TOKEN", "Q129_REPLAY_PASSWORD") if ENV.get(k)]
    found = 0
    blobs = [text] + [json.dumps(r) for tab in TABLES for r in t.rows(tab)]
    for s in secrets:
        found += sum(b.count(s) for b in blobs)
    return found


def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return ""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--only", help="comma-separated case IDs (their depends_on cases are added)")
    ap.add_argument("--data", help="folder with the extracted hold-out file holdout.json")
    ap.add_argument("--no-reset", action="store_true")
    a = ap.parse_args()
    for k in ("N8N_API_KEY", "HUBSPOT_TOKEN", "Q129_WEBHOOK_SECRET"):
        if not ENV.get(k):
            print(f"INVALID RUN: {k} missing in .env")
            return 2
    out_dir = ROOT / "tests" / "results"
    out_dir.mkdir(exist_ok=True)
    started = iso_now()
    proxy = None
    try:
        cases = load_cases(a.data)
        if a.only:
            want = set(a.only.split(","))
            by_id = {c["id"]: c for c in cases}
            stack = list(want)
            while stack:
                for dep in by_id[stack.pop()].get("depends_on", []):
                    if dep not in want:
                        want.add(dep)
                        stack.append(dep)
            cases = [c for c in cases if c["id"] in want]
        proxy = ensure_proxy()
        r = Runner(a.label)
        if not a.no_reset:
            r.t.clear()
            n = reset_hubspot()
            print(f"reset: q129 tables cleared, {n} HubSpot records of this build archived", flush=True)
        results = []
        for c in cases:
            t0 = time.time()
            cr = r.run_case(c)
            ok = not cr.misses
            results.append({"id": c["id"], "kind": c["kind"], "set": "holdout" if c["id"].startswith("H-") else "visible",
                            "simulated": c.get("simulated", False), "pass": ok, "misses": cr.misses,
                            "seconds": round(time.time() - t0, 1), "step_seconds": cr.seconds})
            line = f"{c['id']:7} {'PASS' if ok else 'MISS'} {round(time.time() - t0, 1):6}s"
            if not ok:
                line += "  " + "; ".join(f"{m['where']} [{m['rule']}]" for m in cr.misses[:4])
            print(line, flush=True)
        counts = proxy_counts()
        logs = r.t.rows("q129_log")
        retries = 0
        for row in logs:
            try:
                att = json.loads(row.get("attempts") or "{}") or {}
            except ValueError:
                att = {}
            retries += sum(max(0, int(v) - 1) for v in att.values())
        secs = sorted(float(row.get("seconds") or 0) for row in logs if row.get("mode") == "webhook"
                      and row.get("result") in ("created", "updated"))
        doc = {"label": a.label, "started": started, "finished": iso_now(), "workflow_commit": git_head(),
               "cases_run": len(results), "passed": sum(1 for x in results if x["pass"]),
               "hard_rule_breaks": sum(1 for x in results for m in x["misses"] if m["rule"].startswith("H")),
               "cases": results, "proxy_real_errors": counts.get("real_errors", []),
               "secondary": {"median_seconds_sync": secs[len(secs) // 2] if secs else None,
                             "worst_seconds_sync": secs[-1] if secs else None, "retries": retries,
                             "hubspot_requests_via_proxy": counts.get("requests")}}
        text = json.dumps(doc, ensure_ascii=False, indent=1)
        doc["secret_leaks"] = secret_leaks(r.t, text)
        (out_dir / f"{a.label}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{doc['passed']} of {doc['cases_run']} cases passed; hard-rule breaks {doc['hard_rule_breaks']}; "
              f"secret leaks {doc['secret_leaks']}; real HubSpot errors {len(doc['proxy_real_errors'])}; "
              f"results tests/results/{a.label}.json", flush=True)
        return 0
    except Invalid as e:
        print(f"INVALID RUN: {e}", flush=True)
        return 2
    finally:
        if proxy is not None:
            proxy.terminate()


if __name__ == "__main__":
    sys.exit(main())
