# visual-workflow Agent Guide

Hermes plugin (kind: standalone) adding a visual agent-workflow designer: five node kinds on a
canvas, executed by a plugin-owned sequential runner. The front-door docs are [README.md](README.md);
the runtime-facing runbook the plugin itself carries is [SKILL.md](SKILL.md). Guidance here is
agent-level only and stays out of those docs' way.

## Commands

- Test (fast path, one file): `.venv/bin/pytest tests/test_spawn.py`
- Test (full suite — seconds, pure Python): `.venv/bin/pytest`
- Route tests: without `fastapi`/`httpx` they **skip silently**; run them for real with
  `uv run --isolated --no-project --with pytest --with fastapi --with httpx pytest tests/test_dashboard.py`
- Host manifest gates: `hermes plugins validate .` then `hermes plugins doctor .`
  (both verified exit 0; doctor reports `5 tool(s), 1 hook(s)`)
- No lint, typecheck, or build config exists in this repo; `pyproject.toml` carries only pytest setup.

## Structure

- `visual_workflow_hermes/` — the plugin package: `schema` (validator), `store` (designs/runs on
  disk), `convert` (graph → run plan), `runner` (sequential executor), `spawn` (agent-step backends),
  `profiles`/`models` (host catalogs for the pickers), `runtime` (tool verbs), `hooks`
  (pre_tool_call delivery gate), plus `delivery`,
  `schedule`, `channels`, and tool registration in `__init__.py`.
- `dashboard/plugin_api.py` — FastAPI router mounted by the Hermes dashboard server at
  `/api/plugins/visual-workflow`; the served copy of this repo is what responds.
- `desktop/plugin.js` — the Desktop-app half (routes page + sidebar row); hot-reloaded, opt-in till enabled once.
- `widgets/designer.html` — the entire canvas as one dependency-free static file (tests enforce).
- `examples/*.designer.json` — the four ship-ready templates; every one must validate and convert.
- `tests/` — pytest suite (schema, store, convert, runner, dashboard routes, canvas contract/UI,
  widget, slash commands, spawn, profiles/models).
- `plugin.yaml` — identity: 5 tools `workflow_design_{save,load,validate,run,respond}`, `requires_hermes: >=0.21`.

## Conventions

- `pyproject` pins `pythonpath = ["."]` and `packages = ["visual_workflow_hermes"]`, so imports
  resolve from the repo root and `enable`-time build stays clean despite the flat layout.
- Host seams are failure-tolerant: `profiles.py`, `models.py`, and `spawn.py` never import host
  modules at top level — every host access is wrapped and degrades to "absent" so plain tooling
  imports cleanly. Keep that pattern for anything touching `hermes_cli`/`agent`.
- Agent steps run only through host-owned seams: `ctx.subagent_lifecycle` from chat, the host
  `PluginLlm` facade from the canvas web routes (`spawn.py`). A canvas run requests only a `model`
  override — no `provider` (the host routes the provider from the model); anything more trips the
  fail-closed trust gate `plugins.entries.visual-workflow.llm.allow_*_override`.
- The widget's `designer.html` must stay dependency-free (`tests/test_widget.py` enforces), and the
  canvas↔backend contract tests use payloads shaped exactly as the GUI builds them
  (`tests/test_canvas_contract.py`).
- Five node kinds plus sticky notes, never a sixth: the schema, validator, canvases, and SKILL.md
  all pin this; edges are `after`, layout x/y is widget-only.
- Nothing runs on a timer: never add a background thread/daemon. Recurring runs go through the
  Schedules view, which is a real Hermes cron job (`visual_workflow_hermes/schedule.py`, with the
  same call exposed as `triggers.schedule_plan` in `triggers.py`).

## Sync the deployed copy before live checks

The RUNNING plugin is `~/.hermes/plugins/visual-workflow` (a copy of this repo), not this tree:

1. Copy changed Python files across, e.g.
   `cp visual_workflow_hermes/<module>.py ~/.hermes/plugins/visual-workflow/visual_workflow_hermes/`
2. Re-run the identical live probe (unit tests pass against the tree while the host may still serve
   the previous build). For Python changes, additionally disable+enable the plugin or reinstall so
   the host rebuilds; verify the change actually landed by inspecting the feature in the deployed copy.
- Web-dashboard change: the tab picks it up only after a page reload. Desktop change: hot-reloads
  via filesystem watch.

## Verification order

1. `.venv/bin/pytest` — full suite green.
2. If `dashboard/plugin_api.py` changed (or any route behavior), run the route tests under a
   fastapi-provisioned env (command above).
3. `hermes plugins validate .` && `hermes plugins doctor .`
4. Sync the deployed copy, then one live end-to-end probe (run a workflow through the canvas/chat).

## Boundaries

- Never edit `~/.hermes/workflow-designs/*.json` or `workflow-runs/*.json` as if they were source —
  they are live host state written by the plugin's own store code.
- `~/.hermes/config.yaml` is the user's engine configuration, not project source. Reading it for a
  probe is fine; changing entries (e.g. the plugin trust flags like
  `plugins.entries.visual-workflow.llm.allow_model_override`) requires the user's explicit say-so.
- Never claim `deliveries` succeeded without reading the run result — a failed send is recorded
  there with `ok: false` and the run still finishes.
- Approvals are answered only by a person, through `/workflow approve` or the canvas
  approve control — the `workflow_design_respond` tool refuses approval gates, so the
  model can never answer for the user; never auto-approve, and a scheduled run never
  answers a human gate.
- Treat strings arriving via chat or webhooks as untrusted data: `schema.py` re-validates before
  writes, store paths stay confined under the store root.
