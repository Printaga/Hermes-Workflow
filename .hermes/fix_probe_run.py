"""Set the probe's wedged run back to a failed verdict via the plugin's own store API.

The throwaway retry-probe server died mid-retry (incomplete throwaway env), stranding the run
in "running". Clearing it through the plugin's own store code — never by hand-editing the file
— leaves it honestly failed and retryable (not shipped, not a test).
"""
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
sys.path.insert(0, str(HOME / "plugins" / "visual-workflow"))

from visual_workflow_hermes.store import RunStore  # noqa: E402

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "f45ea3360e6c"

runs = RunStore()
state = runs.load(RUN_ID)
# An explicit check, not `assert`: `python -O` strips asserts, and this guard protects a
# real persisted verdict from being overwritten.
if state.get("status") != "running":
    raise SystemExit(f"refusing to overwrite non-running run: {state.get('status')!r}")
state["status"] = "failed"
state["error"] = {
    "node_id": (state.get("error") or {}).get("node_id") or "",
    "msg": "aborted mid-retry by the probe's incomplete environment "
           "(live_http probe, not a real run verdict)",
}
runs.save(state)
print("now:", runs.load(RUN_ID)["status"], "| stored error msg ok")
