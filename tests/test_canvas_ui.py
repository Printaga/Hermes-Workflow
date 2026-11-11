"""The three canvases must behave the same way about runs, selection and edges.

The dashboard tab (``dashboard/dist/index.js``), the desktop app's canvas
(``desktop/plugin.js``) and the single-file widget (``widgets/designer.html``) are three
copies of one canvas. These tests pin the contracts that a user actually feels, so a fix in
one copy cannot quietly miss the others:

* a run's outcome is a persistent banner above the canvas, not a word in the bar;
* selecting a node never opens an empty band (the node bar must not grow vertically);
* an agent node picks its model from the host catalog and has no provider field;
* edges are made by dragging ports — there is no redundant Connect button.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CANVASES = {
    "dashboard": ROOT / "dashboard" / "dist" / "index.js",
    "desktop": ROOT / "desktop" / "plugin.js",
    "widget": ROOT / "widgets" / "designer.html",
}


@pytest.fixture(scope="module", params=sorted(CANVASES))
def canvas(request) -> tuple[str, str]:
    source = CANVASES[request.param].read_text(encoding="utf-8")
    return request.param, source


# ------------------------------------------------------------------- run feedback
def test_a_run_outcome_lands_in_a_persistent_banner(canvas):
    name, source = canvas
    assert "banner" in source.lower(), f"{name} has no banner for run outcomes"
    # Announced, not just drawn: a status line the user only notices by luck is the bug.
    assert "role=\"status\"" in source or "role='status'" in source, f"{name} banner is not live"
    assert "aria-live" in source, f"{name} banner is not announced"
    # The banner carries the three states a run can end in.
    assert "Run failed" in source, f"{name} does not report a failed run in the banner"
    assert "paused" in source, f"{name} does not say a run is paused"


def test_a_run_that_cannot_start_says_so_instead_of_only_failing_a_request(canvas):
    name, source = canvas
    # An unsaved draft has no server-side design; the canvas must refuse and explain rather
    # than POST a name the backend will 404 on with nothing visible.
    assert "is not saved" in source, f"{name} does not explain an unsaved design on Run"


def test_validation_problems_reach_the_banner(canvas):
    name, source = canvas
    assert "Validate failed" in source, f"{name} swallows a validate failure"


def test_a_cron_step_has_exactly_one_slash_segment(canvas):
    name, source = canvas
    # "*/15/2" is not cron; accepting it saved a schedule the host would never fire.
    assert "step.length !== 2" in source, f"{name} accepts a malformed cron step"


def test_an_edge_key_round_trips_through_json(canvas):
    name, source = canvas
    # A node id may contain '>', so a delimited key could cut the wrong edge.
    assert "JSON.stringify([from, to])" in source, f"{name} uses a colliding edge key"
    assert "JSON.parse(selectedEdge)" in source, f"{name} cannot recover the edge pair"


# --------------------------------------------------------------- selection layout
def compact(text: str) -> str:
    """One rule block with every whitespace run collapsed, so the string check is about the
    declaration and not about how the file happens to indent it."""
    return re.sub(r"\s+", "", text)


def rule(source: str, selector: str) -> str:
    """The first `selector { … }` block in *source*, or "" when the selector is absent."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    return match.group(1) if match else ""


def test_the_node_bar_cannot_grow_vertically(canvas):
    name, source = canvas
    # The node bar is a row in a column shell. As a growing flex item it stretched to fill the
    # height the canvas gave up when a node was selected, so a band of nothing appeared above
    # the canvas. It must keep its own height.
    bar = rule(source, ".vw-kit") or rule(source, "#kit")
    assert bar, f"{name} has no node bar"
    assert "flex:00auto" in compact(bar), f"{name} node bar is allowed to grow: {compact(bar)[:80]}"


