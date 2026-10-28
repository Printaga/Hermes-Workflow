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


def test_validation_rules_are_ported(html):
    # The JS validator must carry the same demands as schema.py, in the same words.
    assert "'out.<node>.<field> <op> <value>'" in html
    assert "workflow needs exactly one trigger" in html
    assert "dependency cycle" in html
    assert "node cannot depend on itself" in html
