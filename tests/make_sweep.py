"""Interaction-sweep cases for n8n-data-sync (Q-129), P4 (eval-gate build checks (a)).

A development set from the R2 red team of the build (shared notes q129-r2-build-redteam.md, SW01-SW22):
interactions the frozen gate does not send. Not gated (the R2 report: "not gated unless the owner
decides"): gate v2, tests/cases/visible.json and its SHA-256 stay as they are. This file only imports the
payload helpers and the reference model of tests/make_cases.py; it never changes them.

What the sweep adds to the visible case format:
- a parallel group may hold different bodies (two versions of one order, two orders of one customer);
  the group's faults sit on its first event and count for the whole group (the proxy has one step);
  `delay_s` sends that event N seconds after the group starts, without waiting for a log row;
  per-event results in a group are lists of the results the race allows; `crm_write_attempts` is null;
- sign mode `empty`: the signature header is sent with an empty value (expected: bad_signature);
- fault target `link`: the deal-contact link call (the proxy keeps its count out of `seen`, so
  `crm_write_attempts` still counts contact and deal upserts only);
- `limit_final`: the end state the README limit allows (R2 finding 1, owner 2026-10-21: two versions of one
  order within about 2 seconds, the older one can show in HubSpot until the next update). The runner
  reports LIMIT when only that end state matches.

Left out (reasons also in sweep.json `left_out`): SW10, SW15, SW16, SW17, SW22.

Run:   python tests/make_sweep.py   -> writes tests/cases/sweep.json and prints its SHA-256.
Every run checks the whole sweep set and stops, writing nothing, on a mistake (tests/test_make_sweep.py).
Standard library only. Deterministic: no clock, no random numbers.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_cases as M  # noqa: E402
from make_cases import (CaseError, Model, case, edit, hr, model_expect, php_json, plus, replay,  # noqa: E402
                        summary, upd, wh)

OUT = os.path.join(HERE, "cases", "sweep.json")
VISIBLE = os.path.join(HERE, "cases", "visible.json")
FORMAT_VERSION = 1
ID_RE = re.compile(r"^SW\d{2}$")
ORDERS = (71001, 71999)
SW = "sweep.harbour-sync.example.com"
DOMAIN = "." + SW
LEFT_OUT = {
    "SW10": "two replays of one row at the same moment: the replay count can be n+1 (version 2 list)",
    "SW15": "needs a second crash switch after the HubSpot writes in the test copy (a workflow change); "
            "the crash-after-writes gap is R2 finding 11 on the version 2 list",
    "SW16": "needs the Slack credential pointed at a wrong channel (an n8n credential change in a shared n8n)",
    "SW17": "the same signed body sent again later is visible case D01 (skipped_duplicate)",
    "SW22": "a static live-vs-test diff, not a case; tests/n8n_match.py and the R2 finding 7 fix cover it",
}
# check_events (make_cases.py) messages the sweep format allows (see the docstring)
ALLOWED = [re.compile(p) for p in (
    r"gated must be true",
    r"parallel group \S+: events must have the same body bytes",
    r"parallel group \S+: faults must be null",
    r"step \d+: unknown sign mode 'empty'",
    r"step \d+: unknown fault target 'link'",
)]


class SweepModel(Model):
    """The reference model plus the sweep's sign mode `empty` and fault target `link`."""

    def webhook(self, ev, ctx):
        if ev.get("sign") == "empty":  # an empty signature never equals the HMAC: as a wrong one
            ev = dict(ev, sign="wrong_secret")
        return Model.webhook(self, ev, ctx)

    def call(self, target, faults, attempts, apply):
        if target != "deals":
            return Model.call(target, faults, attempts, apply)
        links = {o: list(d["contacts"]) for o, d in self.deals.items()}
        err = Model.call(target, faults, attempts, apply)
        if err:
            return err
        err = Model.call("link", faults, {}, lambda: None)  # link attempts are not counted (CASES.md 3.7)
        if err:  # deal written, link not made
            for o, d in self.deals.items():
                if d["contacts"] != links.get(o, d["contacts"]):
                    d["contacts"] = links.get(o, [])
        return err


def later(ev, seconds):
    ev["delay_s"] = seconds
    return ev


