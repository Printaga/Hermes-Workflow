"""Guards for the single-file designer widget (Task 7).

The widget is vanilla HTML/SVG hosted by Hermes `::preview`. It cannot be unit-tested as
DOM here, so these tests pin the properties that would silently rot: the default graph is
real designer JSON (validates AND converts), there are no external dependencies, and the
Hermes bridge is guarded so opening the file in a plain browser does not throw.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from visual_workflow_hermes.convert import build_run_plan
from visual_workflow_hermes.schema import validate_designer_graph

WIDGET = Path(__file__).resolve().parent.parent / "widgets" / "designer.html"

_DEFAULT_RE = re.compile(
    r'<script id="default-graph" type="application/json">(.*?)</script>', re.S
)


@pytest.fixture(scope="module")
def html() -> str:
    assert WIDGET.is_file(), f"missing widget at {WIDGET}"
    return WIDGET.read_text(encoding="utf-8")


def test_widget_is_a_single_substantial_file(html):
    assert len(html) > 5000
    assert "<svg" in html
    assert "doctype" in html.lower()


def test_default_graph_is_valid_designer_json(html):
    match = _DEFAULT_RE.search(html)
    assert match, "widget must embed its default graph as #default-graph JSON"
    graph = json.loads(match.group(1))
    assert graph["name"] == "hello-world"
    assert [n["id"] for n in graph["nodes"]] == ["trigger1", "writer", "out"]
    assert validate_designer_graph(graph) == []


def test_default_graph_converts_to_a_run_plan(html):
    graph = json.loads(_DEFAULT_RE.search(html).group(1))
    plan = build_run_plan(graph)
    assert [s["id"] for s in plan["steps"]] == ["writer", "out"]
    assert plan["meta"]["trigger"]["mode"] == "manual"


def test_no_external_dependencies(html):
    lowered = html.lower()
    assert "react" not in lowered
    assert "<vue" not in lowered and "vue@" not in lowered
    assert "<script src" not in lowered
    assert "cdn." not in lowered
    # Only allowed URL is the SVG namespace literal, which is not a fetch.
    stripped = lowered.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in stripped
    assert "https://" not in stripped


def test_hermes_bridge_is_guarded(html):
    assert "window.hermes.send" in html
    assert 'typeof window.hermes !== "undefined"' in html
    assert "data-hermes-send" in html


def test_uses_host_theme_variables_only(html):
    for var in ("--foreground", "--muted-foreground", "--accent", "--border", "--card"):
        assert f"var({var}" in html, f"widget must theme via {var}"
    assert "background-image" not in html
    assert "@import" not in html


def test_svg_helper_routes_var_paints_through_inline_style(html):
    """SVG presentation attributes do not resolve var(); a paint set that way is black.

    The widget keeps the host token names (its page supplies them), but the paint must land
    in a style declaration where var() is valid.
    """
    match = re.search(r"function svgEl\([^)]*\) \{(.*?)\n  \}", html, re.S)
    assert match, "widget must define svgEl()"
    body = match.group(1)
    paint = re.search(r"PAINT\w*\s*=\s*\{([^}]*)\}", html.split("function svgEl")[0])
    assert paint, "svgEl must name the attributes it treats as paint"
    assert "fill" in paint.group(1) and "stroke" in paint.group(1)
    assert 'indexOf("var(")' in body
    assert "style.setProperty" in body
    assert body.index('indexOf("var(")') < body.index("style.setProperty")
    assert body.index("style.setProperty") < body.index("setAttribute")


def test_validation_rules_are_ported(html):
    # The JS validator must carry the same demands as schema.py, in the same words.
    assert "'out.<node>.<field> <op> <value>'" in html
    assert "workflow needs exactly one trigger" in html
    assert "dependency cycle" in html
    assert "node cannot depend on itself" in html


# ---------------------------------------------------------------- canvas edges
def test_nodes_have_explicit_ports_and_edges_are_curves(html):
    """Click-two-nodes-then-Connect was unusable; the canvas now drags port to port."""
    assert "function outPort(n)" in html and "function inPort(n)" in html
    assert "function edgePath(parent, child)" in html
    assert html.count('"data-port"') >= 2, "every node needs an out port and an in port"
    # The input port is omitted on a trigger: a trigger can never have parents.
    assert 'n.type !== "trigger"' in html
    assert '"edge-hit"' in html, "edges need a fat transparent hit area to be clickable"


def test_dragging_from_a_port_connects_and_bad_edges_are_refused(html):
    assert "function beginLink(" in html
    assert "function finishLink(" in html
    assert "nodeIdAtPoint" in html, "the drop target must be resolved by geometry"
    assert "that edge would close a loop" in html
    assert "a trigger cannot have parents" in html
    assert "function createsCycle(" in html


def test_an_edge_can_be_selected_and_cut(html):
    assert "selectedEdge" in html
    assert "function cutEdge(" in html
    assert "function removeSelected(" in html
    assert "cut " in html


def test_agent_node_offers_a_profile_picker(html):
    assert "function profileControl(" in html
    assert "/api/plugins/visual-workflow/profiles" in html
    assert "profile / bot" in html


def test_output_node_can_deliver_and_validates_its_target(html):
    assert 'field("deliver"' in html
    assert '"notification"' in html and '"channel"' in html
    assert 'field("target"' in html
