"""P2 first-hour probe (BLUEPRINT section 6, P2 row).

Runs every P2 check against the HubSpot "Portfolio Demo" account and the
shared local n8n, prints one PASS/FAIL line per check and exits 0 only when
every check passes.

    python tools/probe.py                  # all checks
    python tools/probe.py --only hubspot   # HubSpot checks only (no n8n use)
    python tools/probe.py --only n8n       # n8n checks only

Secrets come from the git-ignored `.env` (HUBSPOT_TOKEN, N8N_URL,
N8N_API_KEY, Q129_WEBHOOK_SECRET) and are never printed.

Shared-account rules: HubSpot records only on probe.harbour-sync.example.com
with sync_source = harbour-demo-shop, deals only with shop_order_id starting
with P2PROBE; all of them are archived at the end. n8n: only workflows named
"Q129 Probe: ...", tag q129, table q129_probe_ledger, webhooks
/webhook/q129-probe-*; unpublished and archived (table deleted) at the end.
The 4 custom HubSpot properties stay: they are build setup, not probe data.
"""
import argparse
import base64
import hashlib
import hmac
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HS = "https://api.hubapi.com"
DOMAIN = "probe.harbour-sync.example.com"
SOURCE = "harbour-demo-shop"
ORDER_PREFIX = "P2PROBE"
RUN = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
N8N_PREFIX = "Q129 Probe: "
N8N_TAG = "q129"
LEDGER_TABLE = "q129_probe_ledger"
CRYPTO_CRED = "Crypto WooCommerce n8n-data-sync"
PAR_ROUNDS = 5
LEDGER_ROUNDS = 10

CUSTOM_PROPS = {
    ("deals", "shop_order_id"): {"label": "Shop order ID", "type": "string", "fieldType": "text",
                                 "groupName": "dealinformation", "hasUniqueValue": True},
    ("deals", "shop_modified_at"): {"label": "Shop modified at", "type": "datetime", "fieldType": "date",
                                    "groupName": "dealinformation"},
    ("deals", "shop_currency"): {"label": "Shop currency", "type": "string", "fieldType": "text",
                                 "groupName": "dealinformation"},
    ("contacts", "sync_source"): {"label": "Sync source", "type": "string", "fieldType": "text",
                                  "groupName": "contactinformation"},
}
CONTACT_PROPS = ["email", "firstname", "lastname", "phone", "company", "address", "city", "zip", "country",
                 "sync_source"]
DEAL_PROPS = ["shop_order_id", "dealname", "amount", "shop_currency", "deal_currency_code", "dealstage",
              "closedate", "shop_modified_at", "pipeline"]

results = []          # (check id, ok, detail)
created = {"contacts": set(), "deals": set()}


def load_env():
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.setdefault("N8N_URL", "http://localhost:5678")
    return env


ENV = load_env()


def record(check, ok, detail):
    results.append((check, ok, detail))
    print(("PASS " if ok else "FAIL ") + check + ": " + detail, flush=True)


# ---------------------------------------------------------------- HubSpot client

_pace_lock = threading.Lock()
_last_calls = []
rate_headers = {}


def _pace():
    # stay under the account's 10 calls per second (read from the headers in H-RATE)
    with _pace_lock:
        now = time.monotonic()
        while len(_last_calls) >= 6 and now - _last_calls[-6] < 1.0:
            time.sleep(1.0 - (now - _last_calls[-6]) + 0.01)
            now = time.monotonic()
        _last_calls.append(now)
        del _last_calls[:-10]


def hs(method, path, body=None, params=None, paced=True):
    """One HubSpot call. Returns (status, parsed body or text). Retries 429 only (probe machinery)."""
    url = HS + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(4):
        if paced:
            _pace()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + ENV["HUBSPOT_TOKEN"])
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                for k, v in resp.headers.items():
                    if "ratelimit" in k.lower():
                        rate_headers[k.lower()] = v
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < 3:
                time.sleep(min(float(e.headers.get("Retry-After") or 2), 10))
                continue
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw[:500]
    return 429, "rate limited"


def short(body):
    if isinstance(body, dict):
        return (body.get("category") or "") + " " + str(body.get("message") or "")[:220]
    return str(body)[:220]


def email(tag):
    return f"p2-{RUN}-{tag}@{DOMAIN}".lower()


def order(tag):
    return f"{ORDER_PREFIX}{RUN}{tag}"


def upsert(obj, id_prop, key, props, paced=True):
    s, b = hs("POST", f"/crm/v3/objects/{obj}/batch/upsert",
              {"inputs": [{"idProperty": id_prop, "id": key, "properties": props}]}, paced=paced)
    if s in (200, 201, 207) and isinstance(b, dict):
        for r in b.get("results", []):
            created[obj].add(r["id"])
    return s, b


