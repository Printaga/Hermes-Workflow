"""Desktop-plugin contract tests.

Hermes Desktop loads a package's ``desktop/plugin.js`` through the runtime loader
(``apps/desktop/src/contrib/runtime-loader.ts``): plain ESM, only
``@hermes/plugin-sdk`` / ``react*`` specifiers are rewritten to live shims, the
default export is validated as a ``HermesPlugin`` and ``register(ctx)`` wires
contributions. These tests pin that contract without needing the app.

The page lives in the ``routes`` registry area (``data.path`` + ``title`` +
``render``); the sidebar row is a ``sidebar.nav`` data contribution
(``{codicon, label, path}``). Backend calls go through ``ctx.rest``, which the
host scopes to ``/api/plugins/visual-workflow`` — i.e. this plugin's existing
``dashboard/plugin_api.py`` router.

Structural assertions always run. When Node is available, the plugin is also
imported and registered for real against a ``jsx-runtime`` stub, which proves the
contribution shapes rather than pattern-matching them.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
PLUGIN = DESKTOP / "plugin.js"

ALLOWED_IMPORTS = {"@hermes/plugin-sdk", "react/jsx-runtime"}

_IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])([^'"]+)\1""", re.S
)


@pytest.fixture(scope="module")
def source() -> str:
    assert PLUGIN.is_file(), f"missing desktop plugin at {PLUGIN}"
    return PLUGIN.read_text(encoding="utf-8")


def _import_specifiers(source: str) -> list[str]:
    return [match.group(2) for match in _IMPORT_RE.finditer(source)]


# ------------------------------------------------------------------- packaging
def test_plugin_ships_as_plain_runtime_esm(source):
    """A package's desktop half is raw text, not a bundle: ESM + a default export."""
    assert PLUGIN.resolve().relative_to(DESKTOP.resolve()) == Path("plugin.js")
    assert "export default" in source
    for banned in ("</script", "require(", "module.exports"):
        assert banned not in source, f"runtime plugin must stay plain ESM: found {banned!r}"


def test_imports_are_limited_to_the_loader_allowlist(source):
    specifiers = _import_specifiers(source)
    assert specifiers, "plugin must import its jsx runtime"
    unexpected = [spec for spec in specifiers if spec not in ALLOWED_IMPORTS]
    assert not unexpected, f"runtime loader refuses these specifiers: {unexpected}"
    assert not any(spec.startswith(".") for spec in specifiers), (
        "a relative import cannot resolve against the blob: base"
    )


def test_declares_the_plugin_identity(source):
    assert re.search(r"\bid:\s*['\"]visual-workflow['\"]", source)
    assert re.search(r"\bname:\s*['\"]Workflows['\"]", source)
    assert re.search(r"\bdescription:\s*['\"]", source)
    assert re.search(r"\bregister\s*\(\s*ctx\s*\)", source)


def test_contributes_to_the_two_known_areas(source):
    assert re.search(r"area:\s*['\"]routes['\"]", source)
    assert re.search(r"area:\s*['\"]sidebar\.nav['\"]", source)
    assert "path: '/workflows'" in source or 'path: "/workflows"' in source


def test_contributes_without_feature_detection(source):
    """routes, sidebar.nav and rest exist in this host — optional-call syntax would hide rot."""
    assert "ctx.register?." not in source
    assert "ctx.rest?." not in source
    assert "ctx.register(" in source


# --------------------------------------------------------------------- backend
def test_talks_to_its_own_api_only_through_ctx_rest(source):
    assert "ctx.rest(" in source
    assert "/designs" in source
    # No hand-rolled transport or auth: the host scopes the namespace and token.
    assert "fetch(" not in source
    assert "__HERMES_SESSION_TOKEN__" not in source
    assert "Authorization" not in source
    assert "XMLHttpRequest" not in source


def test_canvas_keeps_the_var_paint_fix(source):
    """The desktop page reuses the canvas core; it must not re-learn the black-canvas bug."""
    assert "createElementNS" in source
    assert "--vw-ink" in source and "--vw-node" in source
    assert "PAINT_ATTRS" in source
    assert "style.setProperty" in source


