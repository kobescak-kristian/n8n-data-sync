"""Gate verdict from saved runs (evals/eval_config.yaml).

    python tests/score.py tests/results/gated-1.json tests/results/gated-2.json tests/results/gated-3.json

PASS iff there are 3 runs over the same case list and the same workflow commit, and in every run every gated
case passed, hard_rule_breaks == 0 and secret_leaks == 0. Reports the worst run, the misses per hard rule,
and every case whose pass/fail or misses changed between runs. With fewer than 3 files it reports the
numbers and says that there is no verdict. Exit 0 = PASS, 1 = FAIL or no verdict, 2 = bad input.
"""
import json
import sys
from collections import Counter
from pathlib import Path


def main(paths):
    sys.stdout.reconfigure(encoding="utf-8")
    if not paths:
        print(__doc__)
        return 2
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    lists = [[c["id"] for c in r["cases"]] for r in runs]
    commits = {r.get("workflow_commit") for r in runs}
    for r in runs:
        rules = Counter(m["rule"] for c in r["cases"] for m in c["misses"])
        print(f"{r['label']}: {r['passed']} of {r['cases_run']} cases passed; hard-rule breaks "
              f"{r['hard_rule_breaks']} {dict(rules) if rules else ''}; secret leaks {r.get('secret_leaks')}; "
              f"commit {r.get('workflow_commit')}; real HubSpot errors {len(r.get('proxy_real_errors', []))}")
    worst = min(runs, key=lambda r: (r["passed"], -r["hard_rule_breaks"]))
    print(f"worst run: {worst['label']} ({worst['passed']} of {worst['cases_run']})")
    changed = []
    if len(runs) > 1:
        for cid in lists[0]:
            sig = []
            for r in runs:
                c = next((x for x in r["cases"] if x["id"] == cid), None)
                sig.append(None if c is None else (c["pass"], tuple(sorted(m["where"] for m in c["misses"]))))
            if len(set(sig)) > 1:
                changed.append(cid)
        print("changed between runs: " + (", ".join(changed) if changed else "none"))
    failed = sorted({c["id"] for r in runs for c in r["cases"] if not c["pass"]})
    if failed:
        print("cases with a miss in any run: " + ", ".join(failed))
    if len(runs) != 3:
        print("NO VERDICT: the gate needs 3 runs")
        return 1
    problems = []
    if len({tuple(x) for x in lists}) != 1:
        problems.append("the 3 runs did not run the same case list")
    if len(commits) != 1:
        problems.append("the 3 runs were not on one workflow commit")
    if any(r["passed"] != r["cases_run"] for r in runs):
        problems.append("a case missed")
    if any(r["hard_rule_breaks"] for r in runs):
        problems.append("hard-rule breaks")
    if any(r.get("secret_leaks") for r in runs):
        problems.append("secret leaks")
    print("GATE " + ("PASS" if not problems else "FAIL: " + "; ".join(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