def get_by(obj, id_prop, key, props):
    s, b = hs("GET", f"/crm/v3/objects/{obj}/{urllib.parse.quote(key, safe='')}",
              params={"idProperty": id_prop, "properties": ",".join(props)})
    return s, b


def search_count(obj, prop, value, wait_for=1, timeout=40):
    """H2-style count: search by property; waits until at least wait_for records show, then 5 s more."""
    body = {"filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
            "properties": [prop], "limit": 10}
    end = time.time() + timeout
    ids = []
    while time.time() < end:
        s, b = hs("POST", f"/crm/v3/objects/{obj}/search", body)
        ids = [r["id"] for r in (b or {}).get("results", [])] if s == 200 else []
        if len(ids) >= wait_for:
            break
        time.sleep(2)
    time.sleep(5)
    s, b = hs("POST", f"/crm/v3/objects/{obj}/search", body)
    ids = [r["id"] for r in (b or {}).get("results", [])] if s == 200 else ids
    for i in ids:
        created[obj].add(i)
    return ids


def same_second(a, b):
    def p(v):
        if v in (None, ""):
            return None
        if str(v).isdigit():
            return datetime.fromtimestamp(int(v) / 1000, timezone.utc).replace(microsecond=0)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)
    return p(a) == p(b)


# ---------------------------------------------------------------- HubSpot checks

def check_rate():
    s, b = hs("GET", "/account-info/v3/details")
    keys = ["x-hubspot-ratelimit-max", "x-hubspot-ratelimit-interval-milliseconds",
            "x-hubspot-ratelimit-secondly", "x-hubspot-ratelimit-daily"]
    have = {k.replace("x-hubspot-ratelimit-", ""): rate_headers.get(k) for k in keys}
    record("H-RATE rate limit read", s == 200 and all(have.values()),
           "max %(max)s per %(interval-milliseconds)s ms, %(secondly)s per second, %(daily)s per day" % have)
    return b if s == 200 else {}


def check_props():
    ok_all, notes = True, []
    for (obj, name), spec in CUSTOM_PROPS.items():
        s, b = hs("GET", f"/crm/v3/properties/{obj}/{name}")
        made = False
        if s == 404:
            s, b = hs("POST", f"/crm/v3/properties/{obj}", dict(spec, name=name))
            made = s in (200, 201)
            if not made:
                ok_all = False
                notes.append(f"{name}: create HTTP {s} {short(b)}")
                continue
        if s not in (200, 201):
            ok_all = False
            notes.append(f"{name}: read HTTP {s} {short(b)}")
            continue
        good = b.get("type") == spec["type"] and bool(b.get("hasUniqueValue")) == bool(spec.get("hasUniqueValue"))
        ok_all &= good
        notes.append(f"{obj}.{name} {b.get('type')}{' unique' if b.get('hasUniqueValue') else ''}"
                     f"{' (created)' if made else ' (exists)'}{'' if good else ' WRONG TYPE'}")
    record("H-PROPS 4 custom properties on the free account", ok_all, "; ".join(notes))
    return ok_all


def check_currency(account):
    company = account.get("companyCurrency")
    extra = account.get("additionalCurrencies") or []
    tried = {}
    for cur in ("EUR", "GBP", "USD"):
        s, b = upsert("deals", "shop_order_id", order(f"CUR{cur}"),
                      {"dealname": f"P2 probe currency {cur}", "amount": "1.00", "deal_currency_code": cur,
                       "pipeline": "default", "dealstage": "appointmentscheduled"})
        tried[cur] = s if s != 200 else 200
        if s != 200:
            tried[cur] = f"{s} {short(b).strip()[:80]}"
    one = not extra
    rt = []
    for cur in ("EUR", "GBP", "USD"):
        key = order(f"SC{cur}")
        s, b = upsert("deals", "shop_order_id", key, {"dealname": f"P2 probe shop_currency {cur}", "amount": "1.00",
                                                      "shop_currency": cur, "pipeline": "default",
                                                      "dealstage": "appointmentscheduled"})
        s2, b2 = get_by("deals", "shop_order_id", key, ["shop_currency"])
        rt.append(s == 200 and s2 == 200 and b2["properties"].get("shop_currency") == cur)
    all_codes_ok = all(v == 200 for v in tried.values())
    mapping = "deal_currency_code" if all_codes_ok else "shop_currency"
    ok = all(rt) if mapping == "shop_currency" else True
    record("H-CURRENCY account currency and mapping", ok,
           f"company currency {company}, additional {extra or 'none'} ({'one currency' if one else 'several'}); "
           f"deal_currency_code EUR/GBP/USD -> {tried}; mapping: currency -> {mapping}; "
           f"shop_currency round-trip EUR/GBP/USD {'exact' if all(rt) else 'DIFFERENT'}")
    return mapping


