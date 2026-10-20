"""Generate and load the n8n workflows of the data sync (Q-129, n8n-data-sync).

python workflows/build.py          -> workflows/*.json (test copy) and workflows/live/*.json (live export);
                                      placeholders only, no credential or workflow IDs
python workflows/build.py --push   -> also creates the q129_* data tables that are missing (and adds missing
                                      columns), then creates/updates and publishes every Q129 workflow of the
                                      TEST copy in local n8n through the n8n API (key in the git-ignored .env)

Test copy vs live export (BLUEPRINT section 3, "Test and live"): the test copy sends HubSpot calls to the
local fault proxy (tests/proxy.py, port 8130), honours the forced-crash header of the test runner
(CASES.md 3.13) and has a signed test webhook for the summary; the live export calls api.hubapi.com, has
no crash switch and runs the summary every day at 08:00.

The workflow logic lives here and in sync_js.py; the JSON files are build output.
"""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "workflows"
sys.path.insert(0, str(OUT))
sys.path.insert(0, str(ROOT / "tools"))
import sync_js as J  # noqa: E402

CHANNEL = "#data-sync-alerts"
PROXY_BASE = "http://127.0.0.1:8130"
LIVE_BASE = "https://api.hubapi.com"
CRED_NAMES = {"hubspotAppToken": "HubSpot n8n-data-sync", "slackApi": "Slack n8n-data-sync",
              "crypto": "Crypto WooCommerce n8n-data-sync", "httpBasicAuth": "Replay n8n-data-sync"}
TABLES = {
    "q129_ledger": [("order_number", "string"), ("version", "string"), ("data_hash", "string"),
                    ("updated_at", "string")],
    "q129_attention": [("order_number", "string"), ("version", "string"), ("reason", "string"),
                       ("reasons", "string"), ("body", "string"), ("state", "string"), ("created_at", "string"),
                       ("request_id", "string"), ("delivery_id", "string"), ("replays", "number"),
                       ("closed_by", "string"), ("closed_at", "string"), ("closed_request", "string")],
    "q129_log": [("at", "string"), ("request_id", "string"), ("delivery_id", "string"), ("topic", "string"),
                 ("mode", "string"), ("order_number", "string"), ("result", "string"), ("reasons", "string"),
                 ("contact_id", "string"), ("deal_id", "string"), ("attempts", "string"), ("seconds", "number"),
                 ("row_id", "string"), ("user", "string")],
    "q129_alerts": [("at", "string"), ("type", "string"), ("order_number", "string"), ("reason", "string"),
                    ("row_id", "string"), ("request_id", "string"), ("execution_id", "string"),
                    ("slack_ts", "string"), ("slack_error", "string"), ("text", "string"), ("data", "string")],
}


class WF:
    def __init__(self, key, name, live):
        self.key, self.name, self.live = key, name, live
        self.nodes, self.conn = [], {}
        self.settings = {"executionOrder": "v1"}

    def add(self, name, ntype, version, params, x, y=0, cred=None, **extra):
        n = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"q129/{self.key}/{name}")), "name": name, "type": ntype,
             "typeVersion": version, "position": [int(x * 240), int(y * 170)], "parameters": params}
        if cred:
            n["credentials"] = {cred: {"id": f"__CRED:{cred}__", "name": CRED_NAMES[cred]}}
        n.update(extra)
        self.nodes.append(n)
        return name

    def link(self, a, b, out=0):
        outs = self.conn.setdefault(a, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": b, "type": "main", "index": 0})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def doc(self):
        return {"name": self.name, "nodes": self.nodes, "connections": self.conn, "settings": self.settings}


def js(w, text):
    base = LIVE_BASE if w.live else PROXY_BASE
    return text.strip().replace("__BASE__", base).replace("__TEST__", "false" if w.live else "true") + "\n"


def code(w, name, text, x, y=0, **extra):
    return w.add(name, "n8n-nodes-base.code", 2, {"jsCode": js(w, text)}, x, y, **extra)


def if_true(w, name, expr, x, y=0):
    return w.add(name, "n8n-nodes-base.if", 2.2, {"conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"q129/{w.key}/{name}")), "leftValue": expr,
                        "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
        "combinator": "and"}, "looseTypeValidation": True, "options": {}}, x, y)


