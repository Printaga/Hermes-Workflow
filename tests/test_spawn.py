"""Agent-step spawn (``visual_workflow_hermes/spawn.py``): widget-free unit tests.

The real ``PluginLlm`` is replaced by a fake recording its kwargs, so the tests stay runnable
wherever the host is absent — the same discipline ``models.py``/``profiles.py`` already follow.
"""
from __future__ import annotations

import types

import pytest

from visual_workflow_hermes.spawn import _make_spawn, llm_spawn


class _Llm:
    """Fake ``PluginLlm`` recording kwargs; returns canned text/parsed results."""

    def __init__(self, *, text: str = "AGENT OUTPUT", parsed=None, raises: Exception | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.text = text
        self.parsed = parsed
        self.raises = raises

    def complete(self, **kwargs):
        self.calls.append(("complete", kwargs))
        if self.raises:
            raise self.raises
        return types.SimpleNamespace(text=self.text)

    def complete_structured(self, **kwargs):
        self.calls.append(("structured", kwargs))
        if self.raises:
            raise self.raises
        return types.SimpleNamespace(text=self.text, parsed=self.parsed)


def test_spawn_sends_the_prompt_and_returns_the_text():
    llm = _Llm(text="haiku line one\nhaiku line two")
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "write a haiku"}, {})
    assert out == {"output": "haiku line one\nhaiku line two"}
    (name, kwargs), = llm.calls
    assert name == "complete"
    assert kwargs["messages"] == [{"role": "user", "content": "write a haiku"}]
    # No model/profile selected: the user's active model serves the step, no override needed,
    # and no ``provider`` key is ever sent (the host routes the provider from the model).
    assert kwargs["model"] is None and "provider" not in kwargs


def test_spawn_hands_upstream_output_in_as_context():
    llm = _Llm()
    step = {"id": "show", "kind": "agent", "prompt": "polish this", "after": ["draft"],
            "inputs": ["draft.title"]}
    out = _make_spawn(llm)(step, {"draft": {"title": "Release 1.2", "body": "wip"}})
    content = llm.calls[0][1]["messages"][0]["content"]
    assert content.startswith("polish this")
    assert "--- output from draft ---" in content
    assert '"title": "Release 1.2"' in content and "wip" in content
    assert out["output"] == "AGENT OUTPUT"


def test_spawn_passes_the_node_model_and_audit_purpose():
    llm = _Llm()
    run = {"run_id": "abc123"}
    _make_spawn(llm)({"id": "w", "kind": "agent", "model": "mod-7", "prompt": "p"}, {}, run)
    kwargs = llm.calls[0][1]
    assert kwargs["model"] == "mod-7"
    assert kwargs["purpose"] == "workflow:abc123:w"


def test_spawn_passes_the_step_timeout():
    llm = _Llm()
    _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p", "timeout": 25}, {})
    assert llm.calls[0][1]["timeout"] == 25


def test_spawn_uses_the_structured_lane_for_a_schema_step():
    llm = _Llm(text='{"answer": 42}', parsed={"answer": 42})
    step = {"id": "w", "kind": "agent", "prompt": "score it", "schema": {"type": "object"}}
    out = _make_spawn(llm)(step, {})
    assert out == {"output": '{"answer": 42}', "structured": {"answer": 42}}
    (name, kwargs), = llm.calls
    assert name == "structured"
    assert kwargs["json_schema"] == {"type": "object"}
    assert kwargs["instructions"] == "score it"


def test_spawn_drops_a_non_dict_structured_payload():
    llm = _Llm(text='["x"]', parsed=["x"])
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p",
                            "schema": {"type": "array"}}, {})
    assert out == {"output": '["x"]', "structured": None}


def test_spawn_wraps_a_backend_failure_as_step_data():
    llm = _Llm(raises=RuntimeError("the bot failed"))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out == {"error": "the bot failed"}


# ------------------------------------------------------------------ the diagnosed error
# The Runs view prints a step's error message verbatim, so a bare provider string
# ("Connection error.") is a dead end. spawn explains the surface it saw — reason first,
# original detail kept — and invents nothing when the failure matches nothing known.


def test_spawn_diagnoses_a_rate_limit():
    llm = _Llm(raises=RuntimeError("Error code: 429 - Rate limit reached for model"))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"].startswith("rate limited: "), out["error"]
    assert out["error_kind"] == "rate limited"    # the runner's one-key retry reads this
    assert "429" in out["error"]          # the original detail survives for debugging
    assert "wait a minute" in out["error"]


def test_spawn_diagnoses_a_timeout():
    llm = _Llm(raises=TimeoutError("Request timed out"))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"].startswith("timed out: "), out["error"]
    assert "Request timed out" in out["error"]


def test_spawn_diagnoses_a_trust_refusal():
    llm = _Llm(raises=PermissionError(
        "Plugin 'visual-workflow' cannot override the model (set "
        "plugins.entries.visual-workflow.llm.allow_model_override to true to allow)."))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"].startswith("trust refusal: "), out["error"]
    assert "allow_model_override" in out["error"]


def test_spawn_diagnoses_an_auth_failure():
    llm = _Llm(raises=RuntimeError("Error code: 401 - Invalid API key"))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"].startswith("auth failed: "), out["error"]


def test_spawn_diagnoses_an_unknown_model():
    llm = _Llm(raises=RuntimeError("model 'z-9' does not exist"))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"].startswith("unknown model: "), out["error"]
    assert "Model field" in out["error"]


def test_spawn_diagnoses_a_connection_failure():
    llm = _Llm(raises=RuntimeError("Connection error."))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"].startswith("connection problem: "), out["error"]
    assert "Connection error." in out["error"]


def test_spawn_invents_nothing_for_an_unknown_failure():
    llm = _Llm(raises=RuntimeError("something wholly novel happened"))
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out == {"error": "something wholly novel happened"}


def test_an_empty_message_falls_back_to_the_exception_name():
    llm = _Llm(raises=RuntimeError())
    out = _make_spawn(llm)({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out["error"] == "RuntimeError"


def test_llm_spawn_returns_none_when_the_host_is_absent(monkeypatch):
    class _Boom:
        def __getattr__(self, item):
            raise ModuleNotFoundError("host not importable")

    monkeypatch.setitem(__import__("sys").modules, "agent.plugin_llm", _Boom())
    assert llm_spawn() is None


def test_llm_spawn_accepts_an_injected_facade():
    fake = _Llm()
    spawn = llm_spawn(fake)
    out = spawn({"id": "w", "kind": "agent", "prompt": "p"}, {})
    assert out == {"output": "AGENT OUTPUT"}
