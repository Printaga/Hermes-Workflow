"""Visual Workflow dashboard plugin — backend API, mounted at ``/api/plugins/visual-workflow/``.

Thin wrappers over the plugin's own ``store`` / ``convert`` / ``runner`` modules, i.e. the exact
code paths ``/workflow`` and the ``workflow_design_*`` tools use, so the GUI tab and the chat
surface cannot drift.

Agent steps are never executed here: the web server has no subagent backend, so
``run_plan(..., spawn=None)`` parks the run at ``awaiting_agent`` and the dashboard answers it
through ``POST /runs/{run_id}/respond``.
"""
from __future__ import annotations

import json
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

from visual_workflow_hermes.channels import list_host_channels  # noqa: E402
from visual_workflow_hermes.convert import build_run_plan  # noqa: E402
from visual_workflow_hermes.delivery import deliver_output  # noqa: E402
from visual_workflow_hermes.profiles import list_host_profiles  # noqa: E402
from visual_workflow_hermes.runner import (  # noqa: E402
    StepError,
    check_timeouts,
    new_state,
    resume_plan,
    run_plan,
)
from visual_workflow_hermes.schedule import (  # noqa: E402
    apply_action,
    build_cron,
    list_workflow_jobs,
    schedule_design,
)
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


def _settled(state: dict, runs: RunStore) -> dict:
    """Apply a gate's deadline to a stored run and save the verdict once, when it expires.

    Nothing sweeps paused runs in the background, so reading a run is the moment its timeout
    can be honoured — otherwise an abandoned gate would wait forever, which is the whole point
    of having a deadline.
    """
    before = state.get("status")
    check_timeouts(state)
    if state.get("status") != before:
        runs.save(state)
    return state


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


@router.get("/channels")
def list_channels() -> dict:
    """Delivery targets ("channels") for the output-node picker.

    Always 200: an empty list with ``available: false`` is the honest answer when the host
    gateway has discovered no chats, and the canvas then says so instead of offering a dead
    control. Reads the host's channel directory only — nothing is sent here.
    """
    return list_host_channels(_home())


@router.get("/designs")
def list_designs() -> dict:
    """Names of the saved designs under ``$HERMES_HOME/workflow-designs``."""
    return {"designs": _designs().list_designs()}


# Built-in starting points ship with the plugin, so "New" is not a blank canvas with nothing to
# learn from. Read straight from ``examples/`` at request time: one file is the single source of
# truth for the JSON, the template list, and the tests that validate every example.
TEMPLATES_DIR = _PLUGIN_ROOT / "examples"
_SUFFIX = ".designer.json"


@router.get("/designs/templates")
def list_templates() -> dict:
    """Built-in designs from ``examples/*.designer.json``, ready to load into the canvas.

    Declared BEFORE ``/designs/{name}`` on purpose: FastAPI matches in registration order, so a
    later block here would be swallowed as a design literally named "templates". A file that is
    unreadable or not a JSON object is skipped rather than failing the whole list, and an empty
    list is an honest answer (the canvas then offers only a blank design).
    """
    rows: list[dict] = []
    for path in sorted(TEMPLATES_DIR.glob(f"*{_SUFFIX}")):
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            continue
        name = path.name[: -len(_SUFFIX)]
        rows.append({
            "name": name,
            "title": str(graph.get("title") or name),
            "description": str(graph.get("description") or ""),
            "nodes": len(graph["nodes"]),
            "graph": {**graph, "name": name},
        })
    return {"templates": rows}


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


@router.get("/schedules")
def list_schedules() -> dict:
    """Cron jobs this plugin created (``name`` starts with ``workflow:``).

    Read-only: an empty list with ``available: false`` means the host scheduler could not be
    read here, which the Schedules view states instead of pretending there are no jobs.
    """
    return list_workflow_jobs()


@router.post("/designs/{name}/schedule")
def schedule_design_route(name: str, payload: Optional[dict] = Body(default=None)) -> dict:
    """Turn a design's trigger into a real Hermes cron job (create or update it).

    Body (all optional): ``{"preset": "daily", "time": "09:00", "weekday": "mon",
    "cron": "0 9 * * *", "deliver": "origin"}``. The chosen schedule is written onto the
    design's trigger node, so the canvas and the job cannot disagree. A scheduling problem is
    an expected outcome: 200 with ``{"ok": false, "error": ...}``.
    """
    body = payload if isinstance(payload, dict) else {}
    designer = _load_design(name)
    try:
        cron = build_cron(
            str(body.get("preset") or (designer.get("trigger_mode") or "daily")),
            time=str(body.get("time") or "09:00"),
            weekday=str(body.get("weekday") or "mon"),
            custom=str(body.get("cron") or ""),
        )
    except ValueError as exc:
        return {"ok": False, "name": name, "error": str(exc)}
    trig = next((n for n in designer.get("nodes", [])
                 if isinstance(n, dict) and n.get("type") == "trigger"), None)
    if trig is None:
        raise HTTPException(status_code=400, detail="design has no trigger node")
    trig["trigger_mode"] = "schedule"
    trig["schedule"] = cron
    designer = {**designer, "name": name}
    errors = validate_designer_graph(designer)
    if errors:
        return {"ok": False, "name": name, "errors": errors}
    _designs().save(name, designer)
    result = schedule_design(designer, cron=cron, deliver=str(body.get("deliver") or "origin"))
    return {**result, "name": name, "cron": cron}


@router.post("/schedules/{job_id}/{action}")
def schedule_action(job_id: str, action: str) -> dict:
    """Pause / resume / run-now / remove one scheduled workflow job."""
    return {**apply_action(action, job_id), "job_id": job_id}


@router.get("/runs")
def list_runs(limit: int = 20) -> dict:
    """Recent runs on disk, newest first — including ones this browser did not start.

    The canvas used to know only the run it had just launched, so a run begun by the chat tool,
    a cron job or another tab was invisible and could not be answered. Each row carries what a
    reviewer needs to act: status, and for a gate the question and its options.
    """
    runs = _runs()
    rows = []
    for row in runs.recent(limit):
        state = _settled(row["state"], runs)
        pending = state.get("pending") or {}
        rows.append(
            {
                "run_id": row["run_id"],
                "name": state.get("name"),
                "status": state.get("status"),
                "node_id": pending.get("node_id"),
                "question": pending.get("question"),
                "options": pending.get("options") or [],
                # A timed gate's deadline travels with the row, so the list can show how
                # long the reviewer still has instead of only how old the file is.
                "waiting_since": pending.get("waiting_since"),
                "timeout_minutes": pending.get("timeout_minutes"),
                "error": state.get("error"),
                "deliveries": state.get("deliveries") or [],
                "updated": row["updated"],
            }
        )
    return {"runs": rows}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """One stored run in the same shape a run/respond call returns (for reopening a run)."""
    runs = _runs()
    return _result(_settled(_load_run(run_id), runs))


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
