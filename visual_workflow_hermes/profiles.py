"""Host profiles ("bots") for the agent-node picker, and the model/provider they imply.

The host owns profiles: ``hermes_cli.profiles.list_profiles`` is the same call behind
``GET /api/profiles``. This module is the plugin's thin, failure-tolerant view of it — the
dashboard router and the tools must import where the host package is absent (unit tests,
plain tooling), so nothing is imported at module scope and every failure degrades to "no
profiles" rather than an exception.

Limitation (deliberate, v1): choosing a profile selects the *model and provider* an agent
step runs on. A subagent still executes inside the host profile that is serving the request —
``SubagentLaunchRequest`` has no profile/home field — so a workflow cannot re-home a step to
another profile's skills, SOUL or channels.
"""
from __future__ import annotations

from typing import Optional


def list_host_profiles() -> list[dict]:
    """``[{name, label, model, provider, is_default, description}]``; empty when unavailable."""
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
                "provider": str(getattr(info, "provider", "") or ""),
                "is_default": bool(getattr(info, "is_default", False)),
                "description": str(getattr(info, "description", "") or ""),
            }
        )
    return out


def profile_choice(name: str, profiles: Optional[list[dict]] = None) -> Optional[dict]:
    """The profile record for *name*, or None when the name is blank/unknown."""
    wanted = (name or "").strip()
    if not wanted:
        return None
    for profile in profiles if profiles is not None else list_host_profiles():
        if profile.get("name") == wanted:
            return profile
    return None


def step_model_provider(step: dict, profiles: Optional[list[dict]] = None) -> tuple:
    """``(model, provider)`` for an agent step: explicit node fields win over the profile.

    Returns ``(None, None)`` when the node names no profile and no model/provider, which
    leaves the host's own default in place.
    """
    model = step.get("model") or None
    provider = step.get("provider") or None
    if model and provider:
        return model, provider
    chosen = profile_choice(step.get("profile", ""), profiles)
    if chosen:
        model = model or (chosen.get("model") or None)
        provider = provider or (chosen.get("provider") or None)
    return model, provider
