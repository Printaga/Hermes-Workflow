"""Scheduled runs: friendly cron building, validation, and the host cron-job seam.

A schedule trigger replays a saved design through Hermes' own scheduler. The job is created with
the ``cronjob_manage`` tool (``tools.cronjob_tools.cronjob``) — the same call ``hermes cron``
makes — with a *self-contained prompt* that makes the cron session invoke this plugin's tools.
Jobs have no field for a tool name plus arguments, which is why the replay is a prompt
(``triggers.schedule_plan``).

Everything here is failure-tolerant: no host scheduler (tests, plain tooling) yields
``available: false`` and an empty list, never an exception into the router.
"""
from __future__ import annotations

import json
import re

# Preset ids are what the canvas picker sends; labels live in the UI so each surface can word
# them for its own space.
PRESETS = ("daily", "weekdays", "weekly", "hourly", "custom")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_NAME_PREFIX = "workflow:"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# minute, hour, day-of-month, month, day-of-week
_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_FIELD_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")


def time_parts(value: str) -> tuple:
    """``"09:30"`` -> ``(9, 30)``; raises ValueError for anything else."""
    match = _TIME_RE.match((value or "").strip())
    if not match:
        raise ValueError(f"time must be HH:MM (24h), got {value!r}")
    return int(match.group(1)), int(match.group(2))


def weekday_index(value: str) -> int:
    """``"mon"`` -> 1 (cron day-of-week, Sunday = 0); raises ValueError for an unknown day."""
    wanted = (value or "").strip().lower()[:3]
    if wanted not in WEEKDAYS:
        raise ValueError(f"weekday must be one of {WEEKDAYS}, got {value!r}")
    return (WEEKDAYS.index(wanted) + 1) % 7


def build_cron(preset: str, time: str = "09:00", weekday: str = "mon", custom: str = "") -> str:
    """Turn a preset picker choice into a 5-field cron expression.

    ``custom`` is the advanced field: it is validated and returned verbatim (trimmed) so the
    canvas can keep whatever the user typed.
    """
    name = (preset or "").strip().lower()
    if name not in PRESETS:
        raise ValueError(f"preset must be one of {PRESETS}, got {preset!r}")
    if name == "custom":
        expression = (custom or "").strip()
        problem = validate_cron(expression)
        if problem:
            raise ValueError(problem)
        return expression
    hour, minute = time_parts(time)
    if name == "hourly":
        return f"{minute} * * * *"
    if name == "daily":
        return f"{minute} {hour} * * *"
    if name == "weekdays":
        return f"{minute} {hour} * * 1-5"
    return f"{minute} {hour} * * {weekday_index(weekday)}"


def _valid_field(raw: str, low: int, high: int) -> bool:
    for part in raw.split(","):
        part = part.strip()
        if not part:
            return False
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                return False
        if part == "*":
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            if not (start.isdigit() and end.isdigit()):
                return False
            start, end = int(start), int(end)
            if start > end or start < low or end > high:
                return False
            continue
        if not part.isdigit():
            return False
        if not low <= int(part) <= high:
            return False
    return True


def validate_cron(expression: str) -> str:
    """``""`` when *expression* is a usable 5-field cron, else a one-line problem statement."""
    text = (expression or "").strip()
    if not text:
        return "enter a cron expression (5 fields, e.g. 0 9 * * 1-5)"
    fields = text.split()
    if len(fields) != 5:
        return f"cron needs 5 fields (minute hour day month weekday), got {len(fields)}"
    for raw, (low, high), name in zip(fields, _FIELD_BOUNDS, _FIELD_NAMES):
        if not _valid_field(raw, low, high):
            return f"{name} field {raw!r} is not valid (allowed {low}-{high}, *, */n, a-b)"
    return ""


def describe_cron(expression: str) -> str:
    """A short human line for a cron expression; falls back to the expression itself."""
    text = (expression or "").strip()
    if validate_cron(text):
        return text
    minute, hour, dom, month, dow = text.split()
    if not (dom == "*" and month == "*"):
        return f"Cron {text}"
    if hour == "*":
        return "Every hour" + (f" at :{int(minute):02d}" if minute.isdigit() else "")
    if not (minute.isdigit() and hour.isdigit()):
        return f"Cron {text}"
    at = f"{int(hour):02d}:{int(minute):02d}"
    if dow == "*":
        return f"Daily at {at}"
    if dow == "1-5":
        return f"Weekdays at {at}"
    days = {str((i + 1) % 7): name.title() for i, name in enumerate(WEEKDAYS)}
    days["7"] = days["0"]  # cron accepts both 0 and 7 for Sunday
    if dow in days:
        return f"Every {days[dow]} at {at}"
    return f"Cron {text}"


# --------------------------------------------------------------------- job naming
def job_name(design: str) -> str:
    """The cron job name that marks a job as this plugin's replay of *design*."""
    return f"{_NAME_PREFIX}{(design or '').strip()}"


def design_of_job(name: str) -> str:
    """The design a job name replays; ``""`` when the job is not workflow-linked."""
    text = (name or "").strip()
    return text[len(_NAME_PREFIX):] if text.startswith(_NAME_PREFIX) else ""