def table(name):
    return {"__rl": True, "mode": "name", "value": name}


def schema(cols):
    types = dict(c for t in TABLES.values() for c in t)
    return [{"id": c, "displayName": c, "required": False, "defaultMatch": False, "display": True,
             "type": types.get(c, "string"), "canBeUsedToMatch": True} for c in cols]


def insert(w, name, tbl, x, y=0, **extra):
    return w.add(name, "n8n-nodes-base.dataTable", 1.1, {
        "dataTableId": table(tbl),
        "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": [], "schema": []},
        "options": {}}, x, y, **extra)


def get_rows(w, name, tbl, x, y=0, filters=None, **extra):
    p = {"operation": "get", "dataTableId": table(tbl), "returnAll": True}
    if filters:
        p.update(matchType="allConditions", filters={"conditions": filters})
    return w.add(name, "n8n-nodes-base.dataTable", 1.1, p, x, y, alwaysOutputData=True, **extra)


def cond(key, value_expr):
    return {"keyName": key, "condition": "eq", "keyValue": value_expr}


def update_rows(w, name, tbl, id_expr, values, x, y=0, **extra):
    return w.add(name, "n8n-nodes-base.dataTable", 1.1, {
        "operation": "update", "dataTableId": table(tbl), "matchType": "allConditions",
        "filters": {"conditions": [cond("id", id_expr)]},
        "columns": {"mappingMode": "defineBelow", "value": values, "matchingColumns": [],
                    "schema": schema(values)},
        "options": {}}, x, y, alwaysOutputData=True, **extra)


def upsert_rows(w, name, tbl, key, key_expr, values, x, y=0, **extra):
    return w.add(name, "n8n-nodes-base.dataTable", 1.1, {
        "resource": "row", "operation": "upsert", "dataTableId": table(tbl), "matchType": "allConditions",
        "filters": {"conditions": [cond(key, key_expr)]},
        "columns": {"mappingMode": "defineBelow", "value": values, "matchingColumns": [],
                    "schema": schema(values)},
        "options": {}}, x, y, **extra)


def slack(w, name, text_expr, x, y=0):
    return w.add(name, "n8n-nodes-base.slack", 2.3, {
        "authentication": "accessToken", "select": "channel",
        "channelId": {"__rl": True, "mode": "name", "value": CHANNEL},
        "text": text_expr, "otherOptions": {"includeLinkToWorkflow": False}}, x, y, cred="slackApi",
        onError="continueRegularOutput", retryOnFail=True, maxTries=3, waitBetweenTries=2000)


def raw_webhook(w, name, path, x, y=0):
    # Webhook v1 with "Binary File" on: n8n does not parse the body, the workflow gets the exact bytes (adr/003).
    # Auth is the WooCommerce HMAC signature, checked in the workflow on those bytes.
    return w.add(name, "n8n-nodes-base.webhook", 1, {
        "httpMethod": "POST", "path": path, "responseMode": "responseNode",
        "options": {"binaryData": True, "binaryPropertyName": "data"}}, x, y,
        webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "q129/" + path)))


def sign_body(w, name, x, y=0):
    return w.add(name, "n8n-nodes-base.crypto", 2, {
        "action": "hmac", "type": "SHA256", "binaryData": True, "binaryPropertyName": "data",
        "dataPropertyName": "signature", "encoding": "base64"}, x, y, cred="crypto", onError="continueRegularOutput")


def respond(w, name, body_expr, code_expr, x, y=0):
    return w.add(name, "n8n-nodes-base.respondToWebhook", 1.4, {
        "respondWith": "json", "responseBody": body_expr, "options": {"responseCode": code_expr}}, x, y)


