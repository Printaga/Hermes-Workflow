"""Slash-command verbs, end to end against a throwaway store.

Every verb the usage text advertises must actually do something: the README, the widget's
Save-to-Hermes button and the agent all drive the plugin through these strings.
"""
from __future__ import annotations

import json
import re

import pytest

DESIGN = {
    "name": "demo",
    "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "gate", "type": "approval", "question": "Ship it?",
         "options": ["yes", "no"], "after": ["trigger1"]},
        {"id": "out", "type": "output", "after": ["gate"]},
    ],
}


class FakeCtx:
    """The registration surface the host provides (see tests/test_register.py)."""

    def __init__(self):
        self.commands = {}
        self.tools = {}
        self.hooks = {}

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = {"handler": handler, "description": description}

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kwargs}

    def register_hook(self, hook_name, callback):
        self.hooks[hook_name] = callback


@pytest.fixture()
def run_cmd(tmp_path, monkeypatch):
    """A `/workflow` handler bound to a temporary HERMES_HOME."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from visual_workflow_hermes import register

    ctx = FakeCtx()
    register(ctx)
    return ctx.commands["workflow"]["handler"]


def test_save_list_validate_open_round_trip(run_cmd):
    saved = run_cmd("save demo " + json.dumps(DESIGN))
    assert "saved" in saved and "demo" in saved

    assert "demo" in run_cmd("list")
    assert run_cmd("validate demo") == "demo: valid"

    opened = run_cmd("open demo")
    assert "Ship it?" in opened
    assert "::preview" in opened
    assert json.loads(opened.split("designer JSON:\n", 1)[1])["nodes"][1]["id"] == "gate"


def test_save_accepts_fenced_json(run_cmd):
    fenced = "```json\n" + json.dumps(DESIGN) + "\n```"
    assert "saved" in run_cmd("save fenced " + fenced)


def test_new_points_at_the_widget(run_cmd):
    out = run_cmd("new blank")
    assert "widgets/designer.html" in out
    assert "/workflow save blank" in out


def test_save_rejects_bad_json_without_raising(run_cmd):
    out = run_cmd("save broken {'nodes': [}")
    assert "failed" in out and "not JSON" in out


def test_save_names_the_invalid_node(run_cmd):
    graph = {"name": "bad", "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "writer", "type": "agent", "prompt": "", "after": ["trigger1"]},
    ]}
    out = run_cmd("save bad " + json.dumps(graph))
    assert "writer" in out and "prompt" in out


def test_run_pauses_at_the_gate_and_approve_finishes_it(run_cmd):
    run_cmd("save demo " + json.dumps(DESIGN))

    started = run_cmd("run demo")
    assert "awaiting_approval" in started
    assert "Ship it?" in started and "options: yes, no" in started
    match = re.search(r"/workflow approve (\S+) (\S+) <answer>", started)
    assert match, started

    finished = run_cmd(f"approve {match.group(1)} {match.group(2)} yes")
    assert "done" in finished
    assert "out" in finished


def test_approve_for_a_run_waiting_on_another_node_fails(run_cmd):
    run_cmd("save demo " + json.dumps(DESIGN))
    run_cmd("run demo")
    assert "failed" in run_cmd("approve deadbeefcafe gate yes")


def test_run_of_unknown_design_reports_instead_of_crashing(run_cmd):
    out = run_cmd("run nope")
    assert "failed" in out.lower() or "unknown" in out.lower()


def test_agent_step_without_a_backend_pauses_with_its_prompt(run_cmd):
    graph = {"name": "agentic", "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "writer", "type": "agent", "prompt": "Write a haiku.", "after": ["trigger1"]},
    ]}
    run_cmd("save agentic " + json.dumps(graph))
    out = run_cmd("run agentic")
    assert "awaiting_agent" in out
    assert "Write a haiku." in out
    assert "workflow_design_respond" in out
