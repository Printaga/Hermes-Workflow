"""Set the probe's wedged run back to a failed verdict via the plugin's own store API.

The throwaway retry-probe server died mid-retry (incomplete throwaway env), stranding the run
in "running". Clearing it through the plugin's own store code — never by hand-editing the file
— leaves it honestly failed and retryable (not shipped, not a test).
"""
import sys

sys.path.insert(0, "/home/lenovo/.hermes/plugins/visual-workflow")

from visual_workflow_hermes.store import RunStore

runs = RunStore()
state = runs.load("f45ea3360e6c")
assert state["status"] == "running", state["status"]
state["status"] = "failed"
state["error"] = {
    "node_id": "writer",
    "msg": "aborted mid-retry by the probe's incomplete environment "
           "(live_http probe, not a real run verdict)",
}
runs.save(state)
print("now:", runs.load("f45ea3360e6c")["status"], "| stored error msg ok")
