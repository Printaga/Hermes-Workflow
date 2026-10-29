import pytest

from visual_workflow_hermes.runner import (StepError, evaluate_condition, new_state,
                                           resume_plan, run_plan)


def _plan(*steps):
    return {"name": "t", "steps": list(steps), "meta": {}}


# -- retry on failure -------------------------------------------------------
# Only agent steps retry. A human gate re-asked by a machine is not a retry, and a pure
# expression is deterministic — retrying either would hide the defect instead of fixing it.

def test_a_flaky_agent_step_retries_once_then_succeeds():
    plan = _plan({"id": "a", "kind": "agent", "after": [], "prompt": "p", "retries": 1})
    calls = {"n": 0}

    def spawn(step, outputs, state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StepError("transient")
        return {"output": "second time"}

    state = run_plan(plan, new_state(plan, "retry1"), spawn=spawn)
    assert state["status"] == "done"
    assert state["outputs"]["a"] == "second time"
    assert calls["n"] == 2
    assert state["attempts"] == {"a": 2}, "the run must say how many attempts it took"


def test_a_returned_error_counts_as_a_failure_too():
    plan = _plan({"id": "a", "kind": "agent", "after": [], "prompt": "p", "retries": 2})
    outcomes = [{"error": "boom"}, {"error": "boom"}, {"output": "ok"}]
    state = run_plan(plan, new_state(plan, "retry2"), spawn=lambda s, o, st: outcomes.pop(0))
    assert state["status"] == "done"
    assert state["outputs"]["a"] == "ok"
    assert state["attempts"] == {"a": 3}


def test_without_retries_the_first_failure_fails_the_run_as_before():
    plan = _plan({"id": "a", "kind": "agent", "after": [], "prompt": "p"})
    calls = {"n": 0}

    def spawn(step, outputs, state):
        calls["n"] += 1
        raise StepError("transient")

    state = run_plan(plan, new_state(plan, "retry3"), spawn=spawn)
    assert state["status"] == "failed"
    assert state["error"] == {"node_id": "a", "msg": "transient"}
    assert calls["n"] == 1


def test_an_exhausted_retry_budget_reports_the_last_error():
    plan = _plan({"id": "a", "kind": "agent", "after": [], "prompt": "p", "retries": 2})
    calls = {"n": 0}

    def spawn(step, outputs, state):
        calls["n"] += 1
        raise StepError(f"attempt {calls['n']} failed")

    state = run_plan(plan, new_state(plan, "retry4"), spawn=spawn)
    assert state["status"] == "failed"
    assert calls["n"] == 3, "one try plus two retries"
    assert state["error"]["msg"] == "attempt 3 failed"
    assert state["attempts"] == {"a": 3}


def test_a_non_agent_step_never_retries_even_with_the_field_set():
    plan = _plan({"id": "c", "kind": "condition", "after": [], "retries": 3,
                  "expression": "out.ghost.n > 1"})
    state = run_plan(plan, new_state(plan, "retry5"), spawn=lambda s, o, st: {"output": "x"})
    assert state["status"] == "failed"
    assert state["attempts"] == {}, "only agent steps record attempts"


# -- runner unit tests ------------------------------------------------------

def test_agent_outputs_feed_a_true_condition_and_reach_the_output():
    plan = _plan(
        {"id": "draft", "kind": "agent", "after": [], "prompt": "write"},
        {"id": "big", "kind": "condition", "after": ["draft"],
         "expression": "out.draft.word_count > 2"},
        {"id": "out", "kind": "output", "after": ["big"], "keys": ["draft"]},
    )
    state = run_plan(plan, new_state(plan, "r1"),
                     spawn=lambda s, o, st: {"structured": {"word_count": 9, "text": "hi"}})
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
    state = run_plan(plan, new_state(plan, "r2"),
                     spawn=lambda s, o, st: {"structured": {"word_count": 3}})
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
    assert state["pending"]["node_id"] == "human"
    assert state["pending"]["options"] == ["ship", "edit"]
    state = resume_plan(plan, state, "ship")
    assert state["status"] == "done"
    assert state["outputs"]["out"] == {"human": "ship"}


def test_bad_approval_answer_is_rejected_and_leaves_the_run_resumable():
    plan = _plan({"id": "h", "kind": "approval", "after": [], "question": "q", "options": ["a"]})
    state = run_plan(plan, new_state(plan, "r4"))
    with pytest.raises(StepError, match="not one of"):
        resume_plan(plan, state, "z")
    assert state["status"] == "awaiting_approval"   # not mutated by the rejection
    assert resume_plan(plan, state, "a")["status"] == "done"


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


# -- runtime integration: persistence across tool calls ---------------------

class _Ctx:
    """No subagent_lifecycle: the runtime must fall back to pending-turn pauses."""


def _runtime(tmp_path):
    from visual_workflow_hermes.runtime import WorkflowDesignerRuntime
    from visual_workflow_hermes.store import DesignStore, RunStore

    rt = WorkflowDesignerRuntime(_Ctx(), store=DesignStore(root=tmp_path / "designs"))
    rt._run_store = RunStore(root=tmp_path / "runs")
    return rt


def _save_approval_design(rt):
    return rt.tool_save({"name": "demo", "graph": {"name": "demo", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "draft", "type": "agent", "prompt": "Draft a release note.", "after": ["t"]},
        {"id": "big", "type": "condition", "expression": "out.draft.word_count > 20",
         "after": ["draft"]},
        {"id": "human", "type": "approval", "question": "Ship it?",
         "options": ["ship", "edit"], "after": ["big"]},
        {"id": "out", "type": "output", "after": ["human"]},
    ]}})


