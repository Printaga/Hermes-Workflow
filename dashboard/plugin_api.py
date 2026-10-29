"""Visual Workflow dashboard plugin — backend API, mounted at ``/api/plugins/visual-workflow/``.

Thin wrappers over the plugin's own ``store`` / ``convert`` / ``runner`` modules, i.e. the exact
code paths ``/workflow`` and the ``workflow_design_*`` tools use, so the GUI tab and the chat
surface cannot drift.

Agent steps are never executed here: the web server has no subagent backend, so
``run_plan(..., spawn=None)`` parks the run at ``awaiting_agent`` and the dashboard answers it
through ``POST /runs/{run_id}/respond``.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    # The host imports this file by path, so the plugin dir is not importable as a package.
    sys.path.append(str(_PLUGIN_ROOT))

from fastapi import APIRouter, Body, HTTPException  # noqa: E402

from visual_workflow_hermes.convert import build_run_plan  # noqa: E402
from visual_workflow_hermes.delivery import deliver_output  # noqa: E402
from visual_workflow_hermes.profiles import list_host_profiles  # noqa: E402
from visual_workflow_hermes.runner import StepError, new_state, resume_plan, run_plan  # noqa: E402
from visual_workflow_hermes.schema import validate_designer_graph  # noqa: E402
from visual_workflow_hermes.store import DesignStore, RunStore  # noqa: E402

router = APIRouter()


def _home() -> Path:
    """Hermes home for this request: the profile-scoped ``get_hermes_home()`` when the host is
    importable (it honours the dashboard's per-request profile scope), else ``$HERMES_HOME``."""
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _designs() -> DesignStore:
    return DesignStore(root=_home() / "workflow-designs")


def _runs() -> RunStore:
    return RunStore(root=_home() / "workflow-runs")


def _result(state: dict) -> dict:
    """Run state in the shape ``workflow_design_run`` returns."""
    return {
        "ok": state["status"] != "failed",
        "run_id": state["run_id"],
        "name": state.get("name"),
        "status": state["status"],
        "pending": state["pending"],
        "outputs": state["outputs"],
        "skipped": state["skipped"],
        "deliveries": state.get("deliveries", []),
        "error": state["error"],
    }


def _load_design(name: str) -> dict:
    try:
        return _designs().load(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:  # malformed name
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load_run(run_id: str) -> dict:
    try:
        return _runs().load(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/profiles")
def list_profiles() -> dict:
    """Host profiles ("bots") for the agent-node picker.

    Always 200: an empty list with ``available: false`` is the honest answer when the host
    profile registry cannot be read, and the canvas falls back to a free-text field.
    """
    profiles = list_host_profiles()
    return {"profiles": profiles, "available": bool(profiles)}


@router.get("/designs")
def list_designs() -> dict:
    """Names of the saved designs under ``$HERMES_HOME/workflow-designs``."""
    return {"designs": _designs().list_designs()}


@router.get("/designs/{name}")
def get_design(name: str) -> dict:
    """One saved designer graph."""
    return {"name": name, "graph": _load_design(name)}


@router.post("/designs/{name}")
def save_design(name: str, payload: dict = Body(...)) -> dict:
    """Validate and store a designer graph under ``name``.

    An invalid graph is an expected outcome, not a transport error: 200 with
    ``{"ok": false, "errors": [...]}`` so the canvas can paint the defects inline.
    """
    graph = payload.get("graph") if isinstance(payload, dict) else None
    if not isinstance(graph, dict):
        raise HTTPException(status_code=400, detail="graph must be an object")
    graph = {**graph, "name": name}
    errors = validate_designer_graph(graph)
    if errors:
        return {"ok": False, "name": name, "errors": errors}
    try:
        path = _designs().save(name, graph)
    except ValueError as exc:  # the name itself is malformed
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "name": name, "path": str(path), "nodes": len(graph.get("nodes", []))}


@router.post("/designs/{name}/validate")
def validate_design(name: str, payload: Optional[dict] = Body(default=None)) -> dict:
    """Validate a saved design, or the draft graph posted as ``{"graph": ...}``.

    The body is optional: with no graph the stored design is checked (what the chat tool does
    before running it); with a graph the unsaved canvas is checked.
    """
    graph = (payload or {}).get("graph") if isinstance(payload, dict) else None
    if graph is None:
        graph = _load_design(name)
    if not isinstance(graph, dict):
        raise HTTPException(status_code=400, detail="graph must be an object")
    errors = validate_designer_graph(graph)
    return {"ok": not errors, "name": name, "valid": not errors, "errors": errors}


@router.post("/designs/{name}/run")
def run_design(name: str) -> dict:
    """Start a run now and advance it until it finishes or pauses at a gate / agent step."""
    designer = _load_design(name)
    errors = validate_designer_graph(designer)
    if errors:
        return {"ok": False, "name": name, "status": "invalid", "errors": errors}
    try:
        plan = build_run_plan(designer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run_id = uuid.uuid4().hex[:12]
    runs = _runs()
    state = new_state(plan, run_id)
    runs.save(state)
    state = run_plan(plan, state, spawn=None, on_step=runs.save, deliver=deliver_output)
    return _result(state)


@router.post("/runs/{run_id}/respond")
def respond_run(run_id: str, payload: dict = Body(...)) -> dict:
    """Resume a paused run: an approval ``answer``, or the output of a pending agent step."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be an object")
    node_id = payload.get("node_id") or ""
    answer: Any = payload.get("structured")
    if answer is None:
        answer = payload.get("answer")
    runs = _runs()
    state = _load_run(run_id)
    pending = state.get("pending") or {}
    if pending.get("node_id") != node_id:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id!r} is not waiting on {node_id!r}",
        )
    try:
        plan = build_run_plan(_load_design(state["name"]))
        state = resume_plan(plan, state, answer, spawn=None, on_step=runs.save,
                            deliver=deliver_output)
    except (StepError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result(state)
