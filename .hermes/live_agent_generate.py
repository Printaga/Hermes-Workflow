"""Live probe: resume the real parked run 31d5dbf2d6bb through the DEPLOYED plugin's
respond route with agent_generate — the real host PluginLlm, the live run store.
Run with the tools python: ~/.hermes/tools/python-*/bin/python3 .hermes/live_agent_generate.py
Not shipped, not a test."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

AGENT_ROOT = "/home/lenovo/.hermes/hermes-agent"
if AGENT_ROOT not in sys.path:
    sys.path.insert(0, AGENT_ROOT)
import hermes_bootstrap  # noqa: F401  (the gateway's own dependency bootstrap)
sys.path.insert(0, "/home/lenovo/.hermes/plugins/visual-workflow")

RUN_ID = "31d5dbf2d6bb"
NODE = "write"

PLUG = pathlib.Path("/home/lenovo/.hermes/plugins/visual-workflow")
spec = importlib.util.spec_from_file_location("dp", PLUG / "dashboard" / "plugin_api.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["dp"] = mod
spec.loader.exec_module(mod)
print("spawn backend available:", mod.llm_spawn() is not None, flush=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(mod.router, prefix="/api/plugins/visual-workflow")
client = TestClient(app)

before = json.loads((pathlib.Path.home() / ".hermes/workflow-runs" / f"{RUN_ID}.json").read_text())
print("before:", before["status"], "pending", (before.get("pending") or {}).get("node_id"), flush=True)

res = client.post(
    f"/api/plugins/visual-workflow/runs/{RUN_ID}/respond",
    json={"run_id": RUN_ID, "node_id": NODE, "agent_generate": True},
)
print("HTTP", res.status_code, flush=True)
r = res.json()
print("status:", r.get("status"), flush=True)
print("outputs:", json.dumps(r.get("outputs"), ensure_ascii=False)[:300], flush=True)
print("deliveries:", json.dumps(r.get("deliveries"), ensure_ascii=False), flush=True)
print("error:", r.get("error"), flush=True)
after = json.loads((pathlib.Path.home() / ".hermes/workflow-runs" / f"{RUN_ID}.json").read_text())
print("on disk after:", after["status"], flush=True)
