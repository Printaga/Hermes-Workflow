"""``pre_tool_call`` gate for model-initiated external sends (staff listing review).

The hook fires on ``workflow_design_run`` and escalates to Hermes' human-approval
prompt only when the saved design would actually send: any other tool, a
collect-only design, or an unknown design passes through untouched (None).
"""

from visual_workflow_hermes.hooks import on_pre_tool_call
from visual_workflow_hermes.store import DesignStore, RunStore


def _save(tmp_path, name, *outputs):
    store = DesignStore(root=tmp_path / "workflow-designs")
    store.save(name, {"name": name, "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        *outputs,
    ]})


def _out(node_id, deliver=None, target=None):
    node = {"id": node_id, "type": "output", "after": ["trigger1"]}
    if deliver is not None:
        node["deliver"] = deliver
    if target is not None:
        node["target"] = target
    return node


def test_unrelated_tools_and_missing_names_pass_through(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert on_pre_tool_call("workflow_design_save", {"name": "x"}) is None
    assert on_pre_tool_call("other_tool", {"name": "x"}) is None
    assert on_pre_tool_call("workflow_design_run", {"name": "ghost"}) is None
    assert on_pre_tool_call("workflow_design_run", {}) is None
    assert on_pre_tool_call("workflow_design_run") is None


def test_collect_only_and_unsendable_designs_pass_through(tmp_path, monkeypatch):
    from visual_workflow_hermes.delivery import delivering_targets

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _save(tmp_path, "plain", _out("out"))
    assert on_pre_tool_call("workflow_design_run", {"name": "plain"}) is None
    # Malformed leftovers the schema would never let through save() still gate nothing.
    assert delivering_targets({"nodes": [_out("out", deliver="channel")]}) == []
    assert delivering_targets({"nodes": [_out("out", deliver="channel", target="x")]}) == []
    assert delivering_targets({"nodes": [_out("out", deliver="bogus", target="x")]}) == []


def test_delivering_design_escalates_to_human_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _save(tmp_path, "loud",
          _out("news", deliver="channel", target="telegram:123456"),
          _out("ping", deliver="notification", target="telegram"))
    verdict = on_pre_tool_call("workflow_design_run", {"name": "loud"})
    assert verdict is not None and verdict["action"] == "approve"
    assert "telegram:123456" in verdict["message"]
    assert "telegram" in verdict["message"]
    assert "loud" in verdict["message"]


def test_retry_of_a_delivering_run_escalates_too(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _save(tmp_path, "loud", _out("news", deliver="channel", target="telegram:99"))
    RunStore(root=tmp_path / "workflow-runs").save(
        {"run_id": "abcdef123456", "name": "loud", "status": "failed"})
    verdict = on_pre_tool_call("workflow_design_run", {"retry": "abcdef123456"})
    assert verdict is not None and verdict["action"] == "approve"
    assert "telegram:99" in verdict["message"]
    assert on_pre_tool_call("workflow_design_run", {"retry": "000000000000"}) is None


def test_design_with_agent_but_collect_only_output_is_quiet(tmp_path, monkeypatch):
    # The realistic shape: an agent step whose output only collects.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = DesignStore(root=tmp_path / "workflow-designs")
    store.save("quiet", {"name": "quiet", "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "writer", "type": "agent", "prompt": "Write a haiku.", "after": ["trigger1"]},
        {"id": "out", "type": "output", "after": ["writer"]},
    ]})
    assert on_pre_tool_call("workflow_design_run", {"name": "quiet"}) is None


def test_retry_takes_precedence_over_name(tmp_path, monkeypatch):
    """A call carrying both resolves the retry first, mirroring tool_run."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _save(tmp_path, "quiet", _out("out"))
    _save(tmp_path, "loud", _out("news", deliver="channel", target="telegram:1"))
    RunStore(root=tmp_path / "workflow-runs").save(
        {"run_id": "abcdef123457", "name": "loud", "status": "failed"})
    verdict = on_pre_tool_call("workflow_design_run",
                               {"name": "quiet", "retry": "abcdef123457"})
    assert verdict is not None and verdict["action"] == "approve"
    assert "telegram:1" in verdict["message"]
