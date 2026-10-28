"""Designer-graph schema. A designer graph is plain JSON with 5 node kinds."""
from __future__ import annotations

import re

NODE_KINDS = ("trigger", "agent", "condition", "approval", "output")
TRIGGER_MODES = ("manual", "schedule", "webhook")
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
    triggers = [n for n in nodes if isinstance(n, dict) and n.get("type") == "trigger"]
    if len(triggers) != 1:
        errors.append({"node": "", "field": "trigger",
                       "msg": f"workflow needs exactly one trigger, found {len(triggers)}"})
    for n in nodes:
        if not isinstance(n, dict):
            errors.append({"node": "", "field": "node", "msg": "node must be an object"})
            continue
        nid, kind = n.get("id", ""), n.get("type")
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
            if dep not in ids:
                errors.append({"node": nid, "field": "after",
                               "msg": f"unknown dependency {dep!r}"})
            elif dep == nid:
                errors.append({"node": nid, "field": "after",
                               "msg": "node cannot depend on itself"})
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
