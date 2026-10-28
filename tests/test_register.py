"""Registration contract tests.

FakeCtx mirrors the REAL ``PluginContext.register_tool(name, toolset, schema, handler, **kw)``
signature, so a regression to the old two-argument call fails here instead of at plugin load.
``register_status_segment`` is deliberately absent: v0.22.5 has no such method, and register()
must not depend on it.
"""

TOOLS = (
    "workflow_design_save",
    "workflow_design_load",
    "workflow_design_validate",
    "workflow_design_run",
    "workflow_design_respond",
)


class FakeCtx:
    def __init__(self):
        self.commands = {}
        self.tools = {}

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = {"handler": handler, "description": description}

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kwargs}

    def register_hook(self, hook_name, callback):
        raise AssertionError("this plugin registers no hooks")


def _registered():
    from visual_workflow_hermes import register

    ctx = FakeCtx()
    register(ctx)
    return ctx


def test_register_exposes_slash_command_and_all_tools():
    ctx = _registered()
    assert "workflow" in ctx.commands
    for tool in TOOLS:
        assert tool in ctx.tools, f"{tool} was not registered"


def test_every_tool_registers_with_the_host_signature():
    ctx = _registered()
    for name, entry in ctx.tools.items():
        assert entry["toolset"] == "visual-workflow"
        assert callable(entry["handler"])
        schema = entry["schema"]
        assert schema["name"] == name
        assert schema["description"]
        params = schema["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict) and params["properties"]


def test_tool_schemas_declare_required_arguments():
    ctx = _registered()
    assert ctx.tools["workflow_design_save"]["schema"]["parameters"]["required"] == ["name", "graph"]
    assert ctx.tools["workflow_design_load"]["schema"]["parameters"]["required"] == ["name"]
    assert ctx.tools["workflow_design_validate"]["schema"]["parameters"]["required"] == ["graph"]
    assert ctx.tools["workflow_design_run"]["schema"]["parameters"]["required"] == ["name"]
    assert ctx.tools["workflow_design_respond"]["schema"]["parameters"]["required"] == [
        "run_id", "node_id"]


def test_help_lists_every_verb():
    ctx = _registered()
    out = ctx.commands["workflow"]["handler"]("")
    for verb in ("new", "list", "open", "save", "validate", "run", "approve"):
        assert verb in out


def test_unknown_verb_returns_the_usage_text():
    ctx = _registered()
    out = ctx.commands["workflow"]["handler"]("frobnicate")
    assert "Usage: /workflow" in out


def test_handler_accepts_a_bare_string_argument():
    """The host dispatcher calls ``handler(raw_args: str)`` — bound method, one positional."""
    ctx = _registered()
    assert isinstance(ctx.commands["workflow"]["handler"](""), str)


def test_registered_tool_handlers_return_json_strings():
    """Host contract: handler(args) -> str. The live dispatcher rejected dicts
    (tool_result_contract), so every registered handler must return a JSON str."""
    import json

    ctx = _registered()
    graph = {"name": "t", "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "hi", "after": ["trigger1"]},
        {"id": "out", "type": "output", "after": ["a"]},
    ]}
    out = ctx.tools["workflow_design_validate"]["handler"]({"graph": graph})
    assert isinstance(out, str), type(out)
    assert json.loads(out) == {"ok": True, "errors": []}
