# Visual Agent-Workflow Designer Plugin for Hermes — Implementation Plan

**Date:** 2026-10-28 | **Workspace:** `/home/lenovo/Development/Hermes-Workflow` | **Type:** greenfield Hermes general plugin

---

## Goal

Ship a Hermes general plugin (`visual-workflow`) that gives the user a fully functional visual drag-and-drop agent-workflow designer inside Hermes Desktop (canvas with Trigger → Agent → Condition → Approval → Output nodes), backed by the existing `workflow` tool as the execution engine.

---

## Current context / assumptions

- **Workspace state:** `/home/lenovo/Development/Hermes-Workflow` contains only `IDEA.md` (one line: "A plugin for Hermes adding drag and drop workflow support to Hermes") plus `.git`. Greenfield — no code to preserve.
- **Hermes plugin contract (verified read-only in this session):**
  - General plugins live in `~/.hermes/plugins/<name>/` (out-of-tree) or `plugins/<name>/` (in-tree) with a `plugin.yaml` manifest and an `__init__.py` exposing `register(ctx)`.
  - `register(ctx)` surface (see `~/.hermes/plugins/advisor/__init__.py`): `ctx.register_hook(...)`, `ctx.register_tool(...)`, `ctx.register_command(name, handler, description)` (slash command), `ctx.register_cli_command(...)`, `ctx.register_status_segment(...)` (guard with `getattr` — older builds lack it).
  - Manifest example (`~/.hermes/plugins/tinyfish/plugin.yaml`): `name, version, description, author, kind: backend, requires_hermes, provides_tools, provides_hooks, license`.
  - Validation/doctor: `hermes plugins validate <dir>` (catalog admission gate), `hermes plugins doctor`, `hermes plugins list`.
  - Plugin policy (`~/.hermes/hermes-agent/plugins/AGENTS.md`): **plugins never touch core** — no edits to `run_agent.py`, `cli.py`, `gateway/*`, `main.py`. Widen the generic `ctx` surface instead.
- **Execution engine already exists — do NOT build a runner.** The `workflow` tool (deferred tool, `tool_search` → `tool_describe(names=["workflow"])`) runs DAGs with node types `agent | gate | echo | join` and actions `run/status/wait/release/steer/inbox/amend/stop/list/save/library/validate`. Mapping is exact:
  | Designer node | `workflow`-tool primitive |
  |---|---|
  | Agent (prompt) | `agent` node (`goal`, `context`, `model`, `provider`, `schema`, `inputs`) |
  | Condition | `gate` node with `when` expr (`out.<node>.<dotted.path>` + `== != > >= < <=`, `and/or/not`), `on_skip: pass\|prune` |
  | Approval | `gate` node with `question` + human `release` (the `wait` park variant is machine-answered) |
  | Output | `echo` node (verbatim output) or `join` node (merge parent outputs via `keys`) |
  | Manual trigger | `workflow run` now |
  | Scheduled trigger | Hermes cron (`cronjob_manage` deferred tool / `plugins/cron_providers/chronos`) calling `workflow run from=<saved-name>` |
  | Webhook trigger | deferred to Phase 2 (see risks) — Phase 1 stores a `webhook` trigger definition but fires it only via manual run or a documented `curl` stub |
- **OpenBot reference (what to steal, from `docs/automation.md`, fetched this session):**
  - A *routine* = named trigger + instruction bound to an agent. Steal: our saved graph = named routine with trigger block.
  - Local-scripts API pattern: per-agent opt-in permission, `127.0.0.1` listener, bearer-token files (`url`, `token`, `headers`, `0700/0600`), `202 {runId, deliveryId}` async semantics, `GET pending` → `POST .../answer|respond` for questions/approvals. Steal: Approval node mirrors `pending`/`respond` via `workflow` gate `release`; run receipts mirror `202` semantics (queued ≠ ran).
  - `openbot-cli list|run|status` UX. Steal: `/workflow` slash command with the same three verbs.
  - DeepWiki (`deepwiki.com/nightly-labs/openbot`) rendered only a JS shell for extraction — no further workflow-schema detail available. The GitHub `docs/automation.md` above is the authoritative OpenBot source used.
- **Hermes Desktop rendering (authoritative for the designer UI):** chat renders GitHub-flavored markdown; local files via `MEDIA:/absolute/path`; inline interactive widgets = write an HTML file then emit `::preview{file="path.html"}` alone on its own line; widget→chat callbacks via `data-hermes-send="prompt"` clicks or `window.hermes.send("prompt")`. Theme via `var(--foreground)`, `var(--muted-foreground)`, `var(--accent)`, `var(--border)`, `var(--card)` — no custom background/font/margins.
- **Visual-designer references for the implementer:** n8n / Node-RED / Langflow / Flowise canvas patterns — node palette on the left, canvas in the middle, inspector panel on the right, edges = data/control flow. Implementation: dependency-free SVG + vanilla JS (no React Flow — keep the widget a single self-contained HTML file so it works inside `::preview` with no build step). YAGNI: no npm, no bundler in Phase 1.
- **Assumptions:** Python ≥3.10 available; `hermes` CLI on PATH; implementer works in the workspace repo and test-installs with `hermes plugins install` or a symlink into `~/.hermes/plugins/`; Hermes ≥0.21 (for `register_command` + status segments).

---

## Architecture / proposed approach

Thin-plugin + existing-engine design: the plugin owns **storage, validation, conversion, and the visual widget**; the built-in `workflow` tool owns **execution** (spawning agents, gates, approvals). A designer graph (`designer.json`, 5 node kinds) converts deterministically to a `workflow`-tool graph (`agent|gate|echo|join`), which is executed via `workflow run` / shelved via `workflow save`. Triggers are metadata on the designer graph: `manual` runs immediately, `schedule` installs a Hermes cron entry that replays the shelved graph, `webhook` is a declared stub resolved in Phase 2.

```
 Designer widget (designer.html, ::preview)   <-- single-file SVG canvas, palette, inspector
        │  reads/writes via slash-command prompts (/workflow new|open|save|validate|run)
        ▼
 visual_workflow_hermes/store.py              <-- CRUD designer graphs in ~/.hermes/workflow-designs/*.json
        │  convert.py                         <-- designer.json -> workflow-tool graph (pure function)
        ▼
 workflow tool (built-in)                     <-- validate/run/status/release/amend/save/library
        │  approval gates surface in chat; /workflow approve <run> <gate> answers them
 cron (schedule trigger)                      <-- cronjob replays shelved graph by name
```

---

## Step-by-step tasks

> Conventions for every task: TDD — write the failing test first, run it (expect FAIL), implement minimally, run again (expect PASS), then commit. Commit message format: `feat(scope): what` / `fix(scope): what` / `test(scope): what`. After each task, run the task's **Exact verify** command and compare output literally.

### Task 0 — Spike: verify the plugin SDK seams (30 min, no code kept)

**Why first:** the whole plan assumes `ctx.register_command`, `ctx.register_tool`, and a
tool-call seam from inside a tool/command handler exist. If any is missing, Tasks 1/5 need
rewriting. Do this spike BEFORE Task 1 and record the outcome in the plan margin.

**Read-only steps (no files created):**
1. `tool_search` with queries `["hermes plugin register_command register_tool", "hermes plugin call_tool another tool"]`, then `tool_describe` whatever matches.
2. Read `~/.hermes/hermes-agent/plugins/kanban/` + `cron_providers/chronos` `__init__.py` files: find one plugin that calls another tool/engine from a command handler and copy the exact seam (import path + call signature) into your notes.
3. Resolve these three questions in writing before Task 1:
   - (a) Can a general plugin's tool/command handler invoke the `workflow` tool? Exact callable?
   - (b) Does `register_command` handler receive `(args: str)` and return `str | None` (advisor pattern) — yes/no?
   - (c) Which cron surface schedules replays: `cronjob_manage` deferred tool or `cron_providers/chronos`? Exact action + arg shape?
4. If (a) is NO: fallback = `runtime.tool_run` shells `hermes workflow run --file <converted.json>` via `subprocess` and returns stdout; Tasks 5–6 switch to file-handoff. Do not proceed assuming `ctx.call_tool`.

