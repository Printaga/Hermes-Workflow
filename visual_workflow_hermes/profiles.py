"""Host profiles ("bots") for the agent-node picker, and the model one implies.

The host owns profiles: ``hermes_cli.profiles.list_profiles`` is the same call behind
``GET /api/profiles``. This module is the plugin's thin, failure-tolerant view of it — the
dashboard router and the tools must import where the host package is absent (unit tests,
plain tooling), so nothing is imported at module scope and every failure degrades to "no
profiles" rather than an exception.

A step names *one* model, never a provider: the provider is derived from the model through the
host catalog (``models.provider_for_model``), so the canvas has a single select and cannot
produce a model/provider pair the host would reject.

Limitation (deliberate, v1): choosing a profile selects the *model* an agent step runs on. A
subagent still executes inside the host profile that is serving the request —
``SubagentLaunchRequest`` has no profile/home field — so a workflow cannot re-home a step to
another profile's skills, SOUL or channels.
"""
from __future__ import annotations

from typing import Optional


def list_host_profiles() -> list[dict]:
    """``[{name, label, model, is_default, description}]``; empty when unavailable."""
    try:
        from hermes_cli.profiles import list_profiles

        # lazy_skill_count keeps this cheap: the call is made per request by the drawer.
        infos = list_profiles(lazy_skill_count=True)
    except Exception:  # host not importable, or its profile store is unreadable
        return []
    out: list[dict] = []
    for info in infos:
        name = str(getattr(info, "name", "") or "")
        if not name:
            continue
        label = (
            str(getattr(info, "bot_title", "") or "")
            or str(getattr(info, "display_name", "") or "")
            or name
        )
        out.append(
            {
                "name": name,
                "label": label,
                "model": str(getattr(info, "model", "") or ""),
                "is_default": bool(getattr(info, "is_default", False)),
                "description": str(getattr(info, "description", "") or ""),
            }
        )
    return out


def profile_choice(name: str, profiles: Optional[list[dict]] = None) -> Optional[dict]:
    """The profile record for *name*, or None when the name is blank/unknown.

    Unguarded JSON can hand us a number or an object; that is "no choice", not a crash.
    """
    if not isinstance(name, str):
        return None
    wanted = name.strip()
    if not wanted:
        return None
    for profile in profiles if profiles is not None else list_host_profiles():
        if profile.get("name") == wanted:
            return profile
    return None


def step_model(step: dict, profiles: Optional[list[dict]] = None) -> Optional[str]:
    """Model for an agent step: the node's own field wins over its profile's model.

    Returns None when neither names one, which leaves the host's own default in place.
    """
    raw_model = step.get("model")
    model = raw_model.strip() if isinstance(raw_model, str) else None
    if model:
        return model
    raw_profile = step.get("profile")
    if raw_profile not in (None, "") and not isinstance(raw_profile, str):
        return None
    chosen = profile_choice(raw_profile or "", profiles)
    if chosen:
        chosen_model = chosen.get("model")
        return chosen_model.strip() if isinstance(chosen_model, str) and chosen_model.strip() else None
    return None
