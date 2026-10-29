"""Delivery targets for the output-node picker — the host's own channel directory.

The host already maintains the list of chats it can send to: the gateway builds
``<hermes home>/channel_directory.json`` every few minutes from live platform traffic, and
``send_message_tool(action="list")`` renders that same data for the model. This module is the
plugin's thin, failure-tolerant view of it, exactly like ``profiles.py`` is for bots.

Shape returned to the canvas: ``[{id, label, kind, platform}]`` where ``id`` is a usable
``send_message_tool`` target:

* ``telegram:8522302999`` — a discovered chat (``kind`` is the directory's ``dm``/``group``/…)
* ``telegram`` — that platform's home channel (``kind: "home"``)

Nothing here opens a platform socket and nothing here sends: ``delivery.py`` owns the send, and
a failed send is a receipt on the run, never an exception.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# Session origins that are not messaging channels: they can appear in the directory's platform
# keys but are not valid send targets (gateway/channel_directory.py::_SKIP_SESSION_DISCOVERY).
NOT_MESSAGING = frozenset({"local", "api_server", "webhook"})


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _directory(home: Optional[Path] = None) -> dict:
    """``{"platforms": {<platform>: [{id, name, type}, ...]}}``; ``{}`` when unreadable.

    The host function is preferred (it re-applies aliases and session discovery); the on-disk
    file is the fallback for a process where ``gateway`` cannot be imported (plain tooling).
    """
    try:
        from gateway.channel_directory import load_directory

        data = load_directory()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        raw = (Path(home) if home else _home()) / "channel_directory.json"
        data = json.loads(raw.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def list_delivery_targets(home: Optional[Path] = None) -> list[dict]:
    """``[{id, label, kind, platform}]``; empty when the host has no connected platform."""
    platforms = _directory(home).get("platforms") or {}
    if not isinstance(platforms, dict):
        return []
    out: list[dict] = []
    for platform, entries in sorted(platforms.items()):
        name = str(platform or "").strip().lower()
        if not name or name in NOT_MESSAGING:
            continue
        found = False
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            chat_id = str(entry.get("id") or "").strip()
            if not chat_id:
                continue
            found = True
            out.append(
                {
                    "id": f"{name}:{chat_id}",
                    "label": f"{entry.get('name') or chat_id} \u00b7 {name}",
                    "kind": str(entry.get("type") or "channel"),
                    "platform": name,
                }
            )
        # A platform the gateway has traffic for implies a configured bot, so its home channel
        # is a real target. Discovery may simply not have seen a chat yet.
        if found:
            out.append(
                {
                    "id": name,
                    "label": f"{name.title()} \u2014 home channel",
                    "kind": "home",
                    "platform": name,
                }
            )
    return out


def list_host_channels(home: Optional[Path] = None) -> dict:
    """``{"channels": [...], "available": bool}`` — always safe to return to the canvas."""
    try:
        channels = list_delivery_targets(home)
    except Exception:  # a corrupt directory is "no channels", never a 500
        channels = []
    return {"channels": channels, "available": bool(channels)}