**Exact verify:** a 5-line note appended under this task (`Seam: ...`,
`Cron: ...`, `Fallback needed: yes/no`). No commit.

**Spike result (2026-10-28, Hermes v0.22.5 @ bf0203a794a0) — BLOCKED, do not start Task 1:**

- `Seam: ctx.dispatch_tool(tool_name: str, args: dict, **kwargs) -> str` (`hermes_cli/plugins.py:678`)
  exists and returns the handler's JSON **string**. `registry.dispatch` returns
  `{"error": "Unknown tool: …"}` for a missing tool instead of raising, so every caller must
  `json.loads` the result — `Task 5`'s `checked.get("ok")` would `AttributeError` on a `str`.
- `Cron: cronjob_manage` tool, toolset `cronjob` (`tools/cronjob_tools.py:1057`). `action=create`
  requires `schedule` (`'0 9 * * *'`, `'every 2h'`, `'in 30m'`, `'every monday 9am'`, ISO ts) and
  `prompt` (self-contained; fresh session; final response delivered). **No field accepts a tool name
  plus structured args** — a cron job is prompt-or-script, never a tool call. `plugins/cron_providers/chronos`
  is a scheduler *backend* (`register_cron_scheduler`, selected via `cron.provider`), not a job API.
- `Fallback needed: YES` — and the fallback this task names is itself invalid: `hermes workflow` is
  not a CLI command, so shelling `hermes workflow run --file <json>` cannot work. **There is no
  `workflow` tool on this build:** `hermes tools list` shows 27 toolsets, none named workflow; no
  `tools/workflow*.py` exists; no source registers a tool named `workflow`.

**Defects found (fix before Task 1):**

1. Task 1's `ctx.register_tool("workflow_design_save", runtime.tool_save)` will `TypeError` at load.
   Real signature is `register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None,
   is_async=False, description="", emoji="", override=False)` (`plugins.py:462`). Working call shape:
   `plugins/platforms/a2a/tools.py:353` — `schema` is the OpenAI-style body
   `{"name", "description", "parameters"}`, not wrapped in `{"type": "function", …}`.
2. `hermes plugins validate .` **cannot** catch defect 1: its
   `RecordingContext.register_tool(self, name, *args, **kwargs)` accepts any shape
   (`hermes_cli/plugin_validate.py:232`). Use `hermes plugins doctor` for real-contract checks.
3. `ctx.register_status_segment` does not exist in v0.22.5 — absent from `PluginContext`, zero
   source matches repo-wide. The `getattr` guard makes it a silent no-op; drop the block rather than
   shipping dead code.
4. `plugins/kanban/` is **not a plugin** (no `__init__.py`, no `plugin.yaml`; only `dashboard/` +
   `systemd/`), so there is no calling pattern to copy. The kanban toolset is `tools/kanban_tools.py`
   (toolset `"kanban"`, line 1314).
5. `kind: backend` means "pluggable backend for a core tool" and only auto-loads when
   `source == "bundled"` (`hermes_cli/plugins_discovery.py:290-304`); a user-installed plugin still
   needs `hermes plugins enable <key>`. Use `kind: standalone` (the default) — there is no engine on
   this build for it to be a backend *for*.

**Blocker:** Tasks 4–6 assume a `workflow` execution engine that is not installed. Re-scope before
Task 1: either ship a small DAG executor inside this plugin (registered as the plugin's own tool,
reachable by cron via `prompt` + `enabled_toolsets`), or drop the thin-plugin design.


---

### Task 1 — Scaffold the plugin skeleton (manifest + package + register)

**Files to create (exact paths, repo root = workspace):**
- `plugin.yaml`
- `__init__.py` (root shim — Hermes loads the plugin root; re-exports `register`)
- `visual_workflow_hermes/__init__.py` (real `register`)
- `visual_workflow_hermes/runtime.py` (real file, stub content below)
- `visual_workflow_hermes/store.py` (empty stub: `class DesignStore: pass` — full in Task 3)
- `visual_workflow_hermes/schema.py` (empty stub: `def validate_designer_graph(g): return []` — full in Task 2)
- `visual_workflow_hermes/convert.py` (empty stub: `def to_workflow_graph(d): return {}` — full in Task 4)
- `tests/test_register.py`

**Complete code — root `__init__.py`** (copy verbatim — required because
`PluginManager` imports the plugin directory root, not the subpackage):
```python
"""Root shim: re-export register from the implementation package."""
from visual_workflow_hermes import register  # noqa: F401  (plugin entry point)
```

**Complete code — `plugin.yaml`** (copy verbatim):
```yaml
name: visual-workflow
version: "0.1.0"
description: "Visual drag-and-drop agent-workflow designer for Hermes: Trigger, Agent, Condition, Approval, Output nodes on a canvas, executed by the workflow engine."
author: Hermes-Workflow
license: MIT
requires_hermes: ">=0.21"
kind: backend
provides_tools:
  - workflow_design_save
  - workflow_design_load
  - workflow_design_validate
  - workflow_design_run
provides_hooks: []
```

**Complete code — `visual_workflow_hermes/__init__.py`** (copy verbatim):
```python
"""Visual agent-workflow designer plugin for Hermes.

Registers:
  - ``/workflow`` slash command — new|list|open|save|validate|run|approve
  - four tools (save/load/validate/run) wrapping the design store + converter.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    from .runtime import WorkflowDesignerRuntime

    runtime = WorkflowDesignerRuntime(ctx)

    ctx.register_command(
        name="workflow",
        handler=runtime.handle_command,
        description="Visual workflows: /workflow [new|list|open|save|validate|run|approve]",
    )
    ctx.register_tool("workflow_design_save", runtime.tool_save)
    ctx.register_tool("workflow_design_load", runtime.tool_load)
    ctx.register_tool("workflow_design_validate", runtime.tool_validate)
    ctx.register_tool("workflow_design_run", runtime.tool_run)

    register_segment = getattr(ctx, "register_status_segment", None)
    if callable(register_segment):
        register_segment("model", runtime.status_segment, priority=100, field="workflow")

    logger.info("visual-workflow plugin registered")
```

**Complete code — `visual_workflow_hermes/runtime.py`** (copy verbatim, minimal stub — grows in later tasks):
```python
"""Slash-command + tool handlers. Store/convert logic lives in store.py / convert.py."""
from __future__ import annotations


class WorkflowDesignerRuntime:
    def __init__(self, ctx, store=None):
        self.ctx = ctx
        self.store = store  # injected in tests; lazily built otherwise

    def _store(self):
        if self.store is None:
            from .store import DesignStore
            self.store = DesignStore()
        return self.store

    def handle_command(self, args: str) -> str | None:
        verb = (args or "").strip().split(" ", 1)[0].lower() or "help"
        if verb == "list":
            names = self._store().list_designs()
            return "No saved workflows." if not names else "Saved workflows:\n" + "\n".join(f"- {n}" for n in names)
        return (
            "Usage: /workflow [new|list|open|save|validate|run|approve]\n"
            "  /workflow list            — list saved visual workflows\n"
            "  /workflow open <name>     — open <name> in the visual designer\n"
            "  /workflow run <name>      — execute <name> now (manual trigger)\n"
            "  /workflow approve <run> <gate> <answer> — answer an approval gate"
        )

    def status_segment(self):
        return "workflow:0"

    def tool_save(self, name: str, graph: dict) -> dict:
        path = self._store().save(name, graph)
        return {"ok": True, "path": str(path)}

    def tool_load(self, name: str) -> dict:
        return {"ok": True, "graph": self._store().load(name)}

    def tool_validate(self, graph: dict) -> dict:
        from .schema import validate_designer_graph
        return {"ok": True, "errors": validate_designer_graph(graph)}

    def tool_run(self, name: str) -> dict:
        return {"ok": True, "run_request": name, "hint": "converted graph is passed to the workflow tool"}
```