def raw_json(obj):
    """Like php_json, but non-ASCII letters as raw UTF-8 (JSON_UNESCAPED_UNICODE in a shop plugin)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("/", "\\/")


def padded(p, size):
    """The order body grown to exactly `size` bytes with an ASCII customer note."""
    base = len(php_json(edit(p, customer_note="")).encode("utf-8"))
    body = php_json(edit(p, customer_note="x" * (size - base)))
    assert len(body.encode("utf-8")) == size
    return body


def sweep_case_defs():
    C = []

    def two_versions(num, email, first, last, created):
        v1 = hr(num, email, first, last, [("city500", 1)], created, status="pending", payment="bacs")
        v2 = edit(v1, status="processing", date_modified_gmt=plus(created, 1200),
                  date_modified=plus(created, 1200 + 7200))
        return v1, v2

    v1, v2 = two_versions(71010, "iva.matic@" + SW, "Iva", "Matić", "2026-10-17T07:00:00")
    C.append(dict(case("SW01", "v2 (processing), then the late v1 (pending) 1 s later, overlapping", [
        upd(v2, ["created"], parallel="g1"),
        later(wh(v1, ["skipped_older", "created"], parallel="g1"), 1)]),
        hard_rules=["H5"], limit_older_step=2))
    v1, v2 = two_versions(71020, "roko.vlahovic@" + SW, "Roko", "Vlahović", "2026-10-17T07:10:00")
    C.append(dict(case("SW02", "v1, then v2 1 s later; v1's deal write gets 429 with a 5 s wait", [
        wh(v1, ["created", "skipped_older"], parallel="g1", faults={"deals": ["429:5"]}),
        later(upd(v2, ["created", "updated"], parallel="g1"), 1)]),
        hard_rules=["H5"]))
    v1, v2 = two_versions(71030, "dora.bilic@" + SW, "Dora", "Bilić", "2026-10-17T07:20:00")
    C.append(dict(case("SW03", "v1 and v2 of one order at the same moment", [
        wh(v1, ["created", "updated", "skipped_older"], parallel="g1"),
        upd(v2, ["created", "updated"], parallel="g1")]),
        hard_rules=["H2", "H5"], limit_older_step=1))
    C.append(dict(case("SW04", "Two different orders of one new e-mail at the same moment", [
        wh(hr(71040, "tena.radic@" + SW, "Tena", "Radić", [("helmet", 1)], "2026-10-17T07:30:00"),
           ["created"], parallel="g1"),
        wh(hr(71041, "tena.radic@" + SW, "Tena", "Radić", [("lock", 1)], "2026-10-17T07:30:30"),
           ["created"], parallel="g1")]),
        hard_rules=["H1", "H2"]))

    sw05 = hr(71050, "ante.juric@" + SW, "Ante", "Jurić", [("trek", 1)], "2026-10-17T08:00:00")
    C.append(dict(case("SW05", "Contact write times out 3 times, then the shop sends the same order again", [
        wh(sw05, "needs_attention", "crm_retry_exhausted", faults={"contacts": ["timeout"] * 3}),
        wh(sw05, "created")]), hard_rules=["H2", "H4"]))
    C.append(dict(case("SW06", "Contact times out once; the deal times out 3 times (about 72 s)", [
        wh(hr(71060, "lucija.marin@" + SW, "Lucija", "Marin", [("cargo", 1)], "2026-10-17T08:10:00"),
           "needs_attention", "crm_retry_exhausted",
           faults={"contacts": ["timeout", "pass"], "deals": ["timeout"] * 3})]), hard_rules=["H4"]))
    v1, v2 = two_versions(71070, "filip.knezevic@" + SW, "Filip", "Knežević", "2026-10-17T08:20:00")
    C.append(dict(case("SW07", "Deal answer lost 3 times (written each time), then a newer version", [
        wh(v1, "needs_attention", "crm_retry_exhausted", faults={"deals": ["timeout_after_forward"] * 3}),
        upd(v2, "created")]), hard_rules=["H2", "H5"]))
    C.append(dict(case("SW08", "Contact 429 with Retry-After 0, then 429 with Retry-After 30 (wait capped at 10 s)", [
        wh(hr(71080, "mia.grgic@" + SW, "Mia", "Grgić", [("battery", 1)], "2026-10-17T08:30:00"),
           "created", faults={"contacts": ["429:0", "429:30"]})]), hard_rules=["H1"]))
    v1, v2 = two_versions(71090, "jakov.vukovic@" + SW, "Jakov", "Vuković", "2026-10-17T08:40:00")
    C.append(dict(case("SW09", "Failed replay, then a newer version from the shop, then replay of the closed row", [
        wh(v1, "needs_attention", "crm_retry_exhausted", faults=M.OUTAGE),
        replay(1, "needs_attention", "crm_retry_exhausted", faults=M.OUTAGE),
        upd(v2, "created"),
        replay(1, "replay_refused", "row_closed")]), hard_rules=["H2", "H4"]))

    cut = php_json(hr(71110, "zara.tomic@" + SW, "Zara", "Tomić", [("lock", 1)], "2026-10-17T09:00:00"))[:650]
    sw11 = hr(71111, "noa.lovric@" + SW, "Noa", "Lovrić", [("seat", 1)], "2026-10-17T09:10:00",
              phone="+385 91 555 0111")
    sw11b = edit(sw11, **{"billing.phone": "+385 91 555 0119"})
    C.append(dict(case("SW11", "Replay of a not_json row and of a same_version_different_data row", [
        wh(None, "needs_attention", "not_json", body=cut),
        replay(1, "needs_attention", "not_json"),
        wh(sw11, "created"),
        upd(sw11b, "needs_attention", "same_version_different_data"),
        replay(4, "needs_attention", "same_version_different_data")]), hard_rules=["H4", "H5"]))

    C.append(dict(case("SW12", "Summary: created, failed replay, good replay, rejected, ignored", [
        wh(hr(71120, "ema.saric@" + SW, "Ema", "Šarić", [("lights", 1)], "2026-10-17T09:20:00"), "created"),
        wh(hr(71121, "bruno.kos@" + SW, "Bruno", "Kos", [("trek", 1)], "2026-10-17T09:21:00"),
           "needs_attention", "crm_retry_exhausted", faults=M.OUTAGE),
        replay(2, "needs_attention", "crm_retry_exhausted", faults=M.OUTAGE),
        replay(2, "created"),
        wh(hr(71122, "vita.pavlic@" + SW, "Vita", "Pavlić", [("tube", 2)], "2026-10-17T09:22:00"),
           "rejected", "no_signature", sign="none"),
        wh(None, "ignored", "ping", topic=None, sign="none", body="webhook_id=14", content_type=None),
        summary()]), hard_rules=["H4"]))

    def good(num, local, minute):
        return hr(num, local + "@" + SW, "Sven", "Babić", [("lights", 1)], "2026-10-17T10:%02d:00" % minute)

    stay = [(71130, "sven.babic", {"billing.email": ""}, "missing_email"),
            (71131, "ana.ilic", {"total": "59,90"}, "invalid_total"),
            (71132, "tin.kovac", {"currency": "eur"}, "invalid_currency")]
    fixed = [(71133, "lea.zoric", {"status": "awaiting-shipment"}, "invalid_status"),
             (71134, "ivo.mak", {"billing.first_name": "", "billing.last_name": ""}, "missing_name"),
             (71135, "eva.rak", {"billing.email": "eva.rak@post"}, "invalid_email")]
    events = []
    for i, (n, loc, ch, rs) in enumerate(stay + fixed):
        events.append(wh(edit(good(n, loc, i), **ch), "needs_attention", rs))
    for i, (n, loc, ch, rs) in enumerate(fixed, len(stay)):
        p = good(n, loc, i)
        events.append(upd(edit(p, date_modified_gmt=plus(p["date_modified_gmt"], 3600),
                                date_modified=plus(p["date_modified"], 3600)), "created"))
    C.append(dict(case("SW13", "Six failures in the window, three closed by a later sync before the summary",
                       events + [summary()]), hard_rules=["H4"]))

    sw14 = hr(71140, "ivan.lasic@" + SW, "Ivan", "Lasić", [("city500", 1)], "2026-10-17T11:00:00")
    C.append(dict(case("SW14", "Signed bodies of 262145 bytes (too large) and exactly 262144 bytes", [
        wh(None, "rejected", "too_large", body=padded(sw14, M.MAX_BODY_BYTES + 1)),
        wh(None, "created", body=padded(sw14, M.MAX_BODY_BYTES))]), hard_rules=["H3"]))

    bom = php_json(hr(71180, "maks.dujmovic@" + SW, "Maks", "Dujmović", [("lock", 1)], "2026-10-17T12:00:00"))
    raw = hr(71181, "zeljka.simunovic@" + SW, "Željka", "Šimunović-Đurić", [("helmet", 1)],
             "2026-10-17T12:10:00", city="Đakovo", address_1="Ulica Ćirila i Metoda 7", postcode="31400")
    C.append(dict(case("SW18", "Signed body with a UTF-8 BOM; signed body with raw (not escaped) non-ASCII letters", [
        wh(None, "needs_attention", "not_json", body="﻿" + bom),
        wh(None, "created", body=raw_json(raw))]), hard_rules=["H1", "H4"]))

    p1 = edit(hr(71190, "karla.zupan@" + SW, "Karla", "Župan", [("lights", 1)], "2026-10-17T13:00:00"),
              number="HB-71190")
    p2 = edit(hr(71191, "karla.zupan@" + SW, "Karla", "Župan", [("tube", 1)], "2026-10-17T13:10:00"),
              number="hb-71190")
    C.append(dict(case("SW19", "Order HB-71190, then order hb-71190 (letter case only): observe HubSpot and the ledger", [
        wh(p1, "created"), wh(p2, "created")]), hard_rules=["H2"], observe=True))

    C.append(dict(case("SW20", "Signature header present but empty", [
        wh(hr(71200, "goran.vidic@" + SW, "Goran", "Vidić", [("lock", 1)], "2026-10-17T14:00:00"),
           "rejected", "bad_signature", sign="empty")]), hard_rules=["H3"]))
    sw21 = hr(71210, "tea.petrovic@" + SW, "Tea", "Petrović", [("pannier", 1)], "2026-10-17T14:10:00")
    C.append(dict(case("SW21", "Deal-contact link fails 3 times, then the shop sends the order again", [
        wh(sw21, "needs_attention", "crm_retry_exhausted", faults={"link": ["503", "503", "503"]}),
        wh(sw21, "created")]), hard_rules=["H1", "H4"]))
    return C


def expect_case(model, c, hands):
    """Expected per-event results and end state from the model; hand results must allow the model's."""
    per_event, final = model.run_case(c)
    exps, errs = [], []
    for ev, out, hand in zip(c["events"], per_event, hands):
        if out["result"] is not None and out["result"] not in hand:
            errs.append("%s step %d: hand-written result %s, rules give %s" % (c["id"], ev["step"], hand, out["result"]))
        exp = model_expect(out, ev, hand)
        if ev.get("parallel"):
            exp["crm_write_attempts"] = None  # a group shares one proxy step
        exps.append(exp)
    return exps, final, errs