def test_runtime_run_pauses_for_agent_then_approval_and_persists(tmp_path):
    rt = _runtime(tmp_path)
    assert _save_approval_design(rt)["ok"] is True

    first = rt.tool_run({"name": "demo"})
    assert first["status"] == "awaiting_agent"
    assert first["pending"]["node_id"] == "draft"

    second = rt.tool_respond({"run_id": first["run_id"], "node_id": "draft",
                              "answer": {"word_count": 42}})
    assert second["status"] == "awaiting_approval"
    assert second["pending"]["question"] == "Ship it?"

    # The paused run is on disk, so a fresh runtime can pick it up.
    reloaded = rt._runs().load(first["run_id"])
    assert reloaded["pending"]["node_id"] == "human"

    third = rt.tool_respond({"run_id": first["run_id"], "node_id": "human", "answer": "ship"})
    assert third["status"] == "done"
    assert third["outputs"]["out"] == {"human": "ship"}


def test_runtime_prunes_downstream_and_surfaces_skipped(tmp_path):
    rt = _runtime(tmp_path)
    _save_approval_design(rt)
    run_id = rt.tool_run({"name": "demo"})["run_id"]
    done = rt.tool_respond({"run_id": run_id, "node_id": "draft",
                            "structured": {"word_count": 3}})
    assert done["status"] == "done"
    assert done["skipped"] == ["big", "human", "out"]
    assert done["outputs"] == {"draft": {"word_count": 3}}


def test_runtime_respond_rejects_a_node_that_is_not_pending(tmp_path):
    rt = _runtime(tmp_path)
    _save_approval_design(rt)
    run_id = rt.tool_run({"name": "demo"})["run_id"]
    bad = rt.tool_respond({"run_id": run_id, "node_id": "out", "answer": "x"})
    assert bad["ok"] is False
    assert "not waiting on" in bad["error"]


# -- terminal state is persisted -------------------------------------------
# Regression: run_plan saved through on_step before the cursor advanced past the last step,
# so a finished run stayed "running" on disk (and in the Runs list) forever.

def test_done_status_reaches_on_step():
    plan = _plan(
        {"id": "draft", "kind": "agent", "after": [], "prompt": "write"},
        {"id": "out", "kind": "output", "after": ["draft"], "keys": ["draft"]},
    )
    saved = []
    state = run_plan(plan, new_state(plan, "r1"), spawn=lambda *a: {"output": "hi"},
                     on_step=lambda s: saved.append((s["status"], s["cursor"])))
    assert state["status"] == "done"
    assert saved[-1][0] == "done", f"terminal state never saved; saw {saved}"


def test_finished_run_is_done_on_disk(tmp_path):
    """The stored run must not still say "running" after the last step (the actual bug)."""
    rt = _runtime(tmp_path)
    _save_approval_design(rt)
    run_id = rt.tool_run({"name": "demo"})["run_id"]
    rt.tool_respond({"run_id": run_id, "node_id": "draft", "structured": {"word_count": 3}})
    stored = rt._runs().load(run_id)
    assert stored["status"] == "done"


# -- condition coercion, inputs, context cap (plan Task 1) -------------------
# A confirmed crash: an agent that answers with a string field compared numerically raised a
# bare TypeError that escaped run_plan *and* tool_run, so the dispatcher returned a 500.

def test_string_output_compares_numerically_both_directions():
    outputs = {"draft": {"word_count": "25"}}
    assert evaluate_condition("out.draft.word_count > 20", outputs, {"draft"}) is True
    assert evaluate_condition("out.draft.word_count < 30", outputs, {"draft"}) is True
    # Quotes still mean a string literal, so the left side stays text there too.
    assert evaluate_condition("out.draft.word_count == '25'", outputs, {"draft"}) is True


