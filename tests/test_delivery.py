"""Output-node delivery: the text we build, the seam we call, and what happens when it fails.

The host seam (``tools.send_message_tool.send_message_tool``) is stubbed through a fake module
on ``sys.modules`` — no platform token, no network, no gateway. What is pinned here is our
side of the contract: the exact call shape, the two target modes, and the rule that a failed
delivery is recorded but never fails the run.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from visual_workflow_hermes import delivery
from visual_workflow_hermes.convert import build_run_plan
from visual_workflow_hermes.runner import new_state, run_plan
from visual_workflow_hermes.schema import validate_designer_graph


class Recorder(list):
    """A list of recorded calls that also carries the fake seam's canned result."""

    box: dict = {}


@pytest.fixture
def sent(monkeypatch):
    """Install a fake host send seam that records the args and returns *result*."""
    calls = Recorder()
    box = {"result": json.dumps({"success": True, "note": "Sent to telegram home channel"})}

    def fake(args, **kwargs):
        calls.append((args, kwargs))
        result = box["result"]
        return result(args) if callable(result) else result

    tool = types.ModuleType("tools.send_message_tool")
    tool.send_message_tool = fake
    tools = types.ModuleType("tools")
    tools.send_message_tool = tool
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.send_message_tool", tool)
    calls.box = box
    return calls


# ------------------------------------------------------------------------- text
def test_render_text_names_the_workflow_and_each_parent():
    text = delivery.render_text("daily-digest", "out1", {"writer": "a haiku", "draft": {"n": 2}})
    assert text.startswith("Workflow daily-digest \u2014 out1")
    assert "- writer: a haiku" in text
    assert '- draft: {"n": 2}' in text


def test_render_text_handles_an_empty_payload_and_truncates():
    assert "(no upstream output)" in delivery.render_text("w", "out", {})
    long = delivery.render_text("w", "out", {"a": "x" * 10000})
    assert len(long) == delivery.MAX_TEXT
    assert long.endswith("\u2026")


# ------------------------------------------------------------- deliver_output
def test_a_node_without_a_mode_only_collects(sent):
    outcome = delivery.deliver_output({"id": "out"}, {"a": 1}, "w")
    assert outcome == {"target": "", "ok": True, "detail": "collected only"}
    assert sent == [], "collect-only must not touch the send seam"


def test_deliver_without_a_target_is_reported_not_raised(sent):
    outcome = delivery.deliver_output({"id": "out", "deliver": "notification"}, {}, "w")
    assert outcome["ok"] is False and "no target" in outcome["detail"]
    assert sent == []


def test_a_channel_target_needs_a_chat_id(sent):
    outcome = delivery.deliver_output(
        {"id": "out", "deliver": "channel", "target": "telegram"}, {}, "w"
    )
    assert outcome["ok"] is False and "platform>:<chat" in outcome["detail"]
    assert sent == []


def test_notification_sends_to_the_target_through_the_host_seam(sent):
    outcome = delivery.deliver_output(
        {"id": "out", "deliver": "notification", "target": "telegram"}, {"writer": "hi"}, "w"
    )
    assert outcome["ok"] is True
    assert outcome["target"] == "telegram"
    (args, kwargs), = sent
    assert kwargs == {}
    assert args["action"] == "send" and args["target"] == "telegram"
    assert "Workflow w \u2014 out" in args["message"] and "hi" in args["message"]


def test_channel_sends_to_the_explicit_chat(sent):
    delivery.deliver_output(
        {"id": "out", "deliver": "channel", "target": "slack:#ops"}, {"a": 1}, "w"
    )
    assert sent[0][0]["target"] == "slack:#ops"


def test_a_rejected_send_is_reported_not_raised(sent):
    sent.box["result"] = json.dumps({"error": "telegram is not configured"})
    outcome = delivery.deliver_output(
        {"id": "out", "deliver": "notification", "target": "telegram"}, {}, "w"
    )
    assert outcome["ok"] is False
    assert "not configured" in outcome["detail"]


