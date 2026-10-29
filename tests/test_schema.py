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


def test_a_note_is_legal_and_changes_nothing_else():
    """Sticky notes are annotations: they validate, but they are not workflow steps."""
    graph = {"name": "n", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["t"]},
        {"id": "note1", "type": "note", "text": "remember the tone", "x": 20, "y": 30},
        {"id": "note2", "type": "note", "text": "", "color": "blue", "x": 0, "y": 0},
    ]}
    assert validate_designer_graph(graph) == []


def test_a_design_of_only_a_note_is_invalid():
    """A note cannot start a run: the trigger rule still applies to it."""
    errors = validate_designer_graph({"name": "n", "nodes": [
        {"id": "note1", "type": "note", "text": "just a thought"},
    ]})
    assert any(e["field"] == "trigger" for e in errors)


def test_notes_take_no_edges_in_either_direction():
    """A note has no ports, so an edge to or from one is a design defect, not a no-op."""
    note_with_parent = validate_designer_graph({"name": "n", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["t"]},
        {"id": "note1", "type": "note", "text": "hi", "after": ["a"]},
    ]})
    assert any(e["node"] == "note1" and e["field"] == "after" for e in note_with_parent)

    depends_on_note = validate_designer_graph({"name": "n", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "note1", "type": "note", "text": "hi"},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["t", "note1"]},
    ]})
    assert any(e["node"] == "a" and e["field"] == "after" for e in depends_on_note)


def test_note_colour_is_checked_against_the_known_set():
    def graph(**note):
        node = {"id": "note1", "type": "note", "text": "hi"}
        node.update(note)
        return {"name": "n", "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
            {"id": "a", "type": "agent", "prompt": "x", "after": ["t"]}, node]}

    assert validate_designer_graph(graph()) == []
    assert validate_designer_graph(graph(color="green")) == []
    assert any(e["field"] == "color"
               for e in validate_designer_graph(graph(color="chartreuse")))


def test_agent_retries_are_optional_and_capped():
    def graph(**agent):
        node = {"id": "a", "type": "agent", "prompt": "x", "after": ["t"]}
        node.update(agent)
        return {"name": "r", "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []}, node]}

    assert validate_designer_graph(graph()) == []
    for good in (0, 2, "3"):
        assert validate_designer_graph(graph(retries=good)) == [], good
    for bad in (-1, 4, "lots"):
        errors = validate_designer_graph(graph(retries=bad))
        assert any(e["field"] == "retries" for e in errors), bad


def test_notes_do_not_hide_a_real_cycle():
    graph = {"name": "c", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "note1", "type": "note", "text": "look here"},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["b"]},
        {"id": "b", "type": "agent", "prompt": "y", "after": ["a"]},
    ]}
    assert any("cycle" in e["msg"] for e in validate_designer_graph(graph))


def test_approval_timeout_and_policy_are_validated():
    def graph(**approval):
        node = {"id": "g", "type": "approval", "question": "ok?", "after": ["t"]}
        node.update(approval)
        return {"name": "g", "nodes": [
            {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []}, node]}

    assert validate_designer_graph(graph(timeout_minutes=30, on_timeout="reject")) == []
    assert validate_designer_graph(graph(timeout_minutes="45", on_timeout="escalate")) == []
    assert validate_designer_graph(graph()) == []

    for bad in (0, -5, 4321, "soon"):
        errors = validate_designer_graph(graph(timeout_minutes=bad))
        assert any(e["field"] == "timeout_minutes" for e in errors), bad
    bad_policy = validate_designer_graph(graph(on_timeout="retry"))
    assert any(e["field"] == "on_timeout" for e in bad_policy)