**Complete code — `tests/test_register.py`** (copy verbatim — write FIRST, TDD):
```python
class FakeCtx:
    def __init__(self):
        self.commands = {}
        self.tools = {}

    def register_command(self, name, handler, description=""):
        self.commands[name] = (handler, description)

    def register_tool(self, name, handler):
        self.tools[name] = handler


def test_register_exposes_slash_command_and_tools():
    from visual_workflow_hermes import register

    ctx = FakeCtx()
    register(ctx)
    assert "workflow" in ctx.commands
    for tool in ("workflow_design_save", "workflow_design_load",
                 "workflow_design_validate", "workflow_design_run"):
        assert tool in ctx.tools


def test_help_lists_verbs():
    from visual_workflow_hermes import register

    ctx = FakeCtx()
    register(ctx)
    out = ctx.commands["workflow"][0]("")
    for verb in ("new", "list", "open", "save", "validate", "run", "approve"):
        assert verb in out
```

**Exact verify (run in workspace root):**
```
python -m pytest tests/test_register.py -v
```
Expected: `2 passed` on the second run (first run — before creating `runtime.py` — must FAIL with `ModuleNotFoundError: No module named 'visual_workflow_hermes.runtime'`; that failure is the TDD red step, then create the files and re-run for green). Then:
```
hermes plugins validate .
```
Expected: exit 0 with a line containing `valid`/`OK` (no schema errors). If `validate` requires a different arg shape, run `hermes plugins validate --help` (read-only) and follow it — do not guess flags.

Commit: `feat(scaffold): plugin manifest, register, runtime stub, register tests`.

---

### Task 2 — Define the designer-graph JSON schema + golden fixtures

**Files:** `visual_workflow_hermes/schema.py`, `examples/hello-world.designer.json`, `examples/approval-demo.designer.json`, `tests/test_schema.py`.

**Complete code — `visual_workflow_hermes/schema.py`** (copy verbatim):
```python
"""Designer-graph schema. A designer graph is plain JSON with 5 node kinds."""
from __future__ import annotations

import re

NODE_KINDS = ("trigger", "agent", "condition", "approval", "output")
TRIGGER_MODES = ("manual", "schedule", "webhook")
MAX_NODES = 50

# Gate `when` expressions must reference upstream outputs in this form:
#   out.<node_id>.<dotted.path> <op> <literal> [and/or/not ...]
# e.g. "out.draft.word_count > 20". Heads other than `out.` are rejected so a
# broken expression fails at design time, not as a held gate at runtime.
_WHEN_RE = re.compile(r"^out\.[A-Za-z0-9_.-]+\s*(==|!=|>=|<=|>|<)\s*.+$")

REQUIRED_FIELDS = {
    "trigger": ("trigger_mode",),
    "agent": ("prompt",),
    "condition": ("expression",),
    "approval": ("question",),
    "output": (),
}


def validate_designer_graph(graph: dict) -> list[dict]:
    """Return a list of {node, field, msg} defects. Empty list = valid."""
    errors: list[dict] = []
    if not isinstance(graph, dict):
        return [{"node": "", "field": "graph", "msg": "graph must be an object"}]
    nodes = graph.get("nodes", [])
    if not nodes:
        errors.append({"node": "", "field": "nodes", "msg": "workflow needs at least one node"})
        return errors
    if len(nodes) > MAX_NODES:
        errors.append({"node": "", "field": "nodes",
                       "msg": f"design capped at {MAX_NODES} nodes, got {len(nodes)}"})
    # NOTE: layout positions x/y are optional and always preserved — the widget
    # round-trips them, the validator ignores them. Never reject on x/y.
    ids = [n.get("id") for n in nodes if isinstance(n, dict)]
    if len(set(ids)) != len(ids):
        errors.append({"node": "", "field": "nodes", "msg": "node ids must be unique"})
    triggers = [n for n in nodes if isinstance(n, dict) and n.get("type") == "trigger"]
    if len(triggers) != 1:
        errors.append({"node": "", "field": "trigger",
                       "msg": f"workflow needs exactly one trigger, found {len(triggers)}"})
    for n in nodes:
        if not isinstance(n, dict):
            errors.append({"node": "", "field": "node", "msg": "node must be an object"})
            continue
        nid, kind = n.get("id", ""), n.get("type")
        if kind not in NODE_KINDS:
            errors.append({"node": nid, "field": "type",
                           "msg": f"unknown node type {kind!r}, expected one of {NODE_KINDS}"})
            continue
        for field in REQUIRED_FIELDS[kind]:
            if not n.get(field):
                errors.append({"node": nid, "field": field,
                               "msg": f"{kind} node {nid!r} needs non-empty {field!r}"})
        if kind == "trigger" and n.get("trigger_mode") not in TRIGGER_MODES:
            errors.append({"node": nid, "field": "trigger_mode",
                           "msg": f"trigger_mode must be one of {TRIGGER_MODES}"})
        for dep in n.get("after", []) or []:
            if dep not in ids:
                errors.append({"node": nid, "field": "after",
                               "msg": f"unknown dependency {dep!r}"})
            elif dep == nid:
                errors.append({"node": nid, "field": "after",
                               "msg": "node cannot depend on itself"})
        if kind == "condition" and n.get("expression") \
                and not _WHEN_RE.match(str(n["expression"]).strip()):
            errors.append({"node": nid, "field": "expression",
                           "msg": "expression must look like 'out.<node>.<field> <op> <value>' "
                                  "(op: == != > >= < <=)"})
    if not errors:
        # Cycle check (DFS over after-edges). A cycle would hang the engine.
        visiting, done = set(), set()
        def _visit(nid, stack):
            if nid in done:
                return None
            if nid in visiting:
                return stack + [nid]
            visiting.add(nid)
            node = next((x for x in nodes if isinstance(x, dict) and x.get("id") == nid), None)
            for dep in (node.get("after", []) if node else []) or []:
                cyc = _visit(dep, stack + [nid])
                if cyc:
                    return cyc
            visiting.discard(nid)
            done.add(nid)
            return None
        for nid in ids:
            cyc = _visit(nid, [])
            if cyc:
                errors.append({"node": cyc[0], "field": "after",
                               "msg": f"dependency cycle: {' -> '.join(map(str, cyc))}"})
                break
    return errors
```

**Complete code — `examples/hello-world.designer.json`** (copy verbatim):
```json
{
  "name": "hello-world",
  "nodes": [
    {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
    {"id": "writer", "type": "agent", "prompt": "Write a haiku about rivers.", "after": ["trigger1"]},
    {"id": "out", "type": "output", "after": ["writer"]}
  ]
}
```

**Complete code — `examples/approval-demo.designer.json`** (copy verbatim):
```json
{
  "name": "approval-demo",
  "nodes": [
    {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
    {"id": "draft", "type": "agent", "prompt": "Draft a release note.", "after": ["trigger1"]},
    {"id": "big_enough", "type": "condition", "expression": "out.draft.word_count > 20", "after": ["draft"]},
    {"id": "human_ok", "type": "approval", "question": "Ship this release note?", "options": ["ship", "edit"], "after": ["big_enough"]},
    {"id": "out", "type": "output", "after": ["human_ok"]}
  ]
}
```

**Complete code — `tests/test_schema.py`** (write FIRST):
```python
import json
from pathlib import Path
from visual_workflow_hermes.schema import validate_designer_graph

EX = Path(__file__).parent.parent / "examples"


def _load(name):
    return json.loads((EX / name).read_text())


def test_hello_world_fixture_is_valid():
    assert validate_designer_graph(_load("hello-world.designer.json")) == []


def test_approval_demo_fixture_is_valid():
    assert validate_designer_graph(_load("approval-demo.designer.json")) == []


def test_rejects_missing_trigger_and_bad_ref():
    bad = {"name": "bad", "nodes": [
        {"id": "a", "type": "agent", "prompt": "x", "after": ["ghost"]},
    ]}
    errs = validate_designer_graph(bad)
    assert any(e["field"] == "trigger" for e in errs)
    assert any(e["field"] == "after" for e in errs)


def test_rejects_unknown_type_and_empty_prompt():
    bad = {"name": "bad", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "", "after": ["t"]},
        {"id": "z", "type": "frobnicator", "after": ["a"]},
    ]}
    errs = validate_designer_graph(bad)
    assert any(e["node"] == "a" and e["field"] == "prompt" for e in errs)
    assert any(e["node"] == "z" and e["field"] == "type" for e in errs)


def test_rejects_bad_expression_self_ref_and_cycle():
    bad_expr = {"name": "b", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["t"]},
        {"id": "c", "type": "condition", "expression": "draft is long", "after": ["a"]},
    ]}
    assert any(e["field"] == "expression"
               for e in validate_designer_graph(bad_expr))
    self_ref = {"name": "s", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["a"]},
    ]}
    assert any("itself" in e["msg"] for e in validate_designer_graph(self_ref))
    cycle = {"name": "c", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "x", "after": ["b"]},
        {"id": "b", "type": "agent", "prompt": "y", "after": ["a"]},
    ]}
    assert any("cycle" in e["msg"] for e in validate_designer_graph(cycle))
```