def test_uncomparable_values_raise_step_error_not_type_error():
    outputs = {"draft": {"tags": [1, 2]}}
    with pytest.raises(StepError) as exc:
        evaluate_condition("out.draft.tags > 5", outputs, {"draft"})
    assert "cannot compare" in str(exc.value)


def test_a_condition_crash_inside_run_plan_fails_the_run_instead_of_raising():
    plan = _plan(
        {"id": "a", "kind": "agent", "after": [], "prompt": "x"},
        {"id": "c", "kind": "condition", "expression": "out.a.tags > 5", "after": ["a"]},
    )
    state = run_plan(plan, new_state(plan, "r3"), spawn=lambda *a: {"structured": {"tags": [1]}})
    assert state["status"] == "failed"
    assert state["error"]["node_id"] == "c"


def test_named_inputs_land_in_the_agent_context():
    from visual_workflow_hermes.runner import render_context

    outputs = {"draft": {"text": "hello", "words": 3}, "notes": "plain"}
    context = render_context(
        {"id": "polish", "kind": "agent", "after": [],
         "inputs": ["draft", "draft.words", "notes"]}, outputs)
    assert "hello" in context and "3" in context and "plain" in context
    assert context.count("--- output from") == 3


def test_an_unknown_named_input_is_a_step_error():
    from visual_workflow_hermes.runner import render_context

    with pytest.raises(StepError):
        render_context({"id": "x", "kind": "agent", "inputs": ["ghost"]}, {})
    with pytest.raises(StepError):
        render_context({"id": "x", "kind": "agent", "inputs": ["draft.nope"]},
                       {"draft": {"text": "hi"}})


def test_context_is_capped_per_block_with_a_marker():
    from visual_workflow_hermes.runner import MAX_CONTEXT_CHARS, render_context

    context = render_context({"id": "x", "kind": "agent", "after": ["big"]},
                             {"big": "w" * 10_000})
    assert len(context) < 10_000
    assert "truncated" in context
    assert MAX_CONTEXT_CHARS > 0


def test_failed_status_reaches_on_step():
    plan = _plan({"id": "a", "kind": "agent", "after": [], "prompt": "x"})
    saved = []
    state = run_plan(plan, new_state(plan, "r2"),
                     spawn=lambda *a: {"error": "boom"},
                     on_step=lambda s: saved.append(s["status"]))
    assert state["status"] == "failed"
    assert saved[-1] == "failed"


# -- approval gate timeouts (plan Task 2) ------------------------------------
# A gate that waits forever is the classic HITL production failure; the deadline travels with
# the pause so a run reloaded days later still knows when it expired.

def _gate_plan(**extra):
    step = {"id": "g", "kind": "approval", "after": [], "question": "ok?",
            "options": ["yes", "no"]}
    step.update(extra)
    return _plan(step, {"id": "o", "kind": "output", "after": ["g"], "keys": ["g"]})


def test_gate_timeout_fails_the_run_with_the_policy_in_the_error():
    from visual_workflow_hermes.runner import check_timeouts

    plan = _gate_plan(timeout_minutes=10, on_timeout="escalate")
    state = run_plan(plan, new_state(plan, "r5"))
    assert state["status"] == "awaiting_approval"
    waiting_since = state["pending"]["waiting_since"]
    assert state["pending"]["timeout_minutes"] == 10
    assert state["pending"]["on_timeout"] == "escalate"

    check_timeouts(state, now=waiting_since + 9 * 60)
    assert state["status"] == "awaiting_approval", "must not expire before the deadline"

    check_timeouts(state, now=waiting_since + 11 * 60)
    assert state["status"] == "failed"
    assert state["pending"] is None
    assert state["error"]["node_id"] == "g"
    assert "timed out" in state["error"]["msg"] and "escalate" in state["error"]["msg"]
    assert state["error"]["detail"] == "escalation requested"


def test_a_gate_without_a_timeout_waits_forever():
    from visual_workflow_hermes.runner import check_timeouts

    plan = _gate_plan()
    state = run_plan(plan, new_state(plan, "r6"))
    check_timeouts(state, now=state["pending"]["waiting_since"] + 10 * 365 * 24 * 3600)
    assert state["status"] == "awaiting_approval"


def test_late_answer_after_expiry_is_a_step_error_and_is_persisted():
    from visual_workflow_hermes.runner import check_timeouts

    plan = _gate_plan(timeout_minutes=1)
    state = run_plan(plan, new_state(plan, "r7"))
    check_timeouts(state, now=state["pending"]["waiting_since"] + 120)

    saved = []
    with pytest.raises(StepError) as exc:
        resume_plan(plan, state, "yes", on_step=lambda s: saved.append(s["status"]))
    assert "timed out" in str(exc.value)
    assert saved and saved[-1] == "failed"
