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
from pathlib import Path

import pytest

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
}
SAVE_ROUTE = ("/designs/{name}", "post")
# The agent-node picker lists host profiles; the canvas falls back to a text field when the
# host registry is unreadable, so this route answers 200 with an empty list rather than 500.
PROFILES_ROUTE = ("/profiles", "get")


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
        provider = "anthropic"
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
    assert body["profiles"] == [{
        "name": "writer", "label": "Writer bot", "model": "claude",
        "provider": "anthropic", "is_default": False, "description": "drafts",
    }]


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


def test_entry_offers_and_reports_output_delivery(entry):
    assert 'field("deliver"' in entry
    assert '"notification"' in entry and '"channel"' in entry
    assert 'field("target"' in entry
    assert "function deliveryLine(" in entry
    assert "result.deliveries" in entry


def test_entry_uses_only_scoped_readable_tokens(entry):
    for token in SCOPED_TOKENS:
        assert token in entry, f"entry must define {token} on .vw-shell"
    assert ".vw-shell{" in entry, "the scoped tokens belong on .vw-shell, not :root"
    unsafe = re.findall(r"var\(\s*--(" + "|".join(UNSAFE_TOKENS) + r")\b", entry)
    assert not unsafe, f"entry references host tokens that are absent/transparent here: {unsafe}"
