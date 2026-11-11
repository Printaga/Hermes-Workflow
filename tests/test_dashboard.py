"""Dashboard-plugin contract tests.

Hermes discovers a tab from ``dashboard/manifest.json``, serves ``entry`` from the plugin's
``dashboard/`` directory at ``/dashboard-plugins/<name>/<entry>``, and mounts the module-level
``router`` of the ``api`` file at ``/api/plugins/<name>/`` (hermes_cli/web_server_dashboard.py,
``_mount_plugin_api_routes`` -> ``_mount_one_plugin_api``). These tests pin that contract without
needing a running dashboard.

The router is asserted twice: statically from the source (always runs; ``uvx --with pytest`` has
no FastAPI) and, when FastAPI is importable, by importing the module exactly as the host does.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import types
from pathlib import Path

import pytest

from visual_workflow_hermes.schema import validate_designer_graph

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard"
MANIFEST = DASHBOARD / "manifest.json"
API = DASHBOARD / "plugin_api.py"
ENTRY = DASHBOARD / "dist" / "index.js"

# (path, method) pairs the dashboard calls. The first five are the requested contract; the
# save route is what makes the canvas able to persist a design.
REQUIRED_ROUTES = {
    ("/designs", "get"),
    ("/designs/{name}", "get"),
    ("/designs/{name}/validate", "post"),
    ("/designs/{name}/run", "post"),
    ("/runs/{run_id}/respond", "post"),
    # A failed run is retried from its failed step (the runner owns the reset).
    ("/runs/{run_id}/retry", "post"),
    # Runs view: every run on disk (not just the one this tab started), and one run's detail.
    ("/runs", "get"),
    ("/runs/{run_id}", "get"),
    # Deletion, human paths only (no model-callable delete tool): one saved design
    # (refused while a schedule replays it) and one stored run.
    ("/designs/{name}", "delete"),
    ("/runs/{run_id}", "delete"),
    # "New from template": the built-in designs shipped in examples/.
    ("/designs/templates", "get"),
    # Schedules view: the delivery-target picker and the cron jobs this plugin created.
    ("/channels", "get"),
    ("/schedules", "get"),
    ("/designs/{name}/schedule", "post"),
    ("/schedules/{job_id}/{action}", "post"),
}
SAVE_ROUTE = ("/designs/{name}", "post")
# The agent-node picker lists host profiles; the canvas falls back to a text field when the
# host registry is unreadable, so this route answers 200 with an empty list rather than 500.
PROFILES_ROUTE = ("/profiles", "get")
# The agent-node model picker reads the host catalog through the plugin, so the canvas can use a
# select instead of a free-text id. Answered 200 with ``available: false`` when unreadable.
MODELS_ROUTE = ("/models", "get")


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST.is_file(), f"missing dashboard manifest at {MANIFEST}"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _router_routes() -> set:
    """``{(path, method)}`` from the ``@router.<method>("...")`` decorators in plugin_api.py."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "router" or not decorator.args:
                continue
            path = decorator.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                routes.add((path.value, func.attr.lower()))
    return routes


# --------------------------------------------------------------------- manifest
def test_manifest_parses_and_declares_the_workflows_tab(manifest):
    assert manifest["name"] == "visual-workflow"
    assert manifest["label"] == "Workflows"
    assert manifest["icon"] == "GitBranch"
    tab = manifest["tab"]
    assert tab["path"] == "/workflows"
    assert tab["position"] == "end"
    assert manifest["entry"] == "dist/index.js"
    assert manifest["api"] == "plugin_api.py"


def test_manifest_required_keys_and_types(manifest):
    for key in ("name", "label", "icon", "version", "description"):
        assert isinstance(manifest[key], str) and manifest[key].strip(), f"{key} must be a string"
    assert isinstance(manifest["tab"], dict)


def test_declared_entry_and_api_files_exist(manifest):
    assert ENTRY.is_file(), f"missing plugin entry at {ENTRY}"
    api_path = DASHBOARD / manifest["api"]
    assert api_path.is_file(), f"missing plugin api at {api_path}"
    # The host refuses an api path that is absolute or escapes dashboard/ (_safe_plugin_api_relpath).
    assert not Path(manifest["api"]).is_absolute()
    api_path.resolve().relative_to(DASHBOARD.resolve())


def test_entry_sits_under_the_served_dashboard_root(manifest):
    # Assets are served from dashboard/ (web_routers/dashboard_ui.py serve_plugin_asset).
    (DASHBOARD / manifest["entry"]).resolve().relative_to(DASHBOARD.resolve())


# ----------------------------------------------------------------------- router
def test_router_declares_the_dashboard_routes():
    routes = _router_routes()
    missing = REQUIRED_ROUTES - routes
    assert not missing, f"plugin_api.py is missing routes: {sorted(missing)}"
    assert SAVE_ROUTE in routes
    assert PROFILES_ROUTE in routes
    assert MODELS_ROUTE in routes


