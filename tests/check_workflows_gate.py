"""Workflow check before the frozen commit, with Kristian's recorded exception (adr/003).

    python tests/check_workflows_gate.py      # exit 0 = only the accepted findings; 1 = anything else

Runs tests/check_n8n_workflows.py (a shared checker; only its docstring differs from the shared copy) on workflows/test and workflows/live.
Kristian's decision 2026-10-21 ("Yes to both."), 4 accepted items:
  - the 2 HMAC-signed webhooks 'Order in' (entry.json) and 'Summary in (test)' (summary.json): WooCommerce
    cannot send an auth header; the signature is checked in the workflow on the raw bytes (adr/003);
  - the 2 sub-workflows Core and HubSpot call have no error workflow of their own: they run only from
    Entry and Replay, whose error workflow covers them; their own would send 2 crash alerts for one crash.
Any other finding, or a missing accepted one (the check would then be stale), is exit 1.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB_WORKFLOWS = ("Q129 Core: check and sync one order", "Q129 HubSpot call")
ACCEPTED = {("test", "entry.json", "Order in"), ("live", "entry.json", "Order in"),
            ("test", "summary.json", "Summary in (test)")}
LINE = re.compile(r"^FAIL .*[\\/](test|live)[\\/]([a-z-]+\.json): webhook node '(.+)' has no authentication$")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "tests" / "check_n8n_workflows.py"), "workflows/test", "workflows/live"]
    for name in SUB_WORKFLOWS:
        cmd += ["--no-error-workflow", name]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode not in (0, 1):
        print(r.stdout + r.stderr)
        return 1
    seen, other = set(), []
    for line in r.stdout.splitlines():
        if not line.startswith("FAIL "):
            continue
        m = LINE.match(line)
        if m and m.groups() in ACCEPTED:
            seen.add(m.groups())
        elif not line.startswith("FAIL:"):
            other.append(line)
    for line in other:
        print(line)
    missing = ACCEPTED - seen
    for folder, f, node in sorted(missing):
        print(f"STALE accepted finding not seen: {folder}/{f} '{node}'")
    ok = not other and not missing
    print(f"{len(seen)} accepted findings (adr/003), {len(other)} other findings: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