def test_the_canvas_keeps_its_band_when_a_node_is_selected(canvas):
    name, source = canvas
    # Measured on the dashboard: the whole surface was 911px tall until a node was clicked,
    # then 458px, because the canvas inherited whatever the shell had left. It must ask for
    # its own band instead.
    wrap = rule(source, ".vw-wrap") or rule(source, "#canvaswrap")
    assert wrap, f"{name} has no canvas wrapper"
    assert "min-height:clamp(320px,calc(100dvh-240px),900px)" in compact(wrap), (
        f"{name} canvas band is only as tall as whatever is left over"
    )


# --------------------------------------------------------------- edge creation
def test_no_canvas_offers_a_connect_button(canvas):
    name, source = canvas
    # An edge is made by dragging one port to another. The button only ever joined the two
    # most recently clicked nodes, so it connected the wrong pair as often as the right one —
    # a second, worse way to do the one thing the canvas already does.
    assert 'data-vw="connect"' not in source, f"{name} still renders a Connect button"
    assert 'id="connect"' not in source, f"{name} still renders a Connect button"
    assert '"bar.connect"' not in source, f"{name} still explains a Connect button"


# -------------------------------------------------------------- the model picker
def body_of(source: str, name: str) -> str:
    """The `function <name>(...) { … }` block, matched by brace depth."""
    start = re.search(r"function " + re.escape(name) + r"\([^)]*\) \{", source)
    assert start, f"no function {name}()"
    depth = 0
    for index in range(start.end() - 1, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start.end():index]
    raise AssertionError(f"{name}() is not closed")


def test_an_agent_node_has_no_provider_field(canvas):
    name, source = canvas
    # A step names a model; the runtime derives the provider from the host catalog, so an
    # editable provider is a field that can only disagree with what actually runs.
    assert '"agent.provider"' not in source, f"{name} still explains a provider field"
    assert '"provider (optional)"' not in source, f"{name} still renders a provider field"
    assert "current.provider" not in source, f"{name} still writes a provider onto the node"


# Each surface reaches the backend through its own transport, so name the call instead of the
# path: a URL that only appears in a comment passes a bare substring check while the picker
# stays empty.
MODELS_CALL = {
    "dashboard": 'fetchJSON(API + "/models")',
    "desktop": 'call("/models")',
    "widget": 'window.fetch("/api/plugins/visual-workflow/models"',
}


def test_the_model_picker_only_offers_the_active_providers_models(canvas):
    name, source = canvas
    body = body_of(source, "modelSelect")
    # The runtime derives the provider from the pick and now fails a step whose model
    # is not served by the routed provider — so offering other providers' models is
    # offering guaranteed failures. Unknown active provider falls back to the full
    # catalog, never an empty picker.
    assert "currentProvider" in body, f"{name} model picker ignores the active provider"
    assert ".filter(" in body, f"{name} model picker stores the provider but never filters"
    assert "currentProvider" in source, f"{name} never stores the active provider"


def test_the_model_picker_is_a_select_over_the_host_catalog(canvas):
    name, source = canvas
    assert MODELS_CALL[name] in source, f"{name} never requests the host model catalog"
    body = body_of(source, "modelSelect")
    assert 'createElement("select")' in body, f"{name} model picker is not a select"
    assert 'createElement("optgroup")' in body, f"{name} model picker does not group by provider"
    # No catalog (a bare file:// preview, or a host without one) must stay typeable instead of
    # rendering an empty control.
    assert "textInput(" in body, f"{name} model picker has no free-text fallback"
    # A saved model the catalog no longer lists stays visible rather than being reset silently.
    assert "not listed" in body, f"{name} drops a model the catalog does not list"


# ------------------------------------------------------------ reviewer context
def test_a_paused_run_shows_the_context_it_was_given(canvas):
    name, source = canvas
    # A gate's context is the material being approved; an agent pause's context is what that
    # step will see. Both travel in ``pending``, so a copy that drops them makes someone
    # decide with less information than the backend already sent.
    hits = re.findall(r"\b(?:pending|gate|step)\.context\b", body_of(source, "renderRun"))
    assert len(hits) >= 2, f"{name} drops the context a paused run carries: {hits}"


