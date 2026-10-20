"""Planted-mistake test for the whole-set check in make_cases.py (BLUEPRINT.md section 5).

Plants one mistake at a time in a copy of the visible cases; the check must
stop on every one, with the right message, and must accept the unchanged set.
Also checks that the generator writes nothing when the check stops, that two
builds give the same bytes, and that hold-out rules apply in --set holdout.
Run: python tests/test_make_cases.py
"""
import copy
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_cases as mc  # noqa: E402

BASE = mc.build_visible()


def by_id(cases, cid):
    return next(c for c in cases if c["id"] == cid)


def set_payload(cases, cid, step, **changes):
    """Change the order JSON inside one event body and encode it again."""
    ev = by_id(cases, cid)["events"][step - 1]
    ev["body"] = mc.php_json(mc.edit(json.loads(ev["body"]), **changes))


def as_doc(cases, set_name="visible"):
    return {"format_version": mc.FORMAT_VERSION, "set": set_name,
            "case_count": len(cases), "cases": cases}


def stops(cases, set_name="visible", doc_change=None):
    doc = as_doc(cases, set_name)
    if doc_change:
        doc_change(doc)
    try:
        mc.check_doc(doc, set_name)
    except mc.CaseError as err:
        return str(err)
    return None


def as_holdout(cases):
    """The visible set with hold-out IDs, order numbers (41xxx/42xxx -> 61xxx/62xxx) and domain."""
    text = json.dumps(cases, ensure_ascii=True)
    text = re.sub(r"(?i)harbour-sync\.example\.com", "harbour-sync-h.example.com", text)
    text = re.sub(r"\b4([12]\d{3})\b", r"6\1", text)
    out = json.loads(text)
    for c in out:
        c["id"] = "H-" + c["id"]
        c["related_to"] = ["H-" + r for r in c["related_to"]]
        c["depends_on"] = ["H-" + d for d in c["depends_on"]]
    return out


PLANTS = [
    ("duplicate case id", "duplicate case id",
     lambda cs: cs.append(copy.deepcopy(by_id(cs, "N01")))),
    ("order number shared, cases not related", "order number 41001 shared",
     lambda cs: set_payload(cs, "N02", 1, number="41001")),
    ("e-mail shared (other letter case), cases not related", "e-mail marta.horvat@",
     lambda cs: set_payload(cs, "M06", 1, **{"billing.email": "Marta.Horvat@" + mc.MAIL})),
    ("relation removed from E06 (shares N01's e-mail)", "shared with N01",
     lambda cs: by_id(cs, "E06").update(related_to=[])),
    ("missing dependency", "missing dependency N99",
     lambda cs: by_id(cs, "E06").update(depends_on=["N99"])),
    ("dependency after the case", "comes after",
     lambda cs: by_id(cs, "N01").update(depends_on=["E06"])),
    ("unknown result", "unknown result",
     lambda cs: by_id(cs, "N01")["events"][0]["expect"].update(result=["synced"])),
    ("unknown reason", "unknown reason",
     lambda cs: by_id(cs, "F02")["events"][0]["expect"].update(reasons=["no_email"])),
    ("unknown http code", "unknown http code",
     lambda cs: by_id(cs, "A01")["events"][0]["expect"].update(http=403)),
    ("unknown alert type", "unknown alert type",
     lambda cs: by_id(cs, "F02")["events"][0]["expect"]["alerts"][0].update(type="email")),
    ("unknown attention row state", "unknown attention row state",
     lambda cs: by_id(cs, "F02")["expected_final"]["attention_rows"][0].update(state="pending")),
    ("unknown deal stage", "unknown deal stage",
     lambda cs: by_id(cs, "N01")["expected_final"]["deals"][0]["fields"].update(stage="Won")),
    ("unknown fault response", "unknown fault response",
     lambda cs: by_id(cs, "T01")["events"][0].update(faults={"contacts": ["418"]})),
    ("unknown kind", "unknown kind",
     lambda cs: by_id(cs, "N01").update(kind="X")),
    ("kind count off", "kind S has 4 cases",
     lambda cs: cs.remove(by_id(cs, "S05"))),
    ("replay of a later step", "replay must name an earlier step",
     lambda cs: by_id(cs, "R01")["events"][1].update(row_from_step=2)),
    ("expected result disagrees with the rules", "disagrees with the rules",
     lambda cs: by_id(cs, "U04")["events"][2]["expect"].update(result=["updated"])),
    ("expected reason disagrees with the rules", "disagrees with the rules",
     lambda cs: by_id(cs, "V02")["events"][0]["expect"].update(reasons=["missing_total"])),
    ("expected end value disagrees with the rules", "expected_final.deals disagrees",
     lambda cs: by_id(cs, "N01")["expected_final"]["deals"][0]["fields"].update(amount="2490.01")),
    ("expected kept phone disagrees with the rules", "expected_final.contacts disagrees",
     lambda cs: by_id(cs, "E03")["expected_final"]["contacts"][0]["fields"].update(phone="")),
    ("order number outside the visible range", "outside the visible range",
     lambda cs: set_payload(cs, "N01", 1, number="61001")),
    ("e-mail outside the visible domain", "not on the visible domain",
     lambda cs: set_payload(cs, "N02", 1, **{"billing.email": "tomislav.kralj@example.com"})),
    # gate v2 (R1 findings 4 and 11)
    ("parallel group with different bodies", "must have the same body bytes",
     lambda cs: set_payload(cs, "D02", 2, date_modified_gmt="2026-10-09T09:00:00")),
    ("parallel group with faults", "faults must be null",
     lambda cs: by_id(cs, "D02")["events"][1].update(faults={"deals": ["503", "pass"]})),
    ("parallel group with force_crash", "force_crash must be false",
     lambda cs: by_id(cs, "D06")["events"][2].update(force_crash=True)),
    ("case not gated", "gated must be true",
     lambda cs: by_id(cs, "N01").update(gated=False)),
    ("wrong simulated flag", "simulated must be True",
     lambda cs: by_id(cs, "T01").update(simulated=False)),
]

