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
    missing = REQUIRED_ROUTES - served
    assert not missing, f"router does not serve: {sorted(missing)}"


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
