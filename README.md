# visual-workflow — a visual agent-workflow designer for Hermes

Design an agent workflow on a canvas — Trigger, Agent, Condition, Approval, Output — then save
it and run it. The plugin owns execution: it converts the designer graph into an ordered run
plan and walks it step by step, pausing at approval gates and at agent steps it cannot run
itself. No external workflow engine is involved.

Designs live as plain JSON under `~/.hermes/workflow-designs/<name>.json`; run state lives under
`~/.hermes/workflow-runs/<run_id>.json`.

## Node kinds

| Kind | Fields | Run-plan mapping |
| --- | --- | --- |
| `trigger` | `trigger_mode` (`manual`/`schedule`/`webhook`), `schedule` cron, `webhook_path` | Not a step: recorded in `plan["meta"]["trigger"]`. Exactly one per design. |
| `agent` | `prompt` (required), `model`, `provider`, `schema`, `inputs`, `timeout` | A step that runs an agent. Without a subagent backend it pauses as `awaiting_agent` with `pending.prompt`. |
| `condition` | `expression` (required) — `out.<node>.<field> <op> <value>` | Evaluated locally against upstream outputs; a false gate skips its downstream subtree (reported in `skipped`). |
| `approval` | `question` (required), `options`, `context` | Pauses the run as `awaiting_approval` until `workflow_design_respond` answers it. |
| `output` | — | Collects its parents' outputs under `outputs`. |

Edges are `after: [<node-id>...]`: a node runs once all of its parents have run. Layout `x`/`y`
is widget-only and never reaches the run plan.

## Install

```bash
# either
hermes plugins install <repo-url>
# or link a checkout into the plugin directory
ln -s /path/to/Hermes-Workflow ~/.hermes/plugins/visual-workflow

hermes plugins list          # visual-workflow 0.1.0
hermes plugins validate .    # exit 0
hermes plugins doctor .      # import + registration OK, 5 tools
```

Requires Hermes >= 0.21 and Python >= 3.10. No third-party dependencies.

### Desktop tab: it ships opt-in (one toggle)

`desktop/plugin.js` is the Desktop-app half of this package. Hermes Desktop materializes it as
`<hermes home>/desktop-plugins/visual-workflow/plugin.js` beside a `.hermes-package.json` marker, and
the runtime loader treats **every marked folder as opt-in**: it publishes the row with
`status: 'disabled'` and never calls `register()`, so neither the `/workflows` route nor the
`Workflows` sidebar row exists yet (`apps/desktop/src/contrib/runtime-loader.ts`:
`defaultEnabled: marker ? false : undefined`). A plugin cannot lift that cap itself — the loader
ANDs the root posture with the plugin's own `defaultEnabled`.

Turn it on once: **Settings → Capabilities → Plugins → Workflows → enable**. The choice persists in
Desktop's plugin-decisions store, and the row then loads on every launch (the file is also
fs-watched, so edits hot-reload).

If the row is still missing after that, check in Desktop DevTools (View → Toggle Developer Tools) —
the disabled path logs nothing, so the console is empty either way:

```js
JSON.parse(localStorage.getItem('hermes.desktop.pluginDecisions.v2') || '{}')['visual-workflow']
// undefined => never enabled (the marker's opt-in posture is still in force); true => enabled
document.querySelector('[data-tour="sidebar-nav-visual-workflow:workflows-nav"]')
// null => register() never ran: no /workflows route, no sidebar row. Look for `[plugins]` errors
```

## Use

```text
/workflow new demo                      # where to open the designer, how to save
/workflow list                          # saved designs
/workflow open demo                     # the design's JSON + a ::preview link
/workflow validate demo                 # problems, or "demo: valid"
/workflow save demo {"name":"demo",...} # validate, then write the design
/workflow run demo                      # run it now
/workflow approve <run_id> <gate> <answer>   # answer a paused approval gate
```

The designer itself is one static file:

```text
::preview{file="/path/to/Hermes-Workflow/widgets/designer.html"}
```

Click a node kind in the palette (or drag it onto the canvas), drag nodes to arrange them,
click two nodes and **Connect** to add an edge, and **Delete** to remove the selection. The
inspector edits the selected node; **Validate** runs the same rules as the Python validator;
**Copy JSON** produces the text for `/workflow save`; **Save to Hermes** sends that command
straight to chat when the host exposes `window.hermes.send`, and copies it otherwise.

The agent-facing tools mirror the verbs:

| Tool | Purpose |
| --- | --- |
| `workflow_design_save` | Validate and store a design. |
| `workflow_design_load` | Load a stored design. |
| `workflow_design_validate` | Validate without saving; returns `{node, field, msg}` defects. |
| `workflow_design_run` | Run a design: `done`, `awaiting_approval`, `awaiting_agent`, or `failed`. |
| `workflow_design_respond` | Resume a paused run with an approval answer or an agent output. |

## Triggers

* **Manual** — `/workflow run <name>` (the only fully wired trigger today).
* **Schedule** — `triggers.schedule_plan()` renders the exact `cronjob_manage` arguments for a
  `schedule` trigger: a self-contained prompt that makes the cron session call
  `workflow_design_run` and resume any `awaiting_agent` step. Registering the job stays a
  deliberate, user-initiated action.
* **Webhook** — Phase 1 stub. The designer already stores `webhook_path`, so the data model is
  ready; no listener is started (that needs a security review first).

## OpenBot parity notes

* routines ≈ saved designs; one design, many runs.
* pending actions ≈ approval gates; both resume by answering a specific step.
* OpenBot's copy-run-command ≈ the widget's **Copy JSON** + `/workflow run`.

## Tests

```bash
pytest                # bare pytest works: pyproject pins pythonpath = ["."]
```

The suite covers the schema, the store, the converter/topological order, the runner (gates,
skips, resume, pruning), the cron plan, the widget's embedded graph and its dependency-free
guarantees, and every slash-command verb.
