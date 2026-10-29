"""Designer-graph schema. A designer graph is plain JSON with 5 node kinds."""
from __future__ import annotations

import re

NODE_KINDS = ("trigger", "agent", "condition", "approval", "output")
# A sticky note is an annotation for whoever reads the canvas, not a workflow step. It is a
# legal node so the designer JSON round-trips, but it is excluded from everything that makes a
# run: it is not a step kind, it takes no edges in either direction (it has no ports), and the
# converter drops it exactly like a trigger. Its only payload is `text` plus an optional
# `color`; `x`/`y` are the same widget-only layout keys every node carries.
NOTE_KIND = "note"
NOTE_COLORS = ("yellow", "blue", "green", "red")
# "webhook" was removed rather than stubbed: Hermes' inbound webhooks are operator-managed
# subscriptions (`hermes webhook subscribe`, HMAC secret) that fire the AGENT or an existing cron
# job, and a plugin cannot open a route of its own. A design can still be reached from outside by
# subscribing to it — README documents the exact command — but a picker that records a URL nobody
# listens on is a dead control, so the mode is gone.
TRIGGER_MODES = ("manual", "schedule")
# How an output node hands its payload on: to the platform's home channel ("notification") or
# to an explicit <platform>:<chat> target ("channel"). Absent = collect only.
DELIVER_MODES = ("notification", "channel")
# A paused gate may carry a deadline; without one it waits forever, which the HITL literature
# names as the most common production failure. Three days is the ceiling: longer is a design
# error, not patience.
ON_TIMEOUT = ("reject", "escalate")
MAX_TIMEOUT_MINUTES = 4320
MAX_NODES = 50

# Conditions must reference upstream outputs in this form:
#   out.<node_id>.<dotted.path> <op> <literal>
# e.g. "out.draft.word_count > 20". Heads other than `out.` are rejected so a broken
# expression fails at design time rather than mid-run.
_WHEN_RE = re.compile(r"^out\.[A-Za-z0-9_.-]+\s*(==|!=|>=|<=|>|<)\s*.+$")

REQUIRED_FIELDS = {
    "trigger": ("trigger_mode",),
    "agent": ("prompt",),
    "condition": ("expression",),
    "approval": ("question",),
    "output": (),
}


