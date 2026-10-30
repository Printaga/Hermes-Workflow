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


def diagnose_failure(exc: BaseException) -> dict:
    """A backend exception in the words the Runs view needs.

    ``{"kind": ..., "why": ...}`` when the failure matches a known surface — rate limit,
    timeout, trust refusal, auth, unknown model, connection — else ``{}`` so the raw message
    is what the run records (never a wrong reason invented for an unknown error).
    """
    # The trust gate is a class, not a phrase: ``PluginLlmTrustError`` subclasses
    # ``PermissionError``, and the message then names the exact config key to set.
    if isinstance(exc, PermissionError):
        return {
            "kind": "trust refusal",
            "why": (f"the host refused this step's override — either clear the step's model "
                    f"field or set plugins.entries.{PLUGIN_ID}.llm.allow_model_override in "
                    f"the host config"),
        }
    text = f"{str(exc)} {type(exc).__name__}".lower()
    if "does not exist" in text or "not found" in text or "decommissioned" in text:
        return {"kind": "unknown model",
                "why": "the provider has no model by that id — fix the step's Model field"}
    if "rate limit" in text or "429" in text or "too many requests" in text or "quota" in text:
        return {"kind": "rate limited",
                "why": "the model provider asked to slow down — wait a minute and rerun"}
    if "timed out" in text or "timeout" in text or "deadline" in text:
        return {"kind": "timed out",
                "why": "the call outlived its budget — rerun, or give the step a longer timeout"}
    if ("401" in text or "403" in text or "api key" in text
            or "unauthorized" in text or "authentication" in text):
        return {"kind": "auth failed",
                "why": "the provider rejected the credentials — check that provider's key "
                       "in the host config"}
    if ("connection" in text or "econnrefused" in text or "getaddrinfo" in text
            or "resolve" in text or "reset by peer" in text or "temporarily" in text
            or "unable to reach" in text):
        return {"kind": "connection problem",
                "why": "the model provider is unreachable from this machine — a retry often "
                       "clears it; a repeat means check the host's model setup"}
    return {}


def _explain(exc: BaseException, kind: str, why: str) -> str:
    """The error string a run records: reason first, original detail kept for debugging."""
    raw = str(exc).strip() or type(exc).__name__
    return f"{kind}: {raw} — {why}."


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
            diagnosed = diagnose_failure(exc)
            if diagnosed:
                # ``error_kind`` is the machine-readable signal (the runner's rate-limit
                # backoff keys off it); ``error_hint`` is the same advice as a field, for
                # any route that wants the hint without the prose.
                return {"error": _explain(exc, diagnosed["kind"], diagnosed["why"]),
                        "error_kind": diagnosed["kind"], "error_hint": diagnosed["why"]}
            return {"error": str(exc) or type(exc).__name__}

    return spawn
