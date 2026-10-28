"""Draw docs/architecture.png (what happens to one shop order event). Run: python docs/make_diagram.py"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

INK, MUTED = "#1f2937", "#6b7280"
FILL = {"step": "#eef2ff", "check": "#ede9fe", "ok": "#dcfce7", "person": "#ffedd5", "stop": "#f3f4f6"}

BOXES = {
    "event": (0.9, 6.0, "Shop order event\n(WooCommerce webhook:\ncreated or updated)", "step"),
    "sig": (3.8, 6.0, "Signature check\non the exact bytes;\nanswer the shop at once", "check"),
    "fields": (6.7, 6.0, "Field checks and\nsafe cleaning\n(code, before any write)", "check"),
    "ledger": (9.6, 6.0, "Ledger check:\nthis order version\nalready synced or older?", "check"),
    "crm": (12.5, 6.0, "HubSpot write:\ncontact by e-mail,\ndeal by order number;\nsafe retries", "step"),
    "done": (15.4, 6.0, "Synced: one contact,\none linked deal,\nledger and log row", "ok"),
    "skip": (9.6, 8.4, "Skipped as duplicate\nor older (logged),\nnothing overwritten", "stop"),
    "reject": (3.8, 3.6, "Bad or missing\nsignature: refused,\nnothing written", "stop"),
    "attn": (6.7, 3.6, "Needs-attention list\nand Slack alert; fixed\nin the shop or replayed\nby a person", "person"),
}
ARROWS = [
    ("event", "sig", ""), ("sig", "fields", "valid"), ("fields", "ledger", "pass"), ("ledger", "crm", "new"),
    ("crm", "done", "OK"), ("ledger", "skip", "same or older"), ("sig", "reject", "invalid"),
    ("fields", "attn", "check fails"), ("crm", "attn", "refused, or still failing after retries"),
]
W, H = 2.4, 1.3

fig, ax = plt.subplots(figsize=(17, 8.2), dpi=150)
ax.set_xlim(-0.6, 16.9)
ax.set_ylim(1.4, 9.8)
ax.axis("off")
fig.patch.set_facecolor("white")

for key, (x, y, text, kind) in BOXES.items():
    ax.add_patch(FancyBboxPatch((x - W / 2, y - H / 2), W, H, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=FILL[kind], ec=INK, lw=1.2))
    ax.text(x, y, text, ha="center", va="center", fontsize=9.3, color=INK)

# The diagonal arrow gets explicit start/end points so it ends on the top edge of the needs-attention box.
ANCHORS = {("crm", "attn"): (lambda a, b: ((a[0] - 0.6, a[1] - H / 2), (b[0] + 0.7, b[1] + H / 2)))}


def edge(a, b):
    if (a, b) in ANCHORS:
        return ANCHORS[(a, b)](BOXES[a], BOXES[b])
    (xa, ya, *_), (xb, yb, *_) = BOXES[a], BOXES[b]
    if abs(ya - yb) < 0.01:
        sx = 1 if xb > xa else -1
        return (xa + sx * W / 2, ya), (xb - sx * W / 2, yb)
    sy = 1 if yb > ya else -1
    return (xa, ya + sy * H / 2), (xb, yb - sy * H / 2)


for a, b, label in ARROWS:
    p, q = edge(a, b)
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=12, color=INK, lw=1.1))
    if label:
        flat = abs(p[1] - q[1]) < 0.01
        t = {("crm", "attn"): 0.35}.get((a, b), 0.5)
        ax.text(p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]) + (0.2 if flat else 0), label, ha="center",
                va="center", fontsize=8.5, color=MUTED, style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

ax.text(-0.5, 9.6, "n8n Data Sync: what happens to one shop order", fontsize=13, weight="bold", color=INK)
legend = [("step", "automatic step"), ("check", "code check (no AI)"), ("ok", "synced"),
          ("person", "goes to a person"), ("stop", "stopped, nothing written")]
for i, (kind, label) in enumerate(legend):
    ax.add_patch(FancyBboxPatch((-0.5 + i * 2.6, 1.55), 0.35, 0.3, boxstyle="round,pad=0.01", fc=FILL[kind], ec=INK,
                                lw=0.8))
    ax.text(-0.05 + i * 2.6, 1.7, label, va="center", fontsize=8.5, color=INK)
ax.text(10.6, 3.3, "Every event: one log row.\nEvery day: a summary in Slack, and an\nalert if more than 5 orders fail.\n"
        "Any crash: a Slack alert.", fontsize=9, color=MUTED, va="center")

out = Path(__file__).with_name("architecture.png")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
