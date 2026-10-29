# Workflow plugin improvement plan — simple, fully functional, seamless

**Date:** 2026-10-29 | **Repo:** `/home/lenovo/Development/Hermes-Workflow` | **Status:** review + research done, in-flight work (edges, bot picker, delivery, scheduling GUI, tooltips) stays untouched — this plan starts AFTER Freebuff's current queue lands.

## Goal

Make the visual-workflow plugin so simple a non-technical user succeeds on first try, with zero dead controls, zero crashes on ordinary input, and every Hermes seam used instead of reimplemented — then stop.

## What the review found (verified, not guessed)

**Confirmed bugs (reproduced live or by direct execution):**
1. **Condition crash on mixed types (CRASH).** `evaluate_condition('out.draft.word_count > 20', {'draft': {'word_count': '25'}}, …)` raises bare `TypeError` (`'>' not supported between 'str' and 'int'`). `run_plan` catches only `StepError`; `tool_run` catches only `(ValueError, FileNotFoundError)` — the TypeError escapes both and the tool call dies at the dispatcher. Any agent text output compared numerically kills the run. Fix in `visual_workflow_hermes/runner.py`: coerce both sides with `_coerce` before comparing, and wrap residual comparison errors as `StepError`.
2. **`inputs` silently ignored.** `convert.py` passes `inputs` onto agent steps, but `runner.render_context` only injects `after`-parents. A user-set `inputs` field does nothing. Fix: honor `inputs` in `render_context` (resolve dotted paths from outputs) or remove the field from canvas + schema. Prefer honoring (one function, already half the semantics).
3. **Unbounded context injection.** `render_context` concatenates full upstream outputs with no cap — one long draft can blow the agent's context. Fix: cap each input at 4000 chars with a `[truncated …]` marker (matches delivery.py's MAX_TEXT convention).
4. **Three canvas copies.** `widgets/designer.html`, `dashboard/dist/index.js`, `desktop/plugin.js` each hand-maintain node kinds, fields, validation, and (now) tooltips/ports. They already drifted once (theme tokens). No fix in this plan except the guardrail in Task 1 — full unification is a rewrite, explicitly out of scope.

