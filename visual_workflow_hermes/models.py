"""Host model catalog for the agent-node picker.

The host owns the catalog. This is the plugin's failure-tolerant view of the same call that
backs ``GET /api/model/options`` (``hermes_cli/web_routers/models.py`` ->
``hermes_cli.inventory.build_model_options_payload``), i.e. the payload Hermes' own model
picker renders: ``{"providers": [{slug, name, models: [id], authenticated: bool}], "model",
"provider"}``.

Same discipline as ``profiles.py``: nothing is imported at module scope, so the router and the
tools import where the host package is absent, and every failure degrades to "no models" —
which the canvas renders as a free-text field rather than an empty select or a 500.

The catalog is not free: a cold build probes providers. A short process-local cache keeps a
redraw of the drawer (or a workflow step launch) from rebuilding it per request.
"""
from __future__ import annotations

import copy
import time
from typing import Optional

# Provider catalogs come from the host's disk cache on a normal build, but a cold models.dev
# cache can take seconds. One minute is long enough to absorb a drawer redraw and a step launch,
# short enough that a model switched in the host's own UI shows up without a restart.
_CACHE_TTL_S = 60.0
_cache: "tuple[float, dict] | None" = None


def list_host_models(refresh: bool = False) -> dict:
    """``{"providers": [{slug, label, models}], "available": bool, "current": {model, provider}}``.

    ``available`` is False when the host catalog could not be read (or every provider was
    unusable), which is the canvas' cue to fall back to free-text.
    """
    global _cache
    # The cache is shared process-wide: hand every caller its own copy, or one route that
    # mutates the payload poisons the catalog for everyone until the TTL expires.
    if not refresh and _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL_S:
        return copy.deepcopy(_cache[1])
    payload = _read_catalog()
    _cache = (time.monotonic(), payload)
    return copy.deepcopy(payload)


def clear_cache() -> None:
    """Drop the cached catalog (tests, and the route's ``refresh=1``)."""
    global _cache
    _cache = None


def _read_catalog() -> dict:
    try:
        from hermes_cli.inventory import build_model_options_payload, load_picker_context

        raw = build_model_options_payload(load_picker_context())
    except Exception:  # host not importable, or its catalog build failed
        return {"providers": [], "available": False, "current": {}}
    if not isinstance(raw, dict):
        return {"providers": [], "available": False, "current": {}}

    providers: list[dict] = []
    for row in raw.get("providers") or []:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "").strip()
        models: list[str] = []
        for entry in row.get("models") or []:
            # The host hands plain id strings today; accept a dict entry too so a payload
            # change degrades to "no models" instead of a 500.
            model_id = entry.get("id") if isinstance(entry, dict) else entry
            model_id = str(model_id or "").strip()
            if model_id and model_id not in models:
                models.append(model_id)
        if not slug or not models:
            continue
        providers.append(
            {
                "slug": slug,
                "label": str(row.get("name") or row.get("label") or slug),
                "models": models,
            }
        )
    return {
        "providers": providers,
        "available": bool(providers),
        "current": {
            "model": str(raw.get("model") or ""),
            "provider": str(raw.get("provider") or ""),
        },
    }


def provider_for_model(model: str, catalog: Optional[dict] = None) -> str:
    """Provider slug that serves *model*, or "" when it cannot be known.

    A model id is usually provider-prefixed (``anthropic/claude-…``) so the answer is
    unambiguous; when the same id is listed by several providers the host's current provider
    wins, and an unclear case returns "" so the host's own default routing stays in charge
    instead of guessing wrong.
    """
    wanted = (model or "").strip()
    if not wanted:
        return ""
    payload = catalog if catalog is not None else list_host_models()
    current = payload.get("current") or {}
    hits = [
        str(p.get("slug") or "")
        for p in payload.get("providers") or []
        if wanted in (p.get("models") or [])
    ]
    hits = [slug for slug in hits if slug]
    if not hits:
        return ""
    if len(hits) == 1:
        return hits[0]
    if current.get("model") == wanted and current.get("provider") in hits:
        return str(current["provider"])
    return ""