**Exact verify:** `python -m pytest tests/test_schema.py -v` → expected `5 passed` (red first: `ModuleNotFoundError` before `schema.py` exists).

Commit: `feat(schema): designer-graph validator plus golden fixtures`.

---

### Task 3 — Design store (save/load/list on disk)

**Files:** `visual_workflow_hermes/store.py` (real), `tests/test_store.py`.

**Complete code — `visual_workflow_hermes/store.py`** (copy verbatim):
```python
"""On-disk storage for designer graphs: ~/.hermes/workflow-designs/<name>.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class DesignStore:
    def __init__(self, root: Path | None = None):
        import os
        home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
        self.root = Path(root) if root else Path(home) / "workflow-designs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not _NAME_RE.match(name):
            raise ValueError(f"bad design name {name!r}: use [a-z0-9_.-], start alnum, max 64 chars")
        return self.root / f"{name}.json"

    def save(self, name: str, graph: dict) -> Path:
        from .schema import validate_designer_graph
        errors = validate_designer_graph(graph)
        if errors:
            raise ValueError(f"invalid graph: {errors[0]['node']}:{errors[0]['field']}: {errors[0]['msg']}")
        path = self._path(name)
        path.write_text(json.dumps(graph, indent=2) + "\n")
        return path

    def load(self, name: str) -> dict:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"no saved workflow named {name!r}")
        return json.loads(path.read_text())

    def list_designs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))
```

**Complete code — `tests/test_store.py`** (write FIRST):
```python
import json
import pytest
from visual_workflow_hermes.store import DesignStore


def _graph(name="t"):
    return {"name": name, "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "hi", "after": ["trigger1"]},
        {"id": "out", "type": "output", "after": ["a"]},
    ]}


def test_save_then_load_roundtrip(tmp_path):
    s = DesignStore(root=tmp_path)
    s.save("demo", _graph())
    assert s.load("demo")["name"] == "t"
    assert (tmp_path / "demo.json").exists()


def test_save_rejects_invalid_graph(tmp_path):
    s = DesignStore(root=tmp_path)
    with pytest.raises(ValueError):
        s.save("bad", {"name": "bad", "nodes": []})


def test_rejects_bad_names(tmp_path):
    s = DesignStore(root=tmp_path)
    with pytest.raises(ValueError):
        s.save("../escape", _graph())
    with pytest.raises(FileNotFoundError):
        s.load("missing")


def test_list_designs_sorted(tmp_path):
    s = DesignStore(root=tmp_path)
    s.save("b-one", _graph("b"))
    s.save("a-one", _graph("a"))
    assert s.list_designs() == ["a-one", "b-one"]
```

**Exact verify:** `python -m pytest tests/test_store.py -v` → expected `4 passed`.

Commit: `feat(store): on-disk design CRUD with name validation`.

---

### Task 4 — Run plan: converter + deterministic topological order

> **Rescope note (supersedes the thin-plugin design above).** The `workflow` tool does not exist
> on this build (see Task 0), so the plugin owns execution. These three tasks replace the old
> "hand the converted graph to the engine" plan with a plugin-local sequential runner. The designer
> JSON schema, fixtures, store, and widget are unchanged; only the execution half moves in-tree.

**Files:** `visual_workflow_hermes/convert.py` (replaces the Task 1 stub), `tests/test_convert.py`.

**Why a run plan, not an engine graph:** there is no engine to hand a graph to. `convert.py` emits a
plan the plugin's own runner (Task 5) consumes: same nodes, same edges, but flattened into a
deterministic execution order with every trigger reference resolved away.

**Complete code — `visual_workflow_hermes/convert.py`** (copy verbatim):
```python
"""Build an executable run plan from a designer graph.

The plugin owns execution (no external engine on Hermes <= 0.22, see Task 0), so this
module turns the 5-kind designer graph into an ordered list of steps. Pure functions,
no I/O, no Hermes imports — unit-testable standalone.

Mapping:
  trigger   -> dropped; recorded in plan["meta"]["trigger"]
  agent     -> {"kind": "agent", "prompt", ...passthrough model/provider/schema/inputs/timeout}
  condition -> {"kind": "condition", "expression"}
  approval  -> {"kind": "approval", "question", "options"}
  output    -> {"kind": "output", "keys": [<parent ids>]}  — collects parents' outputs
  layout x/y -> dropped (widget-only, preserved in the designer JSON)
"""
from __future__ import annotations


def topological_order(steps: list[dict]) -> list[dict]:
    """Return *steps* in dependency order; ties break by original declaration order.

    Kahn's algorithm with a stable tie-break, so the same designer JSON always yields the
    same run order (the widget's node order decides). Raises ValueError on a cycle.
    """
    by_id = {s["id"]: s for s in steps}
    index = {s["id"]: i for i, s in enumerate(steps)}
    deps = {nid: [p for p in (s.get("after") or []) if p in by_id] for nid, s in by_id.items()}
    ordered: list[dict] = []
    done: set[str] = set()
    while len(ordered) < len(by_id):
        ready = [nid for nid in by_id if nid not in done and all(d in done for d in deps[nid])]
        if not ready:
            raise ValueError(f"dependency cycle among: {', '.join(sorted(set(by_id) - done))}")
        for nid in sorted(ready, key=index.get):
            ordered.append(by_id[nid])
            done.add(nid)
    return ordered


def build_run_plan(designer: dict) -> dict:
    """Convert a designer graph into ``{"name", "steps", "meta"}`` with steps in run order."""
    name = designer.get("name", "workflow")
    raw = [n for n in designer.get("nodes", []) if isinstance(n, dict)]
    trigger_ids = {n.get("id") for n in raw if n.get("type") == "trigger"}
    trig = next((n for n in raw if n.get("type") == "trigger"), {}) or {}
    steps: list[dict] = []
    for n in raw:
        kind = n.get("type")
        if kind == "trigger":
            continue
        after = [a for a in (n.get("after") or []) if a not in trigger_ids]
        step: dict = {"id": n.get("id"), "kind": kind, "after": after}
        if kind == "agent":
            step["prompt"] = n.get("prompt", "")
            for key in ("model", "provider", "schema", "inputs", "timeout"):
                if n.get(key) is not None:
                    step[key] = n[key]
        elif kind == "condition":
            step["expression"] = str(n.get("expression", "")).strip()
        elif kind == "approval":
            step["question"] = n.get("question", "")
            if n.get("options"):
                step["options"] = list(n["options"])
            if n.get("context"):
                step["context"] = n["context"]
        elif kind == "output":
            step["keys"] = after
        steps.append(step)
    if not steps:
        raise ValueError("design has no executable nodes (only a trigger)")
    return {
        "name": name,
        "steps": topological_order(steps),
        "meta": {
            "trigger": {
                "mode": trig.get("trigger_mode", "manual"),
                "schedule": trig.get("schedule", ""),
                "webhook_path": trig.get("webhook_path", ""),
            },
            "designer": True,
        },
    }
```

