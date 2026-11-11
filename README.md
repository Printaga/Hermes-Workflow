# visual-workflow — a visual agent-workflow designer for Hermes

Home: [pluginsforhermes.com](https://pluginsforhermes.com/)

Design an agent workflow on a canvas — Trigger, Agent, Condition, Approval, Output — then save
it and run it. The plugin owns execution: it converts the designer graph into an ordered run
plan and walks it step by step, pausing at approval gates and at agent steps it cannot run
itself. No external workflow engine is involved.

Designs live as plain JSON under `~/.hermes/workflow-designs/<name>.json`; run state lives under
`~/.hermes/workflow-runs/<run_id>.json`.

## Where you actually work

There are three surfaces, and none of them starts itself:

| Surface | How it is there | What it has |
| --- | --- | --- |
| Dashboard tab | `hermes dashboard`, then open the **Workflows** tab in the browser | Full canvas plus the API-backed pickers (bots, chats, templates), Runs and Schedules views |
| Desktop tab | The **Desktop app** running, with the plugin enabled once in Settings → Capabilities → Plugins (see below) | The same canvas, drawing through the app's own REST door |
| `/workflow` + tools | The gateway serving this plugin, in any chat session | The chat half: save, validate, run, answer a gate — no canvas |

If the toolbar buttons in a tab look inert, the tab is a stale bundle: reload the page after a
plugin update. Nothing in this plugin runs on a timer — a saved design does nothing until you
press **Run** or point a schedule at it.

## Node kinds

| Kind | Fields | Run-plan mapping |
| --- | --- | --- |
| `trigger` | `trigger_mode` (`manual`/`schedule`), `schedule` cron | Not a step: recorded in `plan["meta"]["trigger"]`. Exactly one per design. |
| `agent` | `prompt` (required), `profile`, `model`, `schema`, `inputs`, `timeout`, `retries` | A step that runs an agent. `profile` picks a host bot; its model applies unless the node overrides it. `model` is chosen from the host catalog — there is no `provider` field, the runtime derives it from the model, so only models served by the host's active provider can run (the picker lists those; any other pick fails the step instead of running the wrong model). `retries` (0–3, default 0) re-runs the step when the bot fails, and `attempts` in the run state records how many tries it took. From chat the step runs through the host subagent lifecycle; from a canvas (dashboard/desktop) the web routes run it through the host's plugin LLM facade (`ctx.llm`), which needs no parent session — a model override there is trust-gated by `plugins.entries.visual-workflow.llm.allow_model_override`. With neither backend available it pauses as `awaiting_agent` with `pending.prompt`. |
| `condition` | `expression` (required) — `out.<node>.<field> <op> <value>` (`== != > >= < <=`, plus `contains`/`startswith`; `is [not] empty` needs no value; unquoted `out.<other>` compares two outputs) | Evaluated locally against upstream outputs; a false gate skips its downstream subtree (reported in `skipped`). |
| `approval` | `question` (required), `options`, `context`, `timeout_minutes`, `on_timeout` | Pauses the run as `awaiting_approval` until `workflow_design_respond` answers it. `timeout_minutes` (1–4320) is a deadline: once it passes the run fails with `approval timed out`, and a late answer gets that verdict instead of resuming. `on_timeout` is `reject` (default) or `escalate` (recorded as `detail: "escalation requested"`; real re-routing is Phase 2). |
| `output` | `send_to` (collect only, a home channel, or one chat) | Collects its parents' outputs under `outputs`, then optionally sends that text through the host send seam. A bare platform is its home channel (`telegram`); a chat is `<platform>:<chat id>` (`slack:#ops`). The canvas derives `deliver`/`target` from that one choice, so an invalid pair cannot be built. A failed send is recorded in `deliveries`, never fails the run. |

Edges are `after: [<node-id>...]`: a node runs once all of its parents have run. Layout `x`/`y`
is widget-only and never reaches the run plan.

### When a run fails

A failed run's record is `{node_id, msg, kind?, hint?}`: when the backend failure matches a
known surface — rate limit, timeout, trust refusal, auth, unknown model, connection — the
spawn seam attaches a `kind` label and one-sentence `hint`, and both persist on disk with
the verdict; an undiagnosed failure simply has neither key. The three canvases render the
kind as a chip beside the error text (hint on the tooltip) and offer a **Retry** control —
and `POST /runs/<run_id>/retry` and `/workflow run retry <run_id>` do the same elsewhere. A
retry re-enters the run at the failed step (the runner owns the reset), reusing everything
that already produced output; anything else — a parked gate, a run in flight, a finished
one — is refused. One exception: a retry reset is stamped before any work, so if the host
crashes mid-retry the run sits `running` with no verdict, and a retry it could never see
finish (10 minutes cold) is taken over by the next one instead of wedging forever. A diagnosed rate limit additionally gets one automatic
backed-off retry at run time, before a failure ever exists to retry.

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

## Start from a template

Four worked designs ship in `examples/` and the **start from a template** picker in the top row
of the canvas loads any of them onto the canvas as an unsaved draft:

| Template | Shape |
| --- | --- |
| `hello-world` | one agent, one output — the smallest useful workflow |
| `daily-digest` | schedule trigger (`0 9 * * *`) → agent with one retry → output |
| `approval-demo` | all five kinds: condition filters a short draft, then a human gate |
| `review-gate` | agent → approval with a 60-minute deadline → output, plus a sticky note |

The list is `GET /designs/templates`, which reads `examples/*.designer.json` at request time, so
a copy of the plugin with no `examples/` simply shows no templates. Each file carries its own
`title` and `description`; the tests validate every example, so a template can never ship broken.

## Install

```bash
hermes plugins install <repo-url>
# installs disabled by default — activate it:
hermes plugins enable visual-workflow   # also resolves the plugin's Python deps

hermes plugins list          # visual-workflow 1.0.0
hermes plugins validate .    # from the checkout: "Validation passed."
hermes plugins doctor .      # import + registration OK, 5 tool(s), 1 hook(s)
```

A `file://` or `http://` install source prints a "custom (unreviewed) source" warning;
`https://github.com/<owner>/<repo>.git` does not. To develop on a checkout in place, clone it
**into** the plugin directory (a symlink is discoverable but cannot be tracked — `hermes plugins
adopt` refuses paths that resolve outside the plugins directory), then register it:

```bash
git clone <repo-url> ~/.hermes/plugins/visual-workflow
hermes plugins adopt visual-workflow    # "✓ Adopted … now a tracked git install"
```

Requires Hermes >= 0.21 and Python >= 3.10. `pyproject.toml` declares no pip dependencies —
the dashboard router imports `fastapi`/`httpx` from the Hermes server's own environment, and
tests that need them skip where they are missing.

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
/workflow run retry <run_id>            # re-run a failed run from the step that failed
/workflow approve <run_id> <gate> <answer>   # answer a paused approval gate
```

The designer itself is one static file:

```text
::preview{file="/path/to/Hermes-Workflow/widgets/designer.html"}
```

Click a node kind in the palette (or drag it onto the canvas) and drag nodes to arrange them.
Every node carries an output port on its right edge and an input port on its left (all but a
trigger, which can have no parents): drag from the output port to another node to add an edge.
Click an edge and press **Delete** (or double-click it) to cut it; right-click a node or a
connection for a Delete/Cut menu; edges that would close a loop are refused before they exist.
inspector edits the selected node; **Validate** runs the same rules as the Python validator;
**Copy JSON** produces the text for `/workflow save`; **Save to Hermes** sends that command
straight to chat when the host exposes `window.hermes.send`, and copies it otherwise. After a
run, each node shows an excerpt of what it produced underneath itself (full text in the run
panel; the Runs view recalls it later with a **Result** button). Excerpts key off node ids,
so deleting a node and re-adding one with the same id can briefly show the old run's text
until the next run.

The agent-facing tools mirror the verbs:

| Tool | Purpose |
| --- | --- |
| `workflow_design_save` | Validate and store a design. |
| `workflow_design_load` | Load a stored design. |
| `workflow_design_validate` | Validate without saving; returns `{node, field, msg}` defects. |
| `workflow_design_run` | Run a design: `done`, `awaiting_approval`, `awaiting_agent`, or `failed`. With `retry: <run_id>` instead of `name`, it re-runs a failed run from the step that failed. |
| `workflow_design_respond` | Resume a paused run with an approval answer or an agent output. |

## Triggers

* **Manual** — the Run button, `/workflow run <name>`, or the `workflow_design_run` tool.
* **Schedule** — a `schedule` trigger in the canvas feeds the **Schedules** view, which creates a
  real Hermes cron job (`cronjob_manage`) on your say-so; `triggers.schedule_plan()` is the same
  call as a payload, for scripting. The job's prompt is self-contained: a cron run opens a
  **fresh session**, calls `workflow_design_run`, and answers any `awaiting_agent` step itself.
  It never answers a human gate — an approval pauses the run and waits for a person, and its
  `timeout_minutes` deadline is what stops an abandoned gate from waiting forever.
* **Inbound HTTP** — not a designer mode, because a plugin cannot open a route. Hermes'
  operator-managed `hermes webhook subscribe` (HMAC secret) can fire the schedule's cron job,
  so an outside POST *reaches* a schedule without the canvas pretending to own a URL.

## Limits worth knowing

* **One bot and one model per step.** The agent picker lists host profiles and overrides
  the model for that step only. It does not re-home skills, tools or memory: a step runs
  as the active bot with those two overrides, and picking "the writer bot" does not give the step
  the writer's skill set.
* **Sequential, and no loops.** Steps run one at a time in dependency order. Parallel branches
  need concurrent agent turns the host seam does not offer; loops risk unbounded runs with no
  supervisor yet. Branch with a condition instead — a false gate skips its downstream subtree.
* **Run history is files, not a database.** The **Runs** view lists `~/.hermes/workflow-runs/*.json`
  newest-first (including runs started from chat or cron), and reading a run is the moment its
  gate deadline is enforced. Failed runs carry their diagnosed `kind` and a **Retry** button in
  the same view. Deleting a file forgets the run; there is no pruning job.
* **Delivery is best-effort.** A failed send is recorded in `deliveries` with `ok: false` and a
  `detail`, and the run still finishes — check `deliveries` rather than assuming a message went out.

## Disclosures

What the plugin touches, for the catalog record:

- Network: none directly. Agent steps and message sends go through host-owned
  seams (subagent lifecycle, plugin LLM facade, host send); the plugin opens no
  sockets and calls no third-party service. No telemetry.
- Reads and writes: designs under `~/.hermes/workflow-designs/`, run state
  under `~/.hermes/workflow-runs/`. Run history is plain JSON files; deleting
  a file forgets the run. The plugin never writes outside those two directories
  (plus the host-owned cron jobs it is asked to create).
- Processes: nothing runs on a timer and there are no background threads.
  Recurring runs are real Hermes cron jobs created only on the user's say-so;
  a cron run opens a fresh session and answers its own agent steps, never a
  human approval gate.
- Credentials: none. The plugin declares no `requires_env`, holds no secrets,
  and reads no credential files.
- Tested on Linux, macOS and Windows: the CI matrix
  (`.github/workflows/ci.yml`) runs the full suite plus both host manifest
  gates on all three on every push and pull request.

## License

Apache 2.0 — see [LICENSE](LICENSE). Release history: [changelog.md](changelog.md).

## OpenBot parity notes

* routines ≈ saved designs; one design, many runs.
* pending actions ≈ approval gates; both resume by answering a specific step.
* OpenBot's copy-run-command ≈ the widget's **Copy JSON** + `/workflow run`.

## Tests

```bash
pytest                # bare pytest works: pyproject pins pythonpath = ["."]
```

The suite covers the schema, the store, the converter/topological order, the runner (gates,
skips, resume, pruning, retries, timeouts), the cron plan, every shipped template (each one must
validate and convert), the dashboard router and its live endpoints, all three canvases' layout
and controls, the widget's embedded graph and its dependency-free guarantees, and every
slash-command verb.

Every push runs the full suite under CI (`.github/workflows/ci.yml`) with fastapi/httpx
provisioned, so the dashboard route tests always execute — plus the two host manifest gates,
`hermes plugins validate .` and `hermes plugins doctor .`.