# ------------------------------------------------------------------- features
def test_nodes_have_ports_and_edges_are_draggable(source):
    """The same canvas core as the dashboard tab: port-to-port connect, cut by click."""
    assert "function outPort(n)" in source and "function inPort(n)" in source
    assert "function edgePath(parent, child)" in source
    assert source.count('"data-port"') >= 2
    assert 'n.type !== "trigger"' in source, "a trigger has no input port"
    assert '"vw-edge-hit"' in source
    assert "function beginLink(" in source and "function finishLink(" in source
    assert "function cutEdge(" in source and "selectedEdge" in source


def test_agent_picker_reads_the_plugin_profiles_route(source):
    assert '"/profiles"' in source, "the picker lists profiles through ctx.rest"
    assert "function refreshProfiles(" in source
    assert "function profileSelect(" in source
    assert "profile / bot" in source


def test_schedule_inspector_says_whether_hermes_has_the_job(source):
    assert "const jobStatus = () =>" in source
    assert "Hermes cron: " in source
    assert "not scheduled yet" in source
    assert 'TIPS["schedule.status"]' in source


def test_approval_gate_takes_a_deadline(source):
    """A gate that waits forever is the classic HITL failure; the inspector must offer one."""
    assert 'field("timeout (minutes, optional)"' in source
    assert 'field("if it times out", policy' in source
    assert '"escalate \\u2014 flag it for someone else"' in source
    assert "function waitText(pending)" in source, "the run box must show the remaining wait"
    assert "expires in " in source and "-minute deadline" in source


def test_runs_view_lists_every_run_and_answers_gates(source):
    """A run started in chat or by a cron job must be visible and answerable here too."""
    assert 'data-vw="view-runs"' in source
    assert "function renderRuns(" in source and "function runRow(" in source
    assert '"/runs?limit=20"' in source, "the list must read the runs route"
    assert '"/runs/"' in source and '"/respond"' in source
    assert "function answerRun(" in source


def test_output_delivery_is_offered_as_one_send_to_choice(source):
    assert "function applySendTo(node, value)" in source
    assert 'field("send to"' in source
    assert '"notification"' in source and '"channel"' in source
    assert 'field("deliver"' not in source, "a second dropdown can rebuild the invalid pair"
    assert "function deliveryLine(" in source, "the run box must show what was delivered"
    assert "result.deliveries" in source