def check_upserts():
    key = order("UPS")
    s1, b1 = upsert("deals", "shop_order_id", key, {"dealname": "P2 probe upsert", "amount": "10.00",
                                                    "pipeline": "default", "dealstage": "appointmentscheduled"})
    s2, b2 = upsert("deals", "shop_order_id", key, {"amount": "11.00"})
    ids = {r["id"] for b in (b1, b2) if isinstance(b, dict) for r in b.get("results", [])}
    news = [r.get("new") for b in (b1, b2) if isinstance(b, dict) for r in b.get("results", [])]
    s3, b3 = get_by("deals", "shop_order_id", key, ["amount", "dealname"])
    ok = s1 == 200 and s2 == 200 and len(ids) == 1 and s3 == 200 and \
        Decimal(b3["properties"]["amount"]) == Decimal("11.00") and b3["properties"]["dealname"] == "P2 probe upsert"
    record("H-UPSERT-DEAL upsert by shop_order_id (unique)", ok,
           f"HTTP {s1}/{s2}, one deal id {sorted(ids)}, new flags {news}; second upsert updated amount, kept name"
           if ok else f"HTTP {s1}/{s2} ids {sorted(ids)} {short(b1)} {short(b2)}")
    em = email("ups")
    c1, d1 = upsert("contacts", "email", em, {"firstname": "Probe", "lastname": "Upsert", "sync_source": SOURCE})
    c2, d2 = upsert("contacts", "email", em, {"city": "Split"})
    cids = {r["id"] for b in (d1, d2) if isinstance(b, dict) for r in b.get("results", [])}
    c3, d3 = get_by("contacts", "email", em, ["firstname", "city"])
    ok = c1 == 200 and c2 == 200 and len(cids) == 1 and c3 == 200 and d3["properties"]["firstname"] == "Probe" \
        and d3["properties"]["city"] == "Split"
    record("H-UPSERT-CONTACT upsert by e-mail", ok,
           f"HTTP {c1}/{c2}, one contact id; second upsert added city, kept first name" if ok
           else f"HTTP {c1}/{c2} ids {sorted(cids)} {short(d1)} {short(d2)}")


def parallel_pair(fn):
    barrier = threading.Barrier(2)
    out = [None, None]

    def run(i):
        barrier.wait()
        out[i] = fn(i)
    ts = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def inner_status(s, b):
    if s == 207 and isinstance(b, dict):
        return "207[" + ",".join(str(e.get("status") or e.get("category")) for e in b.get("errors", [])) + "]"
    return str(s)


def check_parallel(obj):
    seen, bad = [], []
    for r in range(PAR_ROUNDS):
        if obj == "deals":
            key, id_prop = order(f"PAR{r}"), "shop_order_id"
            props = [{"dealname": f"P2 probe parallel {r}", "amount": "20.00", "pipeline": "default",
                      "dealstage": "appointmentscheduled"}] * 2
        else:
            key, id_prop = email(f"par{r}"), "email"
            props = [{"firstname": "Probe", "lastname": f"Parallel {r}", "sync_source": SOURCE}] * 2
        out = parallel_pair(lambda i: upsert(obj, id_prop, key, props[i], paced=False))
        round_codes = []
        for s, b in out:
            code = inner_status(s, b)
            if code != "200":
                # build rule (CASES 3.7): a 409 or a 207 with an error inside is retried once as the same upsert
                s2, b2 = upsert(obj, id_prop, key, props[0])
                code += f"->retry {s2}"
                if s2 != 200:
                    bad.append(f"round {r}: retry HTTP {s2} {short(b2)}")
            round_codes.append(code)
        ids = search_count(obj, id_prop, key)
        if len(ids) != 1:
            bad.append(f"round {r}: {len(ids)} records")
        seen.append("/".join(round_codes))
    name = "H-PAR-DEAL two parallel deal upserts, one order number" if obj == "deals" else \
        "H-PAR-CONTACT two parallel contact upserts, same new e-mail"
    record(name, not bad, f"{PAR_ROUNDS} rounds, answers {seen}; " +
           ("one record every round (search count after 5 s)" if not bad else "; ".join(bad)))


