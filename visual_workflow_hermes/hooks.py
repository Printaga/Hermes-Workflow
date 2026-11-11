"""``pre_tool_call`` gate for model-initiated external sends.

``workflow_design_save`` may store an output node with any ``<platform>:<id>``
target, and ``workflow_design_run`` then sends upstream agent output there through
``deliver_output`` — two model tool calls to message other platforms, no human
involved. This hook asks Hermes' own approval prompt first whenever a run the
*model* starts would deliver: ``{"action": "approve", "message": ...}`` names the
target(s); the message text itself does not exist yet (it is whatever the run's
agent steps produce), and the message says so.

Human paths never see this hook: slash commands (``/workflow run``) and the
canvas/dashboard routes call the runner directly instead of going through the
model tool dispatcher, so only model tool calls are gated. Cron replays go
through ``workflow_design_run`` like any model call, so in a session with nobody
to approve, the gate fails closed and blocks the run — a scheduled design that
must send needs a person, or it should collect only.
"""

from __future__ import annotations

from typing import Any, Optional

_RUN_TOOL = "workflow_design_run"


def _design_name_from_args(args: dict) -> str:
    """The design a run call replays, mirroring the tool's own precedence.

    ``tool_run`` checks ``retry`` before ``name``; the hook resolves the same way so
    a call carrying both cannot smuggle a delivering retry behind a quiet name.
    """
    retry = args.get("retry")
    if isinstance(retry, str) and retry.strip():
        try:
            from .store import RunStore

            state = RunStore().load(retry.strip())
        except Exception:
            return ""
        if isinstance(state, dict) and isinstance(state.get("name"), str):
            return state["name"].strip()
        return ""
    name = args.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _describe_target(entry: dict) -> str:
    return f"{entry['target']} (node {entry['node']})"


def on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[dict]:
    """Escalate model-started runs with delivering outputs to human approval.

    Anything else — other tools, collect-only designs, unknown designs — returns
    None and the call proceeds. Unknown designs are fail-open on purpose: the run
    tool itself rejects them with "unknown design", so blocking here would only
    replace its error with ours.
    """
    if tool_name != _RUN_TOOL or not isinstance(args, dict):
        return None
    name = _design_name_from_args(args)
    if not name:
        return None
    try:
        from .delivery import delivering_targets
        from .store import DesignStore

        targets = delivering_targets(DesignStore().load(name))
    except Exception:
        return None
    if not targets:
        return None
    joined = "; ".join(_describe_target(entry) for entry in targets)
    return {
        "action": "approve",
        "message": (
            f"Workflow design {name!r} is about to RUN and then send its collected "
            f"output to: {targets}. The message text does not exist yet — it will be "
            "whatever this run's agent steps produce. Approve to let this run send; "
            "denying blocks the run."
        ),
    }