# ---------------------------------------------------------------- host cron seam
def _cron(args: dict):
    """Call the host ``cronjob_manage`` tool; its JSON reply as a dict, or None if unavailable."""
    try:
        from tools.cronjob_tools import cronjob
    except Exception:
        return None
    try:
        raw = cronjob(**args)
    except Exception:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _job_view(job: dict) -> dict:
    """The subset the Schedules view needs, in one shape."""
    name = str(job.get("name") or "")
    return {
        "job_id": str(job.get("job_id") or job.get("id") or ""),
        "name": name,
        "design": design_of_job(name),
        "schedule": str(job.get("schedule") or ""),
        "next_run_at": job.get("next_run_at"),
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "state": str(job.get("state") or ("enabled" if job.get("enabled", True) else "paused")),
    }


def list_workflow_jobs() -> dict:
    """``{"jobs": [...], "available": bool}`` for jobs this plugin created."""
    reply = _cron({"action": "list"})
    if reply is None or not reply.get("success"):
        return {"jobs": [], "available": False}
    jobs = [_job_view(j) for j in reply.get("jobs") or [] if isinstance(j, dict)]
    return {"jobs": [j for j in jobs if j["design"]], "available": True}


def apply_action(action: str, job_id: str) -> dict:
    """Pause / resume / run-now / remove one workflow job. Returns ``{ok, job?, error?}``.

    Only jobs this plugin created (names starting with ``workflow:``) may be acted on:
    the Schedules view lists workflow jobs exclusively, so anything else is a foreign
    cron job the plugin must not pause, resume, trigger, or delete.
    """
    verb = (action or "").strip().lower()
    if verb not in ("pause", "resume", "run", "remove"):
        return {"ok": False, "error": f"unknown schedule action {action!r}"}
    target = (job_id or "").strip()
    if not target:
        return {"ok": False, "error": "a job id is required"}
    listing = _cron({"action": "list"})
    if listing is None:
        return {"ok": False, "error": "the host scheduler is not available here"}
    if not listing.get("success"):
        return {"ok": False, "error": str(listing.get("error") or "the host scheduler refused it")}
    jobs = listing.get("jobs") or []
    if not isinstance(jobs, list):
        return {"ok": False, "error": "the host scheduler returned a malformed job list"}
    match = next(
        (
            job
            for job in jobs
            if isinstance(job, dict) and str(job.get("job_id") or job.get("id") or "") == target
        ),
        None,
    )
    if match is None:
        return {"ok": False, "error": f"job {target!r} is not a workflow schedule: refusing {verb}"}
    if not str(match.get("name") or "").startswith(_NAME_PREFIX):
        return {
            "ok": False,
            "error": f"job {target!r} is not a workflow schedule "
            f"(name must start with {_NAME_PREFIX!r}): refusing {verb}",
        }
    reply = _cron({"action": verb, "job_id": target})
    if reply is None:
        return {"ok": False, "error": "the host scheduler is not available here"}
    if not reply.get("success"):
        return {"ok": False, "error": str(reply.get("error") or "the host scheduler refused it")}
    job = reply.get("job")
    return {"ok": True, "job": _job_view(job) if isinstance(job, dict) else None}


def schedule_design(designer: dict, *, cron: str = "", deliver: str = "origin") -> dict:
    """Create (or update) the cron job that replays *designer*.

    The cron expression comes from the canvas picker when given, else from the design's own
    trigger node. ``triggers.schedule_plan`` still owns the prompt: the job must be a
    self-contained instruction, never a tool call.
    """
    from .triggers import schedule_plan

    # Strip once and use the stripped name everywhere: job_name/design_of_job strip, so a
    # padded name would otherwise never match its existing job and would create a duplicate.
    name = str(designer.get("name") or "").strip()
    designer = {**designer, "name": name}
    expression = (cron or "").strip()
    if expression:
        problem = validate_cron(expression)
        if problem:
            return {"ok": False, "error": problem}
        trig = next((n for n in designer.get("nodes", [])
                     if isinstance(n, dict) and n.get("type") == "trigger"), None)
        if trig is None:
            return {"ok": False, "error": "design has no trigger node"}
        # The plan builder reads the design, so hand it a copy carrying the chosen schedule.
        designer = {
            **designer,
            "nodes": [
                {**n, "trigger_mode": "schedule", "schedule": expression}
                if n is trig else n
                for n in designer.get("nodes", [])
            ],
        }
    try:
        plan = schedule_plan(designer, deliver=deliver)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    existing = next(
        (j for j in list_workflow_jobs()["jobs"] if j["design"] == name), None
    )
    if existing and existing["job_id"]:
        reply = _cron({
            "action": "update",
            "job_id": existing["job_id"],
            "schedule": plan["schedule"],
            "prompt": plan["prompt"],
            "deliver": plan["deliver"],
        })
        created = False
    else:
        reply = _cron(plan)
        created = True
    if reply is None:
        return {"ok": False, "error": "the host scheduler is not available here"}
    if not reply.get("success"):
        return {"ok": False, "error": str(reply.get("error") or "the host scheduler refused it")}
    job = reply.get("job")
    return {
        "ok": True,
        "created": created,
        "cron": plan["schedule"],
        "job": _job_view(job) if isinstance(job, dict) else None,
    }
