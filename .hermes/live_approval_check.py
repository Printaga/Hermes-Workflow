"""Live approval-gate + delivery check against the real Hermes home.

Not a test (pytest never sends anything): this is the operator-approved live run. It resumes the
paused run named on the command line and prints the delivery receipt.
"""
import json
import os
import sys
import uuid
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
_REPO = str(Path(__file__).resolve().parents[1])  # this checkout
for _p in (_REPO, str(HOME / "hermes-agent")):  # the host send seam lives in the agent tree
    if _p not in sys.path:
        sys.path.insert(0, _p)

from visual_workflow_hermes.convert import build_run_plan
from visual_workflow_hermes.delivery import deliver_output
from visual_workflow_hermes.runner import new_state, resume_plan, run_plan
from visual_workflow_hermes.store import DesignStore, RunStore

DESIGN = "live-test-approval"


def start():
    plan = build_run_plan(DesignStore().load(DESIGN))
    runs = RunStore()
    rid = uuid.uuid4().hex[:12]
    state = new_state(plan, rid)
    runs.save(state)
    state = run_plan(plan, state, spawn=None, on_step=runs.save, deliver=deliver_output)
    print("STATUS:", state["status"])
    print("RUN_ID:", state["run_id"])
    print("GATE:", json.dumps(state["pending"], ensure_ascii=False))


def resume(rid, answer):
    runs = RunStore()
    state = runs.load(rid)
    gate = (state.get("pending") or {}).get("node_id", "-")
    print("RESUMING:", rid, "| status was", state["status"], "| gate:", gate)
    plan = build_run_plan(DesignStore().load(DESIGN))
    state = resume_plan(plan, state, answer, spawn=None, on_step=runs.save, deliver=deliver_output)
    print("STATUS:", state["status"], "| error:", state["error"])
    print("DELIVERIES:", json.dumps(state.get("deliveries", []), indent=2, ensure_ascii=False))
    return state


if __name__ == "__main__":
    if sys.argv[1:2] == ["resume"]:  # resume <run_id> <answer>
        if len(sys.argv) != 4:
            print(f"usage: {sys.argv[0]} [resume <run_id> <answer>]", file=sys.stderr)
            sys.exit(2)
        resume(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 1:
        start()
    else:
        # A typo must not silently start a fresh live run with real delivery side effects.
        print(f"usage: {sys.argv[0]} [resume <run_id> <answer>]", file=sys.stderr)
        sys.exit(2)