def test_router_is_a_module_level_apirouter():
    """The host reads ``getattr(mod, "router")`` — a missing or nested router mounts nothing."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    assigns = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets)
    ]
    assert assigns, "plugin_api.py must assign a module-level `router`"
    value = assigns[0].value
    assert isinstance(value, ast.Call)
    assert getattr(value.func, "id", "") == "APIRouter"


def test_router_imports_exactly_as_the_host_does():
    """Import the file by path (module name mirrors the host) and read the real route table."""
    pytest.importorskip("fastapi")
    import importlib.util

    spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_visual-workflow", API)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)

    from fastapi import APIRouter

    assert isinstance(mod.router, APIRouter)
    served = {
        (route.path, method.lower())
        for route in mod.router.routes
        for method in (route.methods or set())
    }
    missing = (REQUIRED_ROUTES | {PROFILES_ROUTE}) - served
    assert not missing, f"router does not serve: {sorted(missing)}"


# ------------------------------------------------------------- live requests
def _client(tmp_path, monkeypatch):
    """Mount the plugin router the way the host does, against a throwaway HOME."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import importlib.util

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_visual-workflow", API)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/visual-workflow")
    return TestClient(app), mod


def test_templates_route_is_declared_before_the_design_name_route():
    """FastAPI matches in registration order: after ``/designs/{name}`` it is unreachable."""
    source = API.read_text(encoding="utf-8")
    templates = source.index('@router.get("/designs/templates")')
    single = source.index('@router.get("/designs/{name}")')
    assert templates < single


def test_templates_endpoint_serves_every_shipped_example(tmp_path, monkeypatch):
    """The picker's rows come from the files themselves, with the graph already inline."""
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/plugins/visual-workflow/designs/templates").json()
    rows = body["templates"]
    names = [r["name"] for r in rows]
    assert names == sorted(names)
    shipped = sorted(p.name[: -len(".designer.json")]
                     for p in (ROOT / "examples").glob("*.designer.json"))
    assert names == shipped
    assert {"daily-digest", "review-gate"} <= set(names)
    for row in rows:
        assert row["title"].strip() and row["description"].strip()
        assert row["nodes"] == len(row["graph"]["nodes"])
        # Named after the file, so "Save" writes a design the picker can list again.
        assert row["graph"]["name"] == row["name"]
        assert validate_designer_graph(row["graph"]) == [], row["name"]


def test_a_design_literally_named_templates_is_not_shadowed(tmp_path, monkeypatch):
    """Guard the ordering the hard way: a saved design called "templates" must not win."""
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client, name="templates")
    body = client.get("/api/plugins/visual-workflow/designs/templates").json()
    assert "templates" in body and "graph" not in body


def test_delete_design_roundtrip_and_unknown_is_404(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client, name="bye")
    body = client.delete("/api/plugins/visual-workflow/designs/bye").json()
    assert body == {"ok": True, "name": "bye"}
    assert client.get("/api/plugins/visual-workflow/designs").json()["designs"] == []
    assert client.delete("/api/plugins/visual-workflow/designs/bye").status_code == 404
    assert client.delete("/api/plugins/visual-workflow/designs/Bad Name!").status_code == 400


def test_delete_design_refused_while_a_schedule_replays_it(tmp_path, monkeypatch):
    client, mod = _client(tmp_path, monkeypatch)
    _save_gate_design(client, name="sched")
    monkeypatch.setattr(
        mod, "list_workflow_jobs",
        lambda: {"jobs": [{"job_id": "j1", "name": "workflow:sched", "design": "sched"}],
                 "available": True},
    )
    response = client.delete("/api/plugins/visual-workflow/designs/sched")
    assert response.status_code == 409
    assert "sched" in client.get("/api/plugins/visual-workflow/designs").json()["designs"]


def test_delete_run_roundtrip_and_unknown_is_404(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client)
    started = client.post("/api/plugins/visual-workflow/designs/gated/run").json()
    run_id = started["run_id"]
    body = client.delete(f"/api/plugins/visual-workflow/runs/{run_id}").json()
    assert body == {"ok": True, "run_id": run_id}
    assert client.delete(f"/api/plugins/visual-workflow/runs/{run_id}").status_code == 404
    assert client.delete("/api/plugins/visual-workflow/runs/nope!").status_code == 400


def test_profiles_endpoint_answers_even_without_a_host_registry(tmp_path, monkeypatch):
    """No host package here, so the honest answer is an empty list and available=false."""
    client, _ = _client(tmp_path, monkeypatch)
    response = client.get("/api/plugins/visual-workflow/profiles")
    assert response.status_code == 200
    body = response.json()
    assert body["profiles"] == [] and body["available"] is False


def test_profiles_endpoint_lists_the_hosts_profiles(tmp_path, monkeypatch):
    import sys
    import types

    client, _ = _client(tmp_path, monkeypatch)

    class Info:
        name = "writer"
        model = "claude"
        is_default = False
        bot_title = "Writer bot"
        display_name = ""
        description = "drafts"

    mod = types.ModuleType("hermes_cli.profiles")
    mod.list_profiles = lambda **kwargs: [Info()]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.profiles", mod)

    body = client.get("/api/plugins/visual-workflow/profiles").json()
    assert body["available"] is True
    # A step names one model, never a provider: the listing carries no ``provider`` key
    # (see ``visual_workflow_hermes/profiles.py`` and the README's model-picker note).
    assert body["profiles"] == [{
        "name": "writer", "label": "Writer bot", "model": "claude",
        "is_default": False, "description": "drafts",
    }]