def test_an_approval_can_be_given_the_context_it_shows(canvas):
    name, source = canvas
    # Showing a field no canvas can set was the other half of the gap: the same inspector that
    # displays the context must write it, and clearing the box must remove the key rather than
    # persist an empty string forever.
    assert 'field("context (optional)"' in source, f"{name} cannot author approval context"
    assert "current.context" in source, f"{name} never writes approval context"
    assert "delete current.context" in source, f"{name} stores a cleared context as empty"


# ------------------------------------------------ failed runs: diagnosis chips + retry

# A diagnosed failure (spawn.py) reaches the stored error record as ``kind``/``hint``; each
# canvas must label the chip with the kind and ride the hint on its title — and offer a
# retry, which re-enters the run at the failed step instead of rebuilding it.
CHIP = {
    "dashboard": '"vw-chip"',
    "desktop": '"vw-chip"',
    "widget": 'className = "chip"',
}

RETRY_GUARD = {
    "dashboard": 'lastRun.status !== "failed"',
    "desktop": 'lastRun.status !== "failed"',
    "widget": 'lastStatus !== "failed"',
}


def test_a_failed_run_labels_its_diagnosed_kind_with_the_hint_as_tooltip(canvas):
    name, source = canvas
    body = body_of(source, "renderRun")
    assert "error.kind" in body, f"{name} does not show a run's diagnosed kind"
    assert 'error.hint || "diagnosed failure kind"' in source, (
        f"{name} drops the fix hint the backend sent"
    )
    assert CHIP[name] in source, f"{name} has no chip element for the kind"


def test_the_runs_view_carries_the_chip_for_a_failed_run_too(canvas):
    name, source = canvas
    if name == "widget":
        pytest.skip("the standalone widget has no Runs view")
    where = "error.kind" if name == "desktop" else "row.error.kind"
    assert where in source, f"{name}'s Runs view never reads a run's diagnosed kind"
    if name == "dashboard":
        assert "row.error.kind" in source, "the dashboard's Runs row must chip as well"


def test_a_failed_run_can_be_retried_and_only_when_it_failed(canvas):
    name, source = canvas
    body = body_of(source, "retryFailedRun")
    assert RETRY_GUARD[name] in body, f"{name} retries more than failed runs"
    assert '"/retry"' in body, f"{name} has no retry call in retryFailedRun"


def test_the_retry_control_is_tipped_and_offered_in_the_failed_card(canvas):
    name, source = canvas
    assert 'TIPS["runs.retry"]' in source, f"{name} never applies the retry tooltip"
    assert "Retry run" in body_of(source, "renderRun"), (
        f"{name}'s failed-run card offers no Retry control"
    )


@pytest.mark.parametrize("name", ["dashboard", "desktop"])
def test_the_collapsed_inspector_does_not_ask_for_a_percentage_height(name):
    source = CANVASES[name].read_text(encoding="utf-8")
    # Serving canvases sit in a host whose height is not definite. A percentage height on the
    # collapsed toggle turned into a cyclic dependency that Chrome resolved at ~911px, which
    # is the phantom band the canvas lost on selection; the standalone widget owns a definite
    # page height and is unaffected.
    match = re.search(r"\.vw-app\.vw-insp-collapsed \.vw-insp-toggle\s*\{([^}]*)\}", source)
    assert match, f"{name} has no collapsed inspector toggle"
    assert "height:100%" not in compact(match.group(1)), (
        f"{name} collapsed toggle asks for a percentage height inside an auto-height row"
    )


