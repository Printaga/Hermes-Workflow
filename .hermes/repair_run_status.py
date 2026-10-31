"""One-off repair for runs stranded by the terminal-status bug.

A run whose stored cursor has reached the end of its plan was finished, but the old runner
never saved that last transition. Derive the truth from the plan rather than guessing: rebuild
each design's plan and only rewrite a run when ``cursor >= len(steps)`` and nothing is pending.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from visual_workflow_hermes.convert import build_run_plan
from visual_workflow_hermes.store import DesignStore, RunStore


def main() -> None:
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    runs = RunStore(root=home / "workflow-runs")
    designs = DesignStore(root=home / "workflow-designs")

    repaired, skipped = [], []
    # Every run on disk: a limit would silently leave older runs stranded forever.
    for run_id in runs.list_runs():
        try:
            state = runs.load(run_id)
        except (OSError, ValueError) as exc:
            skipped.append((run_id, f"unreadable run: {exc}"))
            continue
        if not isinstance(state, dict) or state.get("status") != "running" \
                or state.get("pending"):
            continue
        try:
            plan = build_run_plan(designs.load(state.get("name") or ""))
            steps = plan.get("steps")
            if not isinstance(steps, list):
                raise ValueError("plan has no steps list")
            cursor = state.get("cursor", 0)
            if not isinstance(cursor, int):
                raise ValueError(f"bad cursor {cursor!r}")
        except Exception as exc:  # one bad run must not abort the batch
            skipped.append((run_id, f"design/plan unreadable: {exc}"))
            continue
        if cursor < len(steps):
            skipped.append((run_id, f"cursor {cursor} < {len(steps)} steps"))
            continue
        # RunStore.save derives the path from state["run_id"]; make it match the file we read,
        # or the repair would write an orphan and leave the original stranded.
        state["run_id"] = run_id
        state["status"] = "done"
        try:
            runs.save(state)
        except (OSError, ValueError, KeyError) as exc:
            skipped.append((run_id, f"save failed: {exc}"))
            continue
        repaired.append(run_id)

    print(json.dumps({"repaired": repaired, "skipped": skipped}, indent=1))


if __name__ == "__main__":
    main()
