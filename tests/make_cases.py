"""Visible test cases for n8n-data-sync (Q-129), BLUEPRINT.md v1.2 section 5.

Rules: tests/CASES.md. This file holds the 76 visible cases (gate v4) and a small
reference model of the CASES.md rules. The model fills in the expected
end state of every case and checks every hand-written expected result.

Every run checks the WHOLE set and stops, writing nothing, on:
- duplicate case IDs;
- an order number or e-mail shared between cases that are not marked related;
- a dependency that is missing or comes after the case that needs it;
- an unknown expected result (HTTP code, result, reason, alert, row state);
- an expected result that disagrees with the rules (reference model);
- (gate v2, R1 findings 4 and 11) a parallel group whose events differ in
  body or carry faults or force_crash; a case that is not gated or whose
  simulated flag is wrong; a file whose format_version or case_count is wrong.

Run:   python tests/make_cases.py
       -> writes tests/cases/visible.json and prints its SHA-256.
Check a hand-written set (hold-out writer; writes nothing):
       python tests/make_cases.py --check FILE --set holdout

Standard library only. Deterministic: no clock, no random numbers.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cases", "visible.json")
CASES_MD = os.path.join(HERE, "CASES.md")
FORMAT_VERSION = 1


class CaseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Closed lists (tests/CASES.md section 4). Anything else is "unknown".
# ---------------------------------------------------------------------------
KIND_COUNTS = {"N": 5, "M": 8, "E": 6, "U": 7, "D": 6, "F": 7, "V": 7,
               "A": 8, "T": 8, "R": 9, "S": 5}
HOLDOUT_MIN_PER_KIND = 2
HARD_RULES_BY_KIND = {
    "N": ["H1", "H2", "H4"], "M": ["H1", "H2", "H4"], "E": ["H1", "H2", "H5"],
    "U": ["H1", "H5"], "D": ["H2", "H5"], "F": ["H3", "H4"], "V": ["H3", "H4"],
    "A": ["H3", "H4"], "T": ["H2", "H3", "H4"], "R": ["H2", "H4"], "S": ["H4"],
}
SETS = {
    "visible": {"id": re.compile(r"^[NMEUDFVATRS]\d{2}$"), "kind_at": 0,
                "orders": (41001, 48999), "domain": ".harbour-sync.example.com"},
    "holdout": {"id": re.compile(r"^H-[NMEUDFVATRS]\d{2}$"), "kind_at": 2,
                "orders": (61001, 69999), "domain": ".harbour-sync-h.example.com"},
}

HTTP_CODES = {200, 401, 413}
RESULTS = {"created", "updated", "skipped_duplicate", "skipped_older",
           "needs_attention", "ignored", "rejected", "replay_refused", "crash"}
CHECK_FIELDS = ["order_number", "email", "name", "total", "currency", "status",
                "date_created", "date_modified"]
ATTENTION_REASONS = (
    ["missing_" + f for f in CHECK_FIELDS]
    + ["invalid_" + f for f in CHECK_FIELDS if f != "name"]
    + ["invalid_text_field", "not_json", "same_version_different_data",
       "crm_retry_exhausted", "crm_auth_error", "crm_bad_request"])
REASONS_BY_RESULT = {
    "needs_attention": set(ATTENTION_REASONS),
    "ignored": {"ping", "other_topic"},
    "rejected": {"no_signature", "bad_signature", "too_large"},
    "replay_refused": {"row_closed", "row_not_found"},
}
ALL_REASONS = set().union(*REASONS_BY_RESULT.values())
ALERT_TYPES = {"attention", "replay_failed", "over_5", "crash"}
ROW_EFFECTS = {"opens", "stays_open", "none"}
ROW_STATES = {"open", "closed"}
CLOSED_BY = {None, "sync", "replay"}
EVENT_TYPES = {"webhook", "replay", "summary"}
SIGN_MODES = {"valid", "none", "wrong_secret", "tampered"}
FAULT_TARGETS = {"contacts", "deals"}
FAULT_RE = re.compile(r"^(pass|429(:\d+)?|500|502|503|504|timeout|timeout_after_forward|close|400|401|403|404)$")
SUMMARY_KEYS = ["synced", "updated", "skipped_duplicate", "skipped_older",
                "needs_attention", "still_open"]

ORDER_TOPICS = {"order.created", "order.updated"}
CURRENCIES = {"EUR", "GBP", "USD"}
STAGE_BY_STATUS = {
    "pending": "Appointment Scheduled", "on-hold": "Qualified To Buy",
    "processing": "Closed Won", "completed": "Closed Won",
    "cancelled": "Closed Lost", "refunded": "Closed Lost",
    "failed": "Closed Lost", "trash": "Closed Lost",
}
STAGES = set(STAGE_BY_STATUS.values())
MAX_BODY_BYTES = 262144
MAX_ATTEMPTS = 3
OVER_FAILURES = 5
SYNC_SOURCE = "harbour-demo-shop"
CONTACT_FIELDS = ["email", "first_name", "last_name", "phone", "company",
                  "address", "city", "postcode", "country"]
DEAL_FIELDS = ["order_number", "name", "amount", "currency", "stage",
               "order_date", "modified"]

# ---------------------------------------------------------------------------
# Cleaning and field checks (tests/CASES.md 3.2 and 3.3)
# ---------------------------------------------------------------------------
# The whitespace set of JavaScript String.prototype.trim(), so the n8n Code
# node and this model trim the same characters.
WS = ("\t\n\v\f\r          "
      "        　﻿")
WS_RUN = re.compile("[" + re.escape(WS) + "]+")
EMAIL_ATOM = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+"
EMAIL_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
EMAIL_RE = re.compile(r"^%s(?:\.%s)*@%s(?:\.%s)+$" % (EMAIL_ATOM, EMAIL_ATOM, EMAIL_LABEL, EMAIL_LABEL))
TOTAL_RE = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?$")
ORDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$")
PING_RE = re.compile(r"^webhook_id=[0-9]+\Z")  # \Z: like JavaScript's $, no match before a final newline (R3-07)


def trim(s):
    return s.strip(WS)


def collapse(s):
    return WS_RUN.sub(" ", trim(s))


def valid_date(s):
    m = DATE_RE.match(s)
    if not m:
        return False
    try:
        datetime(*[int(x) for x in m.groups()])
    except ValueError:
        return False
    return True


def check_and_clean(payload):
    """Return (reasons, rec). rec keeps every value that passed its check."""
    if not isinstance(payload, dict):
        return ["not_json"], {"order_number": None, "modified": None}
    reasons = []
    bad_type = False
    rec = {}

    num = payload.get("number")
    rec["order_number"] = None
    if num is None or (isinstance(num, str) and trim(num) == ""):
        reasons.append("missing_order_number")
    elif not isinstance(num, str) or not ORDER_RE.match(trim(num)):
        reasons.append("invalid_order_number")
    else:
        rec["order_number"] = trim(num)

    billing = payload.get("billing")
    if not isinstance(billing, dict):
        billing = {}

    def text(key, names=False):
        nonlocal bad_type
        v = billing.get(key)
        if v is None:
            return ""
        if not isinstance(v, str):
            bad_type = True
            return ""
        return collapse(v) if names else trim(v)

    email = billing.get("email")
    rec["email"] = None
    if email is None or (isinstance(email, str) and trim(email) == ""):
        reasons.append("missing_email")
    elif not isinstance(email, str):
        reasons.append("invalid_email")
    else:
        e = trim(email).lower()
        if len(e) > 254 or not EMAIL_RE.match(e):
            reasons.append("invalid_email")
        else:
            rec["email"] = e

    first, last = text("first_name", True), text("last_name", True)
    if first == "" and last == "":
        reasons.append("missing_name")

    total = payload.get("total")
    rec["amount"] = None
    if total is None or (isinstance(total, str) and trim(total) == ""):
        reasons.append("missing_total")
    elif not isinstance(total, str) or not TOTAL_RE.match(trim(total)):
        reasons.append("invalid_total")
    else:
        rec["amount"] = str(Decimal(trim(total)).quantize(Decimal("0.01")))

    def listed(key, allowed, field):
        v = payload.get(key)
        if v is None or (isinstance(v, str) and trim(v) == ""):
            reasons.append("missing_" + field)
            return None
        if not isinstance(v, str) or trim(v) not in allowed:
            reasons.append("invalid_" + field)
            return None
        return trim(v)

    rec["currency"] = listed("currency", CURRENCIES, "currency")
    status = listed("status", STAGE_BY_STATUS, "status")

    def date(key, field):
        v = payload.get(key)
        if v is None or (isinstance(v, str) and trim(v) == ""):
            reasons.append("missing_" + field)
            return None
        if not isinstance(v, str) or not valid_date(trim(v)):
            reasons.append("invalid_" + field)
            return None
        return trim(v) + "Z"

    rec["order_date"] = date("date_created_gmt", "date_created")
    rec["modified"] = date("date_modified_gmt", "date_modified")

    phone, company = text("phone"), text("company")
    a1, a2 = text("address_1"), text("address_2")
    city, postcode, country = text("city"), text("postcode"), text("country")
    if bad_type:
        reasons.append("invalid_text_field")
    if reasons:
        return reasons, rec

    rec["contact"] = {
        "email": rec["email"], "first_name": first, "last_name": last,
        "phone": phone, "company": company,
        "address": ", ".join(x for x in (a1, a2) if x),
        "city": city, "postcode": postcode, "country": country,
    }
    rec["deal"] = {
        "order_number": rec["order_number"], "name": "Order #" + rec["order_number"],
        "amount": rec["amount"], "currency": rec["currency"],
        "stage": STAGE_BY_STATUS[status], "order_date": rec["order_date"],
        "modified": rec["modified"],
    }
    return [], rec


# ---------------------------------------------------------------------------
# Reference model of the sync (tests/CASES.md section 3)
# ---------------------------------------------------------------------------
def _no_constant(name):
    raise ValueError("not JSON: " + name)


def parse_body(body):
    # NaN, Infinity and -Infinity are not JSON; JavaScript's JSON.parse refuses them too (R3-07)
    try:
        return json.loads(body, parse_constant=_no_constant)
    except ValueError:
        return None


def case_keys(case):
    """(order numbers, e-mails) a case uses; e-mails trimmed and lower-cased."""
    orders, emails = set(), set()
    for ev in case.get("events", []):
        p = parse_body(ev.get("body", "")) if ev.get("type") == "webhook" else None
        if not isinstance(p, dict):
            continue
        n = p.get("number")
        if isinstance(n, str) and trim(n):
            orders.add(trim(n))
        b = p.get("billing")
        if isinstance(b, dict) and isinstance(b.get("email"), str) and trim(b["email"]):
            emails.add(trim(b["email"]).lower())
    return orders, emails


class Model:
    def __init__(self):
        self.contacts = {}
        self.deals = {}
        self.ledger = {}
        self.rows = []

    # -- HubSpot write with the fault proxy (CASES.md 3.7) --
    @staticmethod
    def call(target, faults, attempts, apply):
        seq = (faults or {}).get(target, [])
        for n in range(1, MAX_ATTEMPTS + 1):
            r = seq[n - 1] if n <= len(seq) else "pass"
            attempts[target] = n
            if r == "pass":
                apply()
                return None
            if r == "timeout_after_forward":
                apply()
                continue
            code = r.split(":")[0]
            if code in ("401", "403"):
                return "crm_auth_error"
            if code in ("400", "404"):
                return "crm_bad_request"
        return "crm_retry_exhausted"

    def attention(self, out, reasons, order, modified, ctx, replay_row):
        out["result"] = "needs_attention"
        out["reasons"] = reasons
        if replay_row is not None:
            replay_row["replays"] += 1
            out["row"] = "stays_open"
            out["alerts"].append({"type": "replay_failed", "order": replay_row["order"],
                                  "reason": reasons[0]})
            return out
        self.rows.append({"case": ctx["case"], "from_step": ctx["step"], "order": order,
                          "modified": modified, "reason": reasons[0], "reasons": reasons,
                          "state": "open", "closed_by": None, "closed_at_step": None,
                          "replays": 0, "body": ctx["body"]})
        out["row"] = "opens"
        out["alerts"].append({"type": "attention", "order": order, "reason": reasons[0]})
        return out

    def close_rows(self, out, order, modified, ctx, replay_row, closed_by_replay_only=False):
        for r in self.rows:
            if r["state"] != "open":
                continue
            mine = r is replay_row
            if closed_by_replay_only and not mine:
                continue
            if mine or (r["order"] == order and (r["modified"] is None or r["modified"] <= modified)):
                r["state"] = "closed"
                r["closed_by"] = "replay" if mine else "sync"
                r["closed_at_step"] = ctx["step"]
                out["closes_rows"].append({"case": r["case"], "from_step": r["from_step"]})

    def core(self, payload, faults, ctx, replay_row=None, crash=False):
        out = {"http": 200, "result": None, "reasons": [], "alerts": [],
               "attempts": {"contacts": 0, "deals": 0}, "row": "none", "closes_rows": []}
        reasons, rec = check_and_clean(payload)
        if reasons:
            return self.attention(out, reasons, rec["order_number"], rec["modified"], ctx, replay_row)
        if crash:  # CASES.md 3.13: after the field checks, before the ledger check
            out.update(result="crash")
            out["alerts"].append({"type": "crash"})
            return out
        order, mod = rec["order_number"], rec["modified"]
        data = hashlib.sha256(json.dumps([rec["contact"], rec["deal"]], sort_keys=True,
                                         ensure_ascii=True).encode("utf-8")).hexdigest()
        led = self.ledger.get(order)
        if led is not None:
            if mod < led["modified"]:
                out["result"] = "skipped_older"
            elif mod == led["modified"]:
                if led["data"] != data:
                    return self.attention(out, ["same_version_different_data"], order, mod,
                                          ctx, replay_row)
                out["result"] = "skipped_duplicate"
            if out["result"]:
                out["reasons"] = []
                if replay_row is not None:
                    self.close_rows(out, order, mod, ctx, replay_row, closed_by_replay_only=True)
                return out
        email = rec["email"]
        sent = {k: v for k, v in rec["contact"].items() if v != ""}
        sent["sync_source"] = SYNC_SOURCE
        err = self.call("contacts", faults, out["attempts"],
                        lambda: self.contacts.setdefault(email, {}).update(sent))
        if err:
            return self.attention(out, [err], order, mod, ctx, replay_row)

        def write_deal():
            d = self.deals.get(order, {"contacts": []})
            links = sorted(set(d["contacts"]) | {email})
            self.deals[order] = dict(rec["deal"], contacts=links)
        err = self.call("deals", faults, out["attempts"], write_deal)
        if err:
            return self.attention(out, [err], order, mod, ctx, replay_row)
        out["result"] = "created" if led is None else "updated"
        self.ledger[order] = {"modified": mod, "data": data}
        self.close_rows(out, order, mod, ctx, replay_row)
        return out

    def webhook(self, ev, ctx):
        body = ev["body"]
        out = {"http": 200, "result": None, "reasons": [], "alerts": [],
               "attempts": None, "row": "none", "closes_rows": []}
        if len(body.encode("utf-8")) > MAX_BODY_BYTES:
            out.update(http=413, result="rejected", reasons=["too_large"])
        elif PING_RE.match(body):
            out.update(result="ignored", reasons=["ping"])
        elif ev["sign"] == "none":
            out.update(http=401, result="rejected", reasons=["no_signature"])
        elif ev["sign"] in ("wrong_secret", "tampered"):
            out.update(http=401, result="rejected", reasons=["bad_signature"])
        elif ev.get("topic") not in ORDER_TOPICS:
            out.update(result="ignored", reasons=["other_topic"])
        else:
            payload = parse_body(body)
            if not isinstance(payload, dict):
                return self.attention(out, ["not_json"], None, None, ctx, None)
            res = self.core(payload, ev.get("faults"), ctx, crash=ev.get("force_crash"))
            if not ev.get("faults"):
                res["attempts"] = None
            return res
        return out

    def replay(self, ev, ctx):
        out = {"http": 200, "result": None, "reasons": [], "alerts": [],
               "attempts": None, "row": "none", "closes_rows": []}
        row = next((r for r in self.rows if r["case"] == ctx["case"]
                    and r["from_step"] == ev["row_from_step"]), None)
        if row is None:
            out.update(result="replay_refused", reasons=["row_not_found"])
            return out
        if row["state"] != "open":
            out.update(result="replay_refused", reasons=["row_closed"])
            return out
        payload = parse_body(row["body"])
        if not isinstance(payload, dict):
            return self.attention(out, ["not_json"], None, None, ctx, row)
        res = self.core(payload, ev.get("faults"), ctx, replay_row=row)
        if not ev.get("faults"):
            res["attempts"] = None
        return res

    def snapshot(self, orders, emails):
        return (copy.deepcopy({e: self.contacts.get(e) for e in emails}),
                copy.deepcopy({o: self.deals.get(o) for o in orders}))

    def run_case(self, case):
        """Expected outcome of every event and the end state of the case."""
        cid = case["id"]
        orders, emails = case_keys(case)
        per_event, results = [], []
        for ev in case["events"]:
            ctx = {"case": cid, "step": ev["step"], "body": ev.get("body")}
            before = self.snapshot(orders, emails)
            p = parse_body(ev.get("body", "")) if ev.get("parallel") is not None else None
            num = trim(p["number"]) if isinstance(p, dict) and isinstance(p.get("number"), str) else None
            open_row = num is not None and any(r["state"] == "open" and r["order"] == num for r in self.rows)
            if ev["type"] == "webhook":
                out = self.webhook(ev, ctx)
            elif ev["type"] == "replay":
                out = self.replay(ev, ctx)
            else:
                rows = [r for r in self.rows if r["case"] == cid]
                counts = {
                    "synced": results.count("created"), "updated": results.count("updated"),
                    "skipped_duplicate": results.count("skipped_duplicate"),
                    "skipped_older": results.count("skipped_older"),
                    "needs_attention": len(rows),
                    "still_open": sum(1 for r in rows if r["state"] == "open"),
                }
                out = {"http": 200, "result": None, "reasons": [], "alerts": [],
                       "attempts": None, "row": "none", "closes_rows": [], "summary": counts}
                if counts["needs_attention"] > OVER_FAILURES:
                    out["alerts"].append({"type": "over_5"})
            if out["result"] is not None:
                results.append(out["result"])
            changed = self.snapshot(orders, emails) != before
            # Asserted only where H3 asks for it; never per event inside a parallel group.
            out["hubspot_unchanged"] = (True if out["result"] not in (None, "created", "updated")
                                        and not changed and not ev.get("parallel") else None)
            out["parallel_meets_open_row"] = open_row
            per_event.append(out)

        valid_emails = sorted(e for e in emails if EMAIL_RE.match(e) and len(e) <= 254)
        valid_orders = sorted(o for o in orders if ORDER_RE.match(o))
        contacts = []
        for e in valid_emails:
            c = self.contacts.get(e)
            fields = None
            if c is not None:
                fields = {k: c.get(k, "") for k in CONTACT_FIELDS}
                fields["sync_source"] = c.get("sync_source", "")
            contacts.append({"email": e, "count": 1 if c else 0, "fields": fields})
        deals = []
        for o in valid_orders:
            d = self.deals.get(o)
            deals.append({"order_number": o, "count": 1 if d else 0,
                          "fields": {k: d[k] for k in DEAL_FIELDS} if d else None,
                          "contacts": d["contacts"] if d else []})
        ledger = [{"order_number": o, "modified": self.ledger[o]["modified"] if o in self.ledger else None}
                  for o in valid_orders]
        rows = [{k: r[k] for k in ("from_step", "order", "reason", "reasons", "state",
                                   "closed_by", "closed_at_step", "replays")}
                for r in self.rows if r["case"] == cid]
        alerts = [dict(a, step=ev["step"]) for ev, out in zip(case["events"], per_event)
                  for a in out["alerts"]]
        final = {"contacts": contacts, "deals": deals, "ledger": ledger,
                 "attention_rows": rows, "alerts": alerts,
                 "summary_posts": sum(1 for ev in case["events"] if ev["type"] == "summary")}
        return per_event, final


def model_expect(out, ev, hand_result):
    exp = {"http": out["http"], "result": hand_result, "reasons": out["reasons"],
           "alerts": out["alerts"], "attention_row": out["row"],
           "closes_rows_from_steps": [c["from_step"] for c in out["closes_rows"]],
           "hubspot_unchanged": out["hubspot_unchanged"],
           "crm_write_attempts": out["attempts"]}
    if ev["type"] == "summary":
        exp["summary"] = out["summary"]
    return exp


# ---------------------------------------------------------------------------
# The whole-set check (structure, keys, dependencies, closed lists, rules)
# ---------------------------------------------------------------------------
def check_set(cases, set_name):
    cfg = SETS[set_name]
    errs = []

    def err(cid, msg):
        errs.append("%s: %s" % (cid, msg))

    ids = [c.get("id") for c in cases]
    seen = set()
    for cid in ids:
        if cid in seen:
            err(cid, "duplicate case id")
        seen.add(cid)
    position = {}
    for i, cid in enumerate(ids):
        position.setdefault(cid, i)

    kinds = {}
    for c in cases:
        cid = c.get("id")
        if not isinstance(cid, str) or not cfg["id"].match(cid):
            err(cid, "case id does not match the %s id pattern" % set_name)
            continue
        kind = cid[cfg["kind_at"]]
        if c.get("kind") != kind:
            err(cid, "unknown kind or kind does not match the id: %r" % c.get("kind"))
        kinds[kind] = kinds.get(kind, 0) + 1
    for k, n in KIND_COUNTS.items():
        got = kinds.get(k, 0)
        if set_name == "visible" and got != n:
            err("set", "kind %s has %d cases, BLUEPRINT section 5 says %d" % (k, got, n))
        if set_name == "holdout" and got < HOLDOUT_MIN_PER_KIND:
            err("set", "kind %s has %d cases, the hold-out needs at least %d" % (k, got, HOLDOUT_MIN_PER_KIND))

    for c in cases:
        cid = c.get("id")
        for d in c.get("depends_on", []):
            if d not in position:
                err(cid, "missing dependency %s" % d)
            elif position[d] >= position.get(cid, -1):
                err(cid, "dependency %s comes after the case that needs it" % d)
        for r in c.get("related_to", []):
            if r not in position:
                err(cid, "related_to names unknown case %s" % r)
        check_events(c, err)

    # shared business keys
    related = set()
    for c in cases:
        for r in c.get("related_to", []):
            related.add(frozenset((c.get("id"), r)))
    owner = {}
    for c in cases:
        cid = c.get("id")
        orders, emails = case_keys(c)
        for kind, keys in (("order number", orders), ("e-mail", emails)):
            for key in keys:
                for other in owner.get((kind, key), []):
                    if frozenset((cid, other)) not in related:
                        err(cid, "%s %s shared with %s, cases not marked related" % (kind, key, other))
                owner.setdefault((kind, key), []).append(cid)
                if kind == "e-mail" and EMAIL_RE.match(key) and not key.endswith(cfg["domain"]):
                    err(cid, "e-mail %s is not on the %s domain *%s" % (key, set_name, cfg["domain"]))
                if kind == "order number" and ORDER_RE.match(key):
                    m = re.match(r"^(?:[A-Za-z]+-)?(\d+)$", key)
                    lo, hi = cfg["orders"]
                    if not m or not lo <= int(m.group(1)) <= hi:
                        err(cid, "order number %s is outside the %s range %d-%d" % (key, set_name, lo, hi))
    if errs:
        raise CaseError("\n".join(errs))

    # the rules: run the reference model over the whole set, in file order
    model = Model()
    for c in cases:
        cid = c["id"]
        per_event, final = model.run_case(c)
        for ev, out in zip(c["events"], per_event):
            exp = ev["expect"]
            if out["parallel_meets_open_row"]:
                err(cid, "step %d: a parallel group meets an open needs-attention row of its order (which copy "
                    "closes it is chance; CASES.md 5.2)" % ev["step"])
            if out["result"] is None and ev["type"] != "summary":
                err(cid, "step %d: model gave no result" % ev["step"])
            if out["result"] is not None and out["result"] not in exp["result"]:
                err(cid, "step %d: expected result %s disagrees with the rules (model: %s)"
                    % (ev["step"], exp["result"], out["result"]))
            want = model_expect(out, ev, exp["result"])
            for key in want:
                if exp.get(key) != want[key]:
                    err(cid, "step %d: expected %s %r disagrees with the rules (model: %r)"
                        % (ev["step"], key, exp.get(key), want[key]))
        if c.get("expected_final") != final:
            for key in final:
                if c.get("expected_final", {}).get(key) != final[key]:
                    err(cid, "expected_final.%s disagrees with the rules (model: %s)"
                        % (key, json.dumps(final[key], ensure_ascii=True)))
    if errs:
        raise CaseError("\n".join(errs))


def check_doc(doc, set_name):
    """File-level checks, then the whole-set check."""
    errs = []
    if doc.get("format_version") != FORMAT_VERSION:
        errs.append("file: format_version must be %d, is %r" % (FORMAT_VERSION, doc.get("format_version")))
    if doc.get("set") != set_name:
        errs.append("file: set is %r, expected %r" % (doc.get("set"), set_name))
    cases = doc.get("cases")
    if not isinstance(cases, list):
        raise CaseError("file: cases must be a list")
    if doc.get("case_count") != len(cases):
        errs.append("file: case_count is %r, the file has %d cases" % (doc.get("case_count"), len(cases)))
    if errs:
        raise CaseError("\n".join(errs))
    check_set(cases, set_name)


def check_events(c, err):
    cid = c.get("id")
    events = c.get("events")
    if not isinstance(events, list) or not events:
        err(cid, "no events")
        return
    for i, ev in enumerate(events, 1):
        if ev.get("step") != i:
            err(cid, "steps must be numbered 1, 2, 3 ... in order")
        t = ev.get("type")
        if t not in EVENT_TYPES:
            err(cid, "step %s: unknown event type %r" % (i, t))
            continue
        if t == "webhook":
            if ev.get("sign") not in SIGN_MODES:
                err(cid, "step %s: unknown sign mode %r" % (i, ev.get("sign")))
            if ev.get("sign") == "tampered":
                tp = ev.get("tamper") or {}
                if not tp.get("find") or ev.get("body", "").count(tp["find"]) != 1:
                    err(cid, "step %s: tamper.find must occur exactly once in the body" % i)
            if not isinstance(ev.get("body"), str):
                err(cid, "step %s: body must be a string" % i)
        if t == "replay":
            target = ev.get("row_from_step")
            if not isinstance(target, int) or not 1 <= target < i:
                err(cid, "step %s: replay must name an earlier step" % i)
        for target, seq in (ev.get("faults") or {}).items():
            if target not in FAULT_TARGETS:
                err(cid, "step %s: unknown fault target %r" % (i, target))
            for r in seq:
                if not isinstance(r, str) or not FAULT_RE.match(r):
                    err(cid, "step %s: unknown fault response %r" % (i, r))
        exp = ev.get("expect") or {}
        if exp.get("http") not in HTTP_CODES:
            err(cid, "step %s: unknown http code %r" % (i, exp.get("http")))
        res = exp.get("result")
        if t == "summary":
            if res != []:
                err(cid, "step %s: a summary event has result []" % i)
            if sorted((exp.get("summary") or {}).keys()) != sorted(SUMMARY_KEYS):
                err(cid, "step %s: summary needs exactly the keys %s" % (i, SUMMARY_KEYS))
        elif not isinstance(res, list) or not res or any(r not in RESULTS for r in res):
            err(cid, "step %s: unknown result %r" % (i, res))
        for r in exp.get("reasons") or []:
            if r not in ALL_REASONS:
                err(cid, "step %s: unknown reason %r" % (i, r))
        for a in exp.get("alerts") or []:
            if a.get("type") not in ALERT_TYPES:
                err(cid, "step %s: unknown alert type %r" % (i, a.get("type")))
        if exp.get("attention_row") not in ROW_EFFECTS:
            err(cid, "step %s: unknown attention_row %r" % (i, exp.get("attention_row")))
    if c.get("gated") is not True:
        err(cid, "gated must be true (every case in this build is gated)")
    sim = any(ev.get("faults") or ev.get("force_crash") for ev in events)
    if c.get("simulated") is not sim:
        err(cid, "simulated must be %s (an event has faults or force_crash: %s)" % (sim, sim))
    groups = {}
    for ev in events:
        if ev.get("parallel") is not None:
            groups.setdefault(ev["parallel"], []).append(ev)
    for name, evs in groups.items():
        if any(ev.get("type") != "webhook" for ev in evs):
            err(cid, "parallel group %s: only webhook events can be parallel" % name)
        if len({ev.get("body") for ev in evs}) != 1:
            err(cid, "parallel group %s: events must have the same body bytes" % name)
        if any(ev.get("faults") is not None for ev in evs):
            err(cid, "parallel group %s: faults must be null" % name)
        if any(ev.get("force_crash") for ev in evs):
            err(cid, "parallel group %s: force_crash must be false" % name)
        first = min(ev.get("step", 0) for ev in evs)
        if any(ev.get("type") == "summary" and ev.get("step", 0) > first for ev in events):
            err(cid, "parallel group %s: no summary after a parallel group (the counts depend on which copy "
                "finishes first; CASES.md 5.2)" % name)
    fin = c.get("expected_final") or {}
    for r in fin.get("attention_rows", []):
        if r.get("state") not in ROW_STATES or r.get("closed_by") not in CLOSED_BY:
            err(cid, "unknown attention row state %r / closed_by %r" % (r.get("state"), r.get("closed_by")))
        for reason in r.get("reasons", []):
            if reason not in REASONS_BY_RESULT["needs_attention"]:
                err(cid, "unknown reason %r in an attention row" % reason)
    for d in fin.get("deals", []):
        if d.get("fields") and d["fields"].get("stage") not in STAGES:
            err(cid, "unknown deal stage %r" % d["fields"].get("stage"))


# ---------------------------------------------------------------------------
# WooCommerce order payloads (shape: WooCommerce REST API v3 docs, see CASES.md 1)
# ---------------------------------------------------------------------------
SHOP_URL = "https://harbour-ebikes.example.com/"
WC_VERSION = "11.2.1"
WP_VERSION = "7.1.3"
USER_AGENT = "WooCommerce/%s Hookshot (WordPress/%s)" % (WC_VERSION, WP_VERSION)
WEBHOOK_IDS = {"order.created": 14, "order.updated": 15, "order.deleted": 16}
BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
D = Decimal
CATALOG = {  # key: (product id, sku, name, gross price incl. 25% VAT)
    "city500": (101, "HB-CITY-500", "Harbour City E-Bike 500", D("2490.00")),
    "trek": (102, "HB-TREK-700", "Coastline Trekking E-Bike", D("3250.00")),
    "cargo": (103, "HB-CARGO-2", "Portwell Cargo E-Bike", D("4190.00")),
    "refurb": (104, "HB-CITY-500-R", "Refurbished City E-Bike (A grade)", D("1250.50")),
    "battery": (201, "HB-BAT-625", "Battery 625 Wh", D("690.00")),
    "helmet": (202, "HB-HELM-M", "Commuter Helmet &ndash; Size M", D("89.00")),
    "lock": (203, "HB-LOCK-F", "Folding Lock", D("45.00")),
    "service": (204, "HB-SERV-1Y", "Annual Service Package", D("120.00")),
    "lights": (205, "HB-LED-SET", "LED Light Set", D("59.90")),
    "tube": (206, "HB-TUBE-28", 'Inner Tube 28"', D("12.50")),
    "seat": (207, "HB-CHILD-SEAT", "Child Seat", D("149.00")),
    "pannier": (208, "HB-PAN-WP", "Waterproof Pannier", D("79.00")),
}
PAYMENTS = {"stripe": "Credit Card (Stripe)", "bacs": "Direct bank transfer",
            "cod": "Cash on delivery", "paypal": "PayPal"}
DROP = object()


def c2(d):
    return str(d.quantize(D("0.01")))


def wc_num(d):
    s = c2(d)
    return s.rstrip("0").rstrip(".") if "." in s else s


def php_json(obj):
    """The bytes WooCommerce sends: trim(wp_json_encode($payload)), PHP default flags."""
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).replace("/", "\\/")


def h(text, n=32):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def plus(gmt, seconds):
    t = datetime.strptime(gmt, "%Y-%m-%dT%H:%M:%S") + timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def order(num, email, first, last, items, created, modified=None, status="processing",
          currency="EUR", phone="", company="", address_1="", address_2="", city="",
          state="", postcode="", country="", payment="stripe", customer_id=0,
          coupon=None, vat=True, refund_reason=None, note=""):
    """A WooCommerce order in the REST API v3 shape, totals computed from the items."""
    n = int(num)
    modified = modified or plus(created, 6)
    rate = D("0.25") if vat else D("0")
    lines, ids = [], iter(range(n * 10 + 1, n * 10 + 10))
    goods_gross = D("0")
    disc_net = disc_tax = D("0")
    if coupon:
        disc_net = (coupon[1] / (1 + rate)).quantize(D("0.01"))
        disc_tax = coupon[1] - disc_net
    for i, (key, qty) in enumerate(items):
        pid, sku, name, gross = CATALOG[key]
        unit_net = gross / (1 + rate)
        assert unit_net == unit_net.quantize(D("0.01")), key
        sub = unit_net * qty
        tot = sub - (disc_net if i == 0 else 0)
        sub_tax, tot_tax = sub * rate, tot * rate
        assert tot_tax == tot_tax.quantize(D("0.01")), key
        goods_gross += tot + tot_tax
        lines.append({
            "id": next(ids), "name": name, "product_id": pid, "variation_id": 0,
            "quantity": qty, "tax_class": "", "subtotal": c2(sub), "subtotal_tax": c2(sub_tax),
            "total": c2(tot), "total_tax": c2(tot_tax),
            "taxes": [{"id": 1, "total": wc_num(tot_tax), "subtotal": wc_num(sub_tax)}] if vat else [],
            "meta_data": [], "sku": sku,
            "price": int(unit_net) if unit_net == int(unit_net) else float(unit_net),
        })
    if goods_gross >= 500:
        ship = {"method_title": "Free shipping", "method_id": "free_shipping", "net": D("0")}
    else:
        ship = {"method_title": "Flat rate", "method_id": "flat_rate",
                "net": D("20.00") if vat else D("25.00")}
    ship_tax = ship["net"] * rate
    cart_tax = sum((D(li["total_tax"]) for li in lines), D("0"))
    total = sum((D(li["total"]) for li in lines), D("0")) + cart_tax + ship["net"] + ship_tax
    assert total == goods_gross + ship["net"] + ship_tax
    paid = status in ("processing", "completed", "refunded") and payment != "cod"
    local = lambda g: plus(g, 7200) if g else None  # site timezone: UTC+2 in October
    date_paid = plus(created, 40) if paid else None
    date_completed = modified if status == "completed" else None
    addr = {"first_name": first, "last_name": last, "company": company,
            "address_1": address_1, "address_2": address_2, "city": city, "state": state,
            "postcode": postcode, "country": country}
    p = {
        "id": n, "parent_id": 0, "number": str(num), "order_key": "wc_order_" + h(str(num), 13),
        "created_via": "checkout", "version": WC_VERSION, "status": status,
        "currency": currency,
        "date_created": local(created), "date_created_gmt": created,
        "date_modified": local(modified), "date_modified_gmt": modified,
        "discount_total": c2(disc_net), "discount_tax": c2(disc_tax),
        "shipping_total": c2(ship["net"]), "shipping_tax": c2(ship_tax),
        "cart_tax": c2(cart_tax), "total": c2(total), "total_tax": c2(cart_tax + ship_tax),
        "prices_include_tax": vat, "customer_id": customer_id,
        "customer_ip_address": "203.0.113.%d" % (n % 250 + 1),
        "customer_user_agent": BROWSER, "customer_note": note,
        "billing": dict(addr, email=email, phone=phone),
        "shipping": dict(addr),
        "payment_method": payment, "payment_method_title": PAYMENTS[payment],
        "transaction_id": ("pi_3Q" + h("tx" + str(num), 22)) if payment == "stripe" and paid else "",
        "date_paid": local(date_paid), "date_paid_gmt": date_paid,
        "date_completed": local(date_completed), "date_completed_gmt": date_completed,
        "cart_hash": hashlib.md5(str(num).encode()).hexdigest(),
        "meta_data": [
            {"id": n * 10 + 1, "key": "_wc_order_attribution_source_type", "value": "typein"},
            {"id": n * 10 + 2, "key": "_wc_order_attribution_device_type", "value": "Desktop"},
        ],
        "line_items": lines,
        "tax_lines": [{"id": n * 10 + 8, "rate_code": "VAT-1", "rate_id": 1, "label": "VAT 25%",
                       "compound": False, "tax_total": c2(cart_tax),
                       "shipping_tax_total": c2(ship_tax), "meta_data": []}] if vat else [],
        "shipping_lines": [{"id": n * 10 + 9, "method_title": ship["method_title"],
                            "method_id": ship["method_id"], "total": c2(ship["net"]),
                            "total_tax": c2(ship_tax), "taxes": [], "meta_data": []}],
        "fee_lines": [],
        "coupon_lines": [{"id": n * 10 + 7, "code": coupon[0], "discount": c2(disc_net),
                          "discount_tax": c2(disc_tax), "meta_data": []}] if coupon else [],
        "refunds": [{"id": n * 10 + 6, "reason": refund_reason, "total": "-" + c2(total)}]
        if refund_reason else [],
        "_links": {"self": [{"href": SHOP_URL + "wp-json/wc/v3/orders/%d" % n}],
                   "collection": [{"href": SHOP_URL + "wp-json/wc/v3/orders"}]},
    }
    return p


def edit(p, **changes):
    """Copy of a payload with dotted-path changes, e.g. edit(p, **{"billing.email": ""}).
    The value DROP removes the key."""
    p = copy.deepcopy(p)
    for path, value in changes.items():
        cur = p
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur[part]
        if value is DROP:
            cur.pop(parts[-1], None)
        else:
            cur[parts[-1]] = value
    return p


def de_amount(d):
    """1234.5 -> '1.234,50' (German number style, a common plugin mistake)."""
    whole, cents = c2(d).split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return ".".join(groups) + "," + cents


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------
def wh(payload, result, reason=None, topic="order.created", sign="valid", tamper=None,
       parallel=None, faults=None, crash=False, body=None, content_type="application/json"):
    return {"type": "webhook", "topic": topic, "sign": sign, "tamper": tamper,
            "content_type": content_type, "parallel": parallel, "faults": faults,
            "force_crash": crash, "body": body if body is not None else php_json(payload),
            "_result": result, "_reason": reason}


def upd(payload, result, reason=None, **kw):
    return wh(payload, result, reason, topic="order.updated", **kw)


def replay(from_step, result, reason=None, faults=None):
    return {"type": "replay", "row_from_step": from_step, "faults": faults,
            "_result": result, "_reason": reason}


def summary():
    return {"type": "summary", "_result": [], "_reason": None}


def case(cid, title, events, related_to=(), depends_on=()):
    return {"id": cid, "title": title, "events": events,
            "related_to": list(related_to), "depends_on": list(depends_on)}


MAIL, INBOX, POST = ("mail.harbour-sync.example.com", "inbox.harbour-sync.example.com",
                     "post.harbour-sync.example.com")
OUTAGE = {"contacts": ["503", "503", "503"]}
DEAL_OUTAGE = {"deals": ["503", "502", "503"]}


def hr(num, email, first, last, items, created, **kw):
    """Customer in Croatia, defaults for the address."""
    base = dict(phone="+385 91 234 5678", address_1="Obala Lazareta 14", city="Split",
                postcode="21000", country="HR")
    base.update(kw)
    return order(num, email, first, last, items, created, **base)


# ---------------------------------------------------------------------------
# The 76 visible cases (BLUEPRINT.md section 5; gate v4 added U07, A07, A08, T07, T08, R06-R09)
# ---------------------------------------------------------------------------
def visible_case_defs():
    C = []

    # N: clean order, new customer --------------------------------------
    C.append(case("N01", "Clean paid order, new customer, card payment", [
        wh(hr(41001, "marta.horvat@" + MAIL, "Marta", "Horvat", [("city500", 1)],
              "2026-10-05T07:12:44", customer_id=311), "created")]))
    C.append(case("N02", "Clean order waiting for bank transfer (pending)", [
        wh(order(41002, "tomislav.kralj@" + INBOX, "Tomislav", "Kralj", [("helmet", 1), ("lock", 1)],
                 "2026-10-05T08:30:10", status="pending", payment="bacs", phone="+385 98 765 4321",
                 address_1="Vukovarska 58", city="Zagreb", postcode="10000", country="HR",
                 customer_id=312), "created")]))
    C.append(case("N03", "Completed order for a company customer, two items", [
        wh(order(41003, "eva.lindqvist@portwell-kayak.harbour-sync.example.com", "Eva", "Lindqvist",
                 [("cargo", 1), ("seat", 2)], "2026-10-05T09:01:00", modified="2026-10-05T15:40:12",
                 status="completed", company="Portwell Kayak Club", phone="+353 21 555 0170",
                 address_1="Harbour Road 40", city="Portwell", postcode="P17 W2X4", country="IE",
                 customer_id=313), "created")]))
    C.append(case("N04", "Order on hold, paid in GBP, UK customer", [
        wh(order(41004, "oliver.bennett@" + POST, "Oliver", "Bennett", [("battery", 1)],
                 "2026-10-05T10:15:33", status="on-hold", currency="GBP", payment="bacs",
                 vat=False, phone="+44 7700 900123", address_1="12 Redcliffe Way",
                 city="Bristol", postcode="BS1 4DJ", country="GB", customer_id=314), "created")]))
    C.append(case("N05", "Paid order in USD with a coupon, US customer", [
        wh(order(41005, "grace.miller@" + MAIL, "Grace", "Miller", [("trek", 1)],
                 "2026-10-05T16:45:02", currency="USD", coupon=("spring50", D("50.00")),
                 phone="(503) 555-0148", address_1="815 SW Alder St", city="Portland",
                 state="OR", postcode="97205", country="US", customer_id=315), "created")]))

    # M: messy but valid -------------------------------------------------
    C.append(case("M01", "E-mail in upper case with spaces around it, names with spaces", [
        wh(hr(41101, "  Luka.Babic@Mail.Harbour-Sync.Example.com  ", " Luka", "Babić  ",
              [("battery", 1)], "2026-10-06T07:02:19"), "created")]))
    C.append(case("M02", "Double spaces and non-breaking spaces in names, newline after city", [
        wh(hr(41102, "anamarija.kovac@" + INBOX, "Ana  Marija", "Kovač  Horvat ",
              [("city500", 1)], "2026-10-06T07:40:00", address_1="Ilica  22",
              city="Zagreb\n", postcode="10000", company="\t"), "created")]))
    C.append(case("M03", "Accented names, city and company", [
        wh(order(41103, "zoe.angstrom@" + POST, "Zoë", "Ångström-Weiß", [("trek", 1)],
                 "2026-10-06T08:12:45", company="Café Ålö AB", phone="+46 31 555 0192",
                 address_1="Östra Hamngatan 5", city="Göteborg", postcode="411 10",
                 country="SE"), "created")]))
    C.append(case("M04", "Name and address in Japanese script", [
        wh(order(41104, "misaki.tanaka@" + MAIL, "美咲", "田中", [("lights", 2), ("lock", 1)],
                 "2026-10-06T09:05:51", phone="+81 45-555-0123", address_1="中区山下町 1-2",
                 city="横浜市", state="JP14", postcode="231-0023", country="JP", vat=False,
                 currency="USD"), "created")]))
    C.append(case("M05", "Phone with brackets and dashes, plus sign in e-mail, spaces in postcode", [
        wh(hr(41105, "ivan.peric+bike@" + INBOX, "Ivan", "Perić", [("service", 1), ("tube", 2)],
              "2026-10-06T10:20:03", phone="+385 (0)91 234-5678 ", postcode=" 10000 ",
              address_1="Savska cesta 41", city="Zagreb"), "created")]))
    C.append(case("M06", "Optional fields empty: phone, company, postcode, country", [
        wh(order(41106, "sara.vidovic@" + POST, "Sara", "Vidović", [("pannier", 1), ("lock", 1)],
                 "2026-10-06T11:11:11", address_1="Put Firula 8", city="Split"), "created")]))
    C.append(case("M07", "Guest checkout with last name only, cash on delivery", [
        wh(order(41107, "osullivan.family@" + MAIL, "", "O'Sullivan", [("seat", 1)],
                 "2026-10-06T12:30:40", payment="cod", phone="087 555 0133",
                 address_1="3 Quay Street", city="Portwell", postcode="P17 K8D2",
                 country="IE"), "created")]))
    m08 = order(41108, "lena.huber@" + INBOX, "Lena", "Huber", [("refurb", 1)],
                "2026-10-06T13:44:09", phone="+43 1 555 0177", address_1="Seestraße 12",
                address_2="Apt 4B", city="Wien", postcode="1010", country="AT")
    C.append(case("M08", "Total written as 1250.5, second address line", [
        wh(edit(m08, total="1250.5"), "created")]))

    # E: existing customer ------------------------------------------------
    e01a = hr(41201, "petra.novak@" + MAIL, "Petra", "Novak", [("city500", 1)], "2026-10-07T07:00:00")
    e01b = hr(41202, "petra.novak@" + MAIL, "Petra", "Novak", [("helmet", 1), ("lights", 1)],
              "2026-10-10T07:30:00")
    C.append(case("E01", "Second order from the same customer", [
        wh(e01a, "created"), wh(e01b, "created")]))
    e02a = hr(41203, "nina.peric@" + POST, "Nina", "Perić", [("battery", 1)], "2026-10-07T08:00:00",
              phone="+385 95 555 0101")
    e02b = hr(41204, "Nina.Peric@Post.Harbour-Sync.Example.com", "Nina", "Perić", [("service", 1)],
              "2026-10-09T08:00:00", phone="+385 95 555 0101")
    C.append(case("E02", "Same e-mail written in another letter case", [
        wh(e02a, "created"), wh(e02b, "created")]))
    e03a = order(41205, "maja.zupan@" + INBOX, "Maja", "Zupan", [("trek", 1)], "2026-10-07T09:00:00",
                 phone="+386 41 555 012", address_1="Trubarjeva 7", city="Ljubljana",
                 postcode="1000", country="SI")
    e03b = edit(order(41206, "maja.zupan@" + INBOX, "Maja", "Zupan", [("lock", 1)],
                      "2026-10-11T09:00:00", address_1="Trubarjeva 7", city="Ljubljana",
                      postcode="1000", country="SI"), **{"billing.phone": ""})
    C.append(case("E03", "Second order without a phone keeps the stored phone", [
        wh(e03a, "created"), wh(e03b, "created")]))
    e04a = hr(41207, "karlo.mlinar@" + MAIL, "Karlo", "Mlinar", [("cargo", 1)], "2026-10-07T10:00:00",
              phone="+385 91 555 0102", address_1="Ulica Kralja Zvonimira 3", city="Rijeka",
              postcode="51000")
    e04b = hr(41208, "karlo.mlinar@" + MAIL, "Karlo", "Mlinar", [("pannier", 2)], "2026-10-12T10:00:00",
              phone="+385 99 555 0199", address_1="Korzo 11", city="Rijeka", postcode="51000")
    C.append(case("E04", "Second order with a new phone and address updates the contact", [
        wh(e04a, "created"), wh(e04b, "created")]))
    e05a = order(41209, "jonas.weber@" + INBOX, "Jonas", "Weber", [("cargo", 1)], "2026-10-07T11:00:00",
                 company="Weber Kurierdienst", phone="+49 30 5550 1234", address_1="Torstraße 101",
                 city="Berlin", postcode="10119", country="DE")
    e05b = order(41210, "  jonas.weber@" + INBOX + " ", "Jonas", "Weber", [("battery", 2)],
                 "2026-10-12T11:00:00", phone="+49 30 5550 1234", address_1="Torstraße 101",
                 city="Berlin", postcode="10119", country="DE")
    C.append(case("E05", "Second order without company, e-mail with spaces, keeps the company", [
        wh(e05a, "created"), wh(e05b, "created")]))
    C.append(case("E06", "Returning customer from case N01 places a new order without phone", [
        wh(edit(hr(41211, "marta.horvat@" + MAIL, "Marta", "Horvat", [("battery", 1)],
                   "2026-10-13T12:00:00", customer_id=311), **{"billing.phone": ""}), "created")],
        related_to=["N01"], depends_on=["N01"]))

    # U: order updates ----------------------------------------------------
    u01 = order(41301, "dino.radic@" + POST, "Dino", "Radić", [("city500", 1)], "2026-10-08T07:00:00",
                status="pending", payment="bacs", phone="+385 92 555 0103", address_1="Ulica grada Vukovara 9",
                city="Osijek", postcode="31000", country="HR")
    u01b = edit(u01, status="processing", date_modified_gmt="2026-10-08T09:00:00",
                date_modified="2026-10-08T11:00:00", date_paid_gmt="2026-10-08T09:00:00",
                date_paid="2026-10-08T11:00:00")
    C.append(case("U01", "Status change from pending to processing after payment", [
        wh(u01, "created"), upd(u01b, "updated")]))
    u02 = order(41302, "ella.fischer@" + MAIL, "Ella", "Fischer", [("helmet", 2), ("lock", 1)],
                "2026-10-08T08:00:00", modified="2026-10-09T10:00:00", status="completed",
                phone="+49 89 5550 4321", address_1="Leopoldstraße 20", city="München",
                postcode="80802", country="DE")
    u02b = order(41302, "ella.fischer@" + MAIL, "Ella", "Fischer", [("helmet", 2), ("lock", 1)],
                 "2026-10-08T08:00:00", modified="2026-10-14T09:30:00", status="refunded",
                 phone="+49 89 5550 4321", address_1="Leopoldstraße 20", city="München",
                 postcode="80802", country="DE", refund_reason="Customer returned both helmets")
    C.append(case("U02", "Full refund: stage changes, amount stays the order total", [
        wh(u02, "created"), upd(u02b, "updated")]))
    u03 = hr(41303, "filip.basic@" + INBOX, "Filip", "Bašić", [("city500", 1)], "2026-10-08T09:00:00")
    u03b = hr(41303, "filip.basic@" + INBOX, "Filip", "Bašić", [("city500", 1), ("helmet", 1)],
              "2026-10-08T09:00:00", modified="2026-10-08T14:20:00")
    C.append(case("U03", "Shop staff add an item: total changes from 2490.00 to 2579.00", [
        wh(u03, "created"), upd(u03b, "updated")]))
    u04 = hr(41304, "iva.matic@" + POST, "Iva", "Matić", [("trek", 1)], "2026-10-08T10:00:00",
             status="pending", payment="bacs")
    u04_v2 = edit(u04, status="on-hold", date_modified_gmt="2026-10-08T11:00:00",
                  date_modified="2026-10-08T13:00:00")
    u04_v3 = edit(u04, status="completed", date_modified_gmt="2026-10-08T12:00:00",
                  date_modified="2026-10-08T14:00:00", date_completed_gmt="2026-10-08T12:00:00",
                  date_completed="2026-10-08T14:00:00")
    C.append(case("U04", "Older update (on-hold) arrives after the newer one (completed)", [
        wh(u04, "created"), upd(u04_v3, "updated"), upd(u04_v2, "skipped_older")]))
    u05 = hr(41305, "goran.loncar@" + MAIL, "Goran", "Lončar", [("cargo", 1)], "2026-10-08T11:00:00",
             company="Lončar Dostava d.o.o.", phone="+385 91 555 0105")
    u05b = edit(u05, status="completed", date_modified_gmt="2026-10-10T08:00:00",
                date_modified="2026-10-10T10:00:00", date_completed_gmt="2026-10-10T08:00:00",
                date_completed="2026-10-10T10:00:00", **{"billing.phone": "", "billing.company": ""})
    C.append(case("U05", "Update with empty phone and company keeps both stored values", [
        wh(u05, "created"), upd(u05b, "updated")]))
    u06_v1 = hr(41306, "tea.kos@" + INBOX, "Tea", "Kos", [("lights", 1), ("tube", 1)],
                "2026-10-08T12:00:00", modified="2026-10-08T12:00:03", status="pending", payment="bacs")
    u06_v2 = edit(u06_v1, status="on-hold", date_modified_gmt="2026-10-08T12:00:09",
                  date_modified="2026-10-08T14:00:09")
    C.append(case("U06", "Update event arrives before the create event", [
        upd(u06_v2, "created"), wh(u06_v1, "skipped_older")]))
    u07 = hr(41307, "nikola.rajic@" + POST, "Nikola", "Rajić", [("helmet", 1)], "2026-10-08T13:00:00")
    u07b = edit(u07, date_modified_gmt="2026-10-08T15:00:00", date_modified="2026-10-08T17:00:00",
                **{"billing.email": "nikola.rajic@" + MAIL})
    C.append(case("U07", "Customer corrects the e-mail in an update: deal linked to both contacts", [
        wh(u07, "created"), upd(u07b, "updated")]))

    # D: duplicate orders --------------------------------------------------
    d01 = hr(41401, "marko.juric@" + MAIL, "Marko", "Jurić", [("battery", 1)], "2026-10-09T07:00:00")
    C.append(case("D01", "Same event delivered twice", [
        wh(d01, "created"), wh(d01, "skipped_duplicate")]))
    d02 = hr(41402, "lucija.bozic@" + POST, "Lucija", "Božić", [("city500", 1)], "2026-10-09T08:00:00")
    ANY_SYNC = ["created", "updated", "skipped_duplicate"]
    C.append(case("D02", "Same event sent twice at the same moment", [
        wh(d02, ANY_SYNC, parallel="p1"), wh(d02, ANY_SYNC, parallel="p1")]))
    d03 = hr(41403, "ante.vukovic@" + INBOX, "Ante", "Vuković", [("trek", 1)], "2026-10-09T09:00:00",
             status="on-hold", payment="bacs")
    d03b = edit(d03, status="processing", date_modified_gmt="2026-10-09T13:00:00",
                date_modified="2026-10-09T15:00:00")
    C.append(case("D03", "Update delivered again after it was synced", [
        wh(d03, "created"), upd(d03b, "updated"), upd(d03b, "skipped_duplicate")]))
    d04 = hr(41404, "klara.saric@" + MAIL, "Klara", "Šarić", [("pannier", 1), ("lights", 1)],
             "2026-10-09T10:00:00")
    C.append(case("D04", "Create and update events for the same order version", [
        wh(d04, "created"), upd(d04, "skipped_duplicate")]))
    d05 = hr(41405, "mateo.kovacevic@" + POST, "Mateo", "Kovačević", [("seat", 1)],
             "2026-10-09T11:00:00", phone="+385 91 555 0106")
    d05b = edit(d05, **{"billing.phone": "+385 91 555 0160"})
    C.append(case("D05", "Same version time but a different phone: not guessed, needs attention", [
        wh(d05, "created"), upd(d05b, "needs_attention", "same_version_different_data")]))
    d06 = hr(41406, "rita.blazevic@" + INBOX, "Rita", "Blažević", [("cargo", 1)], "2026-10-09T12:00:00",
             status="on-hold", payment="bacs")
    d06b = edit(d06, status="processing", date_modified_gmt="2026-10-09T16:00:00",
                date_modified="2026-10-09T18:00:00")
    UPD_OR_DUP = ["updated", "skipped_duplicate"]
    C.append(case("D06", "Three copies of the same update at the same moment", [
        wh(d06, "created"), upd(d06b, UPD_OR_DUP, parallel="p1"),
        upd(d06b, UPD_OR_DUP, parallel="p1"), upd(d06b, UPD_OR_DUP, parallel="p1")]))

    # F: missing required field --------------------------------------------
    def f(num, email, created, **changes):
        return edit(hr(num, email, "Josip", "Barić", [("helmet", 1)], created), **changes)
    C.append(case("F01", "Order number missing (empty)", [
        wh(f(41501, "josip.baric@" + MAIL, "2026-10-10T07:00:00", number=""), "needs_attention",
           "missing_order_number")]))
    C.append(case("F02", "E-mail missing (empty)", [
        wh(f(41502, "", "2026-10-10T07:10:00"), "needs_attention", "missing_email")]))
    C.append(case("F03", "Both name fields empty or spaces only", [
        wh(f(41503, "no.name@" + POST, "2026-10-10T07:20:00",
             **{"billing.first_name": "", "billing.last_name": "   "}), "needs_attention",
           "missing_name")]))
    C.append(case("F04", "Total missing (null)", [
        wh(f(41504, "hana.tomic@" + INBOX, "2026-10-10T07:30:00", total=None), "needs_attention",
           "missing_total")]))
    C.append(case("F05", "Currency key missing", [
        wh(f(41505, "bruno.pavlovic@" + MAIL, "2026-10-10T07:40:00", currency=DROP),
           "needs_attention", "missing_currency")]))
    C.append(case("F06", "Status missing (null)", [
        wh(f(41506, "lea.grgic@" + POST, "2026-10-10T07:50:00", status=None), "needs_attention",
           "missing_status")]))
    C.append(case("F07", "Last-modified date missing (null)", [
        wh(f(41507, "roko.markovic@" + INBOX, "2026-10-10T08:00:00", date_modified_gmt=None,
             date_modified=None), "needs_attention", "missing_date_modified")]))

    # V: invalid format -----------------------------------------------------
    def v(num, email, items, created, **changes):
        return edit(hr(num, email, "Katarina", "Jurić", items, created), **changes)
    C.append(case("V01", "E-mail with a comma instead of a dot", [
        wh(v(41601, "katarina.juric@mail,harbour-sync.example.com", [("lock", 1)], "2026-10-11T07:00:00"),
           "needs_attention", "invalid_email")]))
    C.append(case("V02", "Negative total", [
        wh(v(41602, "toni.santic@" + POST, [("helmet", 1)], "2026-10-11T07:10:00", total="-89.00"),
           "needs_attention", "invalid_total")]))
    v03 = hr(41603, "mia.lovric@" + INBOX, "Mia", "Lovrić", [("tube", 1)], "2026-10-11T07:20:00")
    C.append(case("V03", "Total written with a decimal comma (12,50)", [
        wh(edit(v03, total=de_amount(D(v03["total"]))), "needs_attention", "invalid_total")]))
    v04 = hr(41604, "stjepan.knezevic@" + MAIL, "Stjepan", "Knežević", [("city500", 1)],
             "2026-10-11T07:30:00")
    v04b = hr(41604, "stjepan.knezevic@" + MAIL, "Stjepan", "Knežević",
              [("battery", 1), ("seat", 2), ("pannier", 1), ("service", 1)],
              "2026-10-11T07:30:00", modified="2026-10-11T10:05:00")
    v04b = edit(v04b, total=de_amount(D(v04b["total"])))
    C.append(case("V04", "Update with total 1.187,00 (German style) keeps the stored deal", [
        wh(v04, "created"), upd(v04b, "needs_attention", "invalid_total")]))
    C.append(case("V05", "Old currency code HRK (not in the allowed list)", [
        wh(v(41605, "zvonimir.ilic@" + POST, [("battery", 1)], "2026-10-11T07:40:00", currency="HRK"),
           "needs_attention", "invalid_currency")]))
    C.append(case("V06", "Custom plugin status 'shipped' (not a known status)", [
        wh(v(41606, "dora.mandic@" + INBOX, [("lights", 1)], "2026-10-11T07:50:00", status="shipped"),
           "needs_attention", "invalid_status")]))
    C.append(case("V07", "Order date that does not exist (31 September)", [
        wh(v(41607, "nikola.bilic@" + MAIL, [("lock", 2)], "2026-10-11T08:00:00",
             date_created_gmt="2026-09-31T08:00:00", date_created="2026-09-31T10:00:00"),
           "needs_attention", "invalid_date_created")]))

    # A: entry -----------------------------------------------------------------
    def a(num, email, created):
        return hr(num, email, "Petar", "Šimić", [("city500", 1)], created)
    C.append(case("A01", "No signature header", [
        wh(a(41701, "petar.simic@" + MAIL, "2026-10-12T07:00:00"), "rejected", "no_signature",
           sign="none")]))
    C.append(case("A02", "Signature made with another secret", [
        wh(a(41702, "ema.radman@" + POST, "2026-10-12T07:10:00"), "rejected", "bad_signature",
           sign="wrong_secret")]))
    C.append(case("A03", "Body changed after signing (total 2490.00 to 24.90)", [
        wh(a(41703, "luka.galic@" + INBOX, "2026-10-12T07:20:00"), "rejected", "bad_signature",
           sign="tampered", tamper={"find": '"total":"2490.00"', "replace": '"total":"24.90"'})]))
    C.append(case("A04", "WooCommerce ping when the webhook is saved", [
        wh(None, "ignored", "ping", topic=None, sign="none", body="webhook_id=14",
           content_type=None)]))
    a05 = a(41705, "vesna.kralj@" + MAIL, "2026-10-12T07:40:00")
    C.append(case("A05", "Order deleted in the shop: event ignored, deal stays", [
        wh(a05, "created"),
        wh(None, "ignored", "other_topic", topic="order.deleted", body=php_json({"id": 41705}))]))
    C.append(case("A06", "Signed body that is cut off (not valid JSON)", [
        wh(None, "needs_attention", "not_json",
           body=php_json(a(41706, "boris.lukic@" + POST, "2026-10-12T07:50:00"))[:700])]))
    C.append(case("A07", "Signed empty body (not valid JSON)", [
        wh(None, "needs_attention", "not_json", body="")]))
    C.append(case("A08", "Empty body without a signature", [
        wh(None, "rejected", "no_signature", sign="none", body="")]))

    # T: HubSpot errors (simulated through the fault proxy) ----------------------
    def t(num, email, created):
        return hr(num, email, "Martina", "Pavić", [("trek", 1)], created)
    C.append(case("T01", "HubSpot rate limit (429, wait 2 s) then OK", [
        wh(t(41801, "martina.pavic@" + MAIL, "2026-10-13T07:00:00"), "created",
           faults={"contacts": ["429:2", "pass"]})]))
    C.append(case("T02", "HubSpot server error (503) on the deal, then OK", [
        wh(t(41802, "ivo.brkic@" + POST, "2026-10-13T07:10:00"), "created",
           faults={"deals": ["503", "pass"]})]))
    C.append(case("T03", "Deal write reaches HubSpot but the answer times out, retry", [
        wh(t(41803, "sanja.vlasic@" + INBOX, "2026-10-13T07:20:00"), "created",
           faults={"deals": ["timeout_after_forward", "pass"]})]))
    C.append(case("T04", "HubSpot server errors every time: retries used up", [
        wh(t(41804, "damir.horvatic@" + MAIL, "2026-10-13T07:30:00"), "needs_attention",
           "crm_retry_exhausted", faults=OUTAGE)]))
    C.append(case("T05", "HubSpot says 401 (key problem): no retry", [
        wh(t(41805, "paula.zec@" + POST, "2026-10-13T07:40:00"), "needs_attention",
           "crm_auth_error", faults={"contacts": ["401"]})]))
    C.append(case("T06", "HubSpot says 400 on the deal: no retry, contact already written", [
        wh(t(41806, "hrvoje.sertic@" + INBOX, "2026-10-13T07:50:00"), "needs_attention",
           "crm_bad_request", faults={"deals": ["400"]})]))
    C.append(case("T07", "Contact connection closed then OK, deal 403: no retry", [
        wh(t(41807, "kristina.mlinar@" + MAIL, "2026-10-13T08:00:00"), "needs_attention",
           "crm_auth_error", faults={"contacts": ["close", "pass"], "deals": ["403"]})]))
    C.append(case("T08", "Contact answer times out after HubSpot saved it, deal 404: no retry", [
        wh(t(41808, "zoran.bilic@" + POST, "2026-10-13T08:10:00"), "needs_attention",
           "crm_bad_request", faults={"contacts": ["timeout_after_forward", "pass"], "deals": ["404"]})]))

    # R: replay and fix at source ---------------------------------------------
    def r(num, email, created):
        return hr(num, email, "Lana", "Perković", [("cargo", 1)], created)
    C.append(case("R01", "Replay after a HubSpot outage", [
        wh(r(41901, "lana.perkovic@" + MAIL, "2026-10-14T07:00:00"), "needs_attention",
           "crm_retry_exhausted", faults=OUTAGE),
        replay(1, "created")]))
    C.append(case("R02", "Replay pressed twice", [
        wh(r(41902, "josipa.raic@" + POST, "2026-10-14T07:10:00"), "needs_attention",
           "crm_retry_exhausted", faults=DEAL_OUTAGE),
        replay(1, "created"), replay(1, "replay_refused", "row_closed")]))
    r03 = r(41903, "emil.tadic@" + INBOX, "2026-10-14T07:20:00")
    C.append(case("R03", "Shop resends the order after an outage, then replay of the closed row", [
        wh(r03, "needs_attention", "crm_retry_exhausted", faults=DEAL_OUTAGE),
        wh(r03, "created"), replay(1, "replay_refused", "row_closed")]))
    r04 = r(41904, "", "2026-10-14T07:30:00")
    r04b = edit(r04, date_modified_gmt="2026-10-14T09:00:00", date_modified="2026-10-14T11:00:00",
                **{"billing.email": "vlatka.jukic@" + MAIL})
    C.append(case("R04", "Order fixed in the shop (e-mail added) closes the row by itself", [
        wh(r04, "needs_attention", "missing_email"), upd(r04b, "created")]))
    C.append(case("R05", "Replay during the outage fails, second replay works", [
        wh(r(41905, "denis.bosnjak@" + POST, "2026-10-14T07:40:00"), "needs_attention",
           "crm_retry_exhausted", faults=OUTAGE),
        replay(1, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        replay(1, "created")]))
    # two open rows for one order (H-R02, gate v4): every open row the step may close must close
    r06 = r(41906, "mia.grgic@" + MAIL, "2026-10-14T07:50:00")
    C.append(case("R06", "Two open rows for one order, the shop resends: both close by sync", [
        wh(r06, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        wh(r06, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        wh(r06, "created")]))
    r07 = r(41907, "karlo.vidovic@" + POST, "2026-10-14T08:00:00")
    r07b = edit(r07, status="completed", date_modified_gmt="2026-10-14T10:00:00",
                date_modified="2026-10-14T12:00:00", date_completed_gmt="2026-10-14T10:00:00",
                date_completed="2026-10-14T12:00:00")
    C.append(case("R07", "Two open rows, replay of the second: it closes by replay, the first by sync", [
        wh(r07, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        upd(r07b, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        replay(2, "created")]))
    r08 = r(41908, "lucija.bozic@" + INBOX, "2026-10-14T08:10:00")
    r08_v2 = edit(r08, status="on-hold", date_modified_gmt="2026-10-14T09:00:00",
                  date_modified="2026-10-14T11:00:00")
    r08_v3 = edit(r08, status="completed", date_modified_gmt="2026-10-14T10:00:00",
                  date_modified="2026-10-14T12:00:00", date_completed_gmt="2026-10-14T10:00:00",
                  date_completed="2026-10-14T12:00:00")
    C.append(case("R08", "Two open rows, the older version is resent first: only its row closes", [
        upd(r08_v3, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        upd(r08_v2, "needs_attention", "crm_retry_exhausted", faults=OUTAGE),
        upd(r08_v2, "created"), upd(r08_v3, "updated")]))
    C.append(case("R09", "Replay of a step that opened no row", [
        wh(r(41909, "dora.matkovic@" + MAIL, "2026-10-14T08:20:00"), "created"),
        replay(1, "replay_refused", "row_not_found")]))

    # S: alerts and summary ------------------------------------------------------
    s01 = hr(42001, "kreso.barisic@" + MAIL, "Krešimir", "Barišić", [("trek", 1)],
             "2026-10-15T07:00:00", status="on-hold", payment="bacs")
    s01b = edit(s01, status="processing", date_modified_gmt="2026-10-15T09:00:00",
                date_modified="2026-10-15T11:00:00")
    s01x = hr(42002, "", "Tin", "Rukavina", [("lock", 1)], "2026-10-15T07:30:00")
    C.append(case("S01", "Summary counts match the log", [
        wh(s01, "created"), upd(s01b, "updated"), upd(s01b, "skipped_duplicate"),
        wh(s01, "skipped_older"), wh(s01x, "needs_attention", "missing_email"), summary()]))

    def bad(num, local, reason_change, created):
        return edit(hr(num, local + "@" + POST, "Mirna", "Topić", [("lights", 1)], created),
                    **reason_change)
    six = [
        (42011, "mirna.topic", {"billing.email": ""}, "missing_email"),
        (42012, "ines.puljic", {"total": "59,90"}, "invalid_total"),
        (42013, "toma.jelic", {"currency": "eur"}, "invalid_currency"),
        (42014, "vid.majic", {"status": "awaiting-shipment"}, "invalid_status"),
        (42015, "anja.krstic", {"billing.first_name": "", "billing.last_name": ""}, "missing_name"),
        (42016, "leon.pejic", {"billing.email": "leon.pejic@post"}, "invalid_email"),
    ]
    C.append(case("S02", "Six failed orders in the window: summary and the over-5 alert", [
        wh(bad(n, loc, ch, "2026-10-15T08:%02d:00" % i), "needs_attention", rs)
        for i, (n, loc, ch, rs) in enumerate(six)] + [summary()]))
    five = [
        (42021, "ivana.rogic", {"total": None}, "missing_total"),
        (42022, "davor.lisac", {"currency": "CHF"}, "invalid_currency"),
        (42023, "maja.sokol", {"date_modified_gmt": "2026-10-15 09:00:00"}, "invalid_date_modified"),
        (42024, "luka.zoric", {"total": "1,234.50"}, "invalid_total"),
        (42025, "nora.vukic", {"billing.email": "nora.vukic@@post.harbour-sync.example.com"},
         "invalid_email"),
    ]
    C.append(case("S03", "Exactly five failed orders: summary, no over-5 alert", [
        wh(bad(n, loc, ch, "2026-10-15T09:%02d:00" % i), "needs_attention", rs)
        for i, (n, loc, ch, rs) in enumerate(five)] + [summary()]))
    C.append(case("S04", "Forced crash in an automatic run alerts", [
        wh(hr(42031, "fran.lucic@" + MAIL, "Fran", "Lučić", [("battery", 1)], "2026-10-15T10:00:00"),
           "crash", crash=True)]))
    C.append(case("S05", "Summary with no events in the window still posts, all zero", [summary()]))
    return C


def build_visible():
    """Hand-written cases + expectations filled by the model, checked against the hand values."""
    defs = visible_case_defs()
    model = Model()
    cases, errs = [], []
    for d in defs:
        kind = d["id"][0]
        events = []
        for i, ev in enumerate(d["events"], 1):
            e = {"step": i}
            e.update({k: v for k, v in ev.items() if not k.startswith("_")})
            if e["type"] == "webhook":
                e["delivery_id"] = h("%s:%d" % (d["id"], i)) if e["topic"] else None
                e["webhook_id"] = WEBHOOK_IDS.get(e["topic"])
            e["_result"] = ev["_result"] if isinstance(ev["_result"], list) else [ev["_result"]]
            e["_reason"] = ev["_reason"]
            events.append(e)
        c = {"id": d["id"], "kind": kind, "title": d["title"],
             "related_to": d["related_to"], "depends_on": d["depends_on"],
             "hard_rules": HARD_RULES_BY_KIND[kind],
             "simulated": any(e.get("faults") or e.get("force_crash") for e in events),
             "gated": True, "events": events}
        per_event, final = model.run_case(c)
        for e, out in zip(events, per_event):
            hand_result, hand_reason = e.pop("_result"), e.pop("_reason")
            if out["result"] is not None and out["result"] not in hand_result:
                errs.append("%s step %d: hand-written result %s, rules give %s"
                            % (c["id"], e["step"], hand_result, out["result"]))
            got_reason = out["reasons"][0] if out["reasons"] else None
            if got_reason != hand_reason:
                errs.append("%s step %d: hand-written reason %s, rules give %s"
                            % (c["id"], e["step"], hand_reason, got_reason))
            e["expect"] = model_expect(out, e, hand_result)
        c["expected_final"] = final
        cases.append(c)
    if errs:
        raise CaseError("\n".join(errs))
    return cases


def serialize(cases, set_name):
    doc = {"format_version": FORMAT_VERSION, "set": set_name,
           "rules": "tests/CASES.md", "generator": "tests/make_cases.py",
           "case_count": len(cases), "cases": cases}
    return json.dumps(doc, ensure_ascii=True, indent=1) + "\n"


def check_cases_md(cases):
    try:
        with open(CASES_MD, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        raise CaseError("tests/CASES.md not found")
    missing = [c["id"] for c in cases if "| %s | %s |" % (c["id"], c["title"]) not in text]
    if missing:
        raise CaseError("CASES.md section 7 does not list these cases with their titles: "
                        + ", ".join(missing))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", metavar="FILE", help="check a case file, write nothing")
    ap.add_argument("--set", choices=sorted(SETS), default="visible")
    args = ap.parse_args(argv)
    try:
        if args.check:
            with open(args.check, encoding="utf-8") as fh:
                raw = fh.read()
            doc = json.loads(raw)
            check_doc(doc, args.set)
            print("OK %s: %d cases, SHA-256 %s" % (args.check, len(doc["cases"]),
                                                   hashlib.sha256(raw.encode("utf-8")).hexdigest()))
            return 0
        cases = build_visible()
        text = serialize(cases, "visible")
        check_doc(json.loads(text), "visible")
        check_cases_md(cases)
    except CaseError as e:
        print("test set error, nothing written:\n" + str(e))
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    counts = {}
    for c in cases:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    print("OK %d visible cases (%s), %d events" % (
        len(cases), " ".join("%s%d" % (k, counts[k]) for k in KIND_COUNTS),
        sum(len(c["events"]) for c in cases)))
    print("wrote tests/cases/visible.json SHA-256 %s" % hashlib.sha256(text.encode("utf-8")).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