def run_workflow(w, name, key, x, y=0):
    return w.add(name, "n8n-nodes-base.executeWorkflow", 1.4, {
        "source": "database", "workflowId": {"__rl": True, "mode": "id", "value": f"__WF:{key}__"},
        "options": {"waitForSubWorkflow": True}}, x, y)


def trigger(w, x=0):
    return w.add("Start", "n8n-nodes-base.executeWorkflowTrigger", 1.3, {"inputSource": "passthrough"}, x)


def error_workflow(w):
    w.settings["errorWorkflow"] = "__WF:error__"


# ------------------------------------------------------------------------------------------------ workflows

def build_hubspot_call(live):
    """One HubSpot write (POST, JSON body) with the CASES.md 3.7 retry rules, unrolled to 3 attempts."""
    w = WF("hubspot-call", "Q129 HubSpot call", live)
    trigger(w)

    def attempt(n, x, y):
        w.add(f"Try {n}", "n8n-nodes-base.httpRequest", 4.2, {
            "method": "POST", "url": "={{ $('Start').first().json.base + $('Start').first().json.path }}",
            "authentication": "predefinedCredentialType", "nodeCredentialType": "hubspotAppToken",
            "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($('Start').first().json.body) }}",
            "options": {"timeout": 15000,
                        "response": {"response": {"fullResponse": True, "neverError": True,
                                                  "responseFormat": "json"}}}},
            x, y, cred="hubspotAppToken", onError="continueRegularOutput")
        code(w, f"Check {n}", J.check_try(n), x + 1, y)

    attempt(1, 1, 0)
    if_true(w, "Retry 1?", "={{ $json.done === false }}", 3, 0)
    w.add("Wait 1", "n8n-nodes-base.wait", 1.1, {"resume": "timeInterval", "amount": "={{ $json.wait }}",
                                                 "unit": "seconds"}, 4, 1,
          webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "q129/hubspot-call/wait1")))
    attempt(2, 5, 1)
    if_true(w, "Retry 2?", "={{ $json.done === false }}", 7, 1)
    w.add("Wait 2", "n8n-nodes-base.wait", 1.1, {"resume": "timeInterval", "amount": "={{ $json.wait }}",
                                                 "unit": "seconds"}, 8, 2,
          webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "q129/hubspot-call/wait2")))
    attempt(3, 9, 2)
    code(w, "Result", "return $input.all();", 11, 0)
    w.chain("Start", "Try 1", "Check 1", "Retry 1?")
    w.link("Retry 1?", "Wait 1", 0)
    w.link("Retry 1?", "Result", 1)
    w.chain("Wait 1", "Try 2", "Check 2", "Retry 2?")
    w.link("Retry 2?", "Wait 2", 0)
    w.link("Retry 2?", "Result", 1)
    w.chain("Wait 2", "Try 3", "Check 3", "Result")
    return w


