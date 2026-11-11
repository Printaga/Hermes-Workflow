"""Sequential, resumable executor for run plans. Owned by the plugin (no Hermes imports).

Steps run one at a time in plan order. A step completes, fails, is skipped by a false
condition, or pauses the run at an approval or a pending agent turn. ``state`` is mutated in
place and is JSON-serializable, so a paused run can be persisted and resumed later.
"""
from __future__ import annotations

import json
import operator
import re
import time

COMPARATORS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt,
               ">=": operator.ge, "<": operator.lt, "<=": operator.le}
_HEAD_RE = re.compile(r"^out\.(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$")
# Word operators need whitespace boundaries (node ids may contain dots, never spaces
# in an expression target): `out.n.text contains "x"`, never `out.n.textcontains"x"`.
_WORDS_RE = re.compile(r"^out\.(.+?)\s+(contains|startswith)\s+(.+)$")
# Unary emptiness: `out.n.items is empty`, `out.n.draft is not empty`.
_EMPTY_RE = re.compile(r"^out\.(.+?)\s+is(\s+not)?\s+empty\s*$")
# An unquoted right side shaped like a reference resolves to the other node's output;
# a quoted one stays literal text, exactly like the number/text rule below.
_REF_RE = re.compile(r"^out\.([A-Za-z0-9_.-]+)$")
PAUSED = ("awaiting_approval", "awaiting_agent")
# One upstream output is injected as one block; a long draft must not eat the agent's context.
MAX_CONTEXT_CHARS = 4000
# A transient agent failure may be retried; three extra attempts is the ceiling (schema rejects
# more), because a step that fails four times is a design defect, not bad luck.
MAX_RETRIES = 3
# A diagnosed rate limit gets ONE automatic retry even on a step with no retry budget — a
# delay genuinely fixes it, which no other failure kind can claim. Short by design: the
# provider asking to slow down is usually momentum, not a long outage.
RATE_LIMIT_BACKOFF_SECONDS = 15.0
_TRUNCATED = "\n[\u2026 truncated {n} chars \u2026]"


class StepError(ValueError):
    """A step could not run (bad expression, missing input, agent failure)."""


