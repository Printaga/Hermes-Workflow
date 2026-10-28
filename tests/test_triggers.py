import pytest

from visual_workflow_hermes.triggers import schedule_plan, webhook_stub


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


def test_webhook_stub_declares_without_firing():
    design = {"name": "hook", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": "webhook",
         "webhook_path": "/incoming/foo", "after": []}]}
    stub = webhook_stub(design)
    assert stub["declared"] is True and stub["phase"] == 2
    assert stub["path"] == "/incoming/foo"