def limit_final(c, final, step):
    """The end state of the README limit: the deal holds the values of the older event `step`."""
    if not isinstance(step, int) or not 1 <= step <= len(c["events"]):
        return None
    ev = c["events"][step - 1]
    alone = dict(c, events=[dict(ev, step=1, parallel=None, delay_s=None)])
    _, older = SweepModel().run_case(alone)
    out = copy.deepcopy(final)
    for d in out["deals"]:
        o = next(x for x in older["deals"] if x["order_number"] == d["order_number"])
        d["fields"] = o["fields"]
    return out


def build_sweep():
    model = SweepModel()
    cases, errs = [], []
    for d in sweep_case_defs():
        events = []
        for i, ev in enumerate(d["events"], 1):
            e = {"step": i}
            e.update({k: v for k, v in ev.items() if not k.startswith("_")})
            if e["type"] == "webhook":
                e["delivery_id"] = M.h("%s:%d" % (d["id"], i)) if e["topic"] else None
                e["webhook_id"] = M.WEBHOOK_IDS.get(e["topic"])
            events.append(e)
        c = {"id": d["id"], "kind": "SW", "title": d["title"], "related_to": d["related_to"],
             "depends_on": d["depends_on"], "hard_rules": d["hard_rules"], "observe": d.get("observe", False),
             "simulated": any(e.get("faults") or e.get("force_crash") for e in events),
             "gated": False, "events": events}
        hands = [ev["_result"] if isinstance(ev["_result"], list) else [ev["_result"]] for ev in d["events"]]
        exps, final, e_errs = expect_case(model, c, hands)
        errs += e_errs
        for e, exp, ev in zip(events, exps, d["events"]):
            got = exp["reasons"][0] if exp["reasons"] else None
            if got != ev["_reason"]:
                errs.append("%s step %d: hand-written reason %s, rules give %s" % (c["id"], e["step"], ev["_reason"], got))
            e["expect"] = exp
        c["expected_final"] = final
        if d.get("limit_older_step"):
            c["limit_older_step"] = d["limit_older_step"]
            c["limit_final"] = limit_final(c, final, d["limit_older_step"])
        cases.append(c)
    if errs:
        raise CaseError("\n".join(errs))
    return cases


