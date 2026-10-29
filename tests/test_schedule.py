"""Scheduled runs: cron building/validation, and the exact ``cronjob_manage`` payload.

No test touches the live scheduler: ``schedule._cron`` is the single seam and every test below
replaces it. What is pinned is the contract that matters — a job's schedule, its name (so the
Schedules view can find it again), and a *self-contained prompt* that replays the design through
this plugin's own tools instead of a tool name plus arguments.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from visual_workflow_hermes import schedule

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ build_cron
def test_daily_preset_is_a_fixed_time_every_day():
    assert schedule.build_cron("daily", time="09:30") == "30 9 * * *"


def test_weekdays_preset_excludes_the_weekend():
    assert schedule.build_cron("weekdays", time="18:05") == "5 18 * * 1-5"


def test_weekly_preset_uses_the_chosen_weekday():
    assert schedule.build_cron("weekly", time="08:00", weekday="fri") == "0 8 * * 5"


def test_sunday_is_cron_day_zero():
    assert schedule.build_cron("weekly", time="08:00", weekday="sun") == "0 8 * * 0"


def test_hourly_preset_keeps_the_minute():
    assert schedule.build_cron("hourly", time="00:15") == "15 * * * *"


def test_the_advanced_custom_expression_is_validated_and_passed_through():
    assert schedule.build_cron("custom", custom="  0 9 1 * * ") == "0 9 1 * *"
    with pytest.raises(ValueError, match="cron needs 5 fields"):
        schedule.build_cron("custom", custom="0 9 *")


def test_an_unknown_preset_is_refused():
    with pytest.raises(ValueError, match="preset must be one of"):
        schedule.build_cron("fortnightly")


@pytest.mark.parametrize("value", ["", "9", "9am", "24:00", "09:60", "09-00"])
def test_a_bad_time_is_refused(value):
    with pytest.raises(ValueError, match="HH:MM"):
        schedule.time_parts(value)


# ----------------------------------------------------------------- validate_cron
@pytest.mark.parametrize("expression", [
    "0 9 * * *", "*/15 * * * *", "0 9 * * 1-5", "30 6 1,15 * *", "0 0 1 1 *", "5 4 * * 0-6",
])
def test_valid_cron_expressions(expression):
    assert schedule.validate_cron(expression) == ""


@pytest.mark.parametrize("expression", [
    "", "0 9 * *", "0 9 * * * *", "60 9 * * *", "0 24 * * *", "0 9 0 * *", "0 9 * 13 *",
    "0 9 * * 8", "zero 9 * * *", "*/0 * * * *", "0 9 * * 5-1",
])
def test_invalid_cron_expressions_say_which_field(expression):
    problem = schedule.validate_cron(expression)
    assert problem and isinstance(problem, str)


def test_validate_cron_names_the_offending_field():
    assert "minute" in schedule.validate_cron("60 9 * * *")
    assert "day-of-week" in schedule.validate_cron("0 9 * * 8")


# ---------------------------------------------------------------- describe_cron
def test_describe_cron_reads_common_shapes():
    assert schedule.describe_cron("0 9 * * *") == "Daily at 09:00"
    assert schedule.describe_cron("30 18 * * 1-5") == "Weekdays at 18:30"
    assert schedule.describe_cron("0 8 * * 1") == "Every Mon at 08:00"
    assert schedule.describe_cron("15 * * * *") == "Every hour at :15"
    assert schedule.describe_cron("0 9 1 * *") == "Cron 0 9 1 * *"


# --------------------------------------------------------------------- naming
def test_job_names_round_trip_to_the_design():
    assert schedule.job_name("daily-report") == "workflow:daily-report"
    assert schedule.design_of_job("workflow:daily-report") == "daily-report"
    assert schedule.design_of_job("some other cron job") == ""


# ------------------------------------------------------------- host cron seam
class CronCalls(list):
    """Recorded ``cronjob_manage`` calls plus the canned reply they answer with."""

    def __init__(self, reply):
        super().__init__()
        self.box = {"reply": reply}


@pytest.fixture
def cron(monkeypatch):
    """Record ``cronjob_manage`` calls and answer with a canned reply."""
    calls = CronCalls({"success": True, "job": {"job_id": "job1", "name": "workflow:daily"}})

    def fake(args):
        calls.append(args)
        reply = calls.box["reply"]
        return dict(reply) if isinstance(reply, dict) else reply

    monkeypatch.setattr(schedule, "_cron", fake)
    return calls


def _design(mode="schedule", cron_expr="0 9 * * *"):
    return {"name": "daily", "nodes": [
        {"id": "t", "type": "trigger", "trigger_mode": mode, "schedule": cron_expr, "after": []},
        {"id": "a", "type": "agent", "prompt": "summarise", "after": ["t"]},
    ]}


def test_listing_marks_only_workflow_jobs_and_normalises_them(cron):
    cron.box["reply"] = {"success": True, "jobs": [
        {"job_id": "j1", "name": "workflow:daily", "schedule": "0 9 * * *",
         "next_run_at": "2026-10-30T09:00", "state": "enabled"},
        {"job_id": "j2", "name": "inbox sweep", "schedule": "every 2h"},
    ]}
    listed = schedule.list_workflow_jobs()
    assert listed["available"] is True
    (job,) = listed["jobs"]
    assert job["job_id"] == "j1" and job["design"] == "daily"
    assert job["schedule"] == "0 9 * * *" and job["state"] == "enabled"


def test_listing_without_a_host_scheduler_is_unavailable_not_empty(cron):
    cron.box["reply"] = None
    assert schedule.list_workflow_jobs() == {"jobs": [], "available": False}


def test_a_refused_listing_is_unavailable(cron):
    cron.box["reply"] = {"success": False, "error": "cron store unreadable"}
    assert schedule.list_workflow_jobs()["available"] is False


@pytest.mark.parametrize("action", ["pause", "resume", "run", "remove"])
def test_actions_pass_through_to_the_host_tool(cron, action):
    cron.box["reply"] = {"success": True, "job": {"job_id": "j1", "name": "workflow:daily"}}
    assert schedule.apply_action(action, "j1")["ok"] is True
    assert cron == [{"action": action, "job_id": "j1"}]


def test_an_unknown_action_never_reaches_the_host(cron):
    assert schedule.apply_action("explode", "j1")["ok"] is False
    assert cron == []


def test_a_host_refusal_is_reported(cron):
    cron.box["reply"] = {"success": False, "error": "job not found"}
    outcome = schedule.apply_action("pause", "ghost")
    assert outcome["ok"] is False and "job not found" in outcome["error"]


# --------------------------------------------------------------- schedule_design
def test_creating_a_job_uses_the_self_contained_replay_prompt(cron):
    outcome = schedule.schedule_design(_design(), cron="0 9 * * 1-5")
    assert outcome["ok"] is True and outcome["created"] is True
    # The first call is the existing-job lookup; the create is the one that matters here.
    (payload,) = [call for call in cron if call["action"] == "create"]
    assert payload["action"] == "create"
    assert payload["schedule"] == "0 9 * * 1-5"
    assert payload["name"] == "workflow:daily"
    assert payload["enabled_toolsets"] == ["visual-workflow"]
    assert "workflow_design_run" in payload["prompt"]
    assert "awaiting_approval" in payload["prompt"], "cron must never auto-approve a gate"


def test_an_existing_job_is_updated_in_place_rather_than_duplicated(cron):
    calls = cron

    def fake(args):
        calls.append(args)
        if args["action"] == "list":
            return {"success": True, "jobs": [
                {"job_id": "job1", "name": "workflow:daily", "schedule": "0 9 * * *"}]}
        return {"success": True, "job": {"job_id": "job1", "name": "workflow:daily"}}

    schedule._cron = fake  # type: ignore[assignment]
    outcome = schedule.schedule_design(_design(), cron="0 12 * * *")
    assert outcome["ok"] is True and outcome["created"] is False
    update = [c for c in calls if c["action"] == "update"]
    assert update and update[0]["job_id"] == "job1" and update[0]["schedule"] == "0 12 * * *"


def test_a_manual_trigger_is_refused_without_an_explicit_cron(cron):
    outcome = schedule.schedule_design(_design(mode="manual"))
    assert outcome["ok"] is False and "schedule" in outcome["error"]
    assert cron == []


def test_an_invalid_cron_is_refused_before_the_host_is_called(cron):
    outcome = schedule.schedule_design(_design(), cron="0 9 *")
    assert outcome["ok"] is False and "5 fields" in outcome["error"]
    assert cron == []


def test_a_missing_trigger_is_refused(cron):
    outcome = schedule.schedule_design({"name": "x", "nodes": []}, cron="0 9 * * *")
    assert outcome["ok"] is False and "trigger" in outcome["error"]
    assert cron == []


def test_scheduling_without_a_host_scheduler_says_so(monkeypatch):
    monkeypatch.setattr(schedule, "_cron", lambda args: None)
    outcome = schedule.schedule_design(_design())
    assert outcome["ok"] is False and "not available" in outcome["error"]


def test_the_job_reply_is_returned_in_the_view_shape(cron):
    cron.box["reply"] = {"success": True, "job": {
        "job_id": "job1", "name": "workflow:daily", "schedule": "0 9 * * *",
        "next_run_at": "2026-10-30T09:00", "state": "enabled"}}
    job = schedule.schedule_design(_design())["job"]
    assert job == {"job_id": "job1", "name": "workflow:daily", "design": "daily",
                   "schedule": "0 9 * * *", "next_run_at": "2026-10-30T09:00",
                   "last_run_at": None, "last_status": None, "state": "enabled"}


# ------------------------------------------------------------ canvas parity
CANVASES = {
    "dashboard": ROOT / "dashboard" / "dist" / "index.js",
    "desktop": ROOT / "desktop" / "plugin.js",
    "widget": ROOT / "widgets" / "designer.html",
}


def test_no_canvas_hides_the_time_field_behind_the_hourly_preset():
    """``build_cron("hourly")`` takes the MINUTE from the time field.

    All three canvases hid that field for ``hourly``, so "every hour" was silently pinned to
    :00 and the :15 the user wanted was unreachable — a control that lied by omission.
    """
    for name, path in CANVASES.items():
        source = path.read_text(encoding="utf-8")
        assert not re.search(r'[Pp]reset\s*!==\s*"hourly"', source), (
            f"{name}: the time field must stay visible for the hourly preset"
        )
        assert not re.search(r'[Pp]reset\s*===\s*"hourly"\s*\|\|', source), (
            f"{name}: an hourly guard still hides a field that hourly needs"
        )
        assert re.search(r'[Pp]reset\s*!==\s*"custom"', source), (
            f"{name}: only the advanced (custom cron) preset may hide the time field"
        )
        assert 'field("time (24h)"' in source or 'title: TIPS["trigger.time"]' in source, (
            f"{name}: the time control is gone entirely"
        )


def test_the_host_seam_parses_the_json_string_the_tool_returns(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("tools.cronjob_tools")
    mod.cronjob = lambda **kw: json.dumps({"success": True, "count": 0, "jobs": []})
    tools = types.ModuleType("tools")
    tools.cronjob_tools = mod
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.cronjob_tools", mod)
    assert schedule._cron({"action": "list"}) == {"success": True, "count": 0, "jobs": []}
