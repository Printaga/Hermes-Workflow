"""Contract tests: what a canvas actually builds must save, validate and run.

The bug these exist for: the output inspector offered ``deliver`` and ``target`` as two
independent dropdowns, so ``deliver=channel`` could be paired with a home-channel target
(``telegram``, no colon). The backend rejected that — correctly — but the canvas had already
let the user build it, and the failure only showed up on Save.

So these tests do not hand-write a payload that happens to be valid. They take the payload the
canvas builds:

* the default node objects every ``addNode()`` creates (parsed from each canvas source);
* the ``(deliver, target)`` pair the shipped ``applySendTo()`` produces for each send-to
  choice (the function is extracted from the canvas and executed by Node, so the mapping under
  test is the shipped one, not a copy of it);
* the legacy two-dropdown pair, to pin the exact field error the backend owes the user.

The same payloads go through ``POST /designs/{name}``, ``/validate``, ``/run`` and
``/runs/{id}/respond`` exactly as the canvases call them.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from visual_workflow_hermes.schema import validate_designer_graph

ROOT = Path(__file__).resolve().parent.parent
CANVASES = {
    "dashboard": ROOT / "dashboard" / "dist" / "index.js",
    "desktop": ROOT / "desktop" / "plugin.js",
    "widget": ROOT / "widgets" / "designer.html",
}

# The default node each canvas creates from the palette: the same base keys, plus the one
# field its inspector starts with. A canvas that drifts from this shape fails here instead of
# at Save.
EXPECTED_DEFAULTS = {
    "trigger": {"trigger_mode": "manual"},
    "agent": {"prompt": ""},
    "condition": {"expression": ""},
    "approval": {"question": ""},
    "note": {"text": ""},
}

# One home channel and one chat, shaped exactly as ``channels.list_delivery_targets`` returns.
HOME = {"id": "telegram", "label": "Telegram \u2014 home channel", "kind": "home",
        "platform": "telegram"}
CHAT = {"id": "telegram:8522302999", "label": "Ada \u00b7 telegram", "kind": "dm",
        "platform": "telegram"}
PICKER_VALUES = ["", HOME["id"], CHAT["id"]]
# What each picker value must become: collect only, home-channel notification, one chat.
EXPECTED_PAIRS = {
    "": {},
    "telegram": {"deliver": "notification", "target": "telegram"},
    "telegram:8522302999": {"deliver": "channel", "target": "telegram:8522302999"},
}


@pytest.fixture(scope="module", params=sorted(CANVASES))
def canvas(request) -> tuple[str, str]:
    name = request.param
    return name, CANVASES[name].read_text(encoding="utf-8")


# ------------------------------------------------------------------ source extraction
def function_body(source: str, name: str) -> str:
    """The body of ``function <name>(...) { ... }``, matched by brace depth."""
    start = re.search(r"function " + re.escape(name) + r"\([^)]*\) \{", source)
    assert start, f"no function {name}()"
    depth = 0
    for index in range(start.end() - 1, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start.end():index]
    raise AssertionError(f"{name}() is not closed")


_BASE_RE = re.compile(r"(?:const|let|var)\s+fresh\s*=\s*\{(.*?)\};", re.S)
_DEFAULT_RE = re.compile(
    r'if \(kind === "(\w+)"\)\s*\{?\s*fresh\.(\w+)\s*=\s*([^;]+);'
)


def canvas_defaults(source: str) -> dict:
    """``{kind: {field: value}}`` — every default ``addNode()`` writes, read from the source."""
    body = function_body(source, "addNode")
    base = _BASE_RE.search(body)
    assert base, "addNode() must create its default node as `fresh = {...}`"
    assert re.findall(r"(\w+)\s*:", base.group(1)) == ["id", "type", "after"], (
        f"default node shape changed: {base.group(1)!r}"
    )
    defaults: dict[str, dict] = {}
    for kind, field, literal in _DEFAULT_RE.findall(body):
        defaults.setdefault(kind, {})[field] = json.loads(literal.strip())
    return defaults


def default_node(kind: str, node_id: str, after: list[str] | None = None,
                 defaults: dict | None = None) -> dict:
    """One node exactly as the palette creates it (layout keys included; the validator ignores
    them, the canvas always writes them)."""
    defaults = EXPECTED_DEFAULTS if defaults is None else defaults
    node = {"id": node_id, "type": kind, "after": after or []}
    node.update(defaults.get(kind, {}))
    node["x"] = 26
    node["y"] = 28
    return node


def send_to_pairs(source: str) -> dict:
    """Execute the canvas's own ``applySendTo`` and return ``{picker value: node fields}``."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the source-shape tests still cover the control")
    body = function_body(source, "applySendTo")
    script = """
const fnSource = %s;
const values = %s;
const apply = new Function(fnSource + "\\nreturn applySendTo;")();
const out = {};
values.forEach(function (value) {
  const node = {};
  apply(node, value);
  out[value] = node;
});
console.log(JSON.stringify(out));
""" % (json.dumps("function applySendTo(node, value) {" + body + "}"),
       json.dumps(PICKER_VALUES))
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30,
                         check=False)
    assert run.returncode == 0, f"applySendTo() failed under Node:\n{run.stderr}"
    return json.loads(run.stdout)