def _save_gate_design(client, name="gated"):
    graph = {
        "name": name,
        "nodes": [
            {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "gate", "type": "approval", "question": "Ship it?",
             "options": ["ship", "hold"], "after": ["trigger1"]},
            {"id": "out", "type": "output", "after": ["gate"]},
        ],
    }
    saved = client.post(f"/api/plugins/visual-workflow/designs/{name}", json={"graph": graph})
    assert saved.json()["ok"] is True


def test_runs_list_shows_a_gate_started_outside_this_tab(tmp_path, monkeypatch):
    """The Runs view must see runs on disk and be able to approve them from the list."""
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client)

    started = client.post("/api/plugins/visual-workflow/designs/gated/run").json()
    assert started["status"] == "awaiting_approval"

    listed = client.get("/api/plugins/visual-workflow/runs").json()["runs"]
    (row,) = [r for r in listed if r["run_id"] == started["run_id"]]
    assert row["status"] == "awaiting_approval"
    assert row["node_id"] == "gate"
    assert row["question"] == "Ship it?"
    assert row["options"] == ["ship", "hold"]
    assert row["updated"] > 0

    # Answering straight from the list row is the same call the inline buttons make.
    done = client.post(
        f"/api/plugins/visual-workflow/runs/{started['run_id']}/respond",
        json={"run_id": started["run_id"], "node_id": "gate", "answer": "ship"},
    ).json()
    assert done["status"] == "done"

    # ...and the finished status is what the list reads back, not a stale "running".
    listed = client.get("/api/plugins/visual-workflow/runs").json()["runs"]
    (row,) = [r for r in listed if r["run_id"] == started["run_id"]]
    assert row["status"] == "done"
    detail = client.get(f"/api/plugins/visual-workflow/runs/{started['run_id']}").json()
    assert detail["status"] == "done" and detail["outputs"]["out"] == {"gate": "ship"}


def test_runs_list_sweeps_and_persists_an_expired_gate(tmp_path, monkeypatch):
    """Nothing runs in the background, so reading a run must honour its deadline."""
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client)
    started = client.post("/api/plugins/visual-workflow/designs/gated/run").json()

    path = tmp_path / "workflow-runs" / f"{started['run_id']}.json"
    state = json.loads(path.read_text())
    state["pending"]["timeout_minutes"] = 1
    state["pending"]["waiting_since"] = 1_600_000_000  # long past
    path.write_text(json.dumps(state))

    listed = client.get("/api/plugins/visual-workflow/runs").json()["runs"]
    (row,) = [r for r in listed if r["run_id"] == started["run_id"]]
    assert row["status"] == "failed"
    assert row["node_id"] is None and row["options"] == []
    assert "timed out" in row["error"]["msg"]

    # The verdict is on disk now: a late answer cannot silently resume the run.
    assert json.loads(path.read_text())["status"] == "failed"
    late = client.post(
        f"/api/plugins/visual-workflow/runs/{started['run_id']}/respond",
        json={"run_id": started["run_id"], "node_id": "gate", "answer": "ship"},
    )
    assert late.status_code == 409


def test_runs_list_row_carries_a_timed_gates_deadline(tmp_path, monkeypatch):
    """The list is where a waiting gate is actually seen, so it must carry the deadline."""
    client, _ = _client(tmp_path, monkeypatch)
    graph = {
        "name": "timed",
        "nodes": [
            {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "gate", "type": "approval", "question": "Ship it?",
             "options": ["ship"], "timeout_minutes": 45, "after": ["trigger1"]},
        ],
    }
    assert client.post("/api/plugins/visual-workflow/designs/timed",
                       json={"graph": graph}).json()["ok"] is True
    started = client.post("/api/plugins/visual-workflow/designs/timed/run").json()
    assert started["status"] == "awaiting_approval"

    (row,) = [r for r in client.get("/api/plugins/visual-workflow/runs").json()["runs"]
              if r["run_id"] == started["run_id"]]
    assert row["timeout_minutes"] == 45
    assert row["waiting_since"] > 0


def test_runs_list_respects_a_limit_and_unknown_run_is_404(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client)
    for _ in range(2):
        client.post("/api/plugins/visual-workflow/designs/gated/run")
    assert len(client.get("/api/plugins/visual-workflow/runs?limit=1").json()["runs"]) == 1
    assert client.get("/api/plugins/visual-workflow/runs/ffffffffffff").status_code == 404