def build_core(live):
    w = WF("core", "Q129 Core: check and sync one order", live)
    trigger(w)
    code(w, "Check and clean", J.CHECK, 1)
    if_true(w, "Checks passed?", "={{ $json.ok === true }}", 2)
    if not live:
        code(w, "Test crash switch", J.TEST_CRASH, 2.5, -1)
    w.add("Data hash", "n8n-nodes-base.crypto", 2, {
        "action": "hash", "type": "SHA256", "value": "={{ $json.canonical }}", "dataPropertyName": "data_hash",
        "encoding": "hex"}, 3, -1)
    get_rows(w, "Find ledger row", "q129_ledger", 4, -1,
             filters=[cond("order_number", "={{ $json.order_number }}")], executeOnce=True)
    code(w, "Decide", J.DECIDE, 5, -1, executeOnce=True)
    if_true(w, "Write?", "={{ $json.action === 'write' }}", 6, -1)

    # write path: contact, deal, link (CASES.md 3.7), then ledger and closed rows (3.5, 3.8)
    code(w, "Contact request", J.CONTACT_REQUEST, 7, -2)
    run_workflow(w, "Write contact", "hubspot-call", 8, -2)
    code(w, "After contact", J.after_call("Decide", "contacts", "contact_id"), 9, -2)
    if_true(w, "Contact ok?", "={{ $json.action === 'write' }}", 10, -2)
    code(w, "Deal request", J.DEAL_REQUEST, 11, -2)
    run_workflow(w, "Write deal", "hubspot-call", 12, -2)
    code(w, "After deal", J.after_call("After contact", "deals", "deal_id"), 13, -2)
    if_true(w, "Deal ok?", "={{ $json.action === 'write' }}", 14, -2)
    code(w, "Link request", J.LINK_REQUEST, 15, -2)
    run_workflow(w, "Write link", "hubspot-call", 16, -2)
    code(w, "After link", J.after_call("After deal", "link", ""), 17, -2)
    if_true(w, "Link ok?", "={{ $json.action === 'write' }}", 18, -2)
    code(w, "Ledger row", J.LEDGER_ROW, 19, -2)
    upsert_rows(w, "Upsert ledger", "q129_ledger", "order_number", "={{ $json.order_number }}",
                {c: "={{ $json.%s }}" % c for c in ("order_number", "version", "data_hash", "updated_at")}, 20, -2)
    get_rows(w, "Find open rows", "q129_attention", 21, -2,
             filters=[cond("order_number", "={{ $('After link').first().json.order_number }}"),
                      cond("state", "open")], executeOnce=True)
    code(w, "Rows to close", J.ROWS_TO_CLOSE.replace("__STATE__", "After link"), 22, -2, executeOnce=True)
    close_values = {c: "={{ $json.%s }}" % c for c in ("state", "closed_by", "closed_at", "closed_request")}
    update_rows(w, "Close rows", "q129_attention", "={{ $json.row_id }}", close_values, 23, -2)
    code(w, "Write done", J.STEP_DONE.replace("__STATE__", "After link").replace("__SUFFIX__", ""), 24, -2,
         executeOnce=True)

    # skip path: only the replayed row closes (by replay)
    if_true(w, "Skip?", "={{ $json.action === 'skip' }}", 7, 0)
    get_rows(w, "Find open rows (skip)", "q129_attention", 8, 0,
             filters=[cond("order_number", "={{ $('Decide').first().json.order_number }}"), cond("state", "open")],
             executeOnce=True)
    code(w, "Rows to close (skip)", J.ROWS_TO_CLOSE.replace("__STATE__", "Decide"), 9, 0, executeOnce=True)
    update_rows(w, "Close rows (skip)", "q129_attention", "={{ $json.row_id }}", close_values, 10, 0)
    code(w, "Skip done", J.STEP_DONE.replace("__STATE__", "Decide").replace("__SUFFIX__", " (skip)"), 11, 0,
         executeOnce=True)

    # needs attention: new row + alert, or (replay) replay count + alert (CASES.md 3.8, 3.10)
    code(w, "Attention", J.ATTENTION, 12, 2)
    if_true(w, "Replay row?", "={{ $json.mode === 'replay' }}", 13, 2)
    code(w, "New row", J.NEW_ROW, 14, 3)
    insert(w, "Insert row", "q129_attention", 15, 3)
    code(w, "Row alert", J.NEW_ROW_ALERT, 16, 3)
    code(w, "Replay count", J.REPLAY_ROW_UPDATE, 14, 1)
    update_rows(w, "Update replay row", "q129_attention", "={{ $json.row_id }}", {"replays": "={{ $json.replays }}"},
                15, 1)
    code(w, "Replay alert", J.REPLAY_ALERT, 16, 1)
    code(w, "Alert state", "return $input.all();", 17, 2)
    slack(w, "Slack alert", "={{ $json.alert.text }}", 18, 2)
    code(w, "Alert row", J.alert_row("Alert state"), 19, 2)
    insert(w, "Save alert", "q129_alerts", 20, 2, onError="continueRegularOutput")
    code(w, "Attention done", J.ATTENTION_DONE.replace("__STATE__", "Alert state"), 21, 2)

    code(w, "Log row", J.LOG_ROW, 25, 0)
    insert(w, "Write log", "q129_log", 26, 0)

    w.chain("Start", "Check and clean", "Checks passed?")
    if live:
        w.link("Checks passed?", "Data hash", 0)
    else:
        w.link("Checks passed?", "Test crash switch", 0)
        w.link("Test crash switch", "Data hash")
    w.link("Checks passed?", "Attention", 1)
    w.chain("Data hash", "Find ledger row", "Decide", "Write?")
    w.link("Write?", "Contact request", 0)
    w.link("Write?", "Skip?", 1)
    w.chain("Contact request", "Write contact", "After contact", "Contact ok?")
    w.link("Contact ok?", "Deal request", 0)
    w.link("Contact ok?", "Attention", 1)
    w.chain("Deal request", "Write deal", "After deal", "Deal ok?")
    w.link("Deal ok?", "Link request", 0)
    w.link("Deal ok?", "Attention", 1)
    w.chain("Link request", "Write link", "After link", "Link ok?")
    w.link("Link ok?", "Ledger row", 0)
    w.link("Link ok?", "Attention", 1)
    w.chain("Ledger row", "Upsert ledger", "Find open rows", "Rows to close", "Close rows", "Write done", "Log row")
    w.link("Skip?", "Find open rows (skip)", 0)
    w.link("Skip?", "Attention", 1)
    w.chain("Find open rows (skip)", "Rows to close (skip)", "Close rows (skip)", "Skip done", "Log row")
    w.chain("Attention", "Replay row?")
    w.link("Replay row?", "Replay count", 0)
    w.link("Replay row?", "New row", 1)
    w.chain("New row", "Insert row", "Row alert", "Alert state")
    w.chain("Replay count", "Update replay row", "Replay alert", "Alert state")
    w.chain("Alert state", "Slack alert", "Alert row", "Save alert", "Attention done", "Log row", "Write log")
    return w


