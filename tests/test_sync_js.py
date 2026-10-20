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
    return 1 if bad or guard_bad else 0


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


if __name__ == "__main__":
    sys.exit(main())