def _as_text(value) -> str:
    """One upstream value as context text: strings verbatim, anything else as JSON."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):  # not JSON-serializable: fall back like str() would
        return str(value)


def _context_block(label: str, value) -> str:
    """A labelled block, capped so one long output cannot crowd out the rest."""
    text = _as_text(value)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS] + _TRUNCATED.format(n=len(text) - MAX_CONTEXT_CHARS)
    return f"--- output from {label} ---\n{text}"


def render_context(step: dict, outputs: dict) -> str:
    """Upstream outputs as labelled text, for an agent's ``context``.

    Two ways to name an upstream value, both honoured here because ``convert.py`` passes both
    onto the step: ``after`` (every parent's whole output) and ``inputs`` (an explicit list of
    ``<node>`` or ``<node>.<path>`` refs, so a step can take just the fields it needs). An
    ``inputs`` ref that cannot be resolved is a design defect, raised as ``StepError`` like a
    bad condition, never silently ignored.
    """
    blocks: list[str] = []
    used: set[str] = set()
    for parent in step.get("after", []):
        if parent in outputs:
            blocks.append(_context_block(parent, outputs[parent]))
            used.add(parent)
    for raw in step.get("inputs") or []:
        ref = str(raw or "").strip()
        if not ref or ref in used:
            continue
        # Longest known node id prefix wins, exactly like evaluate_condition: an id may
        # contain dots, and splitting on the first one would resolve ``a.b.c`` as node ``a``.
        node = next((n for n in sorted(outputs, key=len, reverse=True)
                     if ref == n or ref.startswith(f"{n}.")), None)
        if node is None:
            raise StepError(
                f"agent input {ref!r} references a node that has not produced output"
            )
        path = ref[len(node) + 1:] if ref != node else ""
        value = outputs[node] if not path else _dig(outputs[node], path)
        blocks.append(_context_block(ref, value))
        used.add(ref)
    return "\n\n".join(blocks)


def _coerce(text: str):
    """Turn an expression literal into a comparable Python value."""
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


def _resolve_target(target: str, outputs: dict, node_ids, expression: str):
    """An ``out.<node>[.<path>]`` target to its produced value.

    Longest known node id prefix wins, so ids may contain dots. Anything
    unresolvable is a StepError (a design defect), never a silent False.
    """
    node = next((n for n in sorted(node_ids, key=len, reverse=True)
                 if target == n or target.startswith(f"{n}.")), None)
    if node is None:
        raise StepError(f"condition references unknown node in {expression!r}")
    if node not in outputs:
        raise StepError(f"condition references node {node!r} that has not produced output")
    if target == node:
        return outputs[node]
    return _dig(outputs[node], target[len(node) + 1:])


def _resolve_right(literal: str, outputs: dict, node_ids, expression: str):
    """A right side to its comparable value: quoted text stays literal, an unquoted
    ``out.<node>[.<path>]`` naming a known node reads that node's output (comparing
    two runs' outputs), anything else coerces to number/bool/text as written."""
    raw = (literal or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    if _REF_RE.match(raw):
        return _resolve_target(raw[len("out."):], outputs, node_ids, expression)
    return _coerce(raw)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == {} or value == []


def evaluate_condition(expression: str, outputs: dict, node_ids) -> bool:
    """Evaluate one condition expression against prior outputs.

    ``out.<node>.<path> <op> <value>`` with ``op`` one of ``== != > >= < <=``
    plus the word operators ``contains`` (substring, or membership in a list) and
    ``startswith``; ``out.<node>.<path> is [not] empty`` needs no right side; and
    an unquoted right side shaped like ``out.<other>`` compares two outputs.

    Never uses ``eval``. An unresolvable target is a StepError (a design defect),
    not False.
    """
    text = (expression or "").strip()
    empty = _EMPTY_RE.match(text)
    if empty:
        left = _resolve_target(empty.group(1), outputs, node_ids, expression)
        result = _is_empty(left)
        return (not result) if empty.group(2) else result
    match = _WORDS_RE.match(text) or _HEAD_RE.match(text)
    if not match:
        raise StepError(f"unparseable condition expression: {expression!r}")
    target, op, literal = match.groups()
    left = _resolve_target(target, outputs, node_ids, expression)
    right = _resolve_right(literal, outputs, node_ids, expression)
    if op in ("contains", "startswith"):
        if not isinstance(left, str):
            if op == "contains" and isinstance(left, (list, tuple)):
                try:
                    return right in left
                except TypeError as exc:
                    raise StepError(
                        f"cannot check {left!r} contains {right!r} in {expression!r}: {exc}"
                    ) from exc
            raise StepError(
                f"cannot check {left!r} {op} {right!r} in {expression!r}: "
                f"the left side is {type(left).__name__}, not text"
            )
        if not isinstance(right, str):
            right = str(right)
        return right in left if op == "contains" else left.startswith(right)
    # An agent often answers with numbers as text ({"word_count": "25"}). When the author
    # wrote a number, compare the left side as a number too. When the author quoted the
    # literal, they asked for a string comparison and the text is left alone.
    if isinstance(left, str) and not isinstance(right, str):
        left = _coerce(left)
    try:
        return bool(COMPARATORS[op](left, right))
    except (TypeError, ValueError) as exc:
        raise StepError(
            f"cannot compare {left!r} {op} {right!r} in {expression!r}: {exc}"
        ) from exc


def _spawn_with_retries(spawn, step: dict, state: dict) -> dict:
    """Run one agent step, retrying a transient failure up to ``step["retries"]`` times.

    Only agent steps retry. Re-asking a human gate is not a retry (it is the same unanswered
    question), and a condition expression is deterministic — retrying either would hide the
    defect instead of surviving a flaky model call. ``state["attempts"]`` records how many
    tries the node took, so a run result can explain itself.

    One exception to the budget: a failure the spawn seam diagnosed as "rate limited" gets
    a single automatic retry after a short backoff (``RATE_LIMIT_BACKOFF_SECONDS``), because
    a delay is the one thing that actually clears it — and that delay applies inside the
    budget too, since an instant retry after a 429 just re-hits the cap. Exactly once beyond
    the budget — a second rate limit there is a real constraint, not momentum, and the run
    must say so instead of napping forever.
    """
    try:
        budget = max(0, min(MAX_RETRIES, int(step.get("retries") or 0)))
    except (TypeError, ValueError):  # a hand-written JSON is data, not a crash
        budget = 0
    attempts = 0
    rate_retried = False
    while True:
        attempts += 1
        state.setdefault("attempts", {})[step["id"]] = attempts
        try:
            produced = spawn(step, state["outputs"], state) or {}
            if not isinstance(produced, dict):
                raise StepError(
                    f"agent step returned {type(produced).__name__}, expected an object"
                )
            if produced.get("error"):
                err = StepError(str(produced["error"]))
                # The diagnosis travels with the failure signal: the retry policy below keys
                # off the kind, not off the prose, and run_plan persists both into the error
                # record so the canvases can hang a chip off them.
                err.kind = produced.get("error_kind")
                err.hint = produced.get("error_hint")
                raise err
            return produced
        except StepError as exc:
            if getattr(exc, "kind", None) == "wrong provider":
                raise  # a config error, not a flaky call: retrying would re-run the wrong model
            rate_limited = getattr(exc, "kind", None) == "rate limited"
            if rate_limited and attempts <= budget:
                # Inside the budget: same policy, the provider asked to slow down, so an
                # immediate retry would just re-hit the cap. Nap first, then burn the wait.
                time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                continue
            if rate_limited and not rate_retried:
                rate_retried = True  # the one attempt beyond the budget, same short wait
                time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                continue
            if attempts > budget:
                raise


def run_plan(plan: dict, state: dict, spawn=None, on_step=None, deliver=None) -> dict:
    """Advance *state* through *plan* until it finishes or pauses.

    *state* is ``{"run_id", "name", "cursor", "status", "outputs", "skipped", "pending",
    "error", "answers", "deliveries"}``. ``cursor`` is the index of the next step, so resuming
    is a matter of calling again with the same state. ``spawn`` runs an agent step; when it is
    None an agent step pauses the run for the host to perform. ``on_step(state)`` is called
    after each completed step (used to persist). ``deliver(step, payload, run_name)`` sends an
    output node's payload somewhere; when it is None an output only collects. A delivery that
    fails is recorded in ``state["deliveries"]`` and does NOT fail the run.
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
                    state["pending"] = {"node_id": sid, "prompt": step.get("prompt", ""),
                                        "context": render_context(step, state["outputs"])}
                    if on_step:
                        on_step(state)
                    return state
                produced = _spawn_with_retries(spawn, step, state)
                # Key presence, not truthiness: an agent may legitimately return 0/False/{}
                # as its structured payload, and ``or`` would silently replace it with "".
                if produced.get("structured") is not None:
                    state["outputs"][sid] = produced["structured"]
                else:
                    state["outputs"][sid] = produced.get("output", "")
            elif kind == "condition":
                if not evaluate_condition(step["expression"], state["outputs"], node_ids):
                    state["skipped"].append(sid)
                    state["cursor"] += 1
                    if on_step:
                        on_step(state)
                    continue
            elif kind == "approval":
                pending = {"node_id": sid, "question": step.get("question", ""),
                           "options": step.get("options", []),
                           "context": step.get("context", ""),
                           "waiting_since": time.time()}
                # The timeout travels with the pause: check_timeouts(state) has no plan to
                # consult, and a gate must be answerable long after the process is gone.
                # Validate before mutating status, so a malformed value is a normal failed
                # step (StepError) instead of a half-paused run with no pending element.
                if step.get("timeout_minutes"):
                    try:
                        pending["timeout_minutes"] = int(step["timeout_minutes"])
                    except (TypeError, ValueError) as exc:
                        raise StepError(
                            f"bad timeout_minutes {step.get('timeout_minutes')!r}: {exc}"
                        ) from exc
                    pending["on_timeout"] = str(step.get("on_timeout") or "reject")
                state["status"] = "awaiting_approval"
                state["pending"] = pending
                if on_step:
                    on_step(state)
                return state
            elif kind == "output":
                payload = {k: state["outputs"].get(k) for k in step.get("keys", [])}
                state["outputs"][sid] = payload
                if deliver is not None and step.get("deliver"):
                    state.setdefault("deliveries", []).append(
                        _deliver(deliver, step, payload, plan.get("name", ""))
                    )
            else:
                raise StepError(f"unknown step kind {kind!r}")
        except StepError as exc:
            state["status"] = "failed"
            # A diagnosis the spawn seam attached stays with the verdict on disk: ``kind`` is
            # the machine-readable label the Runs view chips, ``hint`` its fix advice. A bare
            # StepError (a bad expression, an expired gate) has neither — the record is then
            # exactly the old shape, so old consumers never learn a new key.
            failure: dict = {"node_id": sid, "msg": str(exc)}
            kind = getattr(exc, "kind", None)
            if kind:
                failure["kind"] = kind
                hint = getattr(exc, "hint", None)
                if hint:
                    failure["hint"] = hint
            state["error"] = failure
            if on_step:
                on_step(state)
            return state
        except Exception as exc:
            # A spawn/hook/state bug is not a reason to leave the run looking in-flight: an
            # unrecorded ``running`` is not retryable and can never be resumed.
            state["status"] = "failed"
            state["error"] = {"node_id": sid,
                              "msg": f"unexpected error: {type(exc).__name__}: {exc}"}
            if on_step:
                on_step(state)
            return state
        state["cursor"] += 1
        if on_step:
            on_step(state)
    state["status"] = "done"
    state["pending"] = None
    # Terminal states must be persisted too: the loop's per-step save happens before the
    # cursor advances past the last step, so without this the stored run stays "running"
    # forever and a reloaded run can never be shown as finished.
    if on_step:
        on_step(state)
    return state


def _deliver(deliver, step: dict, payload, run_name: str) -> dict:
    """Call the delivery hook, stamped with the node it belongs to. Never raises."""
    try:
        outcome = deliver(step, payload, run_name) or {}
    except Exception as exc:  # a delivery problem is data, not a run failure
        outcome = {"ok": False, "detail": f"delivery error: {exc}"}
    return {"node_id": step.get("id"), **outcome}


def check_timeouts(state: dict, now=None) -> dict:
    """Fail a paused approval whose timeout has passed; otherwise return *state* unchanged.

    A human gate must never wait forever — the most-cited production failure in HITL designs.
    The policy is applied when the gate parks (``timeout_minutes`` / ``on_timeout`` on the
    pending element), so this needs no plan and works on a run reloaded from disk.

    ``escalate`` records ``detail: "escalation requested"`` on the error and fails the same way
    as ``reject``: re-routing to another reviewer is Phase 2, and pretending to escalate would be
    the kind of dead control this plan exists to remove.
    """
    pending = state.get("pending") or {}
    minutes = pending.get("timeout_minutes")
    if state.get("status") != "awaiting_approval" or not minutes:
        return state
    started = float(pending.get("waiting_since") or 0)
    moment = time.time() if now is None else float(now)
    if moment - started <= float(minutes) * 60:
        return state
    policy = str(pending.get("on_timeout") or "reject")
    error = {
        "node_id": pending.get("node_id"),
        "msg": f"approval timed out after {int(minutes)} min (policy: {policy})",
    }
    if policy == "escalate":
        error["detail"] = "escalation requested"
    state["status"] = "failed"
    state["error"] = error
    state["pending"] = None
    return state


def resume_plan(plan: dict, state: dict, answer, spawn=None, on_step=None, deliver=None) -> dict:
    """Feed an approval answer / pending agent output back in, then keep running.

    A late answer is checked against the gate's timeout first: the run fails as timed out
    instead of silently resuming as if the reviewer had been on time.
    """
    pending = state.get("pending")
    if not pending:
        # A run that already expired says so; "nothing to answer" would hide the reason.
        error = state.get("error") or {}
        if state.get("status") == "failed" and error.get("msg"):
            if on_step:
                on_step(state)  # idempotent: make sure the verdict is on disk
            raise StepError(str(error["msg"]))
        raise StepError("run is not paused; nothing to answer")
    check_timeouts(state)
    if state.get("status") == "failed":
        if on_step:
            on_step(state)
        raise StepError((state.get("error") or {}).get("msg") or "the approval gate timed out")
    node_id = pending["node_id"]
    index = next((i for i, s in enumerate(plan["steps"]) if s["id"] == node_id), None)
    if index is None:
        raise StepError(f"paused step {node_id!r} is not in the plan")
    step = plan["steps"][index]
    if step["kind"] == "approval":
        # Validate BEFORE mutating, so a rejected answer leaves the run resumable.
        if step.get("options") and answer not in step["options"]:
            raise StepError(f"answer {answer!r} is not one of {step['options']}")
        state["answers"] = {**state.get("answers", {}), node_id: answer}
        state["outputs"][node_id] = answer
    elif step["kind"] == "agent":
        if answer is None:
            raise StepError(f"agent step {node_id!r} needs an answer to resume with")
        state["outputs"][node_id] = answer
    else:
        raise StepError(
            f"paused step {node_id!r} has unexpected kind {step['kind']!r}; the design changed"
        )
    # Re-derive the cursor from the paused id: trusting the stored position would skip or
    # repeat the wrong step if the plan was edited between pause and resume.
    state["cursor"] = index + 1
    state["pending"] = None
    state["status"] = "running"
    return run_plan(plan, state, spawn=spawn, on_step=on_step, deliver=deliver)


# A crashed retry leaves an honest "running" on the failed step (the reset is persisted before
# any work). A legitimate retry cannot sit there long: every completed step is persisted on the
# spot, waiting is only ever an approval gate (a ``pending``), and rate-limit backoff is seconds.
# Past this window a run reset by a retry is unmistakably dead — a later retry takes it over.
# Short of that window the retry may still be genuinely in flight in another process, and taking
# it over would run its steps twice.
RETRY_RECLAIM_SECONDS = 600.0


def retryable(state: dict, now=None) -> bool:
    """Whether a retry may take a run over: a failed one always, a crashed one once cold.

    Only a run whose current ``running`` state was itself set by a retry reset qualifies: that
    reset stamps ``retrying`` before any work, so a mid-retry crash leaves the marker behind.
    A plain ``running`` run (a fresh run, or one mid-flight) has no marker — retrying it could
    duplicate work, so it is refused. Pending states are answered, not re-run.
    """
    if state.get("status") == "failed":
        return True
    if state.get("status") != "running" or state.get("pending") is not None:
        return False
    started = state.get("retrying")
    if not isinstance(started, (int, float)):
        return False
    moment = time.time() if now is None else float(now)
    return moment - float(started) >= RETRY_RECLAIM_SECONDS


def retry_failed(plan: dict, state: dict, spawn=None, on_step=None, deliver=None,
                 now=None) -> dict:
    """Re-run a failed run from the step it failed on, and keep going through the rest.

    ``run_plan`` never advances the cursor past a failed step, so the stored state already
    points at exactly the node to redo: clearing the verdict and returning the status to
    ``running`` is the whole reset. Output that survived the failure is reused, so a retry
    that succeeds repeats only the failed step and everything after it. Anything that is not
    retryable (:func:`retryable`) — a parked gate, a run in flight, a finished one — raises
    ``StepError`` instead of being silently restarted.
    """
    if not retryable(state, now):
        raise StepError(
            f"run {state.get('run_id', '?')!r} is {state.get('status')!r}, "
            "not failed — nothing to retry"
        )
    state["error"] = None
    state["pending"] = None
    state["status"] = "running"
    # Stamp the reset so a crash mid-retry leaves a state a later retry can pick up
    # (:func:`retryable` keys off this marker once it is cold) — not a half-cleared verdict
    # claiming an outcome it never reached. It is persisted before the work: a crash during
    # the first step then still shows the reset, not a stale failure.
    state["retrying"] = time.time() if now is None else float(now)
    if on_step:
        on_step(state)
    return run_plan(plan, state, spawn=spawn, on_step=on_step, deliver=deliver)


def new_state(plan: dict, run_id: str) -> dict:
    return {"run_id": run_id, "name": plan["name"], "cursor": 0, "status": "running",
            "outputs": {}, "skipped": [], "pending": None, "error": None, "answers": {},
            "deliveries": [], "attempts": {}}