def test_the_seam_raising_is_reported(monkeypatch):
    def boom(args, **kwargs):
        raise RuntimeError("socket closed")

    tool = types.ModuleType("tools.send_message_tool")
    tool.send_message_tool = boom
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.send_message_tool", tool)
    outcome = delivery.send_text("telegram", "hello")
    assert outcome["ok"] is False and "socket closed" in outcome["detail"]


def test_a_missing_host_seam_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "tools.send_message_tool", None)
    outcome = delivery.send_text("telegram", "hello")
    assert outcome["ok"] is False and "unavailable" in outcome["detail"]


# -------------------------------------------------------------- runner wiring
def _plan(nodes):
    return build_run_plan({"name": "w", "nodes": nodes})


def test_a_delivering_output_records_the_outcome_on_the_run(sent):
    plan = _plan([
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "writer", "type": "agent", "prompt": "p", "after": ["trigger1"]},
        {"id": "out", "type": "output", "after": ["writer"],
         "deliver": "notification", "target": "telegram"},
    ])
    state = new_state(plan, "run1")
    state["outputs"]["writer"] = "a haiku"
    state["cursor"] = 1  # the agent step already ran; only the output is left
    state = run_plan(plan, state, deliver=delivery.deliver_output)

    assert state["status"] == "done"
    assert state["outputs"]["out"] == {"writer": "a haiku"}
    (record,) = state["deliveries"]
    assert record["node_id"] == "out" and record["ok"] is True
    assert sent[0][0]["message"].startswith("Workflow w \u2014 out")


def test_a_failed_delivery_does_not_fail_the_run(monkeypatch):
    def deliver(step, payload, run_name):
        raise RuntimeError("channel went away")

    plan = _plan([
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "out", "type": "output", "after": ["trigger1"],
         "deliver": "channel", "target": "slack:#ops"},
    ])
    state = run_plan(plan, new_state(plan, "run1"), deliver=deliver)
    assert state["status"] == "done"
    (record,) = state["deliveries"]
    assert record["ok"] is False and "channel went away" in record["detail"]


def test_no_deliver_hook_means_no_delivery_record():
    plan = _plan([
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "out", "type": "output", "after": ["trigger1"],
         "deliver": "notification", "target": "telegram"},
    ])
    state = run_plan(plan, new_state(plan, "run1"))
    assert state["status"] == "done" and state["deliveries"] == []


# ------------------------------------------------------------ convert / schema
def test_convert_passes_the_delivery_fields_through():
    plan = _plan([
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "out", "type": "output", "after": ["trigger1"],
         "deliver": " Channel ", "target": " telegram:42 "},
    ])
    step = plan["steps"][0]
    assert step["deliver"] == "channel" and step["target"] == "telegram:42"


def test_convert_omits_delivery_when_the_node_only_collects():
    plan = _plan([
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "out", "type": "output", "after": ["trigger1"]},
    ])
    assert "deliver" not in plan["steps"][0] and "target" not in plan["steps"][0]


def _graph(**node):
    base = {"id": "out", "type": "output", "after": ["trigger1"]}
    return {"name": "w", "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {**base, **node},
    ]}


def test_schema_rejects_an_unknown_delivery_mode():
    errors = validate_designer_graph(_graph(deliver="email"))
    assert [e["field"] for e in errors] == ["deliver"]


def test_schema_requires_a_target_for_a_delivery():
    errors = validate_designer_graph(_graph(deliver="notification"))
    assert [e["field"] for e in errors] == ["target"]


def test_schema_requires_a_chat_id_for_a_channel_target():
    assert validate_designer_graph(_graph(deliver="channel", target="telegram"))
    assert validate_designer_graph(_graph(deliver="notification", target="telegram")) == []
    assert validate_designer_graph(
        _graph(deliver="channel", target="telegram:42")
    ) == []