def test_run_through_the_router_returns_the_delivery_record(tmp_path, monkeypatch):
    """A delivering output is recorded on the run; a failed send does not fail the run."""
    from visual_workflow_hermes import delivery

    client, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        delivery, "send_text",
        lambda target, text: {"target": target, "ok": False, "detail": "no token"},
    )
    graph = {
        "name": "delivers",
        "nodes": [
            {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "note", "type": "agent", "prompt": "say hi", "after": ["trigger1"]},
        ],
    }
    assert client.post("/api/plugins/visual-workflow/designs/delivers",
                       json={"graph": graph}).json()["ok"] is True

    first = client.post("/api/plugins/visual-workflow/designs/delivers/run").json()
    assert first["status"] == "awaiting_agent"

    graph["nodes"].append({
        "id": "out", "type": "output", "after": ["note"],
        "deliver": "notification", "target": "telegram",
    })
    assert client.post("/api/plugins/visual-workflow/designs/delivers",
                       json={"graph": graph}).json()["ok"] is True

    run = client.post("/api/plugins/visual-workflow/designs/delivers/run").json()
    run_id, node_id = run["run_id"], run["pending"]["node_id"]
    done = client.post(
        f"/api/plugins/visual-workflow/runs/{run_id}/respond",
        json={"run_id": run_id, "node_id": node_id, "answer": "hi"},
    ).json()
    assert done["status"] == "done"
    (record,) = done["deliveries"]
    assert record["node_id"] == "out" and record["ok"] is False
    assert record["target"] == "telegram"


def test_run_route_executes_agent_steps_through_a_host_llm(tmp_path, monkeypatch):
    """A canvas Run advances through an agent node instead of parking at ``awaiting_agent``.

    The route reaches the host ``PluginLlm`` facade through ``llm_spawn``; this test injects a
    fake facade via the same import the route reads, exactly as the host mounts it.
    """
    from visual_workflow_hermes.spawn import _make_spawn

    client, mod = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "llm_spawn",
                        lambda: _make_spawn(_FakeCompleteLlm(text="haiku, two lines.")))
    graph = {
        "name": "spawned",
        "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "write", "type": "agent", "prompt": "Write a two-line haiku.",
             "after": ["t"]},
            {"id": "out", "type": "output", "after": ["write"]},
        ],
    }
    saved = client.post("/api/plugins/visual-workflow/designs/spawned",
                        json={"graph": graph}).json()
    assert saved["ok"] is True
    run = client.post("/api/plugins/visual-workflow/designs/spawned/run").json()
    assert run["status"] == "done", run
    assert run["outputs"]["write"] == "haiku, two lines."
    assert run["outputs"]["out"] == {"write": "haiku, two lines."}
    assert run["pending"] is None


def test_respond_route_runs_the_remaining_agent_step_with_a_host_llm(tmp_path, monkeypatch):
    """A run parked on an agent node (no LLM at the time) can be resumed into a working spawn.

    Covering the respond route matters because it shares the spawn decision the run route made:
    without it a resumed run would park again at the very next agent node.
    """
    from visual_workflow_hermes.spawn import _make_spawn

    client, mod = _client(tmp_path, monkeypatch)
    graph = {
        "name": "later",
        "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "one", "type": "agent", "prompt": "first", "after": ["t"]},
            {"id": "two", "type": "agent", "prompt": "second", "after": ["one"]},
            {"id": "out", "type": "output", "after": ["two"]},
        ],
    }
    saved = client.post("/api/plugins/visual-workflow/designs/later",
                        json={"graph": graph}).json()
    assert saved["ok"] is True

    # First run: no LLM backend (the old status quo) parks at the first agent node.
    monkeypatch.setattr(mod, "llm_spawn", lambda: None)
    parked = client.post("/api/plugins/visual-workflow/designs/later/run").json()
    assert parked["status"] == "awaiting_agent"

    # Resume: the backend comes back, and the run finishes rather than pausing again.
    monkeypatch.setattr(mod, "llm_spawn",
                        lambda: _make_spawn(_FakeCompleteLlm(text="done by the llm")))
    done = client.post(
        f"/api/plugins/visual-workflow/runs/{parked['run_id']}/respond",
        json={"run_id": parked["run_id"], "node_id": "one", "answer": "first result"},
    ).json()
    assert done["status"] == "done", done
    assert done["outputs"]["two"] == "done by the llm"


def test_respond_route_can_generate_the_parked_agent_step_with_the_host_llm(tmp_path, monkeypatch):
    """``agent_generate`` on a parked agent step lets the host agent produce the output now.

    This is the hand-paste escape hatch for runs parked by older builds (before the LLM
    facade existed): the same private facade a Run uses fills the parked step in, and the
    run continues through the remaining agent steps.
    """
    from visual_workflow_hermes.spawn import _make_spawn

    client, mod = _client(tmp_path, monkeypatch)
    graph = {
        "name": "later-generate",
        "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "one", "type": "agent", "prompt": "first", "after": ["t"]},
            {"id": "two", "type": "agent", "prompt": "second", "after": ["one"]},
        ],
    }
    assert client.post("/api/plugins/visual-workflow/designs/later-generate",
                       json={"graph": graph}).json()["ok"] is True

    # Park the run the old way: no agent backend at run time (like an older parked run).
    monkeypatch.setattr(mod, "llm_spawn", lambda: None)
    parked = client.post("/api/plugins/visual-workflow/designs/later-generate/run").json()
    assert parked["status"] == "awaiting_agent"

    # Resume via generation instead of a pasted answer.
    monkeypatch.setattr(mod, "llm_spawn",
                        lambda: _make_spawn(_FakeCompleteLlm(text="generated now")))
    done = client.post(
        f"/api/plugins/visual-workflow/runs/{parked['run_id']}/respond",
        json={"run_id": parked["run_id"], "node_id": "one", "agent_generate": True},
    ).json()
    assert done["status"] == "done", done
    assert done["outputs"]["one"] == "generated now"
    # The remaining agent step ran through the same backend too.
    assert done["outputs"]["two"] == "generated now"
    assert done["pending"] is None


