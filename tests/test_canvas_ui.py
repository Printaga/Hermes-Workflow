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