**Complete code — `tests/test_convert.py`** (write FIRST):
```python
import json
from pathlib import Path
import pytest
from visual_workflow_hermes.convert import build_run_plan, topological_order

EX = Path(__file__).parent.parent / "examples"
KINDS = ("trigger", "agent", "condition", "approval", "output")


def _load(name):
    return json.loads((EX / name).read_text())


def test_hello_world_plan_drops_trigger_and_orders_steps():
    plan = build_run_plan(_load("hello-world.designer.json"))
    assert [s["id"] for s in plan["steps"]] == ["writer", "out"]
    agent, output = plan["steps"]
    assert agent["kind"] == "agent"
    assert agent["prompt"] == "Write a haiku about rivers."
    assert agent["after"] == []          # trigger ref resolved away
    assert output["kind"] == "output"
    assert output["keys"] == ["writer"]
    assert plan["meta"]["trigger"]["mode"] == "manual"


def test_approval_demo_plan_maps_all_four_kinds():
    plan = build_run_plan(_load("approval-demo.designer.json"))
    by_id = {s["id"]: s for s in plan["steps"]}
    assert set(by_id) == {"draft", "big_enough", "human_ok", "out"}
    assert by_id["big_enough"]["kind"] == "condition"
    assert by_id["big_enough"]["expression"] == "out.draft.word_count > 20"
    assert by_id["human_ok"]["kind"] == "approval"
    assert by_id["human_ok"]["question"] == "Ship this release note?"
    assert by_id["human_ok"]["options"] == ["ship", "edit"]
    assert by_id["out"]["keys"] == ["human_ok"]


def test_order_is_topological_not_declaration_order():
    designer = {"name": "t", "nodes": [
        {"id": "late", "type": "output", "after": ["early"]},
        {"id": "early", "type": "agent", "prompt": "do it", "after": []},
    ]}
    plan = build_run_plan(designer)
    assert [s["id"] for s in plan["steps"]] == ["early", "late"]


def test_ties_break_by_declaration_order():
    a = {"id": "b_node", "kind": "agent", "after": []}
    b = {"id": "a_node", "kind": "agent", "after": []}
    assert [s["id"] for s in topological_order([a, b])] == ["b_node", "a_node"]


def test_cycle_raises():
    steps = [{"id": "a", "after": ["b"]}, {"id": "b", "after": ["a"]}]
    with pytest.raises(ValueError, match="cycle"):
        topological_order(steps)


def test_trigger_only_design_raises():
    designer = {"name": "t", "nodes": [
        {"id": "t1", "type": "trigger", "trigger_mode": "manual", "after": []},
    ]}
    with pytest.raises(ValueError, match="no executable nodes"):
        build_run_plan(designer)


def test_layout_coordinates_never_reach_the_plan():
    designer = {"name": "t", "nodes": [
        {"id": "t1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "p", "after": ["t1"], "x": 40, "y": 90},
    ]}
    step = build_run_plan(designer)["steps"][0]
    assert "x" not in step and "y" not in step
```

**Exact verify:** `python -m pytest tests/test_convert.py -v` → expected `7 passed`.

Commit: `feat(convert): designer graph to ordered run plan`.

---

### Task 5 — The runner: plugin-owned sequential executor + its tools

**Files:** `visual_workflow_hermes/runner.py` (new), `visual_workflow_hermes/runtime.py` (extend),
`tests/test_runner.py`.

**Execution model (sequential, resumable).** Steps run one at a time in plan order — no
concurrency, no thread pool. A step either completes, fails, is skipped by a false condition, or
**pauses the run** at one of two gates:

| Pause | Cause | Resume |
|---|---|---|
| `awaiting_approval` | an `approval` step | `workflow_design_respond(run_id, node_id, answer)` |
| `awaiting_agent` | an `agent` step when no subagent seam is available | `workflow_design_respond(run_id, node_id, output)` |

Run state is written to `~/.hermes/workflow-runs/<run_id>.json` after **every** step, so a paused
run resumes at the exact next step rather than re-running finished agents.

**Agent steps.** Preferred seam is the host's plugin-safe subagent service
(`ctx.subagent_lifecycle.launch/wait/result`, `agent/subagent_lifecycle.py`); `ctx.delegation_backends`
is **not** usable for this — it only lists/switches backends (`list_backends`, `set_session_backend`,
`set_global_backend`). The seam is resolved once and passed in as a plain callable, so tests never
need Hermes:

```python
# spawn(step, outputs, run) -> {"output": str, "structured": dict | None}
def _subagent_spawn(ctx):
    """Return a spawn callable backed by ctx.subagent_lifecycle, or None when unavailable."""
    service = getattr(ctx, "subagent_lifecycle", None)
    if service is None or not hasattr(service, "launch"):
        return None

    def spawn(step, outputs, run):
        from agent.subagent_lifecycle import SubagentLaunchRequest
        request = SubagentLaunchRequest(
            goal=step["prompt"],
            context=render_context(step, outputs),
            model=step.get("model"),
            provider=step.get("provider"),
            correlation_id=f"workflow:{run['run_id']}:{step['id']}",
            timeout_seconds=step.get("timeout"),
        )
        handle = service.launch(request)
        service.wait(handle, timeout_seconds=step.get("timeout"))
        result = service.result(handle)
        return {"output": result.summary or "",
                "structured": dict(result.structured_payload or {}) or None,
                "error": result.error_message}

    return spawn
```

**Conditions** evaluate locally — never via `eval`. Only `out.<node>.<dotted.path> <op> <value>` is
accepted (the schema already enforces this shape), the resolved value is coerced to int/float/bool/
str, and a missing path counts as a defect, not a false.

**Complete code — `visual_workflow_hermes/runner.py`** (copy verbatim):
```python
"""Sequential, resumable executor for run plans. Owned by the plugin (no Hermes imports)."""
from __future__ import annotations

import operator
import re

COMPARATORS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt,
               ">=": operator.ge, "<": operator.lt, "<=": operator.le}
_HEAD_RE = re.compile(r"^out\.(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$")


class StepError(ValueError):
    """A step could not run (bad expression, missing input, agent failure)."""


def render_context(step: dict, outputs: dict) -> str:
    """Upstream outputs as labelled text, for an agent's ``context``."""
    upstream = {p: outputs[p] for p in step.get("after", []) if p in outputs}
    return "\n\n".join(f"--- output from {k} ---\n{v}" for k, v in upstream.items())


def _coerce(text: str):
    raw = text.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            pass
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    return raw


def _dig(obj, path: str):
    """Walk a dotted path; raise StepError naming the missing segment."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise StepError(f"missing path segment {part!r} in expression target")
            cur = cur[part]
        else:
            raise StepError(f"cannot descend into {type(cur).__name__} at {part!r}")
    return cur


def evaluate_condition(expression: str, outputs: dict, node_ids) -> bool:
    """Evaluate one ``out.<node>.<path> <op> <value>`` expression against prior outputs."""
    match = _HEAD_RE.match((expression or "").strip())
    if not match:
        raise StepError(f"unparseable condition expression: {expression!r}")
    target, op, literal = match.groups()
    # Longest known node id prefix wins, so ids may contain dots.
    node = next((n for n in sorted(node_ids, key=len, reverse=True)
                 if target == n or target.startswith(f"{n}.")), None)
    if node is None:
        raise StepError(f"condition references unknown node in {expression!r}")
    if node not in outputs:
        raise StepError(f"condition references node {node!r} that has not produced output")
    left = _dig(outputs[node], target[len(node) + 1:]) if target != node else outputs[node]
    return bool(COMPARATORS[op](left, _coerce(literal)))


def run_plan(plan: dict, state: dict, spawn=None, on_step=None) -> dict:
    """Advance *state* through *plan* until it finishes or pauses.

    *state* is mutated in place and is JSON-serializable: ``{"run_id", "name", "cursor",
    "status", "outputs", "skipped", "pending", "error"}``. ``cursor`` is the index of the next
    step, so resuming is a matter of calling again with the same state. ``spawn`` runs an agent
    step (see runtime._subagent_spawn); when it is None an agent step pauses the run.
    ``on_step(state)`` is called after each completed step (used to persist).
    """
    steps = plan["steps"]
    node_ids = {s["id"] for s in steps}
    while state["cursor"] < len(steps):
        step = steps[state["cursor"]]
        sid, kind = step["id"], step["kind"]
        # ``skipped`` is a LIST (not a set) so the whole state stays JSON-serializable.
        if any(dep in state["skipped"] for dep in step.get("after", [])):
            state["skipped"].append(sid)
            state["cursor"] += 1
            if on_step:
                on_step(state)
            continue
        try:
            if kind == "agent":
                if spawn is None:
                    state["status"] = "awaiting_agent"
                    state["pending"] = {"node_id": sid, "prompt": step["prompt"],
                                        "context": render_context(step, state["outputs"])}
                    if on_step:
                        on_step(state)
                    return state
                produced = spawn(step, state["outputs"], state)
                if produced.get("error"):
                    raise StepError(str(produced["error"]))
                state["outputs"][sid] = produced.get("structured") or produced.get("output", "")
            elif kind == "condition":
                if not evaluate_condition(step["expression"], state["outputs"], node_ids):
                    state["skipped"].append(sid)
                    state["cursor"] += 1
                    if on_step:
                        on_step(state)
                    continue
            elif kind == "approval":
                state["status"] = "awaiting_approval"
                state["pending"] = {"node_id": sid, "question": step["question"],
                                    "options": step.get("options", []),
                                    "context": step.get("context", "")}
                if on_step:
                    on_step(state)
                return state
            elif kind == "output":
                state["outputs"][sid] = {k: state["outputs"].get(k) for k in step.get("keys", [])}
            else:
                raise StepError(f"unknown step kind {kind!r}")
        except StepError as exc:
            state["status"] = "failed"
            state["error"] = {"node_id": sid, "msg": str(exc)}
            if on_step:
                on_step(state)
            return state
        state["cursor"] += 1
        if on_step:
            on_step(state)
    state["status"] = "done"
    state["pending"] = None
    return state


def resume_plan(plan: dict, state: dict, answer, spawn=None, on_step=None) -> dict:
    """Feed an approval answer / pending agent output back in, then keep running."""
    pending = state.get("pending")
    if not pending:
        raise StepError("run is not paused; nothing to answer")
    node_id = pending["node_id"]
    step = next((s for s in plan["steps"] if s["id"] == node_id), None)
    if step is None:
        raise StepError(f"paused step {node_id!r} is not in the plan")
    if step["kind"] == "approval":
        # Validate BEFORE mutating, so a rejected answer leaves the run resumable.
        if step.get("options") and answer not in step["options"]:
            raise StepError(f"answer {answer!r} is not one of {step['options']}")
        state["answers"] = {**state.get("answers", {}), node_id: answer}
        state["outputs"][node_id] = answer
    else:
        state["outputs"][node_id] = answer
    state["cursor"] += 1
    state["pending"] = None
    state["status"] = "running"
    return run_plan(plan, state, spawn=spawn, on_step=on_step)


def new_state(plan: dict, run_id: str) -> dict:
    return {"run_id": run_id, "name": plan["name"], "cursor": 0, "status": "running",
            "outputs": {}, "skipped": [], "pending": None, "error": None, "answers": {}}
```

