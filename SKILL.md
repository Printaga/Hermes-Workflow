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

* exactly one `trigger` per design; `trigger_mode` is `manual`, `schedule` or `webhook`
* `agent` needs `prompt`; optional `profile` (a host bot), `model` / `provider` (override it)
* `condition` needs `expression` of the form `out.<node>.<field> <op> <value>`
* `approval` needs `question`; `options` is a list of acceptable answers
* `output` collects its parents' outputs; optional `deliver` (`notification` for a platform's
  home channel, `channel` for a specific chat) plus a `target` (`telegram`, `telegram:123456`,
  `slack:#ops`). Leave both off to only collect. Never claim a delivery happened — read
  `deliveries` in the run result.

Edges are `after: [<parent-id>...]`; a node runs after all parents. `x`/`y` are widget-only.

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
* `failed` — report `error`; do not retry blindly.

Never guess a `run_id` or gate id: use the ones in the response.

## Triggers

Manual runs are wired. For a `schedule` trigger, `triggers.schedule_plan(design)` yields the
`cronjob_manage` arguments; ask the user before registering anything recurring. `webhook` is a
declared stub in Phase 1 — say so instead of promising a listener.