def check_sweep(doc, visible_cases):
    """The whole sweep set: structure, keys (also against the visible set), groups, then the rules."""
    errs = []

    def err(cid, msg):
        if not any(p.search(msg) for p in ALLOWED):
            errs.append("%s: %s" % (cid, msg))

    if doc.get("format_version") != FORMAT_VERSION or doc.get("set") != "sweep":
        errs.append("file: format_version must be %d and set 'sweep'" % FORMAT_VERSION)
    cases = doc.get("cases")
    if not isinstance(cases, list):
        raise CaseError("file: cases must be a list")
    if doc.get("case_count") != len(cases):
        errs.append("file: case_count is %r, the file has %d cases" % (doc.get("case_count"), len(cases)))
    seen = set()
    for c in cases:
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            err(cid, "case id does not match SWnn")
        if cid in seen:
            err(cid, "duplicate case id")
        seen.add(cid)
        if c.get("gated") is not False:
            errs.append("%s: gated must be false (development set)" % cid)
        M.check_events(c, err)
        groups = {}
        for ev in c.get("events", []):
            if ev.get("delay_s") is not None:
                if not ev.get("parallel") or not isinstance(ev["delay_s"], (int, float)) or ev["delay_s"] < 0:
                    err(cid, "step %s: delay_s needs a parallel group and a number >= 0" % ev.get("step"))
            if ev.get("parallel") is not None:
                groups.setdefault(ev["parallel"], []).append(ev)
        for name, evs in groups.items():
            if any(ev.get("faults") for ev in evs[1:]) or evs[0].get("delay_s"):
                err(cid, "parallel group %s: faults only on its first event, which starts at once" % name)
    owner = {}
    for c in visible_cases:
        orders, emails = M.case_keys(c)
        for key in orders | emails:
            owner.setdefault(key, []).append(c["id"])
    for c in cases:
        orders, emails = M.case_keys(c)
        for key in orders | emails:
            if owner.get(key):
                err(c.get("id"), "order number or e-mail %s shared with %s" % (key, owner[key][0]))
            owner.setdefault(key, []).append(c.get("id"))
        for e in emails:
            if M.EMAIL_RE.match(e) and not e.endswith(DOMAIN.lstrip(".")):
                err(c.get("id"), "e-mail %s is not on %s" % (e, SW))
        for o in orders:
            m = re.match(r"^(?:[A-Za-z]+-)?(\d+)$", o)
            if M.ORDER_RE.match(o) and (not m or not ORDERS[0] <= int(m.group(1)) <= ORDERS[1]):
                err(c.get("id"), "order number %s is outside %d-%d" % (o, ORDERS[0], ORDERS[1]))
    if errs:
        raise CaseError("\n".join(errs))

    model = SweepModel()
    for c in cases:
        exps, final, e_errs = expect_case(model, c, [ev["expect"]["result"] for ev in c["events"]])
        errs += e_errs
        for ev, exp in zip(c["events"], exps):
            for key in exp:
                if ev["expect"].get(key) != exp[key]:
                    errs.append("%s step %d: expected %s %r disagrees with the rules (model: %r)"
                                % (c["id"], ev["step"], key, ev["expect"].get(key), exp[key]))
        if c.get("expected_final") != final:
            errs.append("%s: expected_final disagrees with the rules" % c["id"])
        if "limit_final" in c and c["limit_final"] != limit_final(c, final, c.get("limit_older_step")):
            errs.append("%s: limit_final is not the end state with the older event's deal values" % c["id"])
    if errs:
        raise CaseError("\n".join(errs))


def serialize(cases):
    doc = {"format_version": FORMAT_VERSION, "set": "sweep", "gated": False,
           "rules": "tests/CASES.md + tests/make_sweep.py docstring", "generator": "tests/make_sweep.py",
           "source": "R2 red team of the build, SW01-SW22", "left_out": LEFT_OUT,
           "case_count": len(cases), "cases": cases}
    return json.dumps(doc, ensure_ascii=True, indent=1) + "\n"


def load_visible():
    with open(VISIBLE, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    try:
        cases = build_sweep()
        text = serialize(cases)
        check_sweep(json.loads(text), load_visible())
    except CaseError as e:
        print("sweep set error, nothing written:\n" + str(e))
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("OK %d sweep cases (%s), %d events" % (len(cases), " ".join(c["id"] for c in cases),
                                                  sum(len(c["events"]) for c in cases)))
    print("wrote tests/cases/sweep.json SHA-256 %s" % hashlib.sha256(text.encode("utf-8")).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