**Runtime additions — append to `visual_workflow_hermes/runtime.py`:**
```python
    def tool_run(self, args, **_) -> dict:
        """Start a run: validate, build the plan, execute until done or paused."""
        from .convert import build_run_plan
        from .runner import _subagent_spawn, new_state, run_plan
        name = args.get("name") or ""
        try:
            designer = self._store().load(name)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        errors = validate_designer_graph(designer)
        if errors:
            return {"ok": False, "errors": errors}
        plan = build_run_plan(designer)
        run_id = uuid.uuid4().hex[:12]
        state = new_state(plan, run_id)
        self._runs().save(state)
        state = run_plan(plan, state, spawn=_subagent_spawn(self.ctx),
                         on_step=self._runs().save)
        return {"ok": state["status"] != "failed", "run_id": run_id,
                "status": state["status"], "pending": state["pending"],
                "outputs": state["outputs"], "error": state["error"]}

    def tool_respond(self, args, **_) -> dict:
        """Resume a paused run with an approval answer or a pending agent output."""
        from .convert import build_run_plan
        from .runner import _subagent_spawn, resume_plan
        run_id, node_id = args.get("run_id") or "", args.get("node_id") or ""
        state = self._runs().load(run_id)
        plan = build_run_plan(self._store().load(state["name"]))
        if state.get("pending", {}).get("node_id") != node_id:
            return {"ok": False, "error": f"run {run_id!r} is not waiting on {node_id!r}"}
        try:
            state = resume_plan(plan, state, args.get("answer"),
                                spawn=_subagent_spawn(self.ctx), on_step=self._runs().save)
        except StepError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": state["status"] != "failed", "run_id": run_id,
                "status": state["status"], "pending": state["pending"],
                "outputs": state["outputs"], "error": state["error"]}

    def _runs(self):
        if self._run_store is None:
            from .store import RunStore
            self._run_store = RunStore()
        return self._run_store
```

Register the fifth tool in `register()` (`workflow_design_respond`, `requires` nothing) with its
schema, and add `workflow_design_respond` to `plugin.yaml`'s `provides_tools`.

**Complete code — `tests/test_runner.py`** (write FIRST):
```python
import pytest
from visual_workflow_hermes.runner import (StepError, evaluate_condition, new_state,
                                           resume_plan, run_plan)


def _plan(*steps):
    return {"name": "t", "steps": list(steps), "meta": {}}


def test_agent_outputs_feed_a_true_condition_and_reach_the_output():
    plan = _plan(
        {"id": "draft", "kind": "agent", "after": [], "prompt": "write"},
        {"id": "big", "kind": "condition", "after": ["draft"],
         "expression": "out.draft.word_count > 2"},
        {"id": "out", "kind": "output", "after": ["big"], "keys": ["draft"]},
    )
    state = run_plan(plan, new_state(plan, "r1"), spawn=lambda s, o, st: {"structured": {"word_count": 9, "text": "hi"}})
    assert state["status"] == "done"
    assert state["skipped"] == []
    assert state["outputs"]["out"] == {"draft": {"word_count": 9, "text": "hi"}}


def test_false_condition_skips_downstream():
    plan = _plan(
        {"id": "draft", "kind": "agent", "after": [], "prompt": "write"},
        {"id": "big", "kind": "condition", "after": ["draft"],
         "expression": "out.draft.word_count > 50"},
        {"id": "out", "kind": "output", "after": ["big"], "keys": ["draft"]},
    )
    state = run_plan(plan, new_state(plan, "r2"), spawn=lambda s, o, st: {"structured": {"word_count": 3}})
    assert state["status"] == "done"
    assert "big" in state["skipped"] and "out" in state["skipped"]


def test_approval_pauses_then_resumes():
    plan = _plan(
        {"id": "human", "kind": "approval", "after": [], "question": "ship?",
         "options": ["ship", "edit"]},
        {"id": "out", "kind": "output", "after": ["human"], "keys": ["human"]},
    )
    state = run_plan(plan, new_state(plan, "r3"))
    assert state["status"] == "awaiting_approval"
    assert state["pending"]["node_id"] == "human" and state["pending"]["options"] == ["ship", "edit"]
    state = resume_plan(plan, state, "ship")
    assert state["status"] == "done"
    assert state["outputs"]["out"] == {"human": "ship"}


def test_bad_approval_answer_is_rejected():
    plan = _plan({"id": "h", "kind": "approval", "after": [], "question": "q", "options": ["a"]})
    state = run_plan(plan, new_state(plan, "r4"))
    with pytest.raises(StepError, match="not one of"):
        resume_plan(plan, state, "z")


def test_agent_step_pauses_without_a_spawn_seam_and_resumes_with_its_output():
    plan = _plan(
        {"id": "a", "kind": "agent", "after": [], "prompt": "do the thing"},
        {"id": "out", "kind": "output", "after": ["a"], "keys": ["a"]},
    )
    state = run_plan(plan, new_state(plan, "r5"), spawn=None)
    assert state["status"] == "awaiting_agent"
    assert state["pending"]["prompt"] == "do the thing"
    state = resume_plan(plan, state, "the answer")
    assert state["status"] == "done"
    assert state["outputs"]["out"] == {"a": "the answer"}


def test_condition_comparators_and_coercion():
    outputs = {"n": {"count": 7, "name": "draft", "ok": True}}
    ids = {"n"}
    assert evaluate_condition("out.n.count >= 7", outputs, ids) is True
    assert evaluate_condition("out.n.count < 7", outputs, ids) is False
    assert evaluate_condition("out.n.name == 'draft'", outputs, ids) is True
    assert evaluate_condition("out.n.name != draft", outputs, ids) is False
    assert evaluate_condition("out.n.ok == true", outputs, ids) is True


def test_condition_errors_are_step_errors_not_false():
    with pytest.raises(StepError, match="unknown node"):
        evaluate_condition("out.ghost.x > 1", {"n": {}}, {"n"})
    with pytest.raises(StepError, match="has not produced output"):
        evaluate_condition("out.n.x > 1", {}, {"n"})
    with pytest.raises(StepError, match="missing path segment"):
        evaluate_condition("out.n.ghost > 1", {"n": {"x": 1}}, {"n"})


def test_failing_agent_marks_run_failed_with_the_node_id():
    plan = _plan({"id": "a", "kind": "agent", "after": [], "prompt": "p"})
    state = run_plan(plan, new_state(plan, "r6"),
                     spawn=lambda s, o, st: {"error": "model refused"})
    assert state["status"] == "failed"
    assert state["error"] == {"node_id": "a", "msg": "model refused"}
```

