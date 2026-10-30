"""Agent-node profile ("bot") binding.

The host owns profiles (``hermes_cli.profiles.list_profiles``, behind ``GET /api/profiles``).
The plugin only reads them: the dashboard picker lists them, and a chosen profile supplies the
model an agent step runs on unless the node overrides it. No host package is required for any
of it — every lookup degrades to "no profile" instead of raising.
"""
from __future__ import annotations

import sys
import types

import pytest

from visual_workflow_hermes import profiles
from visual_workflow_hermes.convert import build_run_plan


class FakeProfile:
    def __init__(self, name, **kw):
        self.name = name
        self.model = kw.get("model")
        self.provider = kw.get("provider")
        self.is_default = kw.get("is_default", False)
        self.bot_title = kw.get("bot_title", "")
        self.display_name = kw.get("display_name", "")
        self.description = kw.get("description", "")
        self.skill_count = 0


@pytest.fixture
def host(monkeypatch):
    """A fake ``hermes_cli.profiles`` module; returns the list it hands back."""
    box = {"profiles": [FakeProfile("default", model="gpt-5", provider="openai", is_default=True),
                        FakeProfile("writer", model="claude", provider="anthropic",
                                    bot_title="Writer bot")]}

    def list_profiles(**kwargs):
        box["kwargs"] = kwargs
        return box["profiles"]

    mod = types.ModuleType("hermes_cli.profiles")
    mod.list_profiles = list_profiles
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.profiles = mod
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.profiles", mod)
    return box


# ------------------------------------------------------------------------ list
def test_lists_profiles_with_a_display_label(host):
    listed = profiles.list_host_profiles()
    assert [p["name"] for p in listed] == ["default", "writer"]
    assert listed[0]["label"] == "default"
    assert listed[0]["is_default"] is True
    assert listed[1]["label"] == "Writer bot"
    assert listed[1]["model"] == "claude"
    # The provider is not a node/profile field any more: it is derived from the model.
    assert "provider" not in listed[1]


def test_listing_is_lazy_so_the_picker_can_poll(host):
    profiles.list_host_profiles()
    assert host["kwargs"] == {"lazy_skill_count": True}


def test_a_missing_host_registry_yields_no_profiles(monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli.profiles", None)
    assert profiles.list_host_profiles() == []


def test_a_broken_registry_yields_no_profiles(monkeypatch):
    mod = types.ModuleType("hermes_cli.profiles")

    def boom(**kwargs):
        raise RuntimeError("profile store is corrupt")

    mod.list_profiles = boom
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.profiles", mod)
    assert profiles.list_host_profiles() == []


# --------------------------------------------------------------------- model
def test_a_profile_supplies_its_model(host):
    assert profiles.step_model({"profile": "writer"}) == "claude"


def test_an_explicit_node_model_wins_over_the_profile(host):
    assert profiles.step_model({"profile": "writer", "model": "o3"}) == "o3"


def test_an_unknown_profile_leaves_the_host_default(host):
    assert profiles.step_model({"profile": "ghost"}) is None


def test_no_profile_and_no_model_is_no_override():
    assert profiles.step_model({}) is None


# --------------------------------------------------------------- passthrough
def test_convert_carries_the_profile_onto_the_agent_step():
    plan = build_run_plan({"name": "w", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "p", "profile": "writer", "after": ["t"]},
    ]})
    assert plan["steps"][0]["profile"] == "writer"
