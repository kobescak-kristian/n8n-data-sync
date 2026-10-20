"""Small client for the n8n public API (create, update, publish, tag workflows).

The API key lives in the git-ignored `.env` at the repository root
(N8N_URL, N8N_API_KEY; see .env.example). It is read here and never printed.
Shared-n8n rules: only workflows whose name starts with "Q129 " are touched.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
PREFIX = "Q129 "
TAG = "q129"


def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.setdefault("N8N_URL", "http://localhost:5678")
    return env


class Api:
    def __init__(self):
        env = load_env()
        self.base = env["N8N_URL"].rstrip("/") + "/api/v1"
        self.key = env.get("N8N_API_KEY", "")
        if not self.key:
            sys.exit("N8N_API_KEY missing in .env (n8n Settings > n8n API)")

    def request(self, method, path, body=None, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-N8N-API-KEY", self.key)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:800]}")
        except urllib.error.URLError as e:
            sys.exit(f"{method} {path} -> cannot reach n8n: {e.reason}")

    def list_all(self, path, params=None):
        items, cursor = [], None
        while True:
            p = dict(params or {}, limit=100)
            if cursor:
                p["cursor"] = cursor
            page = self.request("GET", path, params=p)
            items.extend(page.get("data", []))
            cursor = page.get("nextCursor")
            if not cursor:
                return items

    def workflow_by_name(self, name):
        for w in self.list_all("/workflows", {"name": name, "excludePinnedData": "true"}):
            if w.get("name") == name and not w.get("isArchived"):
                return w
        return None

    def tag_id(self):
        for t in self.list_all("/tags"):
            if t["name"] == TAG:
                return t["id"]
        return self.request("POST", "/tags", {"name": TAG})["id"]

    def push(self, doc, publish=True):
        """Create or update one Q129 workflow by name; publish and tag it. Returns its id."""
        if not doc["name"].startswith(PREFIX):
            sys.exit("refusing a workflow without the Q129 prefix: " + doc["name"])
        body = {k: doc[k] for k in ("name", "nodes", "connections", "settings")}
        existing = self.workflow_by_name(doc["name"])
        if existing:
            wid = self.request("PUT", f"/workflows/{existing['id']}", body)["id"]
        else:
            wid = self.request("POST", "/workflows", body)["id"]
        self.request("PUT", f"/workflows/{wid}/tags", [{"id": self.tag_id()}])
        if publish:
            self.request("POST", f"/workflows/{wid}/publish", {})
        return wid
