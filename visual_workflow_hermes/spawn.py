"""Agent-step spawn for the web-server routes (the dashboard/desktop canvases).

The chat tool runs an agent step through ``ctx.subagent_lifecycle`` (a full child agent,
bound to the active parent session — ``SubagentLifecycleService.launch`` refuses to run
without one). The web server has no parent session, so it parks at ``awaiting_agent``…
which is exactly the dead end a manual **Run** now hits on any design with an agent node.

The host's plugin LLM facade (``ctx.llm``) covers exactly that gap: it needs no
parent session, runs on the user's active model, and supports the two per-step knobs the
runner already carries (a model override, a JSON schema). This module adapts it to the
runner's ``spawn`` seam. Failures of the host come back as ``None`` (no backend) or an
``{"error": ...}`` record that the runner turns into a step failure, never an unhandled raise.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# The deployed plugin's identity: the host gates model/provider overrides per plugin id
# (``plugins.entries.visual-workflow.llm.allow_model_override``), so this must match plugin.yaml.
PLUGIN_ID = "visual-workflow"


def llm_spawn(llm: Any = None, plugin_id: str = PLUGIN_ID) -> Optional[Callable[..., dict]]:
    """A spawn callable backed by ``PluginLlm``, or ``None`` when the host is not importable.

    ``llm`` accepts an injected facade for tests; production resolves the real one per call,
    so a host hot-reload or a plugin restart cannot strand the routes on a stale object.
    """
    if llm is None:
        try:
            from agent.plugin_llm import PluginLlm

            llm = PluginLlm(plugin_id=plugin_id)
        except Exception:  # host absent (unit tests, plain tooling) or the repository moved
            return None
    return _make_spawn(llm)


def _make_spawn(llm: Any) -> Callable[..., dict]:
    def spawn(step: dict, outputs: dict, run: Optional[dict] = None) -> dict:
        # Imports stay inside the spawn so importing this module stays dependency-free.
        from .profiles import step_model
        from .runner import StepError, render_context

        audit = ""
        if isinstance(run, dict) and run.get("run_id"):
            audit = f"workflow:{run['run_id']}:{step.get('id')}"
        model = step_model(step)
        context = render_context(step, outputs)
        content = step.get("prompt", "")
        if context:
            content = f"{content}\n\n{context}"
        # Only a ``model`` override is requested (and only when the step names one):
        # the host routes the provider itself from the model id, and ``provider`` is
        # not part of the plugin's design contract (see convert.py). Sending one would
        # trip the host's fail-closed ``allow_provider_override`` trust gate.
        overrides = {"model": model or None, "timeout": step.get("timeout"),
                     "purpose": audit}
        try:
            schema = step.get("schema")
            if schema:
                result = llm.complete_structured(
                    instructions=step.get("prompt", ""),
                    input=[{"type": "text", "text": context}] if context else [],
                    json_schema=schema,
                    system_prompt="You are one step of an agent workflow; follow the instructions exactly.",
                    **overrides,
                )
                structured = result.parsed if isinstance(result.parsed, dict) else None
                return {"output": result.text or "", "structured": structured}
            result = llm.complete(messages=[{"role": "user", "content": content}], **overrides)
            return {"output": result.text or ""}
        except StepError:
            raise
        except Exception as exc:  # a backend problem is step data: the runner turns it into a failure
            return {"error": str(exc)}

    return spawn
