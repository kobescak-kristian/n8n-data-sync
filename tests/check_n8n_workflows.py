#!/usr/bin/env python3
"""Keyless check of n8n workflow JSON files.

Named by the "Entry points" line of the build's blueprint template; it
checks webhook auth, the error workflow and that no credential value is
in the JSON.
A shared checker.

Copy it into the build repository as tests/check_n8n_workflows.py and run
it before every frozen commit:

    python tests/check_n8n_workflows.py workflows/
    python tests/check_n8n_workflows.py --selftest

Checks (one FAIL line per finding; exit 1 on any finding, 0 when clean,
2 on a usage or parse error):
  1. every Webhook node has `authentication` set and not "none" (n8n
     leaves the key out when the node uses its default, none);
  2. every workflow names an error workflow (settings.errorWorkflow),
     unless it is itself an error workflow (has an Error Trigger node)
     or its name is listed with --no-error-workflow;
  3. no credential-looking value in the JSON: a known key shape
     (sk-, xox., AKIA, ghp_, AIza, a private key block) anywhere, or a
     literal value under a key named password, apiKey, token or secret
     that is not an n8n expression and not a placeholder.

Only files that look like n8n workflows (a dict with a "nodes" list) are
checked; other JSON files are skipped with a SKIP line.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WEBHOOK_TYPES = {"n8n-nodes-base.webhook"}
ERROR_TRIGGER_TYPE = "n8n-nodes-base.errorTrigger"

SECRET_SHAPE = re.compile(
    r"(sk-(ant-)?[A-Za-z0-9_-]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{30,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
SECRET_KEYS = {
    "password", "apikey", "api_key", "token", "secret", "accesstoken",
    "access_token", "clientsecret", "client_secret", "privatekey",
    "private_key",
}
PLACEHOLDERS = {"", "placeholder", "replace_me", "replaceme", "changeme", "xxx"}


def is_placeholder(value: str) -> bool:
    v = value.strip()
    if v.lower() in PLACEHOLDERS:
        return True
    if v.startswith("=") or "{{" in v or v.startswith("$"):
        return True  # n8n expression, not a literal
    return v.startswith("<") and v.endswith(">")


def walk(obj, path="$"):
    """Yield (path, key, value) for every string value in a JSON tree."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str):
                yield f"{path}.{key}", key, val
            else:
                yield from walk(val, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from walk(val, f"{path}[{i}]")


def check_workflow(data: dict, label: str, no_error_workflow: set[str]) -> list[str]:
    findings: list[str] = []
    nodes = data.get("nodes") or []
    name = data.get("name") or label

    # 1. webhook authentication
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in WEBHOOK_TYPES:
            continue
        auth = (node.get("parameters") or {}).get("authentication", "none")
        if not auth or auth == "none":
            findings.append(
                f"FAIL {label}: webhook node '{node.get('name')}' has no authentication"
            )

    # 2. error workflow
    is_error_workflow = any(
        isinstance(n, dict) and n.get("type") == ERROR_TRIGGER_TYPE for n in nodes
    )
    error_workflow = (data.get("settings") or {}).get("errorWorkflow")
    if not is_error_workflow and name not in no_error_workflow and not error_workflow:
        findings.append(f"FAIL {label}: no settings.errorWorkflow")

    # 3. credential-looking values
    for path, key, value in walk(data):
        if SECRET_SHAPE.search(value):
            findings.append(f"FAIL {label}: credential-shaped value at {path}")
        elif key.lower() in SECRET_KEYS and not is_placeholder(value):
            findings.append(f"FAIL {label}: literal value under key '{key}' at {path}")
    return findings


def collect_files(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*.json") if "node_modules" not in f.parts))
        else:
            files.append(p)
    return files


def run(paths: list[str], no_error_workflow: set[str]) -> int:
    findings: list[str] = []
    checked = 0
    for file in collect_files(paths):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR {file}: {exc}")
            return 2
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            print(f"SKIP {file}: not an n8n workflow")
            continue
        checked += 1
        findings.extend(check_workflow(data, str(file), no_error_workflow))
    for line in findings:
        print(line)
    print(f"{'FAIL' if findings else 'OK'}: {checked} workflows checked, {len(findings)} findings")
    return 1 if findings else 0


def selftest() -> int:
    clean = {
        "name": "clean",
        "settings": {"errorWorkflow": "ErrAlert"},
        "nodes": [
            {"name": "In", "type": "n8n-nodes-base.webhook",
             "parameters": {"authentication": "headerAuth", "path": "in"}},
            {"name": "Call", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"headerParameters": {"parameters": [
                 {"name": "Authorization", "value": "=Bearer {{ $json.t }}"}]}}},
        ],
    }
    open_hook = {
        "name": "open",
        "settings": {"errorWorkflow": "ErrAlert"},
        "nodes": [{"name": "In", "type": "n8n-nodes-base.webhook",
                   "parameters": {"path": "in"}}],
    }
    no_error = {"name": "noerr", "settings": {}, "nodes": [
        {"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}]}
    error_wf = {"name": "ErrAlert", "settings": {}, "nodes": [
        {"name": "Err", "type": ERROR_TRIGGER_TYPE, "parameters": {}}]}
    leaky = {
        "name": "leaky",
        "settings": {"errorWorkflow": "ErrAlert"},
        "nodes": [
            # built at run time so no token-shaped literal sits in this file
            {"name": "Slack", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"token": "xoxb-" + "1234567890-" + "abcdefghij"}},
            {"name": "Mail", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"password": "hunter2"}},
            {"name": "Ok", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"password": "<set in n8n>", "apiKey": "={{ $env.K }}"}},
        ],
    }
    # leaky: one finding per value (the xoxb token counts once, as a shape)
    cases = [
        (clean, 0), (open_hook, 1), (no_error, 1), (error_wf, 0), (leaky, 2),
    ]
    failed = 0
    for data, expected in cases:
        got = check_workflow(data, data["name"], set())
        status = "ok" if len(got) == expected else "WRONG"
        if status == "WRONG":
            failed += 1
        print(f"selftest {data['name']}: expected {expected}, got {len(got)} {status}")
        for line in got:
            print("   ", line)
    allowed = check_workflow(no_error, "noerr", {"noerr"})
    if allowed:
        failed += 1
        print("selftest --no-error-workflow: WRONG, still reported")
    print("selftest OK" if not failed else f"selftest FAILED ({failed})")
    return 0 if not failed else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="workflow JSON files or directories")
    parser.add_argument("--no-error-workflow", action="append", default=[],
                        metavar="NAME", help="name of a test-only workflow that needs no errorWorkflow (repeatable)")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.paths:
        parser.print_usage()
        return 2
    return run(args.paths, set(args.no_error_workflow))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