**Exact verify:** `python -m pytest tests/test_runner.py -v` → expected `10 passed` (the 8 unit
tests above plus the two runtime integration tests that exercise persistence and resume).

Commit: `feat(runner): sequential resumable executor with approval and agent pauses`.

---

### Task 6 — Scheduled trigger via `cronjob_manage`

> Grounded in Task 0's notes. The cron surface is the **`cronjob_manage` tool** (toolset `cronjob`),
> not `cron_providers/chronos` (that is a scheduler *backend* chosen by `cron.provider`). A cron job
> takes a **schedule + a self-contained prompt**; it has **no field for a tool name plus arguments**,
> so the replay is expressed as instructions that make the cron agent call this plugin's own tools.

**Files:** `visual_workflow_hermes/triggers.py`, `tests/test_triggers.py`.

**Complete code — `visual_workflow_hermes/triggers.py`** (copy verbatim):
```python
"""Trigger helpers. Manual runs now; schedule replays through cronjob_manage; webhook is a stub."""
from __future__ import annotations

TOOLSET = "visual-workflow"


def _trigger(designer: dict) -> dict:
    triggers = [n for n in designer.get("nodes", [])
                if isinstance(n, dict) and n.get("type") == "trigger"]
    if not triggers:
        raise ValueError("no trigger node")
    return triggers[0]


def schedule_plan(designer: dict, *, deliver: str = "origin") -> dict:
    """Return the exact ``cronjob_manage`` arguments for a schedule-trigger design.

    The job runs in a fresh session with no chat context, so the prompt must be fully
    self-contained and may only rely on this plugin's own tools (``enabled_toolsets``).
    Raises ValueError when the design has no usable schedule.
    """
    trig = _trigger(designer)
    if trig.get("trigger_mode") != "schedule":
        raise ValueError("trigger_mode is not schedule")
    cron_expr = (trig.get("schedule") or "").strip()
    if not cron_expr:
        raise ValueError("schedule trigger needs a 'schedule' cron expression (e.g. '0 9 * * *')")
    name = designer.get("name", "workflow")
    prompt = (
        f"Run the saved Hermes workflow design '{name}'.\n"
        f"1. Call workflow_design_run with {{\"name\": \"{name}\"}}.\n"
        "2. If status is 'awaiting_agent', do what pending.prompt asks, then call "
        f"workflow_design_respond with run_id, node_id and your output; repeat until the run "
        "is no longer awaiting_agent.\n"
        "3. If status is 'awaiting_approval', do NOT answer it — report the gate question and stop.\n"
        "4. Report the final outputs verbatim.\n"
        "Never invent workflow nodes or edit the saved design."
    )
    return {
        "action": "create",
        "name": f"workflow:{name}",
        "schedule": cron_expr,
        "prompt": prompt,
        "enabled_toolsets": [TOOLSET],
        "deliver": deliver,
    }


def webhook_stub(designer: dict) -> dict:
    """Phase 1 declares the webhook trigger but never fires it (see plan risks)."""
    trig = _trigger(designer)
    if trig.get("trigger_mode") != "webhook":
        raise ValueError("trigger_mode is not webhook")
    path = (trig.get("webhook_path") or "").strip()
    if not path:
        raise ValueError("webhook trigger needs a 'webhook_path'")
    return {"declared": True, "path": path, "phase": 2,
            "note": "Phase 1: fire manually via /workflow run; inbound wiring is Phase 2"}
```

**Complete code — `tests/test_triggers.py`** (write FIRST):
```python
import pytest
from visual_workflow_hermes.triggers import schedule_plan, webhook_stub


def _schedule_design(cron="0 9 * * *"):
    return {"name": "daily", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "schedule",
         "schedule": cron, "after": []},
    ]}


def test_schedule_plan_targets_cronjob_manage_create():
    plan = schedule_plan(_schedule_design())
    assert plan["action"] == "create"
    assert plan["schedule"] == "0 9 * * *"
    assert plan["name"] == "workflow:daily"
    assert plan["enabled_toolsets"] == ["visual-workflow"]
    # cron takes a prompt, never a tool name plus args
    assert "workflow_design_run" in plan["prompt"]
    assert "args" not in plan


def test_prompt_is_self_contained_and_names_both_resume_cases():
    prompt = schedule_plan(_schedule_design())["prompt"]
    assert "workflow_design_respond" in prompt
    assert "awaiting_approval" in prompt     # cron must not auto-approve
    assert "awaiting_agent" in prompt


def test_schedule_plan_rejects_missing_cron():
    with pytest.raises(ValueError, match="cron expression"):
        schedule_plan(_schedule_design(cron="  "))


def test_schedule_plan_rejects_non_schedule_trigger():
    design = {"name": "x", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []}]}
    with pytest.raises(ValueError, match="not schedule"):
        schedule_plan(design)


def test_webhook_stub_declares_without_firing():
    design = {"name": "hook", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "webhook",
         "webhook_path": "/incoming/foo", "after": []}]}
    stub = webhook_stub(design)
    assert stub["declared"] is True and stub["phase"] == 2
    assert stub["path"] == "/incoming/foo"
```

**Exact verify:** `python -m pytest tests/test_triggers.py -v` → expected `5 passed`.

Commit: `feat(trigger): cron replay plan against cronjob_manage plus webhook stub`.

---

### Task 7 — The visual designer widget (single-file SVG canvas + `::preview`)

**Files:** `widgets/designer.html` (the ONLY frontend file — vanilla JS + inline SVG, no dependencies), `examples/` reuse. It must work when opened via Hermes chat as `::preview{file="<abs>/widgets/designer.html"}`.

Functional spec (implement exactly this, nothing more):
1. Left palette with 5 draggable node kinds: Trigger, Agent, Condition, Approval, Output.
2. Canvas: click palette item (or drag) to drop a node at the drop point and persist
   `{x, y}` on the node object; drag nodes to move (updates `x`/`y`); click two nodes
   then "Connect" (or drag edge) to add an `after` edge; Delete key removes selection
   and rewires nothing (children keep remaining parents; validator flags orphans only
   via unknown-ref, never auto-delete).
3. Right inspector: edits the selected node's fields (`prompt` textarea for Agent;
   `model` + `provider` optional text inputs; `trigger_mode` select + `schedule` cron
   text for Trigger; `expression` text with `out.` prefix hint for Condition; `question`
   + comma-separated `options` for Approval; read-only parent list for Output).
   Every edit updates the in-memory designer JSON. `x`/`y` are never shown in the
   inspector and never sent to the engine (convert.py strips them with the trigger).
