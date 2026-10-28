import json
from pathlib import Path

from visual_workflow_hermes.schema import validate_designer_graph

EX = Path(__file__).parent.parent / "examples"


def _load(name):
    return json.loads((EX / name).read_text())


def test_hello_world_fixture_is_valid():
    assert validate_designer_graph(_load("hello-world.designer.json")) == []


def test_approval_demo_fixture_is_valid():
    assert validate_designer_graph(_load("approval-demo.designer.json")) == []


def test_rejects_missing_trigger_and_bad_ref():
    bad = {"name": "bad", "nodes": [
        {"id": "a", "type": "agent", "prompt": "x", "after": ["ghost"]},
    ]}
    errs = validate_designer_graph(bad)
    assert any(e["field"] == "trigger" for e in errs)
    assert any(e["field"] == "after" for e in errs)


def test_rejects_unknown_type_and_empty_prompt():
    bad = {"name": "bad", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "", "after": ["t"]},
        {"id": "z", "type": "frobnicator", "after": ["a"]},
    ]}
    errs = validate_designer_graph(bad)
    assert any(e["node"] == "a" and e["field"] == "prompt" for e in errs)
    assert any(e["node"] == "z" and e["field"] == "type" for e in errs)


def test_rejects_bad_expression_self_ref_and_cycle():
    bad_expr = {"name": "b", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["t"]},
        {"id": "c", "type": "condition", "expression": "draft is long", "after": ["a"]},
    ]}
    assert any(e["field"] == "expression"
               for e in validate_designer_graph(bad_expr))
    self_ref = {"name": "s", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["a"]},
    ]}
    assert any("itself" in e["msg"] for e in validate_designer_graph(self_ref))
    cycle = {"name": "c", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["b"]},
        {"id": "b", "type": "agent", "prompt": "y", "after": ["a"]},
    ]}
    assert any("cycle" in e["msg"] for e in validate_designer_graph(cycle))
