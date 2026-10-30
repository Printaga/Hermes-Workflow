"""Slash-command + tool handlers. Storage lives in store.py, validation in schema.py,
plan building in convert.py, execution in runner.py.

``tool_*`` methods take the host dispatch shape ``handler(args: dict, **kwargs)``
and return plain dicts for internal callers (slash-command paths, unit tests).
The ``register()`` entry point wraps them to the real host result contract
``-> str`` (JSON); the dispatcher rejects any other return type.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

USAGE = (
    "Usage: /workflow [new|list|open|save|validate|run|approve]\n"
    "  /workflow list                      — list saved visual workflows\n"
    "  /workflow new <name>                — start a new design in the visual designer\n"
    "  /workflow open <name>               — open <name> in the visual designer\n"
    "  /workflow save <name> <json>        — validate and save a designer graph\n"
    "  /workflow validate <name>           — check a saved design without running it\n"
    "  /workflow run <name>                — execute <name> now (manual trigger)\n"
    "  /workflow approve <run> <gate> <answer> — answer an approval gate"
)


def _deliver(step, payload, run_name):
    """Output-node delivery through the host send seam (see ``delivery.py``)."""
    from .delivery import deliver_output

    return deliver_output(step, payload, run_name)


def _subagent_spawn(ctx):
    """Return a spawn callable backed by ``ctx.subagent_lifecycle``, or None when unavailable.

    ``ctx.delegation_backends`` is NOT usable here: it only lists/switches backends. The
    plugin-safe seam that actually launches work is ``SubagentLifecycleService``
    (``agent/subagent_lifecycle.py``): ``launch`` -> ``wait`` -> ``result``.
    """
    service = getattr(ctx, "subagent_lifecycle", None)
    if service is None or not hasattr(service, "launch"):
        return None

    def spawn(step, outputs, run):
        from agent.subagent_lifecycle import SubagentLaunchRequest

        from .models import provider_for_model
        from .profiles import step_model
        from .runner import render_context

        # A chosen profile ("bot") supplies the model unless the node overrides it; the
        # provider is looked up from that model in the host catalog (never a node field).
        model = step_model(step)
        provider = provider_for_model(model) if model else None
        metadata = {"workflow_profile": step["profile"]} if step.get("profile") else {}
        request = SubagentLaunchRequest(
            goal=step.get("prompt", ""),
            context=render_context(step, outputs),
            model=model,
            provider=provider,
            correlation_id=f"workflow:{run['run_id']}:{step['id']}",
            metadata=metadata,
            timeout_seconds=step.get("timeout"),
        )
        handle = service.launch(request)
        service.wait(handle, timeout_seconds=step.get("timeout"))
        result = service.result(handle)
        return {
            "output": result.summary or "",
            "structured": dict(result.structured_payload or {}) or None,
            "error": result.error_message,
        }

    return spawn


class WorkflowDesignerRuntime:
    """Holds the ctx, the design store and the run store."""

    def __init__(self, ctx, store=None):
        self.ctx = ctx
        self.store = store      # injected in tests; lazily built otherwise
        self._run_store = None

    # -- store plumbing -----------------------------------------------------
    def _store(self):
        if self.store is None:
            from .store import DesignStore
            self.store = DesignStore()
        return self.store

    def _runs(self):
        if self._run_store is None:
            from .store import RunStore
            self._run_store = RunStore()
        return self._run_store

    # -- slash command ------------------------------------------------------
    def handle_command(self, args: str) -> str | None:
        text = (args or "").strip()
        verb, _, rest = text.partition(" ")
        verb = verb.lower()
        rest = rest.strip()
        try:
            if verb in ("", "help"):
                return USAGE
            if verb == "list":
                return self._cmd_list()
            if verb == "new" and rest:
                return self._cmd_new(rest.split()[0])
            if verb == "open" and rest:
                return self._cmd_open(rest.split()[0])
            if verb == "save" and rest:
                name, _, payload = rest.partition(" ")
                if payload.strip():
                    return self._cmd_save(name, payload)
            if verb == "validate" and rest:
                return self._cmd_validate(rest.split()[0])
            if verb == "run" and rest:
                return self._cmd_run(rest.split()[0])
            if verb == "approve" and rest:
                parts = rest.split(maxsplit=2)
                if len(parts) == 3:
                    return self._cmd_approve(parts[0], parts[1], parts[2])
        except Exception as exc:  # a slash command must never crash the turn
            return f"/workflow {verb} failed: {exc}"
        return USAGE

    @staticmethod
    def _widget_hint() -> str:
        path = Path(__file__).resolve().parent.parent / "widgets" / "designer.html"
        return f'::preview{{file="{path}"}}'

    def _cmd_list(self) -> str:
        names = self._store().list_designs()
        if not names:
            return "No saved workflows."
        return "Saved workflows:\n" + "\n".join(f"- {n}" for n in names)

    def _cmd_new(self, name: str) -> str:
        return (
            f"New design {name!r}. Open the visual designer:\n  {self._widget_hint()}\n"
            "Fill in the prompt, Copy JSON, then:\n"
            f"  /workflow save {name} <paste JSON>"
        )

    def _cmd_open(self, name: str) -> str:
        graph = self._store().load(name)
        return (
            f"{name}: {len(graph.get('nodes', []))} node(s)\n  {self._widget_hint()}\n"
            "designer JSON:\n" + json.dumps(graph)
        )

    def _cmd_save(self, name: str, payload: str) -> str:
        raw = payload.strip().strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
        try:
            graph = json.loads(raw)  # untrusted chat text: parse, never eval
        except ValueError as exc:
            return f"/workflow save failed: graph is not JSON ({exc})"
        result = self.tool_save({"name": name, "graph": graph})
        if not result.get("ok"):
            detail = result.get("error") or ""
            problems = result.get("errors") or []
            if problems:
                detail = "\n".join(
                    f"  {e.get('node') or '-'}:{e.get('field')}: {e.get('msg')}" for e in problems
                )
            return f"/workflow save failed: {detail}"
        return f"saved {name!r} ({result['nodes']} node(s)) -> {result['path']}"

    def _cmd_validate(self, name: str) -> str:
        from .schema import validate_designer_graph

        errors = validate_designer_graph(self._store().load(name))
        if not errors:
            return f"{name}: valid"
        return f"{name}: {len(errors)} problem(s)\n" + "\n".join(
            f"  {e['node'] or '-'}:{e['field']}: {e['msg']}" for e in errors
        )

    def _describe(self, result: dict) -> str:
        """Render a tool result as chat text, including the exact resume command."""
        if not result.get("ok") and result.get("error"):
            return f"run failed: {result['error']}"
        status = result.get("status")
        pending = result.get("pending") or {}
        head = f"run {result.get('run_id')}: {status}"
        if status == "awaiting_approval":
            options = pending.get("options") or []
            choices = f" (options: {', '.join(options)})" if options else ""
            return (
                f"{head}\n  gate {pending.get('node_id')}: {pending.get('question')}{choices}\n"
                f"  /workflow approve {result.get('run_id')} {pending.get('node_id')} <answer>"
            )
        if status == "awaiting_agent":
            return (
                f"{head}\n  do this, then resume:\n  {pending.get('prompt')}\n"
                f"  workflow_design_respond run_id={result.get('run_id')} "
                f"node_id={pending.get('node_id')} answer=<output>"
            )
        if status == "failed":
            return f"{head}\n  {result.get('error')}"
        outputs = result.get("outputs") or {}
        keys = ", ".join(sorted(outputs)) or "(none)"
        skipped = result.get("skipped") or []
        tail = f"\n  skipped: {', '.join(map(str, skipped))}" if skipped else ""
        return f"{head}\n  outputs: {keys}{tail}"

    def _cmd_run(self, name: str) -> str:
        return self._describe(self.tool_run({"name": name}))

    def _cmd_approve(self, run_id: str, gate: str, answer: str) -> str:
        return self._describe(
            self.tool_respond({"run_id": run_id, "node_id": gate, "answer": answer.strip()})
        )

    # -- tools --------------------------------------------------------------
    def tool_save(self, args, **_) -> dict:
        name = args.get("name") or ""
        graph = args.get("graph")
        if not isinstance(graph, dict):
            return {"ok": False, "error": "graph must be an object"}
        try:
            path = self._store().save(name, graph)
        except (ValueError, OSError) as exc:
            # Bad name or invalid graph: report it, never raise into the tool dispatcher.
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(path), "nodes": len(graph.get("nodes", []))}

    def tool_load(self, args, **_) -> dict:
        name = args.get("name") or ""
        try:
            return {"ok": True, "graph": self._store().load(name)}
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def tool_validate(self, args, **_) -> dict:
        from .schema import validate_designer_graph

        graph = args.get("graph")
        if not isinstance(graph, dict):
            return {"ok": False, "error": "graph must be an object"}
        errors = validate_designer_graph(graph)
        return {"ok": not errors, "errors": errors}

    def tool_run(self, args, **_) -> dict:
        """Start a run: validate, build the plan, execute until done or paused."""
        from .convert import build_run_plan
        from .runner import new_state, run_plan
        from .schema import validate_designer_graph

        name = args.get("name") or ""
        try:
            designer = self._store().load(name)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        errors = validate_designer_graph(designer)
        if errors:
            return {"ok": False, "errors": errors}
        try:
            plan = build_run_plan(designer)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        run_id = uuid.uuid4().hex[:12]
        state = new_state(plan, run_id)
        self._runs().save(state)
        state = run_plan(plan, state, spawn=_subagent_spawn(self.ctx),
                         on_step=self._runs().save, deliver=_deliver)
        return self._result(state)

    def tool_respond(self, args, **_) -> dict:
        """Resume a paused run with an approval answer or a pending agent output."""
        from .convert import build_run_plan
        from .runner import StepError, resume_plan

        run_id = args.get("run_id") or ""
        node_id = args.get("node_id") or ""
        # A structured agent result wins over the plain string; either can be fed back.
        answer = args.get("structured")
        if answer is None:
            answer = args.get("answer")
        try:
            state = self._runs().load(run_id)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        pending = state.get("pending") or {}
        if pending.get("node_id") != node_id:
            return {"ok": False,
                    "error": f"run {run_id!r} is not waiting on {node_id!r}"}
        try:
            plan = build_run_plan(self._store().load(state["name"]))
            state = resume_plan(plan, state, answer, spawn=_subagent_spawn(self.ctx),
                                on_step=self._runs().save, deliver=_deliver)
        except (StepError, ValueError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}
        return self._result(state)

    @staticmethod
    def _result(state: dict) -> dict:
        return {
            "ok": state["status"] != "failed",
            "run_id": state["run_id"],
            "status": state["status"],
            "pending": state["pending"],
            "outputs": state["outputs"],
            "skipped": state["skipped"],
            "deliveries": state.get("deliveries", []),
            "error": state["error"],
        }
