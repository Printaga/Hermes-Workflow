"""Live test #2: a real run that pauses at an approval gate.

Uses the same code the dashboard's POST /designs/{name}/run uses (DesignStore -> validate ->
build_run_plan -> new_state -> run_plan), minus the HTTP transport, so the run is persisted to
~/.hermes/workflow-runs and the GUI's respond route can resume it with the user's answer.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from visual_workflow_hermes.convert import build_run_plan
from visual_workflow_hermes.delivery import deliver_output
from visual_workflow_hermes.runner import new_state, run_plan
from visual_workflow_hermes.schema import validate_designer_graph
from visual_workflow_hermes.store import DesignStore, RunStore

NAME = "live-approval-test"
_graph = {
    "name": NAME,
    "nodes": [
        {"id": "start", "type": "trigger", "trigger_mode": "manual", "after": []},
        {
            "id": "gate",
            "type": "approval",
            "question": "TEST \u2014 approve the live workflow delivery?",
            "options": ["TEST: approved", "reject"],
            "after": ["start"],
        },
        {
            "id": "receipt",
            "type": "output",
            "deliver": "notification",
            "target": "telegram",
            "after": ["gate"],
        },
    ],
}


def main() -> None:
    errors = validate_designer_graph(_graph)
    if errors:
        print("INVALID GRAPH:", json.dumps(errors, indent=1))
        sys.exit(2)

    DesignStore().save(NAME, _graph)
    plan = build_run_plan(_graph)
    runs = RunStore()
    run_id = uuid.uuid4().hex[:12]
    state = new_state(plan, run_id)
    runs.save(state)
    state = run_plan(plan, state, spawn=None, on_step=runs.save, deliver=deliver_output)

    print("DESIGN:", NAME)
    print("PLAN STEPS:", json.dumps(plan["steps"], indent=1))
    print("RESULT:", json.dumps(
        {
            "run_id": state["run_id"],
            "status": state["status"],
            "node_id": (state.get("pending") or {}).get("node_id"),
            "question": (state.get("pending") or {}).get("question"),
            "options": (state.get("pending") or {}).get("options"),
            "cursor": state["cursor"],
            "outputs": state["outputs"],
        },
        indent=1,
    ))


if __name__ == "__main__":
    # Importing this module must not validate, overwrite the saved design, or start a run.
    main()