def test_retry_route_reruns_a_failed_run_from_its_failed_step(tmp_path, monkeypatch):
    """A failed run is retried from the step that failed, reusing the outputs that survived.

    The route shares the run route's spawn decision, so the retry picks up whatever backend
    exists now — the run route's fail-fast path built the failed state to be retried from.
    """
    from visual_workflow_hermes.spawn import _make_spawn

    client, mod = _client(tmp_path, monkeypatch)
    graph = {
        "name": "flaky",
        "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "one", "type": "agent", "prompt": "first", "after": ["t"]},
            {"id": "two", "type": "agent", "prompt": "second", "after": ["one"]},
            {"id": "out", "type": "output", "after": ["two"]},
        ],
    }
    assert client.post("/api/plugins/visual-workflow/designs/flaky",
                       json={"graph": graph}).json()["ok"] is True

    def bad_second(step, outputs, run):
        return {"output": "fine"} if step["id"] == "one" else {"error": "boom"}

    monkeypatch.setattr(mod, "llm_spawn", lambda: bad_second)
    failed = client.post("/api/plugins/visual-workflow/designs/flaky/run").json()
    assert failed["status"] == "failed"
    assert failed["error"]["node_id"] == "two"
    assert failed["outputs"]["one"] == "fine"

    monkeypatch.setattr(mod, "llm_spawn",
                        lambda: _make_spawn(_FakeCompleteLlm(text="recovered")))
    retried = client.post(
        f"/api/plugins/visual-workflow/runs/{failed['run_id']}/retry",
        headers={"Content-Type": "application/json"},
        content="{}",
    ).json()
    assert retried["status"] == "done", retried
    assert retried["outputs"]["two"] == "recovered"
    assert retried["outputs"]["one"] == "fine", "earlier output must survive a retry"


def test_retry_route_refuses_a_run_that_is_not_failed_and_404s_the_unknown(tmp_path, monkeypatch):
    client, mod = _client(tmp_path, monkeypatch)
    _save_gate_design(client)
    monkeypatch.setattr(mod, "llm_spawn", lambda: None)
    started = client.post("/api/plugins/visual-workflow/designs/gated/run").json()
    assert started["status"] == "awaiting_approval"

    refused = client.post(
        f"/api/plugins/visual-workflow/runs/{started['run_id']}/retry",
        headers={"Content-Type": "application/json"},
        content="{}",
    )
    assert refused.status_code == 409
    assert "not failed" in refused.json()["detail"]

    assert client.post(
        "/api/plugins/visual-workflow/runs/ffffffffffff/retry",
        headers={"Content-Type": "application/json"},
        content="{}",
    ).status_code == 404


def test_retry_route_reclaims_a_run_crashed_mid_retry_once_it_is_cold(tmp_path, monkeypatch):
    """A retry reset stamped before any work survives a crash as an honest ``running`` state
    with no verdict. While the stamp is fresh the retry may still be in flight in some other
    process, so the request is refused; once it is cold the next retry takes the run over and
    finishes it — a crash mid-retry never wedges a run behind every shipped path."""
    import time as time_mod

    from visual_workflow_hermes.runner import RETRY_RECLAIM_SECONDS
    from visual_workflow_hermes.spawn import _make_spawn

    client, mod = _client(tmp_path, monkeypatch)
    graph = {
        "name": "colder",
        "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "one", "type": "agent", "prompt": "only", "after": ["t"]},
            {"id": "out", "type": "output", "after": ["one"]},
        ],
    }
    assert client.post("/api/plugins/visual-workflow/designs/colder",
                       json={"graph": graph}).json()["ok"] is True
    monkeypatch.setattr(mod, "llm_spawn", lambda: lambda *a: {"error": "boom"})
    failed = client.post("/api/plugins/visual-workflow/designs/colder/run").json()
    assert failed["status"] == "failed"
    run_id = failed["run_id"]

    def post_retry():
        return client.post(
            f"/api/plugins/visual-workflow/runs/{run_id}/retry",
            headers={"Content-Type": "application/json"}, content="{}")

    # Simulate the crash mid-retry: the reset persisted (stamped but fresh), then died.
    runs = mod._runs()
    state = runs.load(run_id)
    state.update({"status": "running", "error": None, "pending": None,
                  "retrying": time_mod.time()})
    runs.save(state)
    refused = post_retry()
    assert refused.status_code == 409, refused.text

    # A different kind of ``running`` is equally untouchable: no stamp at all, i.e. a run
    # that may still genuinely be stepping through its plan somewhere.
    plain = runs.load(run_id)
    plain.pop("retrying")
    runs.save(plain)
    assert post_retry().status_code == 409

    # Cold stamp and a working backend now: the retry takes over and finishes the run.
    monkeypatch.setattr(mod, "llm_spawn",
                        lambda: _make_spawn(_FakeCompleteLlm(text="reclaimed")))
    cold = runs.load(run_id)
    cold.update({"retrying": time_mod.time() - RETRY_RECLAIM_SECONDS - 5})
    runs.save(cold)
    done = post_retry().json()
    assert done["status"] == "done", done
    assert done["outputs"]["one"] == "reclaimed"


