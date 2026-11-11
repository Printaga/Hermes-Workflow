# visual-workflow skill

Design, validate, and run visual agent workflows.

## Open the designer

```text
::preview{file="<REPO_ABS>/widgets/designer.html"}
```

One static file, no dependencies. Click a palette kind to add a node, drag to arrange. Each node
has an output port on its right and an input port on its left (a trigger has no input): drag
from an output port to another node to add an edge, click an edge and press Delete to cut it.

## The five node kinds (never invent others)

`trigger`, `agent`, `condition`, `approval`, `output`.

* exactly one `trigger` per design; `trigger_mode` is `manual` or `schedule`
* `agent` needs `prompt`; optional `profile` (a host bot), `model` (overrides the bot's model;
  there is no `provider` field — the runtime derives it from the host model catalog), and
  the pick must be served by the host's active provider (the picker lists those; any
  other pick fails the step instead of running the wrong model), and
  `retries` (0–3, default 0 — extra attempts when the bot call fails; only agent steps
  retry, because re-asking a human gate is not a retry and a condition is deterministic)
* `condition` needs `expression` of the form `out.<node>.<field> <op> <value>`
* `approval` needs `question`; `options` is a list of acceptable answers. Optional
  `timeout_minutes` (1–4320) is a deadline and `on_timeout` is `reject` or `escalate`; once the
  deadline passes the run is `failed` with `approval timed out` and a late answer gets that
  verdict, so a gate never waits forever
* `output` collects its parents' outputs; optional `deliver` (`notification` for a platform's
  home channel, `channel` for a specific chat) plus a `target` (`telegram`, `telegram:123456`,
  `slack:#ops`). Leave both off to only collect. Never claim a delivery happened — read
  `deliveries` in the run result.

Edges are `after: [<parent-id>...]`; a node runs after all parents. `x`/`y` are widget-only.

A **note** (`{"id", "type": "note", "text", "x", "y", "color"}`) is a sticky label for the
person reading the canvas. It is not a sixth step: it has no ports, takes no edges, is dropped
by the converter like a trigger, and never reaches the runner. Use it to annotate; never route
work through it.

## Start from a template, not a blank page

`examples/*.designer.json` are four working designs — `hello-world`, `daily-digest`,
`approval-demo`, `review-gate`. In a canvas, the **start from a template** picker in the top row
loads one as an unsaved draft; `GET /designs/templates` returns the same list (with the graph
inline) for scripting. Editing a template and saving it under a new name is the fastest correct
start; do not invent field names from memory.

## Workflow

1. Build the graph in the designer, **Validate** until it reports `valid`.
2. **Copy JSON**, then `/workflow save <name> <json>` (or the `workflow_design_save` tool).
3. `workflow_design_validate` on the stored graph before running it.
4. `workflow_design_run` with the design name.

## Running and gates

`workflow_design_run` returns a status:

* `done` — inspect `outputs`; `skipped` lists nodes gated off by a false condition;
  `deliveries` lists each output's send attempt (`node_id`, `target`, `ok`, `detail`).
* `awaiting_approval` — ask the user `pending.question` (options in `pending.options`), then
  `workflow_design_respond` with `run_id`, `node_id` and the chosen `answer`.
* `awaiting_agent` — perform `pending.prompt` yourself, then respond with the output as
  `answer` (or `structured` for a JSON object conditions can read).
* `failed` — report `error`; do not retry blindly. A gate that expired says
  `approval timed out`; a step that ran out of `retries` says what the bot returned.
  A diagnosed failure carries `error.kind` (rate limited, trust refusal, …) and `error.hint`,
  one fix sentence — relay both. When the user wants the run to go again, the deliberate path
  is the offered one: the canvas **Retry** button, or `workflow_design_run`
  `retry=<run_id>` / `/workflow run retry <run_id>` — it re-enters the run at the failed step
  and reuses what already produced output. A run crashed mid-retry shows `running` with no
  verdict; once it sits cold for 10 minutes, the same retry requests take it over. Never
  splice a run_id into a fresh Run.

Never guess a `run_id` or gate id: use the ones in the response.

## Triggers

Manual runs are wired from chat and from every canvas. Recurring runs are created from the
canvas's **Schedules** view (a real Hermes cron job) or from `triggers.schedule_plan(design)`,
which yields the same `cronjob_manage` arguments; ask the user before registering anything
recurring. A scheduled replay opens a **fresh session** and answers `awaiting_agent` steps
itself, but it never answers a human gate — that waits for a person until `timeout_minutes`.
Inbound HTTP is not a mode: point the user at `hermes webhook subscribe`, which can fire that
cron job — never promise a listener the plugin does not own.

## Reports you can make

Read the run, do not narrate it: `outputs` (per node), `skipped` (nodes a false condition gated
off), `attempts` (tries each agent step took), `deliveries` (each send attempt with `ok`),
`error` (`{node_id, msg, kind?, hint?}` — the optional pair is the diagnosed-failure label
and its fix advice) when a run failed. The **Runs** view in a canvas lists the same runs on
disk, newest first, chips a diagnosed kind, and offers Retry for failed runs.
