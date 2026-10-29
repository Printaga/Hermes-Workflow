"""Trigger helpers. Manual runs now; schedule replays through ``cronjob_manage``.

An inbound webhook is not a trigger mode: Hermes' webhook subscriptions are operator-managed
(``hermes webhook subscribe``, HMAC secret) and can fire an existing cron job, so an external
POST reaches a schedule — it cannot reach a plugin route, because plugins cannot open one.

The cron surface is the ``cronjob_manage`` tool (toolset ``cronjob``), not
``cron_providers/chronos`` — chronos is a scheduler *backend* selected via ``cron.provider``.
A cron job takes a schedule plus a self-contained prompt; it has no field for a tool name
with structured arguments, so the replay is expressed as instructions that make the cron
agent call this plugin's own tools.
"""
from __future__ import annotations

TOOLSET = "visual-workflow"


def _trigger(designer: dict) -> dict:
    triggers = [n for n in designer.get("nodes", [])
                if isinstance(n, dict) and n.get("type") == "trigger"]
    if not triggers:
        raise ValueError("no trigger node")
    return triggers[0]


def schedule_plan(designer: dict, *, deliver: str = "origin") -> dict:
    """Return the exact ``cronjob_manage`` arguments for a schedule-trigger design.

    The job runs in a fresh session with no chat context, so the prompt must be fully
    self-contained and may only rely on this plugin's own tools (``enabled_toolsets``).
    Raises ValueError when the design has no usable schedule.
    """
    trig = _trigger(designer)
    if trig.get("trigger_mode") != "schedule":
        raise ValueError("trigger_mode is not schedule")
    cron_expr = (trig.get("schedule") or "").strip()
    if not cron_expr:
        raise ValueError("schedule trigger needs a 'schedule' cron expression (e.g. '0 9 * * *')")
    name = designer.get("name", "workflow")
    prompt = (
        f"Run the saved Hermes workflow design '{name}'.\n"
        f"1. Call workflow_design_run with {{\"name\": \"{name}\"}}.\n"
        "2. If status is 'awaiting_agent', do what pending.prompt asks, then call "
        "workflow_design_respond with run_id, node_id and your output; repeat until the run "
        "is no longer awaiting_agent.\n"
        "3. If status is 'awaiting_approval', do NOT answer it — report the gate question and stop.\n"
        "4. Report the final outputs verbatim.\n"
        "Never invent workflow nodes or edit the saved design."
    )
    return {
        "action": "create",
        "name": f"workflow:{name}",
        "schedule": cron_expr,
        "prompt": prompt,
        "enabled_toolsets": [TOOLSET],
        "deliver": deliver,
    }
