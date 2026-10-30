"""Planted-mistake test for the whole-set check in make_sweep.py (build check b).

Plants one mistake at a time in a copy of the sweep cases; the check must stop on every one with the
right message, and must accept the unchanged set. Also: two builds give the same bytes, and the
generator writes nothing when the check stops.
Run: python tests/test_make_sweep.py
"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_sweep as ms  # noqa: E402

BASE = json.loads(ms.serialize(ms.build_sweep()))
VISIBLE = ms.load_visible()
failures = total = 0


def report(ok, name, detail=""):
    global failures, total
    total += 1
    if not ok:
        failures += 1
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, ("  (" + detail + ")") if detail and not ok else ""))


def by_id(doc, cid):
    return next(c for c in doc["cases"] if c["id"] == cid)


def stops(change):
    doc = copy.deepcopy(BASE)
    change(doc)
    try:
        ms.check_sweep(doc, VISIBLE)
    except ms.CaseError as err:
        return str(err)
    return None


def plant(name, change, want):
    msg = stops(change)
    report(msg is not None and want in msg, name, (msg or "accepted").splitlines()[0])


def set_body(doc, cid, step, **changes):
    ev = by_id(doc, cid)["events"][step - 1]
    ev["body"] = ms.php_json(ms.edit(json.loads(ev["body"]), **changes))


def main():
    msg = stops(lambda d: None)
    report(msg is None, "unchanged sweep set accepted", (msg or "").splitlines()[0] if msg else "")

    plant("duplicate case id", lambda d: d["cases"].append(copy.deepcopy(by_id(d, "SW05"))), "duplicate case id")
    plant("order number shared with a visible case",
          lambda d: set_body(d, "SW08", 1, number="41001"), "shared with N01")
    plant("order number shared between sweep cases",
          lambda d: set_body(d, "SW08", 1, number="71050"), "shared with SW05")
    plant("order number outside 71001-71999", lambda d: set_body(d, "SW08", 1, number="72001"), "outside")
    plant("e-mail not on the sweep domain",
          lambda d: set_body(d, "SW08", 1, **{"billing.email": "mia.grgic@mail.harbour-sync.example.com"}),
          "is not on sweep.harbour-sync.example.com")
    plant("gated true", lambda d: by_id(d, "SW04").update(gated=True), "gated must be false")
    plant("wrong expected result",
          lambda d: by_id(d, "SW08")["events"][0]["expect"].update(result=["updated"]), "rules give created")
    plant("wrong expected_final", lambda d: by_id(d, "SW05")["expected_final"]["deals"][0].update(count=2),
          "expected_final disagrees")
    plant("wrong limit_final", lambda d: by_id(d, "SW01").update(limit_final=by_id(d, "SW01")["expected_final"]),
          "limit_final is not")
    plant("faults on the second event of a group",
          lambda d: by_id(d, "SW01")["events"][1].update(faults={"deals": ["429:5"]}), "faults only on its first event")
    plant("delay_s without a parallel group",
          lambda d: by_id(d, "SW08")["events"][0].update(delay_s=1), "delay_s needs a parallel group")
    plant("unknown sign mode", lambda d: by_id(d, "SW20")["events"][0].update(sign="blank"), "unknown sign mode")
    plant("unknown fault target",
          lambda d: by_id(d, "SW21")["events"][0].update(faults={"links": ["503"]}), "unknown fault target")
    plant("case_count wrong", lambda d: d.update(case_count=1), "case_count")

    a, b = ms.serialize(ms.build_sweep()), ms.serialize(ms.build_sweep())
    report(a == b, "two builds give the same bytes")

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "cases", "sweep.json")
        real_out, real_build = ms.OUT, ms.build_sweep
        planted = ms.build_sweep()
        planted.append(copy.deepcopy(planted[0]))
        ms.OUT, ms.build_sweep = out, (lambda: planted)
        code = None
        try:
            ms.main([])
        except SystemExit as e:
            code = e.code
        finally:
            ms.OUT, ms.build_sweep = real_out, real_build
        report(code == 1 and not os.path.exists(out), "generator stops and writes nothing",
               "exit %s, file written: %s" % (code, os.path.exists(out)))

    print("%d of %d checks failed" % (failures, total))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
