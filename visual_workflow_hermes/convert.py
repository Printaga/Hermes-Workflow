"""Build an executable run plan from a designer graph.

The plugin owns execution (there is no external engine on Hermes <= 0.22, see Task 0 of the
plan), so this module turns the 5-kind designer graph into an ordered list of steps. Pure
functions, no I/O, no Hermes imports — unit-testable standalone.

Mapping:
  trigger   -> dropped; recorded in plan["meta"]["trigger"]
  note      -> dropped (annotation for the reader, never a run step)
  agent     -> {"kind": "agent", "prompt", ...passthrough profile/model/schema/inputs/timeout}
  condition -> {"kind": "condition", "expression"}
  approval  -> {"kind": "approval", "question", "options"}
  output    -> {"kind": "output", "keys": [<parent ids>], ...passthrough deliver/target}
  layout x/y -> dropped (widget-only, preserved in the designer JSON)
"""
from __future__ import annotations

from .schema import NOTE_KIND


def topological_order(steps: list[dict]) -> list[dict]:
    """Return *steps* in dependency order; ties break by original declaration order.

    Kahn's algorithm with a stable tie-break, so the same designer JSON always yields the
    same run order (the widget's node order decides). Raises ValueError on a cycle.
    """
    # An id is the step's identity: a missing or duplicate one would silently drop work
    # from the plan (dict comprehensions keep only the last). Fail loudly instead.
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("id"), str) \
                or not step["id"].strip():
            raise ValueError(f"step is missing a non-empty string 'id': {step!r}")
    ids = [s["id"] for s in steps]
    duplicate_ids = sorted({i for i in ids if ids.count(i) > 1})
    if duplicate_ids:
        raise ValueError(f"duplicate step ids: {', '.join(duplicate_ids)}")
    by_id = {s["id"]: s for s in steps}
    index = {s["id"]: i for i, s in enumerate(steps)}
    deps: dict[str, list[str]] = {}
    for nid, step in by_id.items():
        parents = step.get("after") or []
        if not isinstance(parents, list):
            raise ValueError(f"step {nid!r} has a non-list 'after'")
        # A dangling parent used to be filtered out, silently turning a broken edge into a
        # ready root. The plan builder only strips trigger/note references, so anything
        # else here is a typo the caller must fix.
        unknown = [p for p in parents if not isinstance(p, str) or p not in by_id]
        if unknown:
            raise ValueError(
                f"step {nid!r} depends on unknown step(s): {', '.join(map(repr, unknown))}"
            )
        deps[nid] = list(parents)
    ordered: list[dict] = []
    done: set[str] = set()
    while len(ordered) < len(by_id):
        ready = [nid for nid in by_id if nid not in done and all(d in done for d in deps[nid])]
        if not ready:
            raise ValueError(f"dependency cycle among: {', '.join(sorted(set(by_id) - done))}")
        for nid in sorted(ready, key=index.get):
            ordered.append(by_id[nid])
            done.add(nid)
    return ordered


def build_run_plan(designer: dict) -> dict:
    """Convert a designer graph into ``{"name", "steps", "meta"}`` with steps in run order."""
    name = designer.get("name", "workflow")
    raw = [n for n in designer.get("nodes", []) if isinstance(n, dict)]
    trigger_ids = {n.get("id") for n in raw if n.get("type") == "trigger"}
    # Notes are annotations: the validator refuses edges to them, and stripping the ids here
    # too means a hand-written JSON can never turn a note into a phantom dependency.
    note_ids = {n.get("id") for n in raw if n.get("type") == NOTE_KIND}
    skipped_ids = trigger_ids | note_ids
    trig = next((n for n in raw if n.get("type") == "trigger"), {}) or {}
    steps: list[dict] = []
    for n in raw:
        kind = n.get("type")
        if kind in ("trigger", NOTE_KIND):
            continue
        after = [a for a in (n.get("after") or []) if a not in skipped_ids]
        step: dict = {"id": n.get("id"), "kind": kind, "after": after}
        if kind == "agent":
            step["prompt"] = n.get("prompt", "")
            # No ``provider``: a step names a model, and the runtime derives the provider
            # from the host catalog (``models.provider_for_model``).
            for key in ("profile", "model", "schema", "inputs", "timeout", "retries"):
                if n.get(key) is not None:
                    step[key] = n[key]
        elif kind == "condition":
            step["expression"] = str(n.get("expression", "")).strip()
        elif kind == "approval":
            step["question"] = n.get("question", "")
            if n.get("options"):
                step["options"] = list(n["options"])
            if n.get("context"):
                step["context"] = n["context"]
            if n.get("timeout_minutes"):
                step["timeout_minutes"] = int(n["timeout_minutes"])
            if n.get("on_timeout"):
                step["on_timeout"] = str(n["on_timeout"]).strip().lower()
        elif kind == "output":
            step["keys"] = after
            # Delivery is optional: an output that only collects stays exactly as before.
            if n.get("deliver"):
                step["deliver"] = str(n["deliver"]).strip().lower()
            if n.get("target"):
                step["target"] = str(n["target"]).strip()
        else:
            # Unknown/missing type: a payload-less step would still enter the plan and run
            # as an error at best, so reject it while the graph is being converted.
            raise ValueError(f"unknown node type {kind!r} for node {n.get('id')!r}")
        steps.append(step)
    if not steps:
        raise ValueError("design has no executable nodes (only a trigger)")
    return {
        "name": name,
        "steps": topological_order(steps),
        "meta": {
            "trigger": {
                "mode": trig.get("trigger_mode", "manual"),
                "schedule": trig.get("schedule", ""),
            },
            "designer": True,
        },
    }
