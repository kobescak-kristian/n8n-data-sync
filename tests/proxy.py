"""Fault proxy between the Q129 test workflows and HubSpot (tests/CASES.md 5.4). Port 8130.

    python tests/proxy.py            # runs until stopped; tests/runner.py starts it when it is not running

Every request is forwarded to https://api.hubapi.com with its own headers (the n8n HubSpot credential adds
the key), except the upsert requests of a step that has faults:
  POST /crm/v3/objects/contacts/batch/upsert  (target "contacts")
  POST /crm/v3/objects/deals/batch/upsert     (target "deals")
The n-th upsert request of a target in a step gets the n-th response of its fault list; after the list,
every request passes. Responses: pass, 429, 429:<seconds>, 500, 502, 503, 504, 400, 401, 403, 404 (answered
here, not forwarded), timeout (not forwarded, never answered), timeout_after_forward (forwarded, the answer
held past the 15 s timeout of the workflow), close (connection closed, not forwarded).

Control (local test runner only):
  POST /__control  {"step": "<label>", "faults": {...} | null}   starts a new step, counters to 0
  GET  /__counts   {"step", "seen": {...}, "forwarded": {...}, "real_errors": [...]}
Real non-2xx answers from HubSpot are kept in real_errors (time, path, status) so a miss caused by HubSpot
itself can be explained in evals/RESULTS.md.
"""
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8130
UPSTREAM = "https://api.hubapi.com"
TARGETS = {"/crm/v3/objects/contacts/batch/upsert": "contacts", "/crm/v3/objects/deals/batch/upsert": "deals"}
HOLD_SECONDS = 20
FORWARD_HEADERS = ("authorization", "content-type", "accept")

lock = threading.Lock()
state = {"step": None, "faults": {}, "seen": {"contacts": 0, "deals": 0},
         "forwarded": {"contacts": 0, "deals": 0}, "requests": 0, "real_errors": []}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, status, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _forward(self, body):
        req = urllib.request.Request(UPSTREAM + self.path, data=body if self.command != "GET" else None,
                                     method=self.command)
        for k, v in self.headers.items():
            if k.lower() in FORWARD_HEADERS:
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, r.read(), {k: v for k, v in r.headers.items()
                                            if k.lower() in ("retry-after", "content-type")}
        except urllib.error.HTTPError as e:
            data = e.read()
            with lock:
                state["real_errors"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": state["step"],
                                             "path": self.path.split("?")[0], "status": e.code})
            return e.code, data, {k: v for k, v in e.headers.items() if k.lower() in ("retry-after",)}
        except Exception as e:  # noqa: BLE001 - network trouble to HubSpot is answered as a 502, logged
            with lock:
                state["real_errors"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": state["step"],
                                             "path": self.path.split("?")[0], "status": "network: " + str(e)[:80]})
            return 502, json.dumps({"status": "error", "message": "proxy could not reach HubSpot"}).encode(), {}

    def _control(self, body):
        if self.path == "/__control":
            d = json.loads(body or b"{}")
            with lock:
                state["step"] = d.get("step")
                state["faults"] = d.get("faults") or {}
                state["seen"] = {"contacts": 0, "deals": 0}
                state["forwarded"] = {"contacts": 0, "deals": 0}
            self._send(200, {"ok": True})
        elif self.path == "/__counts":
            with lock:
                self._send(200, {k: state[k] for k in ("step", "seen", "forwarded", "requests", "real_errors")})
        else:
            self._send(404, {"error": "unknown control path"})

    def _handle(self):
        body = self._body() if self.command in ("POST", "PUT", "PATCH", "DELETE") else b""
        if self.path.startswith("/__"):
            return self._control(body)
        path = self.path.split("?")[0]
        target = TARGETS.get(path) if self.command == "POST" else None
        answer = "pass"
        with lock:
            state["requests"] += 1
            if target:
                state["seen"][target] += 1
                seq = state["faults"].get(target) or []
                n = state["seen"][target]
                answer = seq[n - 1] if n <= len(seq) else "pass"
                if answer in ("pass", "timeout_after_forward"):
                    state["forwarded"][target] += 1
        if answer == "pass":
            status, data, headers = self._forward(body)
            return self._send(status, data, headers)
        if answer == "timeout_after_forward":
            status, data, headers = self._forward(body)
            time.sleep(HOLD_SECONDS)
            try:
                self._send(status, data, headers)
            except OSError:
                pass
            return None
        if answer == "timeout":
            time.sleep(HOLD_SECONDS)
            self.close_connection = True
            return None
        if answer == "close":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return None
        code, _, secs = answer.partition(":")
        headers = {"Retry-After": secs} if secs else {}
        return self._send(int(code), {"status": "error", "message": f"simulated {code} (fault proxy)",
                                      "category": "SIMULATED"}, headers)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"fault proxy on 127.0.0.1:{PORT} -> {UPSTREAM}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
