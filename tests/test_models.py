"""Host model catalog for the agent-node picker.

Seam: ``hermes_cli.inventory.build_model_options_payload(load_picker_context())`` — the exact
call behind ``GET /api/model/options`` (``hermes_cli/web_routers/models.py``) and therefore the
list Hermes' own model picker renders. The plugin reads it, never invents a list, and every
failure degrades to "no models" so the canvas can fall back to free-text.
"""
from __future__ import annotations

import sys
import types

import pytest

from visual_workflow_hermes import models


@pytest.fixture(autouse=True)
def _fresh_cache():
    models.clear_cache()
    yield
    models.clear_cache()


@pytest.fixture
def host(monkeypatch):
    """A fake host catalog; ``box['payload']`` is what the inventory call returns."""
    box = {
        "payload": {
            "model": "anthropic/claude-x",
            "provider": "openrouter",
            "providers": [
                {
                    "slug": "openrouter",
                    "name": "OpenRouter",
                    "authenticated": True,
                    "models": ["anthropic/claude-x", "openai/gpt-5"],
                },
                {
                    "slug": "local",
                    "name": "Local",
                    "authenticated": True,
                    "models": ["qwen3:8b"],
                },
                {"slug": "broken", "name": "Broken", "models": []},
            ],
        },
        "calls": 0,
    }

    def build(ctx, **kwargs):  # the host takes the picker context positionally
        box["calls"] += 1
        return box["payload"]

    inventory = types.ModuleType("hermes_cli.inventory")
    inventory.build_model_options_payload = build
    inventory.load_picker_context = lambda: "ctx"
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.inventory = inventory
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.inventory", inventory)
    return box


# ------------------------------------------------------------------------ list
def test_flattens_host_providers_to_slug_label_and_ids(host):
    payload = models.list_host_models()
    assert payload["available"] is True
    assert payload["providers"] == [
        {"slug": "openrouter", "label": "OpenRouter",
         "models": ["anthropic/claude-x", "openai/gpt-5"]},
        {"slug": "local", "label": "Local", "models": ["qwen3:8b"]},
    ]
    assert payload["current"] == {"model": "anthropic/claude-x", "provider": "openrouter"}


def test_a_provider_without_models_is_dropped(host):
    slugs = [p["slug"] for p in models.list_host_models()["providers"]]
    assert "broken" not in slugs


def test_dict_shaped_model_entries_are_accepted(host):
    host["payload"]["providers"][1]["models"] = [{"id": "qwen3:8b"}, {"id": ""}, "extra"]
    local = models.list_host_models()["providers"][1]
    assert local["models"] == ["qwen3:8b", "extra"]


def test_the_catalog_is_cached_and_refresh_rebuilds_it(host):
    models.list_host_models()
    models.list_host_models()
    assert host["calls"] == 1
    models.list_host_models(refresh=True)
    assert host["calls"] == 2


def test_a_missing_host_package_is_no_models_not_an_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli.inventory", None)
    payload = models.list_host_models()
    assert payload == {"providers": [], "available": False, "current": {}}


def test_a_failing_catalog_build_is_no_models(monkeypatch):
    def boom(ctx, **kwargs):
        raise RuntimeError("catalog build blew up")

    inventory = types.ModuleType("hermes_cli.inventory")
    inventory.build_model_options_payload = boom
    inventory.load_picker_context = lambda: "ctx"
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.inventory", inventory)
    assert models.list_host_models()["available"] is False


# -------------------------------------------------------------------- provider
def test_a_unique_model_resolves_to_its_provider(host):
    assert models.provider_for_model("qwen3:8b") == "local"


def test_an_unknown_model_resolves_to_nothing(host):
    assert models.provider_for_model("nope/model") == ""


def test_an_ambiguous_model_prefers_the_current_provider(host):
    host["payload"]["providers"][1]["models"].append("anthropic/claude-x")
    host["payload"]["provider"] = "local"
    assert models.provider_for_model("anthropic/claude-x") == "local"


def test_an_ambiguous_model_without_a_current_provider_resolves_to_nothing(host):
    host["payload"]["providers"][1]["models"].append("anthropic/claude-x")
    host["payload"]["provider"] = "gone"
    assert models.provider_for_model("anthropic/claude-x") == ""


def test_blank_model_is_no_provider():
    assert models.provider_for_model("") == ""