# -------------------------------------------------- live registration (Node)
@pytest.fixture(scope="module")
def registration(tmp_path_factory, source):
    """Import the plugin with a jsx-runtime stub and run register() against a mock ctx."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; structural tests still cover the contract")

    work = tmp_path_factory.mktemp("desktop-plugin")
    (work / "plugin.mjs").write_text(source, encoding="utf-8")

    react = work / "node_modules" / "react"
    react.mkdir(parents=True)
    (react / "package.json").write_text(
        json.dumps(
            {
                "name": "react",
                "type": "module",
                "exports": {"./jsx-runtime": "./jsx-runtime.mjs"},
            }
        ),
        encoding="utf-8",
    )
    (react / "jsx-runtime.mjs").write_text(
        "export const jsx = (type, props) => ({ type, props });\n"
        "export const jsxs = jsx;\n"
        "export const Fragment = Symbol.for('react.fragment');\n",
        encoding="utf-8",
    )

    driver = work / "driver.mjs"
    driver.write_text(
        "import plugin from './plugin.mjs'\n"
        "const registrations = []\n"
        "const restCalls = []\n"
        "const disposer = () => {}\n"
        "const ctx = {\n"
        "  register: (c) => { registrations.push(c); return disposer },\n"
        "  rest: (path, opts) => { restCalls.push([path, opts ?? null]); return Promise.resolve({ designs: [] }) }\n"
        "}\n"
        "plugin.register(ctx)\n"
        "const calls = registrations.map((c) => {\n"
        "  let rendered = null\n"
        "  let renderError = null\n"
        "  if (typeof c.render === 'function') {\n"
        "    try { const el = c.render(); rendered = el && el.type ? (typeof el.type === 'string' ? el.type : 'component') : null }\n"
        "    catch (err) { renderError = String(err && err.message ? err.message : err) }\n"
        "  }\n"
        "  return {\n"
        "    id: c.id, area: c.area, title: c.title ?? null, data: c.data ?? null,\n"
        "    renderType: typeof c.render, rendered, renderError\n"
        "  }\n"
        "})\n"
        "console.log(JSON.stringify({\n"
        "  id: plugin.id, name: plugin.name ?? null, description: plugin.description ?? null,\n"
        "  calls, restCalls\n"
        "}))\n",
        encoding="utf-8",
    )

    run = subprocess.run(
        [node, str(driver)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, f"plugin register() failed under Node:\n{run.stderr}"
    return json.loads(run.stdout)


def test_register_contributes_a_full_page(registration):
    assert registration["id"] == "visual-workflow"
    pages = [c for c in registration["calls"] if c["area"] == "routes"]
    assert len(pages) == 1, registration["calls"]
    page = pages[0]
    assert page["data"] == {"path": "/workflows"}
    assert page["title"] == "Workflows"
    assert page["renderType"] == "function"
    assert page["renderError"] is None, page["renderError"]
    assert page["rendered"] == "component", "render() must return the jsx element for the page component"


def test_register_contributes_the_sidebar_row(registration):
    rows = [c for c in registration["calls"] if c["area"] == "sidebar.nav"]
    assert len(rows) == 1, registration["calls"]
    assert rows[0]["data"] == {"codicon": "project", "label": "Workflows", "path": "/workflows"}
    assert rows[0]["title"] is None, "sidebar.nav is a data contribution, not a rendered row"


def test_register_only_touches_the_two_areas_and_does_not_fetch_eagerly(registration):
    assert {c["area"] for c in registration["calls"]} == {"routes", "sidebar.nav"}
    assert registration["restCalls"] == [], "register() must not call the backend before the page mounts"


# ------------------------------------------------------------ canvas layout
# Same brief as the dashboard tab (all three canvases stay in sync): node creation is a top
# bar, the inspector is a collapsible strip, and the canvas fits its width.
def test_canvas_puts_node_creation_in_a_top_bar(source):
    assert 'class="vw-kit"' in source
    assert source.index('class="vw-kit"') < source.index('data-vw="canvas"')
    assert "vw-palette" not in source, "the left palette rail must be gone"
    kit = source[source.index('class="vw-kit"'):source.index('class="vw-bar"')]
    assert kit.count('data-kind="') == 6, "five step kinds plus the sticky note"
    assert kit.count('class="ico"') == 6


def test_saved_workflows_move_into_the_top_row(source):
    assert '<select class="vw-grow" data-vw="designs"' in source
    assert "function renderDesigns()" in source
    assert "renderRail" not in source
    assert ".vw-rail{" not in source, "the 190px rail is what squeezed the canvas"


def test_templates_load_from_the_same_top_row(source):
    assert 'data-vw="templates"' in source
    assert 'call("/designs/templates")' in source
    assert "function renderTemplates()" in source
    assert "function useTemplate(name)" in source
    # A template loads as an unsaved draft, so Save writes it under the user's own name.
    assert "active = \"\";" in source.split("function useTemplate(name)", 1)[1].split("}", 8)[0]


def test_inspector_starts_collapsed_and_can_be_closed(source):
    assert 'class="vw-app vw-insp-collapsed"' in source
    assert 'data-vw="insp-toggle"' in source and 'aria-expanded="false"' in source
    assert ".vw-app.vw-insp-collapsed .vw-inspector{width:30px" in source
    assert "function setInspector(open)" in source
    assert "setInspector(true)" in source


def test_canvas_fits_its_width_and_recomputes_on_resize(source):
    assert "function fit()" in source
    assert 'setAttribute("viewBox"' in source
    assert "ResizeObserver" in source
    assert "fitLocked" in source


def test_agent_node_offers_a_retry_budget(source):
    assert 'field("retries (optional)"' in source
    assert 'TIPS["agent.retries"]' in source
    assert "current.retries = Math.min(3, count)" in source


# ------------------------------------------------------------ sticky notes
def test_desktop_offers_sticky_notes_as_annotations(source):
    assert 'data-kind="note"' in source
    assert 'const NOTE = "note"' in source
    assert 'const KINDS = ["trigger", "agent", "condition", "approval", "output"]' in source
    assert "KINDS.concat([NOTE])" in source
    assert "NOTE_COLORS" in source


def test_a_note_has_no_ports_and_is_edited_as_free_text(source):
    assert "if (n.type !== NOTE) {" in source
    assert "a note cannot hold a workflow step" in source
    assert 'field("note text"' in source
    assert 'TIPS["note.color"]' in source
    assert 'n.type === "note" ? n.text || ""' in source


def test_nodes_are_compact_with_a_two_line_preview(source):
    assert "const NODE_W = 150;" in source and "const NODE_H = 58;" in source
    assert "function previewLines(n)" in source
    assert "previewLines(n).forEach" in source
    assert "lines.length === 2" in source
