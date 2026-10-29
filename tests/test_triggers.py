import pytest

from visual_workflow_hermes.triggers import schedule_plan


def _schedule_design(cron="0 9 * * *"):
    return {"name": "daily", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "schedule",
         "schedule": cron, "after": []},
    ]}


def test_schedule_plan_targets_cronjob_manage_create():
    plan = schedule_plan(_schedule_design())
    assert plan["action"] == "create"
    assert plan["schedule"] == "0 9 * * *"
    assert plan["name"] == "workflow:daily"
    assert plan["enabled_toolsets"] == ["visual-workflow"]
    # cron takes a prompt, never a tool name plus args
    assert "workflow_design_run" in plan["prompt"]
    assert "args" not in plan


def test_prompt_is_self_contained_and_names_both_resume_cases():
    prompt = schedule_plan(_schedule_design())["prompt"]
    assert "workflow_design_respond" in prompt
    assert "awaiting_approval" in prompt     # cron must not auto-approve
    assert "awaiting_agent" in prompt


def test_schedule_plan_rejects_missing_cron():
    with pytest.raises(ValueError, match="cron expression"):
        schedule_plan(_schedule_design(cron="  "))


def test_schedule_plan_rejects_non_schedule_trigger():
    design = {"name": "x", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "manual", "after": []}]}
    with pytest.raises(ValueError, match="not schedule"):
        schedule_plan(design)


def test_schedule_plan_rejects_a_design_with_no_trigger():
    with pytest.raises(ValueError, match="no trigger"):
        schedule_plan({"name": "x", "nodes": []})


def test_webhook_is_not_offered_as_a_trigger_mode():
    """A plugin cannot open an inbound route, so a mode that records a URL would be a lie.

    Hermes' own webhook subscriptions fire an existing cron job; README points there instead.
    """
    from visual_workflow_hermes import triggers
    from visual_workflow_hermes.schema import TRIGGER_MODES

    assert "webhook" not in TRIGGER_MODES
    assert not hasattr(triggers, "webhook_stub")