def build_entry(live):
    w = WF("entry", "Q129 Entry: WooCommerce order webhook", live)
    error_workflow(w)
    raw_webhook(w, "Order in", "q129-order", 0)
    code(w, "Read request", J.READ_REQUEST, 1)
    sign_body(w, "Sign body", 2)
    code(w, "Gate", J.GATE, 3)
    if_true(w, "Accepted?", "={{ $json.result === 'accepted' }}", 4)
    respond(w, "Answer 200", "={{ JSON.stringify({ ok: true }) }}", "={{ 200 }}", 5, -1)
    code(w, "Core input", J.CORE_INPUT, 6, -1)
    run_workflow(w, "Run core", "core", 7, -1)
    code(w, "Entry log", J.ENTRY_LOG, 5, 1)
    insert(w, "Write entry log", "q129_log", 6, 1, onError="continueRegularOutput")
    respond(w, "Answer", "={{ JSON.stringify({ result: $('Gate').first().json.result, reason: $('Gate').first().json.reason }) }}",
            "={{ $('Gate').first().json.http }}", 7, 1)
    w.chain("Order in", "Read request", "Sign body", "Gate", "Accepted?")
    w.link("Accepted?", "Answer 200", 0)
    w.link("Accepted?", "Entry log", 1)
    w.chain("Answer 200", "Core input", "Run core")
    w.chain("Entry log", "Write entry log", "Answer")
    return w


