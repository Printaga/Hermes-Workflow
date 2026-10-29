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
| `trigger` | `trigger_mode` (`manual`/`schedule`), `schedule` cron | Not a step: recorded in `plan["meta"]["trigger"]`. Exactly one per design. |
| `agent` | `prompt` (required), `profile`, `model`, `provider`, `schema`, `inputs`, `timeout` | A step that runs an agent. `profile` picks a host bot; its model/provider apply unless the node overrides them. Without a subagent backend it pauses as `awaiting_agent` with `pending.prompt`. |
| `condition` | `expression` (required) — `out.<node>.<field> <op> <value>` | Evaluated locally against upstream outputs; a false gate skips its downstream subtree (reported in `skipped`). |
| `approval` | `question` (required), `options`, `context` | Pauses the run as `awaiting_approval` until `workflow_design_respond` answers it. |
| `output` | `deliver` (`notification`/`channel`), `target` | Collects its parents' outputs under `outputs`, then optionally sends that text through the host send seam. `notification` targets a platform's home channel (`telegram`); `channel` needs `<platform>:<chat id>` (`slack:#ops`). A failed send is recorded in `deliveries`, never fails the run. |

Edges are `after: [<node-id>...]`: a node runs once all of its parents have run. Layout `x`/`y`
is widget-only and never reaches the run plan.

### Sticky notes

A **note** (`{"id", "type": "note", "text", "x", "y", "color"}`) is a label for whoever reads
the canvas — the "remember the dry tone here" kind of thing. It is deliberately *not* a sixth
step kind:

* it has no ports, so it takes no edges in either direction (the validator rejects an `after`
  that names a note, and rejects an edge *to* one);
* it is dropped by the converter exactly like a trigger, so the runner never sees it;
* `color` is one of `yellow`, `blue`, `green`, `red` and defaults to yellow.

Because it is not a step, a design of only a note is still invalid — a workflow needs exactly
one trigger and at least one executable node. Use notes freely; they change nothing about how
the workflow runs.

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

If the row is still missing after that, three checks in Desktop DevTools (View → Toggle Developer
Tools) settle where it stopped. The disabled path logs nothing — the loader only writes
`[plugins] runtime load failed (<origin>)` when a load actually throws — so silence is evidence,
not proof:

```js
JSON.parse(localStorage.getItem('hermes.desktop.pluginDecisions.v2') || '{}')['visual-workflow']
// undefined = never decided (the marker's opt-in posture still applies) | true = enabled | false = off
```

1. The value above — `undefined` means the toggle never took.
2. The `[plugins]` filter in the console — any `runtime load failed` line is a real import error
   in `plugin.js` (the row would show as `disabled`, not missing).
3. `ls "$HERMES_HOME/desktop-plugins/visual-workflow/.hermes-package.json"` — the marker is what
   makes the folder opt-in; delete the folder and reinstall the package to regenerate both.

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

Click a node kind in the palette (or drag it onto the canvas) and drag nodes to arrange them.
Every node carries an output port on its right edge and an input port on its left (all but a
trigger, which can have no parents): drag from the output port to another node to add an edge.
Click an edge and press **Delete** (or double-click it) to cut it; edges that would close a
loop are refused before they exist. The
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
* **Inbound HTTP** — not a designer mode, because a plugin cannot open a route. Hermes'
  operator-managed `hermes webhook subscribe` (HMAC secret) can fire the schedule's cron job,
  so an outside POST *reaches* a schedule without the canvas pretending to own a URL.

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
