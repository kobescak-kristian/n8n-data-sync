"""Static check: no n8n Code node with "Execute Once" reads all its input items (H-R02).

    python tests/check_execute_once.py            -> checks workflows/test/*.json and workflows/live/*.json
    python tests/check_execute_once.py --self-test -> also shows that a planted node is caught

n8n passes only the first input item to a node with executeOnce, so `$input.all()` or `$items(` there silently
sees one item. Exit 0 = no such node; exit 1 = a list of workflow and node names.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READS_ALL = ("$input.all()", "$items(")


def findings(doc):
    out = []
    for n in doc.get("nodes", []):
        code = n.get("parameters", {}).get("jsCode", "")
        if n.get("executeOnce") and any(r in code for r in READS_ALL):
            out.append(n["name"])
    return out


def main():
    bad = 0
    files = sorted((ROOT / "workflows" / "test").glob("*.json")) + sorted((ROOT / "workflows" / "live").glob("*.json"))
    for f in files:
        for name in findings(json.loads(f.read_text(encoding="utf-8"))):
            bad += 1
            print(f"FAIL {f.parent.name}/{f.name}: node \"{name}\" has executeOnce and reads all input items")
    if "--self-test" in sys.argv:
        planted = {"nodes": [{"name": "planted", "executeOnce": True, "parameters": {"jsCode": "return $input.all();"}},
                             {"name": "fine", "parameters": {"jsCode": "return $input.all();"}}]}
        if findings(planted) != ["planted"]:
            print("FAIL self-test: the planted node was not caught")
            bad += 1
        else:
            print("self-test: planted node caught, the node without executeOnce passed")
    print(f"{len(files)} workflow files checked, {bad} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