def build_replay(live):
    w = WF("replay", "Q129 Replay: needs-attention row", live)
    error_workflow(w)
    w.add("Replay form", "n8n-nodes-base.formTrigger", 2.4, {
        "authentication": "basicAuth", "path": "q129-replay",
        "formTitle": "Replay a needs-attention row",
        "formDescription": "Use this after a HubSpot outage. Orders that failed a field check are fixed in the shop.",
        "formFields": {"values": [
            {"fieldLabel": "Row ID", "fieldName": "row_id", "fieldType": "number", "requiredField": True},
            {"fieldType": "hiddenField", "fieldName": "request_id"}]},
        "responseMode": "onReceived", "options": {}}, 0, cred="httpBasicAuth",
        webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "q129/q129-replay")))
    code(w, "Replay request", J.REPLAY_REQUEST, 1)
    get_rows(w, "Find row", "q129_attention", 2, filters=[cond("id", "={{ $json.row_id }}")], executeOnce=True)
    code(w, "Replay decide", J.REPLAY_DECIDE, 3, executeOnce=True)
    if_true(w, "Replay allowed?", "={{ $json.go === true }}", 4)
    code(w, "Core input", "return [{ json: $json.core }];", 5, -1)
    run_workflow(w, "Run core", "core", 6, -1)
    code(w, "Refused log", J.REPLAY_REFUSED_LOG, 5, 1)
    insert(w, "Write refused log", "q129_log", 6, 1)
    w.chain("Replay form", "Replay request", "Find row", "Replay decide", "Replay allowed?")
    w.link("Replay allowed?", "Core input", 0)
    w.link("Replay allowed?", "Refused log", 1)
    w.chain("Core input", "Run core")
    w.chain("Refused log", "Write refused log")
    return w


def build_summary(live):
    w = WF("summary", "Q129 Summary: daily summary", live)
    error_workflow(w)
    if live:
        w.add("Every day 08:00", "n8n-nodes-base.scheduleTrigger", 1.2,
              {"rule": {"interval": [{"field": "days", "triggerAtHour": 8}]}}, 0)
        code(w, "Window", J.SUMMARY_WINDOW_LIVE, 5)
        w.chain("Every day 08:00", "Window")
    else:
        raw_webhook(w, "Summary in (test)", "q129-test-summary", 0)
        code(w, "Read request", J.READ_REQUEST, 1)
        sign_body(w, "Sign body", 2)
        code(w, "Summary gate", J.SUMMARY_GATE, 3)
        if_true(w, "Signed?", "={{ $json.ok === true }}", 4)
        respond(w, "Answer 200", "={{ JSON.stringify({ ok: true }) }}", "={{ 200 }}", 4.5, -1)
        respond(w, "Answer 401", "={{ JSON.stringify({ ok: false }) }}", "={{ 401 }}", 5, 1)
        code(w, "Window", "const g = $('Summary gate').first().json;\n"
                          "return [{ json: { window_start: g.window_start, request_id: g.request_id } }];", 5)
        w.chain("Summary in (test)", "Read request", "Sign body", "Summary gate", "Signed?")
        w.link("Signed?", "Answer 200", 0)
        w.link("Signed?", "Answer 401", 1)
        w.chain("Answer 200", "Window")
    get_rows(w, "Log rows", "q129_log", 6, executeOnce=True)
    get_rows(w, "Attention rows", "q129_attention", 7, executeOnce=True)
    code(w, "Count", J.SUMMARY_COUNT.replace("__WINDOW__", "Window"), 8, executeOnce=True)
    slack(w, "Slack summary", "={{ $json.alert.text }}", 9)
    code(w, "Summary row", J.alert_row("Count"), 10)
    insert(w, "Save summary", "q129_alerts", 11, onError="continueRegularOutput")
    if_true(w, "Over 5?", "={{ $('Count').first().json.over5 === true }}", 12)
    code(w, "Over 5 state", J.OVER5_STATE, 13, 1)
    slack(w, "Slack over 5", "={{ $json.alert.text }}", 14, 1)
    code(w, "Over 5 row", J.alert_row("Over 5 state"), 15, 1)
    insert(w, "Save over 5", "q129_alerts", 16, 1, onError="continueRegularOutput")
    w.chain("Window", "Log rows", "Attention rows", "Count", "Slack summary", "Summary row", "Save summary", "Over 5?")
    w.link("Over 5?", "Over 5 state", 0)
    w.chain("Over 5 state", "Slack over 5", "Over 5 row", "Save over 5")
    return w