def test_agent_generate_without_a_backend_leaves_the_run_resumable(tmp_path, monkeypatch):
    """A 503 on ``agent_generate`` never half-resumes: the run stays parked and a pasted
    answer still works afterwards."""
    from visual_workflow_hermes.spawn import _make_spawn

    client, mod = _client(tmp_path, monkeypatch)
    graph = {
        "name": "still-parked",
        "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "one", "type": "agent", "prompt": "first", "after": ["t"]},
        ],
    }
    assert client.post("/api/plugins/visual-workflow/designs/still-parked",
                       json={"graph": graph}).json()["ok"] is True
    monkeypatch.setattr(mod, "llm_spawn", lambda: None)
    parked = client.post("/api/plugins/visual-workflow/designs/still-parked/run").json()
    assert parked["status"] == "awaiting_agent"

    refused = client.post(
        f"/api/plugins/visual-workflow/runs/{parked['run_id']}/respond",
        json={"run_id": parked["run_id"], "node_id": "one", "agent_generate": True},
    )
    assert refused.status_code == 503
    assert "paste the step's result" in refused.json()["detail"]

    # ...and nothing was consumed: the run still waits on step one.
    detail = client.get(f"/api/plugins/visual-workflow/runs/{parked['run_id']}").json()
    assert detail["status"] == "awaiting_agent" and detail["pending"]["node_id"] == "one"
    monkeypatch.setattr(mod, "llm_spawn",
                        lambda: _make_spawn(_FakeCompleteLlm(text="backend text")))
    done = client.post(
        f"/api/plugins/visual-workflow/runs/{parked['run_id']}/respond",
        json={"run_id": parked["run_id"], "node_id": "one", "answer": "pasted instead"},
    ).json()
    assert done["status"] == "done" and done["outputs"]["one"] == "pasted instead"


def test_agent_generate_on_an_approval_gate_is_refused_not_consumed(tmp_path, monkeypatch):
    """Generation is for agent steps only: a gate is refused and the gate stays open."""
    client, _ = _client(tmp_path, monkeypatch)
    _save_gate_design(client)
    started = client.post("/api/plugins/visual-workflow/designs/gated/run").json()
    assert started["status"] == "awaiting_approval"

    refused = client.post(
        f"/api/plugins/visual-workflow/runs/{started['run_id']}/respond",
        json={"run_id": started["run_id"], "node_id": "gate", "agent_generate": True},
    )
    assert refused.status_code == 400
    detail = client.get(f"/api/plugins/visual-workflow/runs/{started['run_id']}").json()
    assert detail["status"] == "awaiting_approval" and detail["pending"]["node_id"] == "gate"


class _FakeCompleteLlm:
    """Minimal ``PluginLlm`` stand-in for route tests: records to nothing, answers with text."""

    def __init__(self, *, text: str):
        self.text = text

    def complete(self, **kwargs):
        return types.SimpleNamespace(text=self.text)

    def complete_structured(self, **kwargs):
        return types.SimpleNamespace(text=self.text, parsed=None)


# ------------------------------------------------------------------------ entry
@pytest.fixture(scope="module")
def entry() -> str:
    assert ENTRY.is_file(), f"missing plugin entry at {ENTRY}"
    return ENTRY.read_text(encoding="utf-8")


def test_entry_registers_the_tab_by_manifest_name(entry):
    assert 'PLUGINS.register("visual-workflow", WorkflowsTab)' in entry
    assert "window.__HERMES_PLUGINS__" in entry


def test_entry_guards_on_the_plugin_sdk(entry):
    assert "window.__HERMES_PLUGIN_SDK__" in entry
    assert "if (!SDK)" in entry, "the bundle must bail out when the SDK is absent"


def test_entry_talks_to_the_backend_only_through_the_sdk(entry):
    assert '/api/plugins/visual-workflow' in entry
    assert "SDK.fetchJSON" in entry or "SDK.fetchJSON;" in entry or "fetchJSON" in entry
    # Hand-rolled auth or a bare fetch would bypass the host's token/cookie handling.
    assert "window.__HERMES_SESSION_TOKEN__" not in entry
    assert "fetch(" not in entry.replace("fetchJSON", "")


