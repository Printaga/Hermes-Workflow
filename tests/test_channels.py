"""Delivery-target picker data: the host channel directory, read and never sent to.

The seam is the host's own ``channel_directory.json`` (built by the gateway) — the same data
``send_message_tool(action="list")`` renders. Nothing here imports a platform adapter, opens a
socket, or needs a token: a missing/corrupt directory is simply "no channels discovered".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from visual_workflow_hermes import channels


def _write(home: Path, platforms: dict) -> None:
    (home / "channel_directory.json").write_text(
        json.dumps({"updated_at": "2026-10-29T00:00:00", "platforms": platforms}),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _no_host_import(monkeypatch):
    """Force the on-disk fallback so the test does not depend on the host checkout."""

    def only_file(home=None):
        try:
            raw = (Path(home) if home else channels._home()) / "channel_directory.json"
            return json.loads(raw.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}

    monkeypatch.setattr(channels, "_directory", only_file)


def test_the_directory_reader_never_raises(monkeypatch):
    """A missing home is an empty directory, not an exception into the router."""
    assert channels._directory(Path("/nonexistent-home")) == {}
    monkeypatch.setitem(sys.modules, "gateway.channel_directory", None)
    assert isinstance(channels._directory(Path("/nonexistent-home")), dict)


def test_a_discovered_chat_becomes_a_send_target(tmp_path):
    _write(tmp_path, {"telegram": [{"id": "8522302999", "name": "Ronny Skog", "type": "dm"}]})
    listed = channels.list_delivery_targets(tmp_path)
    chat = listed[0]
    assert chat == {
        "id": "telegram:8522302999",
        "label": "Ronny Skog \u00b7 telegram",
        "kind": "dm",
        "platform": "telegram",
    }


def test_each_discovered_platform_also_offers_its_home_channel(tmp_path):
    _write(tmp_path, {"telegram": [{"id": "1", "name": "A", "type": "dm"}]})
    home = [c for c in channels.list_delivery_targets(tmp_path) if c["kind"] == "home"]
    assert [c["id"] for c in home] == ["telegram"]
    assert "home channel" in home[0]["label"]


def test_non_messaging_platforms_are_not_offered(tmp_path):
    _write(tmp_path, {
        "api_server": [{"id": "x", "name": "x", "type": "dm"}],
        "local": [{"id": "y", "name": "y", "type": "dm"}],
        "webhook": [{"id": "z", "name": "z", "type": "dm"}],
        "slack": [{"id": "C1", "name": "#ops", "type": "channel"}],
    })
    ids = [c["id"] for c in channels.list_delivery_targets(tmp_path)]
    assert ids == ["slack:C1", "slack"]


def test_a_missing_directory_is_no_channels_rather_than_an_error(tmp_path):
    assert channels.list_host_channels(tmp_path) == {"channels": [], "available": False}


def test_a_corrupt_directory_is_no_channels(tmp_path):
    (tmp_path / "channel_directory.json").write_text("{not json", encoding="utf-8")
    assert channels.list_host_channels(tmp_path)["channels"] == []


def test_an_empty_platform_list_is_no_channels(tmp_path):
    _write(tmp_path, {"telegram": []})
    payload = channels.list_host_channels(tmp_path)
    assert payload == {"channels": [], "available": False}


def test_entries_without_an_id_are_skipped(tmp_path):
    _write(tmp_path, {"telegram": [{"name": "nameless"}, {"id": "", "name": "blank"}]})
    assert channels.list_delivery_targets(tmp_path) == []