# -------------------------------------------------------------------------- API client
@pytest.fixture
def client(tmp_path, monkeypatch):
    """Mount the plugin router the way the host does, against a throwaway HOME."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    api = ROOT / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_contract", api)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/visual-workflow")
    return TestClient(app), mod


def _save(client, name: str, graph: dict) -> dict:
    return client.post(f"/api/plugins/visual-workflow/designs/{name}",
                       json={"graph": graph}).json()


def _validate(client, name: str, graph: dict) -> dict:
    return client.post(f"/api/plugins/visual-workflow/designs/{name}/validate",
                       json={"graph": graph}).json()


def _run(client, name: str) -> dict:
    return client.post(f"/api/plugins/visual-workflow/designs/{name}/run").json()


def _design(name: str, nodes: list[dict]) -> dict:
    return {"name": name, "nodes": nodes}


def _runnable(name: str, defaults: dict, send_to: dict) -> dict:
    """A workflow that reaches every pause and the output node, built only from canvas defaults."""
    out = default_node("output", "out", ["gate"], defaults)
    out.update(send_to)
    return _design(name, [
        default_node("trigger", "trigger1", defaults=defaults),
        {**default_node("agent", "writer", ["trigger1"], defaults),
         "prompt": "say hi"},
        {**default_node("condition", "check", ["writer"], defaults),
         "expression": 'out.writer == "hi"'},
        {**default_node("approval", "gate", ["check"], defaults),
         "question": "Ship it?", "options": ["ship", "hold"]},
        out,
    ])


# ---------------------------------------------------------------------- node shapes
def test_every_canvas_builds_the_same_default_node_objects(canvas):
    name, source = canvas
    parsed = canvas_defaults(source)
    assert parsed == EXPECTED_DEFAULTS, f"{name} default node objects drifted: {parsed}"


def test_the_default_node_objects_are_read_by_the_backend(canvas):
    """The defaults are *shaped* right: the validator reads them and asks only for the one
    required field the palette leaves empty."""
    name, source = canvas
    defaults = canvas_defaults(source)
    for kind, fields in EXPECTED_DEFAULTS.items():
        if kind == "note":
            continue
        if kind == "trigger":
            # A trigger is complete on its own — and the validator allows exactly one. A default
            # that fails must not hide behind an expectation for a missing field.
            errors = validate_designer_graph(_design(
                "defaults", [default_node("trigger", "trigger1", defaults=defaults)]))
            assert errors == [], f"{name}: the default trigger is invalid: {errors}"
            continue
        nodes = [default_node("trigger", "trigger1", defaults=defaults),
                 default_node(kind, "node1", ["trigger1"], defaults)]
        errors = validate_designer_graph(_design("defaults", nodes))
        missing = [e for e in errors if e["field"] in fields]
        assert missing, f"{name}: the backend did not read the default {kind} fields"


# --------------------------------------------------------- the send-to payload contract
def test_one_send_to_control_derives_deliver_and_target(canvas):
    """No independent deliver select: the invalid pair cannot be built in the inspector."""
    name, source = canvas
    assert "function applySendTo(node, value)" in source, f"{name} has no one-choice mapping"
    assert 'field("send to"' in source, f"{name} does not offer a single send-to control"
    assert 'field("deliver"' not in source, f"{name} still offers a separate deliver mode"
    assert "current.deliver = deliver.value" not in source, (
        f"{name} still lets the deliver mode be chosen independently of the target"
    )
    # The options are the host's channel directory (home channels + chats), not a fixed list of
    # delivery modes.
    body = function_body(source, "sendToSelect")
    assert "item.id" in body, f"{name} send-to picker does not use the host channel ids"
    assert '"notification"' not in body and '"channel"' not in body, (
        f"{name} send-to picker hard-codes delivery modes instead of channel entries"
    )


def test_every_send_to_choice_produces_the_one_valid_pair(canvas):
    name, source = canvas
    pairs = send_to_pairs(source)
    assert pairs == EXPECTED_PAIRS, f"{name} derives the wrong (deliver, target) pairs: {pairs}"
    for value, fields in pairs.items():
        if fields.get("deliver") == "channel":
            assert ":" in fields["target"], f"{name} produced a channel target without a chat"


@pytest.mark.parametrize("value", PICKER_VALUES)
def test_canvas_shaped_design_saves_validates_and_runs(client, canvas, value):
    """Save, validate, run to ``awaiting_agent``, answer it, answer the gate, finish."""
    api, _ = client
    name, source = canvas
    design_name = f"contract-{name}-{value.replace(':', '-') or 'collect'}"
    graph = _runnable(design_name, canvas_defaults(source), send_to_pairs(source)[value])

    saved = _save(api, design_name, graph)
    assert saved["ok"] is True, saved
    validated = _validate(api, design_name, graph)
    assert validated["ok"] is True and validated["errors"] == []

    first = _run(api, design_name)
    assert first["status"] == "awaiting_agent", first
    assert first["pending"]["node_id"] == "writer"
    assert first["pending"]["prompt"] == "say hi"

    # The exact body each canvas's respond() builds for a text answer.
    resumed = api.post(
        f"/api/plugins/visual-workflow/runs/{first['run_id']}/respond",
        json={"run_id": first["run_id"], "node_id": "writer", "answer": "hi"},
    ).json()
    assert resumed["status"] == "awaiting_approval", resumed
    assert resumed["pending"]["node_id"] == "gate"

    done = api.post(
        f"/api/plugins/visual-workflow/runs/{first['run_id']}/respond",
        json={"run_id": first["run_id"], "node_id": "gate", "answer": "ship"},
    ).json()
    assert done["status"] == "done", done
    assert done["outputs"]["writer"] == "hi"
    assert done["outputs"]["out"] == {"gate": "ship"}
    if value:
        (record,) = done["deliveries"]
        assert record["node_id"] == "out"
        assert record["target"] == value
    else:
        assert done["deliveries"] == []


def test_the_old_two_dropdown_combo_keeps_the_exact_field_error(client):
    """The payload the two independent dropdowns produced: broadcast the channel error."""
    api, _ = client
    graph = _design("legacy-combo", [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "out", "type": "output", "after": ["trigger1"],
         "deliver": "channel", "target": "telegram"},
    ])
    expected = [{
        "node": "out",
        "field": "target",
        "msg": "a channel target needs <platform>:<chat id>",
    }]

    saved = _save(api, "legacy-combo", graph)
    assert saved["ok"] is False
    assert saved["errors"] == expected

    validated = _validate(api, "legacy-combo", graph)
    assert validated["ok"] is False and validated["errors"] == expected

    ran = _run(api, "legacy-combo")
    # The route runs saved designs only, and this invalid graph was never saved — so the
    # run leg is a 404, not the field report; the exact error is carried by save+validate
    # above, which are what the canvas shows before a run exists.
    assert ran == {"detail": "no saved workflow named 'legacy-combo'"}


# ------------------------------------------------------------------- the resume dead-end
def test_the_run_panel_resumes_an_agent_step_inline(canvas):
    """A paused agent step must offer a result box and a resume button where the run is shown,
    and still say the workflow can be run from chat."""
    name, source = canvas
    body = function_body(source, "renderRun")
    assert "awaiting_agent" in body, f"{name} does not render the agent pause"
    assert 'createElement("textarea")' in body, f"{name} has no inline result box"
    assert re.search(r"respond\([^)]*node_id", body) or "respond(step.node_id" in body, (
        f"{name} has no resume call wired to the run panel"
    )
    assert "from chat" in body or "from chat" in source, f"{name} drops the run-via-chat hint"
    assert "runs.resume" in source, f"{name} does not explain the resume control"


def test_the_run_panel_can_let_the_agent_produce_the_parked_step(canvas):
    """A parked agent step must not force hand-pasting: the canvas offers the host agent's
    own execution (``agent_generate`` — the facade a Run uses), and never claims the canvas
    categorically cannot run an agent."""
    name, source = canvas
    body = function_body(source, "renderRun")
    assert "Run this step with the agent" in body, f"{name} buttons the generation off"
    # The payload the control builds lives in the canvas's own respond helper; either way it
    # must reach the resume route, never a hand-pasted fallback.
    assert "agent_generate" in source, f"{name} has no run-with-agent control on the pause card"
    assert "cannot run an agent" not in body and "cannot run an agent" not in source, (
        f"{name} still claims it cannot run an agent at all"
    )


def test_a_run_started_elsewhere_can_be_reopened_into_the_resume_box(canvas):
    """The Runs list must not dead-end a paused agent step in a 'go to chat' sentence."""
    name, source = canvas
    if name == "widget":
        pytest.skip("the standalone widget has no runs list")
    assert re.search(r"/runs/\" \+ encodeURIComponent\(", source), (
        f"{name} never reads a stored run back"
    )
    assert "showRun" in source or "openRun" in source, (
        f"{name} cannot bring a paused run back into its run panel"
    )
