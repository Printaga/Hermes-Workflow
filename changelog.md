# Changelog

## [1.1.0] - 2026-11-11

- Human-in-the-loop delivery: a model-started run whose design delivers to a chat
  first asks for host approval naming the target; denying blocks the run.
- Approval gates are human-only: `workflow_design_respond` refuses them, so they are
  answered through `/workflow approve` or the canvas approve control.
- Resumes are record-anchored: the run stamps `approved_targets` at start, and a
  resume whose design gained a delivery target is refused.
- Guided condition builder with `contains`, `startswith`, `is-empty`, and
  output-vs-output comparisons; field-path suggestions drawn from previous runs.
- Delete saved workflows and stored runs through the human paths.
- Canvas shows finished runs and recalls them from Runs; result recall and edit
  ergonomics; standalone theme fallbacks for the canvas paint vars.
- Agent steps fail loudly when the host runs them on the wrong provider instead of
  silently running another provider's weights.
- Schedule actions restricted to `workflow:`-prefixed cron jobs.

## [1.0.0] - 2026-11-10

- Initial release.
