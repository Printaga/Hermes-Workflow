"""One-off repair for runs stranded by the terminal-status bug.

A run whose stored cursor has reached the end of its plan was finished, but the old runner
never saved that last transition. Derive the truth from the plan rather than guessing: rebuild
each design's plan and only rewrite a run when ``cursor >= len(steps)`` and nothing is pending.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/lenovo/Development/Hermes-Workflow")

from visual_workflow_hermes.convert import build_run_plan
from visual_workflow_hermes.store import DesignStore, RunStore

home = Path.home() / ".hermes"
runs = RunStore(root=home / "workflow-runs")
designs = DesignStore(root=home / "workflow-designs")

repaired, skipped = [], []
for row in runs.recent(limit=200):
    state, run_id = row["state"], row["run_id"]
    if state.get("status") != "running" or state.get("pending"):
        continue
    try:
        plan = build_run_plan(designs.load(state.get("name") or ""))
    except (FileNotFoundError, ValueError):
        skipped.append((run_id, "design missing or invalid"))
        continue
    if state.get("cursor", 0) < len(plan["steps"]):
        skipped.append((run_id, f"cursor {state.get('cursor')} < {len(plan['steps'])} steps"))
        continue
    state["status"] = "done"
    runs.save(state)
    repaired.append(run_id)

print(json.dumps({"repaired": repaired, "skipped": skipped}, indent=1))
