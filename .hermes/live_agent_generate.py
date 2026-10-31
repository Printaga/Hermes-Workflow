"""Live probe: resume the real parked run through the DEPLOYED plugin's respond route with
agent_generate — the real host PluginLlm, the live run store.
Run with the tools python: ~/.hermes/tools/python-*/bin/python3 .hermes/live_agent_generate.py
Not shipped, not a test.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import sys

HOME = pathlib.Path(os.environ.get("HERMES_HOME") or (pathlib.Path.home() / ".hermes"))
AGENT_ROOT = str(HOME / "hermes-agent")
if AGENT_ROOT not in sys.path:
    sys.path.insert(0, AGENT_ROOT)
import hermes_bootstrap  # noqa: F401  (the gateway's own dependency bootstrap)
PLUG = HOME / "plugins" / "visual-workflow"
sys.path.insert(0, str(PLUG))

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "31d5dbf2d6bb"
NODE = sys.argv[2] if len(sys.argv) > 2 else "write"

API_FILE = PLUG / "dashboard" / "plugin_api.py"
spec = importlib.util.spec_from_file_location("dp", API_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load plugin_api from {API_FILE}")
mod = importlib.util.module_from_spec(spec)
sys.modules["dp"] = mod
spec.loader.exec_module(mod)
print("spawn backend available:", mod.llm_spawn() is not None, flush=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(mod.router, prefix="/api/plugins/visual-workflow")
client = TestClient(app)

run_file = HOME / "workflow-runs" / f"{RUN_ID}.json"
before = json.loads(run_file.read_text())
print("before:", before["status"], "pending", (before.get("pending") or {}).get("node_id"), flush=True)

# This POST rewrites the real parked run in place; keep a restore point in case generation
# fails part-way and leaves it unusable.
backup = run_file.with_suffix(".json.bak")
shutil.copy2(run_file, backup)

res = client.post(
    f"/api/plugins/visual-workflow/runs/{RUN_ID}/respond",
    json={"run_id": RUN_ID, "node_id": NODE, "agent_generate": True},
)
print("HTTP", res.status_code, flush=True)
try:
    r = res.json()
except ValueError:
    print("non-JSON body:", res.text[:2000], flush=True)
    raise
print("status:", r.get("status"), flush=True)
print("outputs:", json.dumps(r.get("outputs"), ensure_ascii=False)[:300], flush=True)
print("deliveries:", json.dumps(r.get("deliveries"), ensure_ascii=False), flush=True)
print("error:", r.get("error"), flush=True)
after = json.loads(run_file.read_text())
print("on disk after:", after["status"], flush=True)