def test_schedule_inspector_says_whether_hermes_has_the_job(entry):
    """The canvas edits a cron string; only the host knows whether a job exists."""
    assert "function jobStatus()" in entry
    assert '"Hermes cron: "' in entry
    assert "not scheduled yet" in entry
    assert 'TIPS["schedule.status"]' in entry


def test_entry_shows_a_gate_deadline(entry):
    """A timed gate must say how long the reviewer has, on the card and in the list."""
    assert 'field("timeout (minutes, optional)"' in entry
    assert 'field("if it times out", policy' in entry
    assert "function waitText(pending)" in entry
    assert "expires in " in entry
    assert "-minute deadline" in entry


def test_entry_has_a_runs_view_that_answers_gates_inline(entry):
    """Runs started elsewhere must be listed and answerable from the canvas itself."""
    assert "function RunsPanel" in entry
    assert 'fetchJSON(API + "/runs?limit=20")' in entry, "the Runs view must read GET /runs"
    assert '/respond"' in entry or "/respond'" in entry, "inline approve must post to respond"
    assert 'view === "runs"' in entry


def test_entry_is_a_no_build_iife(entry):
    """A plain IIFE the host can inject with a <script> tag — no bundler, no imports."""
    assert entry.lstrip().startswith("/**")
    assert "(function () {" in entry
    for banned in ("</script", "console.log(", "require(", "import ", "export "):
        assert banned not in entry, f"entry must stay dependency-free: found {banned!r}"


def test_entry_embeds_a_valid_blank_graph(entry):
    """The canvas starts from designer JSON that passes the Python validator."""
    from visual_workflow_hermes.schema import validate_designer_graph

    match = re.search(r"var BLANK_JSON =\s*\n?\s*'(.+?)';", entry)
    assert match, "entry must embed its base graph as BLANK_JSON"
    blank = json.loads(match.group(1))
    assert [n["id"] for n in blank["nodes"]] == ["trigger1"]
    assert validate_designer_graph(blank) == []


# ------------------------------------------------------------ canvas legibility
# Two independent bugs made the canvas compute black on the host's LENS_0 theme:
#  1. SVG presentation attributes do not resolve var() — only declarations do. A paint set
#     with setAttribute("fill", "var(--card)") is invalid and falls back to black.
#  2. The host theme has no global --card/--border/--muted-foreground/--accent, and its
#     --foreground is transparent (alpha 0), so even resolving them would paint nothing.
UNSAFE_TOKENS = ("foreground", "border", "card", "accent", "muted-foreground", "destructive")

SCOPED_TOKENS = (
    "--vw-ink:var(--midground,#ffe6cb)",
    "--vw-dim:color-mix(in srgb,var(--midground,#ffe6cb) 72%,transparent)",
    "--vw-surface:color-mix(in srgb,var(--midground,#ffe6cb) 5%,var(--background,#041c1c))",
    "--vw-line:color-mix(in srgb,var(--midground,#ffe6cb) 16%,transparent)",
    "--vw-node:color-mix(in srgb,var(--midground,#ffe6cb) 7%,var(--background,#041c1c))",
    "--vw-accent:var(--series-output-token,#34d399)",
    "--vw-danger:#fb2c36",
)


def _function_body(source: str, name: str) -> str:
    """The body of ``function <name>(...) { ... }`` — enough for a source assertion."""
    match = re.search(r"function " + re.escape(name) + r"\([^)]*\) \{(.*?)\n  \}", source, re.S)
    assert match, f"entry must define function {name}()"
    return match.group(1)


def test_entry_svg_helper_routes_var_paints_through_inline_style(entry):
    """A var() paint must become a declaration, never a presentation attribute."""
    body = _function_body(entry, "svgEl")
    paint = re.search(r"PAINT\w*\s*=\s*\{([^}]*)\}", entry.split("function svgEl")[0])
    assert paint, "svgEl must name the attributes it treats as paint"
    assert "fill" in paint.group(1) and "stroke" in paint.group(1)
    assert 'indexOf("var(")' in body, "the var() case must be detected explicitly"
    assert "style.setProperty" in body, "a var() paint must be set as an inline style declaration"
    assert body.index('indexOf("var(")') < body.index("style.setProperty")
    assert body.index("style.setProperty") < body.index("setAttribute"), (
        "setAttribute must be the else-branch for plain values only"
    )


def test_entry_canvas_has_ports_and_cuttable_edges(entry):
    """Click-two-nodes-then-Connect was unusable; the canvas drags port to port."""
    assert "function outPort(n)" in entry and "function inPort(n)" in entry
    assert "function edgePath(parent, child)" in entry
    assert entry.count('"data-port"') >= 2
    assert 'n.type !== "trigger"' in entry, "a trigger has no input port"
    assert "\"vw-edge-hit\"" in entry
    assert "function beginLink(" in entry and "function finishLink(" in entry
    assert "function cutEdge(" in entry and "selectedEdge" in entry


def test_entry_lists_profiles_for_the_agent_picker(entry):
    assert 'API + "/profiles"' in entry
    assert "function profileSelect(" in entry
    assert "profile / bot" in entry
    assert "setProfiles" in entry


