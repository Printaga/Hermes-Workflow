"""Deliver an output node's text to a messaging target through the host's own send seam.

The seam is ``tools.send_message_tool.send_message_tool`` — the non-model entry point the
`hermes send` CLI and the cron scheduler import too (it is deliberately *not* registered as an
agent-callable tool). A plugin never opens a platform socket itself.

Two modes, both through that one call:

* ``notification`` — a bare platform target (``telegram``) means "the home channel": the send
  seam resolves ``<PLATFORM>_HOME_CHANNEL`` on its own. Hermes has no OS-level notification
  API, so "notify me" is exactly this DM.
* ``channel`` — an explicit ``<platform>:<chat id>`` (``telegram:123456``, ``slack:#ops``).

v1 is text only. A failed delivery never fails the run: the outcome is recorded on the run
state so the canvas can show it, matching OpenBot, where a failing action leaves earlier
actions in place.
"""
from __future__ import annotations

import json

MODES = ("notification", "channel")
MAX_TEXT = 4000  # keep one notification readable; the seam chunks anything longer anyway
_COLLECT_ONLY = {"target": "", "ok": True, "detail": "collected only"}


def render_text(run_name: str, node_id: str, payload) -> str:
    """Turn an output node's collected payload into a short plain-text message."""
    head = f"Workflow {run_name or 'workflow'} \u2014 {node_id}"
    if isinstance(payload, dict) and payload:
        lines = []
        for key, value in payload.items():
            if isinstance(value, str):
                text = value
            else:
                try:
                    text = json.dumps(value, ensure_ascii=False)
                except (TypeError, ValueError):
                    # A set/bytes/custom object must not turn delivery into an exception;
                    # this function is documented as never raising.
                    text = str(value)
            lines.append(f"- {key}: {text}")
        body = "\n".join(lines)
    elif payload in (None, {}, []):
        body = "(no upstream output)"
    else:
        body = str(payload)
    text = f"{head}\n\n{body}"
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "\u2026"


def send_text(target: str, text: str) -> dict:
    """Send *text* to *target* via the host seam. Never raises."""
    try:
        from tools.send_message_tool import send_message_tool
    except Exception as exc:  # host not importable (tests, standalone tooling)
        return {"target": target, "ok": False, "detail": f"host send seam unavailable: {exc}"}
    try:
        raw = send_message_tool({"action": "send", "target": target, "message": text})
    except Exception as exc:  # the seam catches its own errors; this is a last resort
        return {"target": target, "ok": False, "detail": f"send failed: {exc}"}
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            # A plain-text error from the seam is the only diagnosis available; keep it
            # instead of reducing the receipt to a generic "send failed".
            data = {"error": raw} if raw else {}
    if isinstance(data, dict) and data.get("success"):
        return {"target": target, "ok": True, "detail": str(data.get("note") or "sent")}
    detail = (data or {}).get("error") if isinstance(data, dict) else raw
    return {"target": target, "ok": False, "detail": str(detail or "send failed")}


def delivering_targets(graph: dict) -> list:
    """Output steps of *graph* that would actually attempt a send, in graph order.

    Each item is ``{"node": id, "target": target}``. Mirrors :func:`deliver_output`'s
    own rules exactly: a send is attempted if and only if the mode is known, a target
    is set, and a ``channel`` target carries ``<platform>:<chat id>``. The hook and
    the run-resume guard both key off this one definition so they cannot drift.
    """
    found = []
    for node in (graph.get("nodes", []) if isinstance(graph, dict) else []) or []:
        if not isinstance(node, dict) or node.get("type") != "output":
            continue
        mode = str(node.get("deliver") or "").strip().lower()
        if mode not in MODES:
            continue
        target = node.get("target")
        text = target.strip() if isinstance(target, str) else ""
        if not text:
            continue
        if mode == "channel" and ":" not in text:
            continue
        found.append({"node": node.get("id"), "target": text})
    return found


def deliver_output(step: dict, payload, run_name: str = "") -> dict:
    """Deliver one output node's payload. Returns ``{target, ok, detail}``; never raises.

    Called by the runner for every output step that declares a ``deliver`` mode; a node that
    only collects has no mode and is not passed here.
    """
    mode = str(step.get("deliver") or "").strip().lower()
    if mode not in MODES:
        return dict(_COLLECT_ONLY)
    target = str(step.get("target") or "").strip()
    if not target:
        return {"target": "", "ok": False, "detail": "output node has no target"}
    if mode == "channel" and ":" not in target:
        return {
            "target": target,
            "ok": False,
            "detail": "a channel target needs <platform>:<chat id>",
        }
    text = render_text(run_name, str(step.get("id") or ""), payload)
    return send_text(target, text)