**Dead / misleading surface (remove or finish):**
5. **Webhook trigger is a stub that looks real.** The trigger picker offers `webhook`, but `webhook_stub` only raises/errors at runtime. Either wire it to Hermes' real webhooks surface (dashboard has a Webhooks page + `hermes webhook` CLI for dynamic subscriptions — spike first) or REMOVE `webhook` from all three pickers until Phase 2. No stub options in the UI — this is the "unused options" cleanup the user asked for.
6. **`triggers.py` vs `schedule.py` overlap.** `schedule_plan` (cron payload) lives in `triggers.py` while preset validation/cron building grew in `schedule.py`. Consolidate: one module owns trigger→cron, the other is deleted, tests merged. (Check Freebuff's in-flight scheduling work first — it may have already settled this; if so, delete this task.)
7. **Approval `context` field.** `pending` carries `context` but no canvas may display it (verify). If undisplayed, either render it in the approval card (reviewer context is the #1 HITL usability finding — proposal first, reasoning second) or drop the field.

**Research grounding (workflowbuilder.io 2026 roundup + HITL placement guide):**
- Standard node set for agent builders: LLM call, tools, retrieval, router/condition, parallel, human approval, loops, fallback/retry, triggers (manual/schedule/event), outputs (chat/API/MCP/scheduled). We have 5 kinds; the gaps that matter for "simple but functional" are **retry-on-failure** and **gate timeouts**, not loops/parallel (defer both — parallel needs concurrent agent turns the host seam doesn't offer; loops invite infinite runs).
- Every human gate needs a **timeout policy** (auto-reject/escalate, never wait forever) — currently ours waits indefinitely. This is the single most-cited production failure in the HITL literature.
- Reviewer UI must show **proposal → reasoning → context** on one screen, with approve/reject/edit. Our approval card should show the question + options + the upstream output being approved, not just the question.
- Winners (Dify/Langflow/Sim/n8n) all ship **templates, test runs, and versioning**. We need 3 built-in templates and per-run history visibility, not a template marketplace.

## Proposed end state (the simplicity contract)

- **5 node kinds stay** (trigger, agent, condition, approval, output). No parallel, no loop, no script node in v1 — each refused addition documented with the one-line reason.
- **Trigger modes:** manual + schedule only, until webhooks are real (Task 3 decides: wire or remove).
- **Every picker is populated or absent.** Bot picker ← profiles endpoint (done, in-flight). Channel picker ← channels endpoint (done, in-flight). No control renders without data or a telling empty state.
- **Every run is explainable:** inline node errors, delivery receipts, run history viewable from the canvas.

## Tasks

### Task 1 — Crash + silent-ignore fixes (runner.py), ~30 min
**Files:** `visual_workflow_hermes/runner.py`, `tests/test_runner.py`.
1. In `evaluate_condition`, coerce the left side: after resolving `left`, run it through `_coerce` when it is a `str` (so `'25' > 20` compares as `25 > 20`); wrap the comparison in try/except `(TypeError, ValueError)` → `raise StepError(f"cannot compare …")`.
2. In `render_context(step, outputs)`, after the `after`-parents block, additionally resolve `step.get("inputs")` (list of `<node>` or `<node>.<path>` strings, same syntax as planned for the workflow engine): bare id → whole output; dotted → `_dig`. Unknown ref → `StepError` (design defect, fail loud like conditions).
3. Cap each injected block at 4000 chars + `\n[…truncated N chars…]`.
4. Tests (write first): mixed str/int comparisons both directions; uncomparable types → StepError not TypeError; `inputs` with bare + dotted refs land in context; unknown input ref → StepError; 10KB upstream output truncated with marker.
5. Verify: `PYTHONPATH=. uvx --with pytest pytest tests/test_runner.py -v` → all pass; `hermes plugins doctor` clean. Commit `fix(runner): coerce condition operands, honor inputs, cap context`.

### Task 2 — Gate timeouts (schema + runner + canvases), ~1 h
**Files:** `visual_workflow_hermes/schema.py`, `runner.py`, `tests/test_runner.py`, all three canvases' approval inspectors.
1. Schema: approval node accepts optional `timeout_minutes` (positive int ≤ 4320) and `on_timeout` (`reject`|`escalate`, default `reject`). Validator rejects unknown values.
2. Runner: stamp `pending["waiting_since"]` (epoch) when parking at approval. Add `check_timeouts(state, now=None)` returning the run to `failed` with `error={node_id, msg:"approval timed out…"}` when expired (escalate v1 = same as reject + `detail:"escalation requested"` recorded; true re-routing is Phase 2 — say so in the docstring). Call it at the top of `resume_plan` so a late answer gets the timeout verdict, not a silent resume.
3. Canvas: timeout + on-timeout controls on the approval inspector with tooltips; show remaining wait on the approval card.
4. Tests first: expiry fails the run; late answer after expiry → StepError; no timeout → unchanged behavior. Commit `feat(approval): gate timeout policy`.

### Task 3 — Webhook: wire or remove (spike ≤30 min, then act), ~1 h
1. Spike: can a Hermes dynamic webhook subscription (`hermes webhook --help`, dashboard Webhooks page) target `POST /api/plugins/visual-workflow/runs/by-trigger/<path>`? Check auth model (unsigned n8n-style URL vs signed) against SECURITY posture — webhooks receive untrusted input, so the design must treat payload as data (existing `deliver` pattern).
2. If yes: implement inbound route (validate path, enqueue run, return run_id), canvas shows route URL + copy button, tests for 404-on-unknown-path and payload-as-data. If no: DELETE `webhook` from all three trigger pickers + `webhook_stub` + its tests, and record the removal reason in the plan margin. No third option — stubs don't ship. Commit either `feat(webhook): inbound trigger runs` or `chore(webhook): remove stub trigger`.

### Task 4 — Retry on failure (runner + canvas), ~45 min
**Files:** `runner.py`, `convert.py` (passthrough), `schema.py` (optional `retries` 0–3 on agent nodes), canvases (number input, default 0).
1. Agent step keeps `attempts` in state; on `StepError` from `spawn`, retry while `attempts <= retries`, else fail as today. Only agent steps retry (conditions/approvals fail fast — document why: retrying a human gate is nonsense, retrying a pure expression is deterministic).
2. Tests first: flaky spawn (fail once, succeed) with retries=1 → done; retries=0 → failed as before. Commit `feat(agent): retry on failure`.

### Task 5 — Templates + run history visibility, ~1 h
1. Add `examples/` templates (keep existing two): `daily-digest.designer.json` (schedule trigger + agent + output), `review-gate.designer.json` (manual + agent + approval with timeout + output). Each must validate + convert in tests (extend the golden-fixture pattern).
2. Canvas "New from template" dropdown listing all `examples/*.designer.json` by name (fetch list from a new `GET /designs/templates` endpoint or reuse the examples dir — spike cheapest; prefer endpoint so desktop + dashboard share it).
3. Run history: `GET /runs` (list recent run_ids + status) already? If `RunStore` lacks listing, add `list_runs(limit)` + endpoint; canvas shows last-10 runs with status + reopen. Check what exists first — don't build twice.
4. Tests + commit `feat(templates,history): built-in templates and run list`.

### Task 6 — Single node-spec guardrail against canvas drift, ~30 min
1. Add `node-spec.json` at repo root: the 5 kinds, each field (name, type, tooltip, required), each trigger mode, each deliver mode. Hand-written once.
2. One test (`tests/test_node_spec.py`) asserting all three canvases mention every kind/field (string presence, like existing grep tests) and that the spec itself validates against `schema.py` minima.
3. This does NOT unify the implementations — it only fails loudly on the next drift. Commit `test(spec): single node-spec parity guard`.

### Task 7 — Docs + seamlessness pass, ~30 min
1. README: "needs Desktop app running (in-window tab) OR `hermes dashboard` (browser tab)" — kill the autostart confusion in writing. Document: where designs live, cron replay behavior (fresh session, approvals never auto-answered), delivery semantics (failures recorded, never fatal), profile picker limitation (model/provider only, no skill re-homing).
2. `SKILL.md`: refresh the verb list to match what shipped (run/respond/schedules).
3. Verify full suite + doctor, commit `docs(seamless): honest operating picture`.

## Tests / validation
- TDD per task (red→green→commit), same as before. Full suite must stay green; count will grow past 127 — requirement is **0 failed**, never an exact number.
- Live gates (do once, after Task 1): re-run the chat-tool hello-world save+run (regression), one dashboard HTTP save+run, one approval pause+resume with timeout set to 1 min (verify expiry verdict, user-approved pattern).
- Never fire live notifications/channels in tests — monkeypatch the send seam (existing pattern).

## Risks, tradeoffs, open questions
1. **Sequential only, by decision.** Research says parallel is standard, but our host seam runs one agent turn at a time and parallel needs concurrent spawn + join semantics. Documented deferral, not a gap we hide: branching (condition+skip) covers 80% of parallel's use cases (run A then B vs run A and B together rarely matters at human timescales).
2. **No loops, by decision.** Loops risk infinite runs with no supervisor UI yet. Re-running a saved design on schedule covers the legitimate loop use case.
3. **Webhook auth is the hard part of Task 3**, not the route. If Hermes webhooks can't give us an unguessable per-workflow URL, removal is the correct outcome.
4. **Three canvases remain.** Task 6 detects drift; unification waits until a second drift actually bites (YAGNI).
5. **Open question for the user:** should timeouts also apply to `awaiting_agent` pauses (subagent never returns)? Proposal: no — agent pauses are worked by the host turn, not wall-clock; only human gates get timeouts. Speak now if otherwise.

## Deployment trap (learned live, 2026-10-29)

The installed plugin is a **git clone** at `~/.hermes/plugins/visual-workflow` (origin = this
repo), and it silently went stale: it sat on `03dc81f` while `main` was two commits ahead, and
`hermes plugins update` still reported "up-to-date". The gateway serves *that copy*, so a live
test can pass against old code and prove nothing.

Rules for every task below:

1. After **every commit that changes Python (or the dashboard bundle)**, deploy before any live
   check: `hermes plugins disable visual-workflow && hermes plugins enable visual-workflow`.
   That path rebuilds from the clone; `hermes plugins update` is not trustworthy.
2. Then **verify the active copy**, never the working tree:
   `grep -c "<feature marker>" ~/.hermes/plugins/visual-workflow/{visual_workflow_hermes,dashboard}/…`
   and `git -C ~/.hermes/plugins/visual-workflow log --oneline -1`.
3. If the clone is behind, `git -C ~/.hermes/plugins/visual-workflow pull --ff-only` first —
   enabling alone does not fetch. Local edits in that clone (it had one in README) block a
   fast-forward; inspect, stash and drop them rather than forcing.
4. A browser tab keeps the old JS bundle: reload the Workflows tab after a bundle change.
5. Live HTTP checks against the gateway (`127.0.0.1:9119`) answer **401** without a dashboard
   session, so verify a route by importing the deployed `dashboard/plugin_api.py` by path and
   calling the handler against the real `$HERMES_HOME` store — that is the same code the
   session-protected route runs.
