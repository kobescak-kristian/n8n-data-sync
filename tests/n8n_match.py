"""Check that the Q129 workflows running in n8n are the committed test copy (R2 finding 3).

    python tests/n8n_match.py        # exit 0 = n8n runs workflows/test/*.json; 1 = differs; prints the hash

Reads the 6 Q129 workflows through the n8n API (read only). For each one it takes the published version
(the one n8n runs), puts the placeholders back (__WF:key__, __CRED:type__), drops ids and positions, and
compares nodes, connections and settings with workflows/test/<key>.json. tests/runner.py calls match()
at the start of every run and writes the hash into the results file; tests/score.py requires one hash
in all 3 gated runs.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
TEST_DIR = ROOT / "workflows" / "test"
NODE_KEYS = ("name", "type", "typeVersion", "parameters", "credentials", "onError", "retryOnFail", "maxTries",
             "waitBetweenTries", "alwaysOutputData", "executeOnce", "webhookId", "disabled")
SETTING_KEYS = ("errorWorkflow", "executionOrder")


def local_docs():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(TEST_DIR.glob("*.json"))}


def norm(doc):
    nodes = {}
    for n in doc["nodes"]:
        m = {k: n[k] for k in NODE_KEYS if k in n}
        if "credentials" in m:
            m["credentials"] = {t: {"id": f"__CRED:{t}__", "name": c.get("name")} for t, c in m["credentials"].items()}
        nodes[n["name"]] = m
    settings = {k: doc.get("settings", {}).get(k) for k in SETTING_KEYS}
    return {"name": doc["name"], "nodes": nodes, "connections": doc["connections"], "settings": settings}


def workflow_hash(docs=None):
    docs = docs or local_docs()
    blob = json.dumps({k: norm(d) for k, d in sorted(docs.items())}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def match(api):
    """Returns (hash of the committed test copy, list of differences; empty = n8n runs exactly that copy)."""
    docs = local_docs()
    found, problems = {}, []
    for key, d in docs.items():
        w = api.workflow_by_name(d["name"])
        if not w:
            problems.append(f"{d['name']}: not in n8n")
            continue
        found[key] = api.request("GET", f"/workflows/{w['id']}")
    ids = {w["id"]: key for key, w in found.items()}
    for key, w in found.items():
        name = docs[key]["name"]
        av = w.get("activeVersion") or {}
        if not w.get("active") or not av or w.get("activeVersionId") != w.get("versionId"):
            problems.append(f"{name}: not published, or the draft differs from the published version")
            continue
        s = json.dumps({"name": w["name"], "nodes": av.get("nodes", []), "connections": av.get("connections", {}),
                        "settings": w.get("settings") or {}})
        for wid, k in ids.items():
            s = s.replace(json.dumps(wid), json.dumps(f"__WF:{k}__"))
        got, want = norm(json.loads(s)), norm(docs[key])
        for n, m in got["nodes"].items():
            if "webhookId" not in want["nodes"].get(n, {}):
                m.pop("webhookId", None)  # n8n gives Slack nodes their own webhook ID on save
        if got == want:
            continue
        for part in ("connections", "settings"):
            if got[part] != want[part]:
                problems.append(f"{name}: {part} differ")
        for n in sorted(set(got["nodes"]) | set(want["nodes"])):
            if got["nodes"].get(n) != want["nodes"].get(n):
                problems.append(f"{name}: node '{n}' differs")
    return workflow_hash(docs), problems


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    from n8n_api import Api
    h, problems = match(Api())
    print(f"workflow hash {h}")
    for p in problems:
        print("DIFF " + p)
    print("n8n runs the committed test copy" if not problems else f"{len(problems)} differences")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