def check_archived_reuse():
    key = order("ARC")
    s1, b1 = upsert("deals", "shop_order_id", key, {"dealname": "P2 probe archive", "amount": "30.00",
                                                    "pipeline": "default", "dealstage": "appointmentscheduled"})
    old = b1["results"][0]["id"] if s1 == 200 else None
    sd, _ = hs("DELETE", f"/crm/v3/objects/deals/{old}") if old else (0, None)
    time.sleep(3)
    s2, b2 = upsert("deals", "shop_order_id", key, {"dealname": "P2 probe archive again", "amount": "31.00",
                                                    "pipeline": "default", "dealstage": "appointmentscheduled"})
    new = b2["results"][0]["id"] if s2 == 200 else None
    s3, b3 = get_by("deals", "shop_order_id", key, ["dealname", "amount"])
    ok = s1 == 200 and sd == 204 and s2 == 200 and new and new != old and s3 == 200 and \
        b3["id"] == new and b3["properties"]["dealname"] == "P2 probe archive again"
    record("H-ARCH-DEAL archived deal's order number used again", ok,
           f"create {s1}, archive {sd}, upsert again {s2}: " +
           (f"new deal {new} (old {old} stays archived)" if ok else f"{short(b2)}; read {s3} {short(b3)}"))
    em = email("arc")
    c1, d1 = upsert("contacts", "email", em, {"firstname": "Probe", "lastname": "Archive", "sync_source": SOURCE})
    cold = d1["results"][0]["id"] if c1 == 200 else None
    cd, _ = hs("DELETE", f"/crm/v3/objects/contacts/{cold}") if cold else (0, None)
    time.sleep(3)
    c2, d2 = upsert("contacts", "email", em, {"firstname": "Probe", "lastname": "Archive again",
                                              "sync_source": SOURCE})
    cnew = d2["results"][0]["id"] if c2 == 200 else None
    c3, d3 = get_by("contacts", "email", em, ["lastname"])
    ok = c1 == 200 and cd == 204 and c2 == 200 and cnew and c3 == 200 and d3["id"] == cnew and \
        d3["properties"]["lastname"] == "Archive again"
    record("H-ARCH-CONTACT archived contact's e-mail used again", ok,
           f"create {c1}, archive {cd}, upsert again {c2}: " +
           (f"contact {cnew} ({'new id' if cnew != cold else 'same id restored'})" if ok
            else f"{short(d2)}; read {c3} {short(d3)}"))


# Values from visible cases M02, M04, M05, M07, N01, U02 (tests/cases/visible.json)
RT_CONTACTS = {
    "m02": {"firstname": "Ana Marija", "lastname": "Kovač Horvat", "phone": "+385 91 234 5678",
            "address": "Ilica  22", "city": "Zagreb", "zip": "10000", "country": "HR"},
    "m04": {"firstname": "美咲", "lastname": "田中", "phone": "+81 45-555-0123", "address": "中区山下町 1-2",
            "city": "横浜市", "zip": "231-0023", "country": "JP", "company": "Harbour  Test Co."},
    "m05": {"firstname": "Ivan", "lastname": "Perić", "phone": "+385 (0)91 234-5678",
            "address": "Savska cesta 41", "city": "Zagreb", "zip": "10000", "country": "HR"},
    "m07": {"lastname": "O'Sullivan", "phone": "087 555 0133", "address": "3 Quay Street", "city": "Portwell",
            "zip": "P17 K8D2", "country": "IE"},
}


