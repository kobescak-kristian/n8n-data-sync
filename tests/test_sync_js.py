"""The Code-node field checks (workflows/sync_js.py CHECK_FN) agree with the reference model.

    python tests/test_sync_js.py

Runs checkAndClean in Node on every webhook body of tests/cases/visible.json and on generated
variants of every check (amounts, dates, e-mails, names, types, whitespace), and compares reasons,
order number, version, contact and deal with tests/make_cases.py check_and_clean. Exit 0 = all agree.
Needs node on PATH. Reads only the visible cases (never the hold-out).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "workflows"))
import make_cases as M  # noqa: E402
import sync_js as J  # noqa: E402


def variants(base):
    """Bodies that move one field at a time through the check rules."""
    p = json.loads(base)
    out = []

    def put(path, value):
        q = json.loads(base)
        obj = q
        for k in path[:-1]:
            obj = obj[k]
        if value is M.DROP:
            obj.pop(path[-1], None)
        else:
            obj[path[-1]] = value
        out.append(json.dumps(q, ensure_ascii=False))

    for v in ["12", "12.5", "12.50", "0", "00", "007.1", "1250.505", "12,50", "1.234,50", "-1.00", " 89.90 ",
              "1e3", "12.", ".5", "", "  ", None, 12.5, True, " 12.00　", M.DROP]:
        put(["total"], v)
    for v in ["EUR", "eur", " GBP ", "HRK", "", None, 1, M.DROP]:
        put(["currency"], v)
    for v in ["pending", "processing", " completed", "shipped", "Processing", "", None, M.DROP, "trash", "on-hold"]:
        put(["status"], v)
    for key in ["date_created_gmt", "date_modified_gmt"]:
        for v in ["2026-10-05T07:12:44", "2026-02-29T10:00:00", "2024-02-29T10:00:00", "1900-02-29T00:00:00",
                  "2000-02-29T00:00:00", "2026-09-31T10:00:00", "2026-10-05T24:00:00", "2026-10-05T23:59:60",
                  "2026-10-05T23:60:00", "0000-01-01T00:00:00", "2026-10-05 07:12:44", "2026-10-05T07:12:44Z",
                  "2026-10-05T07:12:44.123", "2026-13-01T00:00:00", "", None, 20261005, M.DROP]:
            put([key], v)
    for v in ["41001", " 41001 ", "HB-41001", "-41001", "41 001", "A" * 40, "A" * 41, "", None, 41001, M.DROP,
              "41001 "]:
        put(["number"], v)
    for v in ["Ana@Example.COM", "  ana.kovac@mail.harbour-sync.example.com ", "ana..k@x.example.com",
              "ana@x", "ana@x.example.com.", "a,b@x.example.com", "ana kovac@x.example.com", "ä@x.example.com",
              "ana@-x.example.com", "ana+tag@x.example.com", "", None, 5, M.DROP, "x" * 250 + "@a.example.com",
              "Kim@x.example.com"]:
        put(["billing", "email"], v)
    for key in ["first_name", "last_name"]:
        for v in ["  Ana  Marija ", "Ana  Marija", "Ana\nMarija", "", "   ", None, 7, M.DROP, "田中"]:
            put(["billing", key], v)
    for key in ["phone", "company", "address_1", "address_2", "city", "postcode", "country"]:
        for v in ["  x  y ", "", None, False, ["a"], {"a": 1}, M.DROP]:
            put(["billing", key], v)
    put(["billing"], "not an object")
    put(["billing"], None)
    out.extend(["", "null", "[]", "[1]", "\"text\"", "{", "this is not json", "{\"number\": \"1\"}", "123"])
    return out


def main():
    doc = json.loads((ROOT / "tests" / "cases" / "visible.json").read_text(encoding="utf-8"))
    bodies = []
    for c in doc["cases"]:
        for ev in c["events"]:
            if ev.get("type") == "webhook" and ev.get("body"):
                bodies.append(ev["body"])
    base = next(b for b in bodies if b.startswith("{") and '"total":"' in b)
    bodies += variants(base)
    bodies.append(base.replace('"total":"', '"total":NaN,"total_text":"', 1))  # not JSON in JS or the model (R3-07)

    expected = []
    for b in bodies:
        payload = M.parse_body(b)
        reasons, rec = M.check_and_clean(payload)
        e = {"reasons": reasons, "order_number": rec.get("order_number"), "modified": rec.get("modified")}
        if not reasons:
            e["contact"] = rec["contact"]
            e["deal"] = rec["deal"]
        expected.append(e)

    js = J.CHECK_FN + r"""