DOC_PLANTS = [
    ("case_count does not match the file", "case_count is 66",
     lambda doc: doc.update(case_count=66)),
    ("unknown format_version", "format_version must be 1",
     lambda doc: doc.update(format_version=2)),
]


def main():
    failures, total = 0, 0

    def report(ok, name, msg=""):
        nonlocal failures, total
        total += 1
        failures += not ok
        print(("PASS " if ok else "FAIL ") + name + ((" | " + msg) if msg else ""))

    msg = stops(copy.deepcopy(BASE))
    report(msg is None, "unchanged set accepted", msg or "")

    for name, expected, change in PLANTS:
        cases = copy.deepcopy(BASE)
        change(cases)
        msg = stops(cases)
        first = (msg or "not caught").splitlines()[0]
        report(msg is not None and expected in msg, name,
               first if msg and expected in msg else "wanted %r, got: %s" % (expected, msg))

    for name, expected, change in DOC_PLANTS:
        msg = stops(copy.deepcopy(BASE), doc_change=change)
        first = (msg or "not caught").splitlines()[0]
        report(msg is not None and expected in msg, name,
               first if msg and expected in msg else "wanted %r, got: %s" % (expected, msg))

    # hold-out rules: visible IDs are refused in a hold-out set ...
    msg = stops(copy.deepcopy(BASE), "holdout")
    report(msg is not None and "holdout id pattern" in msg,
           "visible ids refused as hold-out", (msg or "not caught").splitlines()[0])
    # ... and the same cases moved to hold-out IDs, numbers and domains pass
    msg = stops(as_holdout(BASE), "holdout")
    report(msg is None, "set moved to the hold-out ranges accepted", (msg or "").splitlines()[0] if msg else "")

    # same bytes on two builds
    a, b = mc.serialize(mc.build_visible(), "visible"), mc.serialize(mc.build_visible(), "visible")
    report(a == b, "two builds give the same bytes")

    # the generator writes nothing when the check stops
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "cases", "visible.json")
        real_out, real_build = mc.OUT, mc.build_visible
        planted = copy.deepcopy(BASE)
        planted.append(copy.deepcopy(by_id(planted, "N01")))
        mc.OUT, mc.build_visible = out, (lambda: planted)
        code = None
        try:
            mc.main([])
        except SystemExit as e:
            code = e.code
        finally:
            mc.OUT, mc.build_visible = real_out, real_build
        report(code == 1 and not os.path.exists(out), "generator stops and writes nothing",
               "exit %s, file written: %s" % (code, os.path.exists(out)))

    print("%d of %d checks failed" % (failures, total))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
