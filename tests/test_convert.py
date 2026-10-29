import json
from pathlib import Path

import pytest

from visual_workflow_hermes.convert import build_run_plan, topological_order

EX = Path(__file__).parent.parent / "examples"


def _load(name):
    return json.loads((EX / name).read_text())


def test_hello_world_plan_drops_trigger_and_orders_steps():
    plan = build_run_plan(_load("hello-world.designer.json"))
    assert [s["id"] for s in plan["steps"]] == ["writer", "out"]
    agent, output = plan["steps"]
    assert agent["kind"] == "agent"
    assert agent["prompt"] == "Write a haiku about rivers."
    assert agent["after"] == []          # trigger ref resolved away
    assert output["kind"] == "output"
    assert output["keys"] == ["writer"]
    assert plan["meta"]["trigger"]["mode"] == "manual"


def test_approval_demo_plan_maps_all_four_kinds():
    plan = build_run_plan(_load("approval-demo.designer.json"))
    by_id = {s["id"]: s for s in plan["steps"]}
    assert set(by_id) == {"draft", "big_enough", "human_ok", "out"}
    assert by_id["big_enough"]["kind"] == "condition"
    assert by_id["big_enough"]["expression"] == "out.draft.word_count > 20"
    assert by_id["human_ok"]["kind"] == "approval"
    assert by_id["human_ok"]["question"] == "Ship this release note?"
    assert by_id["human_ok"]["options"] == ["ship", "edit"]
    assert by_id["out"]["keys"] == ["human_ok"]


def test_order_is_topological_not_declaration_order():
    designer = {"name": "t", "nodes": [
        {"id": "late", "type": "output", "after": ["early"]},
        {"id": "early", "type": "agent", "prompt": "do it", "after": []},
    ]}
    plan = build_run_plan(designer)
    assert [s["id"] for s in plan["steps"]] == ["early", "late"]


def test_ties_break_by_declaration_order():
    a = {"id": "b_node", "kind": "agent", "after": []}
    b = {"id": "a_node", "kind": "agent", "after": []}
    assert [s["id"] for s in topological_order([a, b])] == ["b_node", "a_node"]


def test_agent_passthrough_fields_are_kept():
    designer = {"name": "t", "nodes": [
        {"id": "t1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "p", "model": "m1", "provider": "prov",
         "schema": {"type": "object"}, "after": ["t1"]},
    ]}
    step = build_run_plan(designer)["steps"][0]
    assert step["model"] == "m1" and step["provider"] == "prov"
    assert step["schema"] == {"type": "object"}


def test_cycle_raises():
    steps = [{"id": "a", "after": ["b"]}, {"id": "b", "after": ["a"]}]
    with pytest.raises(ValueError, match="cycle"):
        topological_order(steps)


def test_trigger_only_design_raises():
    designer = {"name": "t", "nodes": [
        {"id": "t1", "type": "trigger", "trigger_mode": "manual", "after": []},
    ]}
    with pytest.raises(ValueError, match="no executable nodes"):
        build_run_plan(designer)


def test_layout_coordinates_never_reach_the_plan():
    designer = {"name": "t", "nodes": [
        {"id": "t1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "p", "after": ["t1"], "x": 40, "y": 90},
    ]}
    step = build_run_plan(designer)["steps"][0]
    assert "x" not in step and "y" not in step


def test_schedule_metadata_survives_into_the_plan():
    designer = {"name": "daily", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "schedule",
         "schedule": "0 9 * * *", "after": []},
        {"id": "a", "type": "agent", "prompt": "p", "after": ["t"]},
    ]}
    meta = build_run_plan(designer)["meta"]["trigger"]
    assert meta == {"mode": "schedule", "schedule": "0 9 * * *"}


def test_approval_timeout_survives_into_the_plan():
    designer = {"name": "gated", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "g", "type": "approval", "question": "ok?", "options": ["yes", "no"],
         "timeout_minutes": 15, "on_timeout": "Escalate", "after": ["t"]},
    ]}
    step = build_run_plan(designer)["steps"][0]
    assert step["timeout_minutes"] == 15
    assert step["on_timeout"] == "escalate"