def test_entry_offers_one_send_to_choice_and_reports_delivery(entry):
    assert "function applySendTo(node, value)" in entry
    assert 'field("send to"' in entry
    assert '"notification"' in entry and '"channel"' in entry
    assert 'field("deliver"' not in entry, "a second dropdown can rebuild the invalid pair"
    assert "function deliveryLine(" in entry
    assert "result.deliveries" in entry


def test_entry_uses_only_scoped_readable_tokens(entry):
    for token in SCOPED_TOKENS:
        assert token in entry, f"entry must define {token} on .vw-shell"
    assert ".vw-shell{" in entry, "the scoped tokens belong on .vw-shell, not :root"
    unsafe = re.findall(r"var\(\s*--(" + "|".join(UNSAFE_TOKENS) + r")\b", entry)
    assert not unsafe, f"entry references host tokens that are absent/transparent here: {unsafe}"


# ------------------------------------------------------------ canvas layout
# At 1280px with both Hermes sidebars open the tab is ~760px wide. A 130px node palette plus a
# 250px inspector left the canvas unusable, so node creation moved to a top bar and the
# inspector starts collapsed. Asserted structurally: the toolbar must precede the <svg>, the
# left rail must be gone, and the collapsed-by-default class must be on the app root.
def test_canvas_puts_node_creation_in_a_top_bar(entry):
    assert 'class="vw-kit"' in entry, "node creation belongs in the top bar"
    assert entry.index('class="vw-kit"') < entry.index('data-vw="canvas"'), (
        "the node bar must come before the canvas, not beside it"
    )
    assert "vw-palette" not in entry, "the left palette rail must be gone"
    kit = entry[entry.index('class="vw-kit"'):entry.index('class="vw-bar"')]
    assert kit.count('data-kind="') == 6, "five step kinds plus the sticky note"
    assert kit.count('class="ico"') == 6, "each button needs an icon next to its label"


def test_the_template_picker_sits_in_the_same_top_row(entry):
    """"New" alone leaves a first-time user staring at an empty canvas."""
    assert '"start from a template"' in entry
    assert "/designs/templates" in entry
    assert "function useTemplate(name)" in entry
    # Chosen template is a draft on the canvas, never a saved design of someone else's.
    body = entry.split("function useTemplate(name)", 1)[1][:400]
    assert 'setActive("")' in body


def test_canvas_has_no_left_rail_and_the_shell_is_one_column(entry):
    assert ".vw-rail{" not in entry and 'className: "vw-rail"' not in entry
    assert "flex-direction:column" in entry.split(".vw-shell{", 1)[1].split("}", 1)[0]
    assert '<select class="vw-grow" data-vw="designs"' in entry or '"vw-grow",' in entry, (
        "saved workflows belong in the top row, not a 190px rail"
    )


def test_inspector_starts_collapsed_and_can_be_closed(entry):
    assert 'class="vw-app vw-insp-collapsed"' in entry, "collapsed is the default state"
    assert 'data-vw="insp-toggle"' in entry and 'aria-expanded="false"' in entry
    assert ".vw-app.vw-insp-collapsed .vw-inspector{width:30px" in entry
    assert ".vw-app.vw-insp-collapsed .vw-insp-body{display:none}" in entry
    assert "function setInspector(open)" in entry
    assert "setInspector(true)" in entry, "selecting a node must expand the panel"


def test_canvas_fits_its_width_and_recomputes_on_resize(entry):
    assert "function fit()" in entry
    assert 'setAttribute("viewBox"' in entry
    assert "preserveAspectRatio" in entry
    assert "ResizeObserver" in entry, "opening a sidebar must re-fit, not clip"
    assert "fitLocked" in entry, "a drag must not rescale the sheet under the pointer"


def test_agent_node_offers_a_retry_budget(entry):
    """A flaky model call should not fail the whole run; the inspector owns the budget."""
    assert 'field("retries (optional)"' in entry
    assert 'TIPS["agent.retries"]' in entry
    assert "current.retries = Math.min(3, count)" in entry, "the schema caps retries at 3"


# ------------------------------------------------------------ sticky notes
def test_dashboard_offers_sticky_notes_as_annotations(entry):
    assert 'data-kind="note"' in entry
    assert 'var NOTE = "note"' in entry
    assert 'var KINDS = ["trigger", "agent", "condition", "approval", "output"]' in entry
    assert "KINDS.concat([NOTE])" in entry
    assert "NOTE_COLORS" in entry


def test_a_note_has_no_ports_and_is_edited_as_free_text(entry):
    assert "if (n.type !== NOTE) {" in entry
    assert "a note cannot hold a workflow step" in entry
    assert 'field("note text"' in entry
    assert 'TIPS["note.color"]' in entry
    assert 'n.type === "note" ? n.text || ""' in entry


def test_nodes_are_compact_with_a_two_line_preview(entry):
    assert "var NODE_W = 150;" in entry and "var NODE_H = 58;" in entry
    assert "function previewLines(n)" in entry
    assert "previewLines(n).forEach" in entry
    assert "lines.length === 2" in entry
    assert "preview(n)" not in entry, "the old one-line preview is gone"