4. Top bar: design name input + buttons **Validate** (runs `validate_designer_graph` ported to JS, shows errors inline), **Copy JSON** (copies designer JSON to clipboard for `/workflow save`), **Load example** (loads hello-world).
5. Hermes round-trip: a **Save to Hermes** button emits `window.hermes.send("/workflow save <name> " + JSON.stringify(graph))` when available, else falls back to clipboard. `data-hermes-send` attributes on static buttons where possible.
6. Styling: use ONLY `var(--foreground)`, `var(--muted-foreground)`, `var(--accent)`, `var(--border)`, `var(--card)`; no page background, no webfonts, flush-left layout.

Acceptance checklist (all must pass before commit):
- [ ] hello-world loads, Validate shows 0 errors, Copy JSON round-trips through `validate_designer_graph` in Python with 0 errors (positions ignored).
- [ ] Empty agent prompt → Validate names the node id.
- [ ] Condition `draft is long` → Validate rejects (must start with `out.`).
- [ ] Self-edge or 2-node cycle → Validate reports cycle/self-ref.
- [ ] No React/Vue/CDN `<script src>` in the file (grep); single file, works from `file://`.
- [ ] `window.hermes.send` guarded by `typeof window.hermes !== "undefined"` (no throw in plain browser).

**Implementation note for the implementer:** ~350-line single HTML file. Suggested internal structure (follow it):
```html
<!doctype html><meta charset="utf-8">
<style>/* palette left, canvas center, inspector right; vars only */</style>
<div id="bar">…name input + Validate/Copy/Load/Save buttons…</div>
<div id="main"><div id="palette">…5 buttons data-kind…</div>
<svg id="canvas" width="900" height="560"></svg>
<div id="inspector">…field editors…</div></div>
<pre id="errors"></pre>
<script>
let graph = {name:"hello-world", nodes:[/* hello-world nodes */]};
// render(): draw nodes as <g> rects + edges as <line>s from `after` refs
// select(id): populate inspector; oninput updates node + render()
// validate(): JS port of schema.py REQUIRED_FIELDS + trigger/after checks
</script>
```
Do NOT add pan/zoom, minimap, undo/redo, or collaboration — YAGNI, explicitly out of scope.

**Exact verify (no Hermes needed):**
```
python -c "from pathlib import Path; h=Path('widgets/designer.html').read_text(); assert 'data-hermes-send' in h or 'window.hermes.send' in h; assert 'React' not in h; print(len(h),'chars ok')"
```
Expected: `<N> chars ok` (any N > 5000), exit 0. Then visual check: open the file in a browser, click Agent → node appears; Validate with empty prompt → error names the node.

Commit: `feat(widget): single-file SVG designer with Hermes save hook`.

---

### Task 8 — Docs, install path, and catalog readiness

**Files:** `README.md`, `SKILL.md` (slash-command + widget usage for the agent), `pyproject.toml` (pytest config), update `plugin.yaml` version if changed.

**Complete code — `pyproject.toml`** (copy verbatim):
```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "visual-workflow-hermes"
version = "0.1.0"
description = "Visual agent-workflow designer plugin for Hermes"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
# `python -m pytest` puts CWD on sys.path but bare `pytest` does not.
pythonpath = ["."]
```

**`README.md` outline (write ~80 lines, include exactly these sections):** What it is (one para) → Node kinds table (Trigger/Agent/Condition/Approval/Output + workflow-tool mapping from Task 4) → Install (`hermes plugins install <repo-url>` or symlink `~/.hermes/plugins/visual-workflow` → repo; then `hermes plugins list` shows it) → Use (`/workflow list`, open widget via `::preview`, Validate, `/workflow run <name>`, `/workflow approve <run> <gate> <answer>`) → Triggers (manual now, schedule via cron replay from Task 6, webhook = Phase 2 stub) → OpenBot parity notes (routines≈saved designs, pending≈gates, copy-run-command≈Copy JSON).

**`SKILL.md` (copy verbatim skeleton, expand to ~40 lines):**
```markdown
# visual-workflow skill
Design, validate, and run visual agent workflows.
- Open the designer: ::preview{file="<REPO_ABS>/widgets/designer.html"}
- Validate locally, then `workflow_design_validate`, then `workflow_design_run`.
- Approvals surface as `workflow` gate nodes; answer with release (approve).
- Never invent node types: trigger, agent, condition, approval, output only.
```

**Exact verify:** `python -m pytest tests/ -v` → full suite green (requirement is
**0 failed**; count grows as tasks land — do not assert an exact number).
Then live engine check (Task 0 seam required):
```
hermes plugins validate .
```
Expected: exit 0. Plus one live round-trip: convert `examples/hello-world.designer.json`
with `to_workflow_graph`, pass the result to the `workflow` tool's `validate` action, and
confirm `ok: true` — if it rejects `meta`, `join.keys`, or gate `options`, fix `convert.py`
only (validator and fixtures stay frozen) and note the engine's exact demand in the commit.

Commit: `docs(install): README, SKILL.md, packaging`.

---

## Tests / validation

- TDD per task as specified above (red → green → commit). Full suite (`python -m pytest tests/ -v`) must be green before every commit from Task 3 onward.
- Converter goldens: `examples/*.designer.json` must validate AND convert on every run (covered by `test_schema.py` + `test_convert.py`).
- Engine contract check (needs Hermes running, do once after Task 5): use `tool_describe(names=["workflow"])` and confirm `validate` accepts the converted `hello-world` graph shape (`{name, nodes:[{id,type,after,...}]}`); if the live schema rejects a field, fix `convert.py` only — never patch around it in runtime.
- Widget check (Task 7 command) + one manual browser pass.
- Final gate: `hermes plugins validate .` exit 0 AND `hermes plugins doctor` shows the plugin with no import errors.

---

## Risks, tradeoffs, and open questions

1. **`workflow`-tool schema drift.** The tool grammar was read from a tool description, not source. If `validate` rejects our converted graphs (e.g. `meta` key stripped, `echo.output` shape, `options` on gates), the fix is confined to `convert.py` + `test_convert.py`. Mitigation: Task 5's live `validate` check happens before any UI work.
2. **No `ctx.call_tool` on this Hermes build.** `runtime._workflow_call` raises a clear error in that case; fallback is shelling `hermes` CLI or documenting manual `/workflow run` copy-paste. Check `tool_describe`/`skill_view` for the plugin SDK during Task 5 — do not assume the seam exists.
3. **Webhook trigger is a stub in Phase 1** (by design — YAGNI). Options for Phase 2, in preference order: (a) Hermes gateway inbound route replaying the shelved graph; (b) cron-poll of an inbox file the external system drops; (c) long-running plugin HTTP listener (rejected today: conflicts with OpenBot's 127.0.0.1 token-file pattern and Hermes egress policy — needs a security review first). The designer already captures `webhook_path` so Phase 2 is data-compatible.
4. **Widget↔chat bandwidth.** Large graphs travel via clipboard/`window.hermes.send` prompts, which have length limits. Cap: designs ≤ 50 nodes (enforced in `validate_designer_graph` only if hit in practice — do not pre-build pagination).
5. **Schedule semantics differ from OpenBot routines** (OpenBot routines support pause/skip-at-limit; ours is cron-replay, no run history inline). Acceptable for v0.1; history comes free from `workflow list/status`.
6. **Open question for the user:** which Hermes build hosts this — Desktop chat only, or must the designer also work in the gateway/Telegram surfaces (no `::preview` there)? Phase 1 targets Desktop `::preview`; other surfaces get `/workflow` text verbs only.
7. **Open question for the user:** webhook Phase 2 — is a localhost-only listener with a bearer-token file (exact OpenBot pattern) acceptable, or must webhooks arrive via the existing gateway? Answer decides the Phase 2 design; Phase 1 is unaffected.
8. **Security (implementer must not skip):** designer JSON arrives via chat prompts
   (`/workflow save <name> <json>`) — treat it as untrusted data: `json.loads` inside
   `try/except`, `store.save` re-validates before write, `_NAME_RE` blocks path escape,
   `save` overwrites only `<name>.json` under the store root (never absolute paths).
   Webhook payloads (Phase 2) must be passed as data under an `event` heading like
   OpenBot's `--- event from a local script ---`, never concatenated into agent
   instructions. Approval answers only ever flow through the `workflow` tool's `release`
   — the plugin never auto-approves, and browser-takeover/secret gates stay manual.