def check_roundtrip(mapping):
    diffs, contact_ids = [], {}
    for tag, props in RT_CONTACTS.items():
        em = email("rt" + tag)
        sent = dict(props, sync_source=SOURCE)
        s, b = upsert("contacts", "email", em, sent)
        if s != 200:
            diffs.append(f"contact {tag} HTTP {s} {short(b)}")
            continue
        cid = b["results"][0]["id"]
        contact_ids[tag] = cid
        s2, b2 = hs("GET", f"/crm/v3/objects/contacts/{cid}", params={"properties": ",".join(CONTACT_PROPS)})
        got = b2.get("properties", {}) if s2 == 200 else {}
        for k, v in dict(sent, email=em).items():
            if got.get(k) != v:
                diffs.append(f"contact {tag}.{k}: sent {v!r} got {got.get(k)!r}")
    record("H-RT-CONTACT contact fields stored exactly (read back by ID)", not diffs,
           "phone raw, double spaces, non-Latin text, accents, apostrophe all unchanged" if not diffs
           else "; ".join(diffs))

    # deal round-trip: N01 values (created directly in Closed Won), then U02 path (stage moves)
    cur_prop = "shop_currency" if mapping == "shop_currency" else "deal_currency_code"
    ddiffs = []
    deals = {
        "n01": {"dealname": f"Order #{order('N01')}", "amount": "2490.00", cur_prop: "EUR",
                "pipeline": "default", "dealstage": "closedwon", "closedate": "2026-10-05T07:12:44Z",
                "shop_modified_at": "2026-10-05T07:12:50Z"},
        "m04": {"dealname": f"Order #{order('M04')}", "amount": "189.80", cur_prop: "USD",
                "pipeline": "default", "dealstage": "closedwon", "closedate": "2026-10-06T09:05:51Z",
                "shop_modified_at": "2026-10-06T09:05:57Z"},
        "u02": {"dealname": f"Order #{order('U02')}", "amount": "248.00", cur_prop: "EUR",
                "pipeline": "default", "dealstage": "appointmentscheduled", "closedate": "2026-10-08T08:00:00Z",
                "shop_modified_at": "2026-10-08T08:00:06Z"},
    }

    def compare(tag, sent, got):
        for k, v in sent.items():
            g = got.get(k)
            if k == "amount":
                same = g not in (None, "") and Decimal(g) == Decimal(v)
            elif k in ("closedate", "shop_modified_at"):
                same = same_second(g, v)
            else:
                same = g == v
            if not same:
                ddiffs.append(f"deal {tag}.{k}: sent {v!r} got {g!r}")

    deal_ids = {}
    for tag, sent in deals.items():
        key = order(tag.upper())
        s, b = upsert("deals", "shop_order_id", key, sent)
        if s != 200:
            ddiffs.append(f"deal {tag} HTTP {s} {short(b)}")
            continue
        did = b["results"][0]["id"]
        deal_ids[tag] = did
        s2, b2 = hs("GET", f"/crm/v3/objects/deals/{did}", params={"properties": ",".join(DEAL_PROPS)})
        compare(tag, dict(sent, shop_order_id=key), b2.get("properties", {}))
    record("H-RT-DEAL deal fields stored exactly (read back by ID)", not ddiffs,
           f"name, amount (exact decimal), {cur_prop}, stage, closedate, shop_modified_at (date-time, to the "
           f"second), shop_order_id unchanged" if not ddiffs else "; ".join(ddiffs))

    # closedate when the stage moves (U02: Appointment Scheduled -> Closed Won -> Closed Lost).
    # Seen in the first run (2026-10-20): an upsert that sends the stage WITHOUT closedate makes HubSpot set
    # closedate to "now". The build sends closedate (order_date, a required field) in every deal upsert
    # (adr/002), so the gated check is the move WITH closedate; the stage-only move is recorded as evidence.
    cdiffs, observed = [], "U02 deal not created"
    if "u02" in deal_ids:
        key = order("U02")

        def move(stage, with_date):
            props = {"dealstage": stage, "shop_modified_at": "2026-10-14T09:30:00Z"}
            if with_date:
                props["closedate"] = "2026-10-08T08:00:00Z"
            s, b = upsert("deals", "shop_order_id", key, props)
            s2, b2 = hs("GET", f"/crm/v3/objects/deals/{deal_ids['u02']}", params={"properties": "closedate,dealstage"})
            p = b2.get("properties", {}) if s2 == 200 else {}
            kept = s == 200 and p.get("dealstage") == stage and same_second(p.get("closedate"), "2026-10-08T08:00:00Z")
            return kept, f"to {stage}: HTTP {s}, closedate {p.get('closedate')!r}"

        kept, line = move("closedwon", False)
        observed = f"stage only {line} ({'kept' if kept else 'HubSpot set it to now'})"
        for stage in ("closedlost", "closedwon"):
            kept, line = move(stage, True)
            if not kept:
                cdiffs.append("with closedate " + line)
    else:
        cdiffs.append(observed)
    record("H-CLOSEDATE closedate as sent when the stage moves to Closed Lost / Closed Won (closedate in the upsert)",
           not cdiffs, ("closedate stays 2026-10-08T08:00:00Z after both moves" if not cdiffs else "; ".join(cdiffs))
           + "; evidence: " + observed)

    # link deal -> contact (default association), read back
    ok_link, note = False, "no ids"
    if "n01" in deal_ids and "m02" in contact_ids:
        s, b = hs("PUT", f"/crm/v4/objects/deals/{deal_ids['n01']}/associations/default/contacts/{contact_ids['m02']}")
        s2, b2 = hs("GET", f"/crm/v4/objects/deals/{deal_ids['n01']}/associations/contacts")
        linked = [str(r.get("toObjectId")) for r in (b2 or {}).get("results", [])] if s2 == 200 else []
        ok_link = s in (200, 201) and linked == [contact_ids["m02"]]
        note = f"PUT default association HTTP {s}; read back {len(linked)} linked contact(s)"
        if not ok_link:
            note += f" {short(b)}"
    record("H-LINK deal linked to contact (default association)", ok_link, note)


def hubspot_cleanup():
    """Archive every probe record. Safety: only probe e-mails / P2PROBE order numbers."""
    # safety net for records whose answer was lost: probe contacts by sync_source, filtered by domain below
    body = {"filterGroups": [{"filters": [{"propertyName": "sync_source", "operator": "EQ", "value": SOURCE}]}],
            "properties": ["email"], "limit": 100}
    s, b = hs("POST", "/crm/v3/objects/contacts/search", body)
    for r in (b or {}).get("results", []) if s == 200 else []:
        if str(r["properties"].get("email") or "").endswith("@" + DOMAIN):
            created["contacts"].add(r["id"])
    archived, refused = 0, []
    for obj, props in (("deals", ["shop_order_id"]), ("contacts", ["email", "sync_source"])):
        for rid in sorted(created[obj]):
            s, b = hs("GET", f"/crm/v3/objects/{obj}/{rid}", params={"properties": ",".join(props)})
            if s == 404:
                continue
            p = (b or {}).get("properties", {})
            mine = str(p.get("shop_order_id") or "").startswith(ORDER_PREFIX) if obj == "deals" else \
                str(p.get("email") or "").endswith("@" + DOMAIN) and p.get("sync_source") == SOURCE
            if not mine:
                refused.append(f"{obj} {rid}")
                continue
            sd, _ = hs("DELETE", f"/crm/v3/objects/{obj}/{rid}")
            archived += sd == 204
    print(f"cleanup: {archived} probe records archived in HubSpot" +
          (f"; NOT touched (not probe records): {refused}" if refused else ""), flush=True)