const fs = require('fs');
const bodies = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(bodies.map((b) => checkAndClean(b))));
"""
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp)
        (tp / "bodies.json").write_text(json.dumps(bodies), encoding="utf-8")
        (tp / "check.js").write_text(js, encoding="utf-8")
        r = subprocess.run(["node", str(tp / "check.js"), str(tp / "bodies.json")], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode("utf-8", "replace"))
            return 2
        got = json.loads(r.stdout.decode("utf-8"))

    bad = 0
    for b, e, g in zip(bodies, expected, got):
        g = {k: g.get(k) for k in e}
        if g != e:
            bad += 1
            if bad <= 15:
                sys.stdout.buffer.write((f"DIFF body {b[:120]!r}\n  model {json.dumps(e, ensure_ascii=False)[:400]}\n"
                                         f"  js    {json.dumps(g, ensure_ascii=False)[:400]}\n").encode("utf-8"))
    print(f"{len(bodies) - bad} of {len(bodies)} bodies agree ({len(bodies) - len(variants(base))} visible, "
          f"{len(variants(base))} variants)")
    guard_bad = ledger_guard()
    wait_bad = retry_wait_guard()
    race_bad = contact_race_guard()
    gate_bad = gate_guard()
    close_bad = rows_to_close_guard()
    return 1 if bad or guard_bad or wait_bad or race_bad or gate_bad or close_bad else 0


def run_js(name, js, arg):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / name
        p.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", str(p), json.dumps(arg)], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        return None
    return json.loads(r.stdout)


def gate_guard():
    """Entry Gate (R3-03, R3-07): an empty body keeps its request ID and signature check, a failed Crypto node is a
    bad signature (not a lost request), and the Gate agrees with the model on what is accepted."""
    sig = "c2lnbmF0dXJl"
    cases = {  # name: (read-request fields, Crypto output, model event)
        "signed empty body": ({"bytes": 0, "text": "", "has_sig": True, "sig": sig}, {"signature": sig},
                              {"body": "", "sign": "valid", "topic": "order.created"}),
        "unsigned empty body": ({"bytes": 0, "text": "", "has_sig": False, "sig": ""}, {"signature": sig},
                                {"body": "", "sign": "none", "topic": "order.created"}),
        "crypto failed": ({"bytes": 3, "text": "abc", "has_sig": True, "sig": sig}, {"error": {"message": "x"}},
                          {"body": "abc", "sign": "wrong_secret", "topic": "order.created"}),
        "ping": ({"bytes": 13, "text": "webhook_id=14", "has_sig": False, "sig": ""}, {"signature": sig},
                 {"body": "webhook_id=14", "sign": "none", "topic": None}),
        "ping with final newline": ({"bytes": 14, "text": "webhook_id=14\n", "has_sig": False, "sig": ""},
                                    {"signature": sig}, {"body": "webhook_id=14\n", "sign": "none", "topic": None}),
    }
    arg = {}
    for k, (rr, crypto, _) in cases.items():
        rr = dict(rr, topic="order.created", delivery_id="d-1", request_id="runner-1", test_crash=False, received_ms=0)
        arg[k] = [rr, crypto]
    js = r"""
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [k, [rr, crypto]] of Object.entries(cases)) {
  const $ = (n) => ({ first: () => ({ json: n === 'Read request' ? rr : {} }) });
  const $input = { first: () => ({ json: crypto }) };
  const $execution = { id: '7' };
  const g = (() => { __GATE__ })()[0].json;
  out[k] = [g.http, g.result, g.reason, g.request_id];
}
process.stdout.write(JSON.stringify(out));
""".replace("__GATE__", J.GATE)
    got = run_js("gate.js", js, arg)
    if got is None:
        return 1
    bad = 0
    for k, (_, _, ev) in cases.items():
        m = M.Model().webhook(dict(ev, faults=None, force_crash=False), {"case": "G", "step": 1, "body": ev["body"]})
        accepted = m["result"] not in ("rejected", "ignored")
        g = got[k]
        ok = g[3] == "runner-1" and ((g[1] == "accepted") == accepted) and (
            accepted or (g[0] == m["http"] and g[1] == m["result"] and g[2] == m["reasons"][0]))
        if not ok:
            bad += 1
            print(f"DIFF gate {k}: model {m['http']} {m['result']} {m['reasons']}, js {g}")
    print(f"{len(cases) - bad} of {len(cases)} gate checks agree")
    return bad


def rows_to_close_guard():
    """Rows to close (H-R02, CASES.md 3.8): every open row the step may close closes, also with two open rows."""
    v1, v2, v3 = "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z"
    row = lambda i, v: {"id": i, "order_number": "HB-1", "version": v, "state": "open"}  # noqa: E731
    cases = {  # name: (state, open rows, want [(row_id, closed_by)])
        "sync closes two rows": ({"action": "write", "modified": v1}, [row(1, v1), row(2, v1)],
                                 [[1, "sync"], [2, "sync"]]),
        "replay of the second row": ({"action": "write", "modified": v2, "replay": {"row_id": 2}},
                                     [row(1, v1), row(2, v2)], [[1, "sync"], [2, "replay"]]),
        "only the older row": ({"action": "write", "modified": v2}, [row(1, v3), row(2, v2)], [[2, "sync"]]),
        "skip closes only the replayed row": ({"action": "skip", "modified": v2, "replay": {"row_id": 2}},
                                              [row(1, v1), row(2, v2)], [[2, "replay"]]),
        "no open row": ({"action": "write", "modified": v1}, [{}], []),
    }
    js = r"""
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [k, [state, rows]] of Object.entries(cases)) {
  const S = Object.assign({ order_number: 'HB-1', request_id: 'r-1', replay: null }, state);
  const $ = () => ({ first: () => ({ json: S }) });
  const $input = { all: () => rows.map((json) => ({ json })) };
  const res = (() => { __CLOSE__ })().map((i) => i.json).filter((j) => j.row_id !== -1);
  out[k] = res.map((j) => [j.row_id, j.closed_by]);
}
process.stdout.write(JSON.stringify(out));
""".replace("__CLOSE__", J.ROWS_TO_CLOSE.replace("__STATE__", "S"))
    got = run_js("close.js", js, {k: v[:2] for k, v in cases.items()})
    if got is None:
        return 1
    bad = 0
    for k, v in cases.items():
        if sorted(got[k]) != v[2]:
            bad += 1
            print(f"DIFF rows to close {k}: want {v[2]}, got {got[k]}")
    print(f"{len(cases) - bad} of {len(cases)} rows-to-close checks agree")
    return bad


def ledger_guard():
    """The ledger rechecks (R2 finding 1): stop only when the ledger now holds a newer version; never write it back."""
    v = "2026-10-01T10:00:00Z"
    rows = {"none": [{}], "older": [{"id": 1, "version": "2026-10-01T09:00:00Z"}],
            "same": [{"id": 1, "version": v}], "newer": [{"id": 1, "version": "2026-10-01T11:00:00Z"}]}
    want = {"none": ("write", True), "older": ("write", True), "same": ("write", True), "newer": ("skip", False)}
    run = lambda body: "(() => {" + body + "})()"  # noqa: E731
    js = r"""
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [k, rows] of Object.entries(cases)) {
  const state = { order_number: 'HB-1', modified: '__V__', action: 'write', result: 'updated', data_hash: 'h' };
  const $ = () => ({ first: () => ({ json: state }) });
  const $input = { all: () => rows.map((json) => ({ json })) };
  const a = __RECHECK__[0].json;
  const b = __LEDGER__[0].json;
  out[k] = [a.action, b.write, a.action === 'skip' ? a.result : null];
}
process.stdout.write(JSON.stringify(out));
""".replace("__V__", v).replace("__RECHECK__", run(J.recheck("X"))).replace("__LEDGER__", run(J.LEDGER_ROW))
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "guard.js"
        p.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", str(p), json.dumps(rows)], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        return 1
    got = json.loads(r.stdout)
    bad = 0
    for k, (act, write) in want.items():
        g = got[k]
        if g[0] != act or g[1] != write or (act == "skip" and g[2] != "skipped_older"):
            bad += 1
            print(f"DIFF ledger guard {k}: want {act}/{write}, got {g}")
    print(f"{len(want) - bad} of {len(want)} ledger guard checks agree")
    return bad


def retry_wait_guard():
    """The ledger read after a retry wait (SW02): stop only on a newer version; Core then ends skipped_older."""
    v = "2026-10-01T10:00:00Z"
    rows = {"none": [{}], "older": [{"id": 1, "version": "2026-10-01T09:00:00Z"}],
            "same": [{"id": 1, "version": v}], "newer": [{"id": 1, "version": "2026-10-01T11:00:00Z"}]}
    want = {"none": "retry", "older": "retry", "same": "retry", "newer": "skip"}
    run = lambda body: "(() => {" + body + "})()"  # noqa: E731
    js = r"""
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [k, rows] of Object.entries(cases)) {
  const nodes = { 'Start': { order_number: 'HB-1', version: '__V__' },
    'Check 1': { done: false, ok: false, attempts: 1, status: 429, reason: null, wait: 5 },
    'X': { order_number: 'HB-1', modified: '__V__', action: 'write', result: 'updated' } };
  const $ = (n) => ({ first: () => ({ json: nodes[n] }) });
  let $input = { all: () => rows.map((json) => ({ json })) };
  const w = __WAIT__[0].json;
  $input = { first: () => ({ json: w }) };
  const a = __AFTER__[0].json;
  out[k] = [w.skip === true ? 'skip' : 'retry', w.done, a.action, a.result];
}
process.stdout.write(JSON.stringify(out));
""".replace("__V__", v).replace("__WAIT__", run(J.recheck_wait(1))).replace(
        "__AFTER__", run(J.after_call("X", "deals", "deal_id")))
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "wait.js"
        p.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", str(p), json.dumps(rows)], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        return 1
    got = json.loads(r.stdout)
    bad = 0
    for k, w in want.items():
        g = got[k]
        ok = (g[:3] == ["skip", True, "skip"] and g[3] == "skipped_older") if w == "skip" else \
            (g[:2] == ["retry", False] and g[2] == "attention")
        if not ok:
            bad += 1
            print(f"DIFF retry wait {k}: want {w}, got {g}")
    print(f"{len(want) - bad} of {len(want)} retry-wait checks agree")
    return bad


def contact_race_guard():
    """HubSpot 404 OBJECT_NOT_FOUND on a contact upsert (D02, SW03 race): one retry after 1 s; every other 404 and a
    simulated 404 of the fault proxy: no retry, crm_bad_request (CASES.md 3.7)."""
    contacts, deals = "/crm/v3/objects/contacts/batch/upsert", "/crm/v3/objects/deals/batch/upsert"
    race = {"status": "error", "category": "OBJECT_NOT_FOUND", "message": "Cannot update contact that doesn't exist"}
    sim = {"status": "error", "category": "SIMULATED", "message": "simulated 404 (fault proxy)"}
    cases = {  # name: (path, try number, status code, body, want)
        "race contact try 1": (contacts, 1, 404, race, ["retry", 1]),
        "race contact try 2": (contacts, 2, 404, race, ["stop", "crm_retry_exhausted"]),
        "race on a deal": (deals, 1, 404, race, ["stop", "crm_bad_request"]),
        "simulated 404": (contacts, 1, 404, sim, ["stop", "crm_bad_request"]),
        "race in a 207": (contacts, 1, 207, {"errors": [{"status": "404", "category": "OBJECT_NOT_FOUND"}]}, ["retry", 1]),
        "plain 404 no body": (contacts, 1, 404, None, ["stop", "crm_bad_request"]),
    }
    js = r"""
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [k, [path, n, code, body]] of Object.entries(cases)) {
  const $ = (x) => ({ first: () => ({ json: { path } }) });
  const $input = { first: () => ({ json: { statusCode: code, body, headers: {} } }) };
  const fns = { 1: () => { __T1__ }, 2: () => { __T2__ } };
  const o = fns[n]()[0].json;
  out[k] = o.done === false ? ["retry", o.wait] : ["stop", o.reason];
}
process.stdout.write(JSON.stringify(out));
""".replace("__T1__", J.check_try(1)).replace("__T2__", J.check_try(2))
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "race.js"
        p.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", str(p), json.dumps({k: v[:4] for k, v in cases.items()})], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        return 1
    got = json.loads(r.stdout)
    bad = 0
    for k, v in cases.items():
        if got[k] != v[4]:
            bad += 1
            print(f"DIFF contact race {k}: want {v[4]}, got {got[k]}")
    print(f"{len(cases) - bad} of {len(cases)} contact-race retry checks agree")
    return bad


if __name__ == "__main__":
    sys.exit(main())
