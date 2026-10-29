"""Sequential, resumable executor for run plans. Owned by the plugin (no Hermes imports).

Steps run one at a time in plan order. A step completes, fails, is skipped by a false
condition, or pauses the run at an approval or a pending agent turn. ``state`` is mutated in
place and is JSON-serializable, so a paused run can be persisted and resumed later.
"""
from __future__ import annotations

import operator
import re

COMPARATORS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt,
               ">=": operator.ge, "<": operator.lt, "<=": operator.le}
_HEAD_RE = re.compile(r"^out\.(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$")
PAUSED = ("awaiting_approval", "awaiting_agent")


class StepError(ValueError):
    """A step could not run (bad expression, missing input, agent failure)."""


def render_context(step: dict, outputs: dict) -> str:
    """Upstream outputs as labelled text, for an agent's ``context``."""
    upstream = {p: outputs[p] for p in step.get("after", []) if p in outputs}
    return "\n\n".join(f"--- output from {k} ---\n{v}" for k, v in upstream.items())


def _coerce(text: str):
    """Turn an expression literal into a comparable Python value."""
    raw = text.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            pass
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    return raw


def _dig(obj, path: str):
    """Walk a dotted path; raise StepError naming the missing segment."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise StepError(f"missing path segment {part!r} in expression target")
            cur = cur[part]
        else:
            raise StepError(f"cannot descend into {type(cur).__name__} at {part!r}")
    return cur


def evaluate_condition(expression: str, outputs: dict, node_ids) -> bool:
    """Evaluate one ``out.<node>.<path> <op> <value>`` expression against prior outputs.

    Never uses ``eval``. An unresolvable target is a StepError (a design defect), not False.
    """
    match = _HEAD_RE.match((expression or "").strip())
    if not match:
        raise StepError(f"unparseable condition expression: {expression!r}")
    target, op, literal = match.groups()
    # Longest known node id prefix wins, so ids may contain dots.
    node = next((n for n in sorted(node_ids, key=len, reverse=True)
                 if target == n or target.startswith(f"{n}.")), None)
    if node is None:
        raise StepError(f"condition references unknown node in {expression!r}")
    if node not in outputs:
        raise StepError(f"condition references node {node!r} that has not produced output")
    left = outputs[node] if target == node else _dig(outputs[node], target[len(node) + 1:])
    return bool(COMPARATORS[op](left, _coerce(literal)))


def run_plan(plan: dict, state: dict, spawn=None, on_step=None, deliver=None) -> dict:
    """Advance *state* through *plan* until it finishes or pauses.

    *state* is ``{"run_id", "name", "cursor", "status", "outputs", "skipped", "pending",
    "error", "answers", "deliveries"}``. ``cursor`` is the index of the next step, so resuming
    is a matter of calling again with the same state. ``spawn`` runs an agent step; when it is
    None an agent step pauses the run for the host to perform. ``on_step(state)`` is called
    after each completed step (used to persist). ``deliver(step, payload, run_name)`` sends an
    output node's payload somewhere; when it is None an output only collects. A delivery that
    fails is recorded in ``state["deliveries"]`` and does NOT fail the run.
    """
    steps = plan["steps"]
    node_ids = {s["id"] for s in steps}
    while state["cursor"] < len(steps):
        step = steps[state["cursor"]]
        sid, kind = step["id"], step["kind"]
        # ``skipped`` is a LIST (not a set) so the whole state stays JSON-serializable.
        if any(dep in state["skipped"] for dep in step.get("after", [])):
            state["skipped"].append(sid)
            state["cursor"] += 1
            if on_step:
                on_step(state)
            continue
        try:
            if kind == "agent":
                if spawn is None:
                    state["status"] = "awaiting_agent"
                    state["pending"] = {"node_id": sid, "prompt": step.get("prompt", ""),
                                        "context": render_context(step, state["outputs"])}
                    if on_step:
                        on_step(state)
                    return state
                produced = spawn(step, state["outputs"], state)
                if produced.get("error"):
                    raise StepError(str(produced["error"]))
                state["outputs"][sid] = produced.get("structured") or produced.get("output", "")
            elif kind == "condition":
                if not evaluate_condition(step["expression"], state["outputs"], node_ids):
                    state["skipped"].append(sid)
                    state["cursor"] += 1
                    if on_step:
                        on_step(state)
                    continue
            elif kind == "approval":
                state["status"] = "awaiting_approval"
                state["pending"] = {"node_id": sid, "question": step.get("question", ""),
                                    "options": step.get("options", []),
                                    "context": step.get("context", "")}
                if on_step:
                    on_step(state)
                return state
            elif kind == "output":
                payload = {k: state["outputs"].get(k) for k in step.get("keys", [])}
                state["outputs"][sid] = payload
                if deliver is not None and step.get("deliver"):
                    state.setdefault("deliveries", []).append(
                        _deliver(deliver, step, payload, plan.get("name", ""))
                    )
            else:
                raise StepError(f"unknown step kind {kind!r}")
        except StepError as exc:
            state["status"] = "failed"
            state["error"] = {"node_id": sid, "msg": str(exc)}
            if on_step:
                on_step(state)
            return state
        state["cursor"] += 1
        if on_step:
            on_step(state)
    state["status"] = "done"
    state["pending"] = None
    return state


def _deliver(deliver, step: dict, payload, run_name: str) -> dict:
    """Call the delivery hook, stamped with the node it belongs to. Never raises."""
    try:
        outcome = deliver(step, payload, run_name) or {}
    except Exception as exc:  # a delivery problem is data, not a run failure
        outcome = {"ok": False, "detail": f"delivery error: {exc}"}
    return {"node_id": step.get("id"), **outcome}


def resume_plan(plan: dict, state: dict, answer, spawn=None, on_step=None, deliver=None) -> dict:
    """Feed an approval answer / pending agent output back in, then keep running."""
    pending = state.get("pending")
    if not pending:
        raise StepError("run is not paused; nothing to answer")
    node_id = pending["node_id"]
    step = next((s for s in plan["steps"] if s["id"] == node_id), None)
    if step is None:
        raise StepError(f"paused step {node_id!r} is not in the plan")
    if step["kind"] == "approval":
        # Validate BEFORE mutating, so a rejected answer leaves the run resumable.
        if step.get("options") and answer not in step["options"]:
            raise StepError(f"answer {answer!r} is not one of {step['options']}")
        state["answers"] = {**state.get("answers", {}), node_id: answer}
        state["outputs"][node_id] = answer
    else:
        state["outputs"][node_id] = answer
    state["cursor"] += 1
    state["pending"] = None
    state["status"] = "running"
    return run_plan(plan, state, spawn=spawn, on_step=on_step, deliver=deliver)


def new_state(plan: dict, run_id: str) -> dict:
    return {"run_id": run_id, "name": plan["name"], "cursor": 0, "status": "running",
            "outputs": {}, "skipped": [], "pending": None, "error": None, "answers": {},
            "deliveries": []}