# ---------------------------------------------------------------- n8n client and checks

def n8n(method, path, body=None, params=None):
    url = ENV["N8N_URL"].rstrip("/") + "/api/v1" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-N8N-API-KEY", ENV["N8N_API_KEY"])
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]


def n8n_all(path, params=None):
    items, cursor = [], None
    while True:
        p = dict(params or {}, limit=100)
        if cursor:
            p["cursor"] = cursor
        s, page = n8n("GET", path, params=p)
        if s != 200:
            sys.exit(f"n8n GET {path} -> HTTP {s}: {page}")
        items.extend(page.get("data", []))
        cursor = page.get("nextCursor")
        if not cursor:
            return items


def hook(path, body, headers=None):
    url = ENV["N8N_URL"].rstrip("/") + "/webhook/" + path
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:200].decode("utf-8", "replace")


def node(name, type_, version, params, x, cred=None, **extra):
    n = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "q129probe/" + name)), "name": name, "type": type_,
         "typeVersion": version, "position": [x * 240, 0], "parameters": params}
    if cred:
        n["credentials"] = cred
    n.update(extra)
    return n


def chain(*names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


# Reads the raw body while the webhook's binary is this node's input (n8n keeps it in its binary store, so
# only getBinaryDataBuffer on the own input works); passes the binary on for the Crypto node.
READ_JS = r"""
const item = $input.first();
const raw = item.binary && item.binary.data ? await this.helpers.getBinaryDataBuffer(0, 'data') : Buffer.alloc(0);
let parsed = 'not_json';
try { const o = JSON.parse(raw.toString('utf8')); parsed = (o && typeof o === 'object' && !Array.isArray(o)) ? 'object' : 'not_object'; } catch (e) {}
return [{ json: { headers: item.json.headers, raw_b64: raw.toString('base64'), bytes: raw.length, parsed }, binary: item.binary }];
"""

VERIFY_JS = r"""
const it = $input.first().json;
const got = String((it.headers || {})['x-wc-webhook-signature'] || '');
const want = String(it.signature || '');
let diff = got.length ^ want.length;
for (let i = 0; i < Math.max(got.length, want.length); i++) diff |= (got.charCodeAt(i) || 0) ^ (want.charCodeAt(i) || 0);
return [{ json: { ok: got.length > 0 && diff === 0, computed: want, raw_b64: it.raw_b64, parsed: it.parsed } }];
"""


def sig_workflow(cred_id):
    # Webhook v1 with "Binary File" on: n8n does not parse the body (webhook-helpers parseRequestBody returns
    # early), so a signed body that is not JSON still reaches the workflow (v2 answers 422 itself). adr/003.
    hook_node = node("Order in", "n8n-nodes-base.webhook", 1,
                     {"httpMethod": "POST", "path": "q129-probe-sig", "responseMode": "responseNode",
                      "options": {"binaryData": True, "binaryPropertyName": "data"}}, 0,
                     webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "q129/probe-sig")))
    read = node("Read raw body", "n8n-nodes-base.code", 2, {"jsCode": READ_JS}, 1)
    sign = node("Sign raw body", "n8n-nodes-base.crypto", 2,
                {"action": "hmac", "type": "SHA256", "binaryData": True, "binaryPropertyName": "data",
                 "dataPropertyName": "signature", "encoding": "base64"}, 2,
                cred={"crypto": {"id": cred_id, "name": CRYPTO_CRED}})
    verify = node("Verify signature", "n8n-nodes-base.code", 2, {"jsCode": VERIFY_JS}, 3)
    answer = node("Answer", "n8n-nodes-base.respondToWebhook", 1.4,
                  {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}",
                   "options": {"responseCode": "={{ $json.ok ? 200 : 401 }}"}}, 4)
    return {"name": N8N_PREFIX + "raw body signature", "nodes": [hook_node, read, sign, verify, answer],
            "connections": chain("Order in", "Read raw body", "Sign raw body", "Verify signature", "Answer"),
            "settings": {"executionOrder": "v1"}}


