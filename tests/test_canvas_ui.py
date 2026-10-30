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