def validate_designer_graph(graph: dict) -> list[dict]:
    """Return a list of {node, field, msg} defects. Empty list = valid."""
    errors: list[dict] = []
    if not isinstance(graph, dict):
        return [{"node": "", "field": "graph", "msg": "graph must be an object"}]
    nodes = graph.get("nodes", [])
    if not nodes:
        errors.append({"node": "", "field": "nodes", "msg": "workflow needs at least one node"})
        return errors
    if len(nodes) > MAX_NODES:
        errors.append({"node": "", "field": "nodes",
                       "msg": f"design capped at {MAX_NODES} nodes, got {len(nodes)}"})
    # Layout positions x/y are optional and always preserved — the widget round-trips
    # them, the validator ignores them. Never reject on x/y.
    ids = [n.get("id") for n in nodes if isinstance(n, dict)]
    if len(set(ids)) != len(ids):
        errors.append({"node": "", "field": "nodes", "msg": "node ids must be unique"})
    note_ids = {n.get("id") for n in nodes
                if isinstance(n, dict) and n.get("type") == NOTE_KIND}
    triggers = [n for n in nodes if isinstance(n, dict) and n.get("type") == "trigger"]
    if len(triggers) != 1:
        errors.append({"node": "", "field": "trigger",
                       "msg": f"workflow needs exactly one trigger, found {len(triggers)}"})
    for n in nodes:
        if not isinstance(n, dict):
            errors.append({"node": "", "field": "node", "msg": "node must be an object"})
            continue
        nid, kind = n.get("id", ""), n.get("type")
        if kind == NOTE_KIND:
            # Informative only: no required fields, no connectivity, no cycle participation.
            if n.get("after"):
                errors.append({"node": nid, "field": "after",
                               "msg": "a note takes no edges \u2014 it is only information"})
            color = n.get("color")
            if color not in (None, "") \
                    and str(color).strip().lower() not in NOTE_COLORS:
                errors.append({"node": nid, "field": "color",
                               "msg": f"color must be one of {NOTE_COLORS} or empty"})
            continue
        if kind not in NODE_KINDS:
            errors.append({"node": nid, "field": "type",
                           "msg": f"unknown node type {kind!r}, expected one of {NODE_KINDS}"})
            continue
        for field in REQUIRED_FIELDS[kind]:
            if not n.get(field):
                errors.append({"node": nid, "field": field,
                               "msg": f"{kind} node {nid!r} needs non-empty {field!r}"})
        if kind == "trigger" and n.get("trigger_mode") not in TRIGGER_MODES:
            errors.append({"node": nid, "field": "trigger_mode",
                           "msg": f"trigger_mode must be one of {TRIGGER_MODES}"})
        for dep in n.get("after", []) or []:
            if dep in note_ids:
                errors.append({"node": nid, "field": "after",
                               "msg": f"{dep!r} is a note and cannot be a dependency"})
            elif dep not in ids:
                errors.append({"node": nid, "field": "after",
                               "msg": f"unknown dependency {dep!r}"})
            elif dep == nid:
                errors.append({"node": nid, "field": "after",
                               "msg": "node cannot depend on itself"})
        if kind == "output":
            deliver = n.get("deliver")
            if deliver not in (None, "") and str(deliver).strip().lower() not in DELIVER_MODES:
                errors.append({"node": nid, "field": "deliver",
                               "msg": f"deliver must be one of {DELIVER_MODES} or empty"})
            elif str(deliver or "").strip().lower() in DELIVER_MODES:
                target = str(n.get("target") or "").strip()
                if not target:
                    errors.append({"node": nid, "field": "target",
                                   "msg": f"deliver={deliver!r} needs a target "
                                          "(e.g. 'telegram' or 'telegram:123456')"})
                elif str(deliver).strip().lower() == "channel" and ":" not in target:
                    errors.append({"node": nid, "field": "target",
                                   "msg": "a channel target needs <platform>:<chat id>"})
        if kind == "approval":
            timeout = n.get("timeout_minutes")
            if timeout not in (None, ""):
                try:
                    minutes = int(timeout)
                except (TypeError, ValueError):
                    errors.append({"node": nid, "field": "timeout_minutes",
                                   "msg": "timeout_minutes must be a whole number of minutes"})
                else:
                    if minutes <= 0 or minutes > MAX_TIMEOUT_MINUTES:
                        errors.append({
                            "node": nid, "field": "timeout_minutes",
                            "msg": f"timeout_minutes must be 1..{MAX_TIMEOUT_MINUTES}",
                        })
            policy = n.get("on_timeout")
            if policy not in (None, "") \
                    and str(policy).strip().lower() not in ON_TIMEOUT:
                errors.append({"node": nid, "field": "on_timeout",
                               "msg": f"on_timeout must be one of {ON_TIMEOUT} or empty"})
        if kind == "condition" and n.get("expression") \
                and not _WHEN_RE.match(str(n["expression"]).strip()):
            errors.append({"node": nid, "field": "expression",
                           "msg": "expression must look like 'out.<node>.<field> <op> <value>' "
                                  "(op: == != > >= < <=)"})
    if not errors:
        # Cycle check (DFS over after-edges). A cycle would hang the runner.
        visiting: set = set()
        done: set = set()

        def _visit(nid, stack):
            if nid in done:
                return None
            if nid in visiting:
                return stack + [nid]
            visiting.add(nid)
            node = next((x for x in nodes if isinstance(x, dict) and x.get("id") == nid), None)
            for dep in (node.get("after", []) if node else []) or []:
                cyc = _visit(dep, stack + [nid])
                if cyc:
                    return cyc
            visiting.discard(nid)
            done.add(nid)
            return None

        for nid in ids:
            cyc = _visit(nid, [])
            if cyc:
                errors.append({"node": cyc[0], "field": "after",
                               "msg": f"dependency cycle: {' -> '.join(map(str, cyc))}"})
                break
    return errors