def ledger_workflow(table_id):
    hook_node = node("Ledger write in", "n8n-nodes-base.webhook", 2.1,
                     {"httpMethod": "POST", "path": "q129-probe-ledger", "responseMode": "responseNode",
                      "options": {}}, 0,
                     webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "q129/probe-ledger")))
    up = node("Upsert ledger row", "n8n-nodes-base.dataTable", 1.1, {
        "resource": "row", "operation": "upsert",
        "dataTableId": {"__rl": True, "mode": "id", "value": table_id},
        "matchType": "allConditions",
        "filters": {"conditions": [{"keyName": "order_number", "condition": "eq",
                                    "keyValue": "={{ $json.body.order_number }}"}]},
        "columns": {"mappingMode": "defineBelow", "value": {
            "order_number": "={{ $json.body.order_number }}", "version": "={{ $json.body.version }}",
            "data_hash": "={{ $json.body.data_hash }}"},
            "matchingColumns": [], "schema": [
                {"id": c, "displayName": c, "required": False, "defaultMatch": False, "display": True,
                 "type": "string", "canBeUsedToMatch": True} for c in ("order_number", "version", "data_hash")]},
        "options": {}}, 1)
    answer = node("Answer", "n8n-nodes-base.respondToWebhook", 1.4,
                  {"respondWith": "json", "responseBody": "={{ JSON.stringify({ ok: true }) }}", "options": {}}, 2)
    return {"name": N8N_PREFIX + "ledger write", "nodes": [hook_node, up, answer],
            "connections": chain("Ledger write in", "Upsert ledger row", "Answer"),
            "settings": {"executionOrder": "v1"}}


def push_workflow(doc, tag_id):
    assert doc["name"].startswith(N8N_PREFIX)
    existing = [w for w in n8n_all("/workflows", {"name": doc["name"]})
                if w.get("name") == doc["name"] and not w.get("isArchived")]
    if existing:
        s, b = n8n("PUT", f"/workflows/{existing[0]['id']}", doc)
    else:
        s, b = n8n("POST", "/workflows", doc)
    if s != 200:
        sys.exit(f"n8n workflow save {doc['name']} -> HTTP {s}: {b}")
    wid = b["id"]
    n8n("PUT", f"/workflows/{wid}/tags", [{"id": tag_id}])
    s, b = n8n("POST", f"/workflows/{wid}/publish", {})
    if s != 200:
        sys.exit(f"n8n publish {doc['name']} -> HTTP {s}: {b}")
    time.sleep(1)
    return wid


def wc_sign(body):
    return base64.b64encode(hmac.new(ENV["Q129_WEBHOOK_SECRET"].encode("utf-8"), body, hashlib.sha256).digest()).decode()


def check_signature(cred_id, tag_id, wids):
    wids.append(push_workflow(sig_workflow(cred_id), tag_id))
    # body as WooCommerce sends it: PHP json_encode default flags ("\/" and "\uXXXX"), trimmed
    body = (b'{"id":727,"number":"P2PROBE","billing":{"first_name":"Ana Marija","last_name":"Kova\\u010d",'
            b'"email":"probe@' + DOMAIN.encode() + b'"},"total":"2490.00","currency":"EUR",'
            b'"payment_url":"https:\\/\\/harbour-ebikes.example.com\\/checkout\\/","note":"  two  spaces "}')
    hdr = {"Content-Type": "application/json", "X-WC-Webhook-Topic": "order.created"}
    fails = []

    def expect(label, payload, headers, want, parsed=None):
        s, b = hook("q129-probe-sig", payload, headers)
        raw_ok = isinstance(b, dict) and base64.b64decode(b.get("raw_b64") or "") == payload
        got_parsed = b.get("parsed") if isinstance(b, dict) else None
        line = f"{label}: HTTP {s}" + ("" if raw_ok else " (raw bytes DIFFER)") + \
            (f", parsed {got_parsed}" if parsed else "")
        if s != want or not raw_ok or (parsed and got_parsed != parsed):
            fails.append(line)
        return line, b

    good, b = expect("signed", body, dict(hdr, **{"X-WC-Webhook-Signature": wc_sign(body)}), 200, "object")
    same_secret = isinstance(b, dict) and b.get("computed") == wc_sign(body)
    if not same_secret:
        fails.append("n8n credential secret differs from Q129_WEBHOOK_SECRET in .env")
    lines = [good]
    lines.append(expect("wrong signature", body, dict(hdr, **{"X-WC-Webhook-Signature": wc_sign(b"x")}), 401)[0])
    changed = body.replace(b"2490.00", b"2490.01")
    lines.append(expect("body changed after signing", changed,
                        dict(hdr, **{"X-WC-Webhook-Signature": wc_sign(body)}), 401)[0])
    lines.append(expect("no signature", body, hdr, 401)[0])
    notjson = b"this is not json \xc3\xa9"
    lines.append(expect("signed, not JSON", notjson, {"Content-Type": "application/json",
                                                       "X-WC-Webhook-Signature": wc_sign(notjson)}, 200,
                        "not_json")[0])
    ping = b"webhook_id=12"
    lines.append(expect("ping body, form type", ping, {"Content-Type": "application/x-www-form-urlencoded",
                                                       "X-WC-Webhook-Signature": wc_sign(ping)}, 200)[0])
    record("N-SIG raw-body signature check in an n8n webhook (v1, Binary File on)", not fails,
           "; ".join(lines) + ("; n8n Crypto credential = .env secret" if same_secret else "") +
           "; raw bytes read from the n8n binary store")


