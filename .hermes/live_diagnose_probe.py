"""Live probe: one tiny agent step through the DEPLOYED plugin's spawn seam, to see what a
real diagnosed failure (or success) records now. Run with the tools python:
~/.hermes/tools/python-*/bin/python3 .hermes/live_diagnose_probe.py
Not shipped, not a test.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
AGENT_ROOT = str(HOME / "hermes-agent")
if AGENT_ROOT not in sys.path:
    sys.path.insert(0, AGENT_ROOT)
import hermes_bootstrap  # noqa: F401  (the gateway's own dependency bootstrap)
sys.path.insert(0, str(HOME / "plugins" / "visual-workflow"))

from visual_workflow_hermes.spawn import llm_spawn  # noqa: E402

spawn = llm_spawn()
print("spawn backend available:", spawn is not None, flush=True)
if spawn is None:
    print("no spawn backend: host PluginLlm not importable", flush=True)
    sys.exit(2)

BOGUS = os.environ.get("PROBE_BOGUS_MODEL") == "1"
step = {"id": "probe", "kind": "agent", "prompt": "Reply with the single word: ok"}
if BOGUS:
    step["model"] = "definitely-not-a-real-model-xyz"
out = spawn(step, {})
print("live step result keys:", sorted(out), flush=True)
print("recorded error (if any):", out.get("error", "(none — step succeeded)"), flush=True)
