"""Visual agent-workflow designer plugin for Hermes.

Registers:
  - ``/workflow`` slash command — new|list|open|save|validate|run|approve
  - five tools (save/load/validate/run/respond) wrapping the design store and run plan.

Tools are registered against the real host contract
``register_tool(name, toolset, schema, handler, ...)``; ``schema`` is the OpenAI-style
body ``{"name", "description", "parameters"}``. There is no ``register_status_segment``
on Hermes 0.22.5, so none is attempted.
"""
import logging

logger = logging.getLogger(__name__)

TOOLSET = "visual-workflow"


def _as_json(handler):
    """Adapt a dict-returning tool method to the host contract ``(args) -> str``.

    The host tool dispatcher rejects non-str results (tool_result_contract);
    in-tree tools return ``json.dumps(...)``. Internal callers (slash-command
    paths, unit tests) keep calling the raw ``tool_*`` methods for dicts.
    """
    import functools
    import json

    @functools.wraps(handler)
    def wrapper(args, **kwargs):
        return json.dumps(handler(args, **kwargs))

    return wrapper

_SAVE_SCHEMA = {
    "name": "workflow_design_save",
    "description": (
        "Save a visual workflow design under a name. A design is a trigger plus any of "
        "agent, condition, approval and output nodes. The graph is validated before it is written."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Design name: [a-z0-9_.-], starts alphanumeric, max 64 chars.",
            },
            "graph": {
                "type": "object",
                "description": 'The designer graph, e.g. {"name": "...", "nodes": [...]}.',
            },
        },
        "required": ["name", "graph"],
    },
}

_LOAD_SCHEMA = {
    "name": "workflow_design_load",
    "description": "Load a saved visual workflow design by name and return its graph.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Saved design name."},
        },
        "required": ["name"],
    },
}

_VALIDATE_SCHEMA = {
    "name": "workflow_design_validate",
    "description": (
        "Validate a designer graph without saving it. Returns an empty error list when the "
        "graph is valid, otherwise one {node, field, msg} defect per problem."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "graph": {"type": "object", "description": "The designer graph to check."},
        },
        "required": ["graph"],
    },
}

_RUN_SCHEMA = {
    "name": "workflow_design_run",
    "description": (
        "Run a saved workflow design now. Executes steps sequentially and returns the run status: "
        "'done' with outputs, 'awaiting_approval' (answer with workflow_design_respond), or "
        "'awaiting_agent' (perform pending.prompt, then respond with the output)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Saved design name to run."},
        },
        "required": ["name"],
    },
}


_RESPOND_SCHEMA = {
    "name": "workflow_design_respond",
    "description": (
        "Resume a paused workflow run. For 'awaiting_approval' pass the chosen option as answer; "
        "for 'awaiting_agent' pass the step's output as answer (or structured, which downstream "
        "conditions can read). Returns the next run status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "Run id returned by workflow_design_run."},
            "node_id": {"type": "string", "description": "The pending node id."},
            "answer": {
                "type": "string",
                "description": "Approval option, or the agent step's text output.",
            },
            "structured": {
                "type": "object",
                "description": "Optional structured agent output; downstream conditions can read it.",
            },
        },
        "required": ["run_id", "node_id"],
        # A resume with neither field would silently store None as the step's output and
        # advance the run; require one of them in the schema instead of trusting the caller.
        "anyOf": [{"required": ["answer"]}, {"required": ["structured"]}],
    },
}


def register(ctx) -> None:
    """Plugin entry point: one slash command plus five tools."""
    from .runtime import WorkflowDesignerRuntime

    runtime = WorkflowDesignerRuntime(ctx)

    ctx.register_command(
        name="workflow",
        handler=runtime.handle_command,
        description="Visual workflows: /workflow [new|list|open|save|validate|run|approve]",
        args_hint="[new|list|open|save|validate|run|approve]",
    )

    for schema, handler in (
        (_SAVE_SCHEMA, runtime.tool_save),
        (_LOAD_SCHEMA, runtime.tool_load),
        (_VALIDATE_SCHEMA, runtime.tool_validate),
        (_RUN_SCHEMA, runtime.tool_run),
        (_RESPOND_SCHEMA, runtime.tool_respond),
    ):
        ctx.register_tool(
            name=schema["name"],
            toolset=TOOLSET,
            schema=schema,
            handler=_as_json(handler),
            description=schema["description"],
            emoji="🧩",
        )

    logger.info("visual-workflow plugin registered (toolset=%s)", TOOLSET)