def check_ledger(tag_id, wids, table_holder):
    s, b = n8n("POST", "/data-tables", {"name": LEDGER_TABLE, "columns": [
        {"name": "order_number", "type": "string"}, {"name": "version", "type": "string"},
        {"name": "data_hash", "type": "string"}]})
    if s not in (200, 201):
        existing = [t for t in n8n_all("/data-tables") if t.get("name") == LEDGER_TABLE]
        if not existing:
            record("N-LEDGER two parallel ledger writes, one new order", False, f"create table HTTP {s}: {b}")
            return
        table_id = existing[0]["id"]
    else:
        table_id = b["id"]
    table_holder.append(table_id)
    wids.append(push_workflow(ledger_workflow(table_id), tag_id))
    bad, codes = [], []
    for r in range(LEDGER_ROUNDS):
        num = order(f"L{r}")
        payload = json.dumps({"order_number": num, "version": "2026-10-05T07:12:50Z",
                              "data_hash": hashlib.sha256(num.encode()).hexdigest()}).encode()
        out = parallel_pair(lambda i: hook("q129-probe-ledger", payload, {"Content-Type": "application/json"}))
        codes.append("/".join(str(s) for s, _ in out))
        filt = json.dumps({"type": "and", "filters": [{"columnName": "order_number", "condition": "eq",
                                                       "value": num}]})
        s, rows = n8n("GET", f"/data-tables/{table_id}/rows", params={"filter": filt, "limit": 50})
        n = len(rows.get("data", [])) if s == 200 else -1
        if n != 1:
            bad.append(f"{num}: {n} rows (HTTP {s})")
    record("N-LEDGER two parallel ledger writes (data table upsert), one new order", not bad,
           f"{LEDGER_ROUNDS} rounds, webhook answers {codes}; " +
           ("one row per order every round" if not bad else "; ".join(bad)))


def n8n_checks():
    if not ENV.get("N8N_API_KEY") or not ENV.get("Q129_WEBHOOK_SECRET"):
        sys.exit("N8N_API_KEY or Q129_WEBHOOK_SECRET missing in .env")
    import sqlite3  # credential id by name, read-only (the public API has no credential list)
    import os
    db = os.path.expanduser("~/.n8n/database.sqlite")
    con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    row = con.execute("select id from credentials_entity where name = ? and type = 'crypto'", (CRYPTO_CRED,)).fetchone()
    con.close()
    if not row:
        sys.exit(f"n8n credential '{CRYPTO_CRED}' (type Crypto) not found")
    tags = [t for t in n8n_all("/tags") if t["name"] == N8N_TAG]
    tag_id = tags[0]["id"] if tags else n8n("POST", "/tags", {"name": N8N_TAG})[1]["id"]
    wids, table_holder = [], []
    try:
        check_signature(row[0], tag_id, wids)
        check_ledger(tag_id, wids, table_holder)
    finally:
        for wid in wids:
            n8n("POST", f"/workflows/{wid}/unpublish", {})
            n8n("POST", f"/workflows/{wid}/archive", {})
        for tid in table_holder:
            n8n("DELETE", f"/data-tables/{tid}")
        print(f"cleanup: {len(wids)} probe workflows unpublished and archived; "
              f"{len(table_holder)} probe table deleted", flush=True)


# ---------------------------------------------------------------- main

def hubspot_checks():
    if not ENV.get("HUBSPOT_TOKEN"):
        sys.exit("HUBSPOT_TOKEN missing in .env")
    try:
        account = check_rate()
        if not check_props():
            print("custom properties missing: the remaining HubSpot checks cannot run", flush=True)
            return
        mapping = check_currency(account)
        check_upserts()
        check_parallel("deals")
        check_parallel("contacts")
        check_archived_reuse()
        check_roundtrip(mapping)
    finally:
        hubspot_cleanup()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["hubspot", "n8n"])
    a = ap.parse_args()
    print(f"P2 probe run {RUN} ({datetime.now(timezone.utc).isoformat(timespec='seconds')})", flush=True)
    if a.only in (None, "hubspot"):
        hubspot_checks()
    if a.only in (None, "n8n"):
        n8n_checks()
    failed = [c for c, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed" +
          (f"; failed: {', '.join(failed)}" if failed else ""), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