def build_error(live):
    w = WF("error", "Q129 Error: crash alert", live)
    w.add("Error in", "n8n-nodes-base.errorTrigger", 1, {}, 0)
    code(w, "Crash state", J.CRASH_STATE, 1)
    slack(w, "Slack crash", "={{ $json.alert.text }}", 2)
    code(w, "Crash row", J.alert_row("Crash state"), 3)
    insert(w, "Save crash", "q129_alerts", 4, onError="continueRegularOutput")
    w.chain("Error in", "Crash state", "Slack crash", "Crash row", "Save crash")
    return w


# order matters for --push: a workflow's __WF:key__ references must already exist
BUILDERS = [("error", build_error), ("hubspot-call", build_hubspot_call), ("core", build_core),
            ("entry", build_entry), ("replay", build_replay), ("summary", build_summary)]


def substitute(obj, creds, wf_ids):
    s = json.dumps(obj)
    for t, cid in creds.items():
        s = s.replace(f"__CRED:{t}__", cid)
    for k, wid in wf_ids.items():
        s = s.replace(f"__WF:{k}__", wid)
    if "__CRED:" in s or "__WF:" in s:
        raise SystemExit("unresolved placeholder in " + obj["name"])
    return json.loads(s)


def write(docs, folder):
    folder.mkdir(exist_ok=True)
    for key, d in docs:
        (folder / f"{key}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def credential_ids(api):
    """Credential IDs by name and type (the public API lists credentials; else the local n8n database, read-only)."""
    found = {}
    try:
        items = api.list_all("/credentials")
    except SystemExit:
        items = []
    if not items:
        import os
        import sqlite3
        db = os.path.expanduser("~/.n8n/database.sqlite")
        con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
        items = [{"id": r[0], "name": r[1], "type": r[2]} for r in
                 con.execute("select id, name, type from credentials_entity where name like '%n8n-data-sync%'")]
        con.close()
    for c in items:
        for t, n in CRED_NAMES.items():
            if c.get("name") == n and c.get("type") == t:
                found[t] = c["id"]
    missing = [CRED_NAMES[t] for t in CRED_NAMES if t not in found]
    if missing:
        raise SystemExit("credentials missing in n8n: " + ", ".join(missing))
    return found


def ensure_tables(api):
    have = {t["name"]: t["id"] for t in api.list_all("/data-tables") if t.get("name") in TABLES}
    for name, cols in TABLES.items():
        if name not in have:
            api.request("POST", "/data-tables", {"name": name, "columns": [{"name": c, "type": t} for c, t in cols]})
            print(f"created data table {name}")
            continue
        cur = {c["name"] for c in api.request("GET", f"/data-tables/{have[name]}/columns")}
        for c, t in cols:
            if c not in cur:
                api.request("POST", f"/data-tables/{have[name]}/columns", {"name": c, "type": t})
                print(f"added column {c} to {name}")


def main():
    test_docs = [(k, fn(False).doc()) for k, fn in BUILDERS]
    live_docs = [(k, fn(True).doc()) for k, fn in BUILDERS]
    write(test_docs, OUT / "test")
    write(live_docs, OUT / "live")
    print(f"wrote {len(test_docs)} test-copy workflows to workflows/test/ and {len(live_docs)} live-export "
          f"workflows to workflows/live/")
    if "--push" not in sys.argv:
        return
    from n8n_api import Api
    api = Api()
    creds = credential_ids(api)
    ensure_tables(api)
    wf_ids = {}
    for key, d in test_docs:
        wid = api.push(substitute(d, creds, wf_ids))
        wf_ids[key] = wid
        print(f"pushed {d['name']} -> {wid}")


if __name__ == "__main__":
    main()