# ------------------------------------------------- finished runs: show the result
def test_a_finished_run_row_offers_its_result(canvas):
    name, source = canvas
    if name == "widget":
        pytest.skip("the standalone widget has no Runs view")
    # A finished run's text lives only on disk; the row must offer it, not just the
    # design. Both surfaces mount the stored run through the single-run fetch.
    assert 'TIPS["runs.result"]' in source, f"{name} has no tooltip for the Result control"
    if name == "desktop":
        assert "showStoredRun(run)" in body_of(source, "runRow"), (
            f"{name} Result control does not reopen the stored run")
    else:
        assert "props.onResult(row)" in source, f"{name} Result control is not wired"
        assert "onResult: showStoredResult" in source, f"{name} never mounts the stored run"
        assert '"/runs/" + encodeURIComponent(row.run_id)' in source, (
            f"{name} Result control does not fetch the stored run")


# ------------------------------------------------------- deletion, human paths
def test_finished_work_can_be_deleted_from_the_gui(canvas):
    name, source = canvas
    if name == "widget":
        pytest.skip("the standalone widget has no lists to delete from")
    # Saved workflows: a Delete control next to New, refused while scheduled.
    assert 'TIPS["bar.delete_design"]' in source, f"{name} never tips design deletion"
    # Stored runs: every row offers Delete with a confirm, then re-reads the list.
    assert 'TIPS["runs.delete"]' in source, f"{name} never tips run deletion"
    assert '{ method: "DELETE" }' in source, f"{name} never issues a DELETE request"
    if name == "desktop":
        assert 'data-vw="delete-design"' in source, f"{name} has no design Delete button"
        assert 'call("/designs/" + encodeURIComponent(name), { method: "DELETE" })' in source, (
            f"{name} design Delete never calls the backend")
        assert 'call("/runs/" + encodeURIComponent(run.run_id), { method: "DELETE" })' in source, (
            f"{name} run Delete never calls the backend")
    else:
        assert 'key: "delete-design"' in source, f"{name} has no design Delete button"
        assert "removeActive" in source, f"{name} never deletes the open design"
        assert "remove(row)" in source, f"{name} never deletes a stored run"
        assert '"/runs/" + encodeURIComponent(row.run_id), {' in source, (
            f"{name} run Delete never calls the backend")


# --------------------------------------- right-click deletion on the canvas
def test_right_click_deletes_nodes_and_cuts_edges(canvas):
    name, source = canvas
    # Right-click opens a one-item menu: "Delete node" on nodes (which selects and
    # removes), "Cut connection" on edges. No confirm — draft-level like Delete.
    node_body = body_of(source, "wireNode")
    assert "showCtxMenu" in node_body, f"{name} right-click never opens a menu"
    assert '"Delete node"' in node_body, f"{name} menu never offers node deletion"
    assert '"Cut connection"' in source, f"{name} menu never offers cutting the edge"
    assert "vw-ctxmenu" in source, f"{name} menu has no dismissable element"


# --------------------------------------- finished runs paint onto the canvas
def test_a_mounted_run_paints_excerpts_under_its_nodes(canvas):
    name, source = canvas
    # No schema change, no new node kind: the canvas excerpts the mounted run's
    # outputs (already in the run state) beneath the nodes that produced them, and
    # only while the mounted run belongs to the open design.
    assert "summarizeOutputs(result)" in source, f"{name} never captures a run's outputs"
    assert "outputLines(n.id)" in source, f"{name} never paints outputs under nodes"
    assert "lastRunName !== graph.name" in source, (
        f"{name} can paint one design's outputs onto another")
    # A fresh failure or parked gate must drop the previous run's excerpts, and
    # slicing must be code-point based so emoji never splits into tofu.
    assert 'lastRunName = ""' in source, f"{name} never clears stale excerpts"
    assert "Array.from" in body_of(source, "summarizeOutputs"), (
        f"{name} caps output text on UTF-16 units")
    assert "Array.from" in body_of(source, "outputLines"), (
        f"{name} wraps output text on UTF-16 units")
    # The selected node shows the full text in the inspector, not just the canvas lines.
    assert '"last output"' in body_of(source, "buildInspector"), (
        f"{name} inspector hides a node's full output")
    assert "lastFull[current.id]" in body_of(source, "buildInspector"), (
        f"{name} inspector never reads the mounted run")
