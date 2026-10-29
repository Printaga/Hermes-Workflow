"""Every node kind and every inspector option explains itself, on all three canvases.

The three designers are copies (no build step, so the canvas core is duplicated on purpose):
``dashboard/dist/index.js``, ``desktop/plugin.js`` and ``widgets/designer.html``. Each carries the
same ``TIPS`` table and applies it with a native ``title`` — the smallest mechanism that works in
a React tab, inside SVG (a child ``<title>``) and in a standalone HTML file alike.

These tests are source greps, in the style of ``test_dashboard.py`` / ``test_desktop.py``: they
pin that the table is complete, that every sentence is a sentence, and that each surface actually
*uses* the entry instead of merely declaring it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SURFACES = {
    "dashboard": ROOT / "dashboard" / "dist" / "index.js",
    "desktop": ROOT / "desktop" / "plugin.js",
    "widget": ROOT / "widgets" / "designer.html",
}

# The five runnable node kinds plus the annotation-only sticky note.
KIND_KEYS = ("trigger", "agent", "condition", "approval", "output", "note")

# One key per inspector option. Names mirror the field the canvas writes (``<kind>.<field>``),
# so a new option without a tip shows up here as a failure rather than as a silent gap.
OPTION_KEYS = (
    "trigger.trigger_mode",
    "trigger.preset",
    "trigger.time",
    "trigger.weekday",
    "trigger.schedule",
    "agent.prompt",
    "agent.profile",
    "agent.model",
    "agent.provider",
    "agent.retries",
    "condition.expression",
    "approval.question",
    "approval.options",
    "approval.timeout",
    "approval.on_timeout",
    "output.parents",
    "output.deliver",
    "output.target",
    "output.target.custom",
    "note.text",
    "note.color",
)

REQUIRED = KIND_KEYS + OPTION_KEYS


def _read(path: Path) -> str:
    assert path.is_file(), f"missing canvas at {path}"
    return path.read_text(encoding="utf-8")


def _tips_block(source: str) -> str:
    """The text of the ``TIPS = { ... }`` object literal."""
    start = source.find("TIPS = {")
    assert start >= 0, "canvas must declare a TIPS table"
    end = min(
        (i for i in (source.find("\n  };", start), source.find("\n};", start)) if i > 0),
        default=-1,
    )
    assert end > start, "TIPS table must be a closed object literal"
    return source[start:end]


_TIP_RE = re.compile(r'"?([a-z][a-z._]*)"?\s*:\s*"((?:[^"\\]|\\.)*)"')


def _tips(source: str) -> dict:
    return {key: value for key, value in _TIP_RE.findall(_tips_block(source))}


@pytest.fixture(scope="module", params=sorted(SURFACES))
def surface(request):
    return request.param, _read(SURFACES[request.param])


def test_every_kind_and_option_has_a_tip(surface):
    name, source = surface
    tips = _tips(source)
    missing = [key for key in REQUIRED if key not in tips]
    assert not missing, f"{name}: no tooltip for {missing}"


def test_every_tip_is_a_plain_language_sentence(surface):
    name, source = surface
    for key, value in _tips(source).items():
        assert len(value) >= 25, f"{name}: tooltip {key!r} is too short to explain anything"
        assert " " in value, f"{name}: tooltip {key!r} is not a sentence"
        assert value.strip() == value and value.endswith("."), (
            f"{name}: tooltip {key!r} must be one trimmed sentence ending in a period"
        )
        assert key.replace(".", " ") not in value.lower(), (
            f"{name}: tooltip {key!r} just restates the field name"
        )


def test_every_kind_applies_its_tip(surface):
    """A palette button and a node must both show the kind's sentence."""
    name, source = surface
    assert "TIPS[kind]" in source or "TIPS[n.type]" in source, (
        f"{name}: the palette must title each node kind from TIPS"
    )
    assert 'svgEl("title"' in source, (
        f"{name}: an SVG node needs a child <title> — a title attribute does not show"
    )


def test_each_option_reference_uses_the_table(surface):
    name, source = surface
    for key in OPTION_KEYS:
        literal = f'TIPS["{key}"]'
        prefixed = f'TIPS["{key}.'  # e.g. output.target.custom
        parent = f'TIPS["{key.rsplit(".", 1)[0]}"]'
        assert literal in source or prefixed in source or parent in source, (
            f"{name}: inspector option {key!r} declares a tip but never applies it"
        )


def test_no_surface_declares_a_tip_it_never_shows(surface):
    """A tip for a control this canvas does not have is dead text, not documentation.

    This is how the standalone widget kept five `schedules.*` sentences for a job list it
    cannot render: harmless-looking, and the reason a copy's TIPS table stopped meaning
    "what this surface explains".
    """
    name, source = surface
    dead = []
    for key in _tips(source):
        stem = key.split(".")[0]
        applied = (
            f'TIPS["{key}"]' in source
            or f'TIPS["{key}.' in source            # a more specific tip, e.g. output.target.custom
            or f'TIPS["{key.rsplit(".", 1)[0]}"]' in source  # the parent's tip is reused
            or f'TIPS["{stem}."' in source          # chosen at render time, e.g. "presets." + name
        )
        if not applied:
            dead.append(key)
    assert not dead, f"{name}: tooltips declared but never shown: {dead}"


def test_inspector_field_helper_carries_a_tip(surface):
    name, source = surface
    assert "function field(labelText, control, tip)" in source, (
        f"{name}: field() must take the tip so every row applies it the same way"
    )
    assert "label.title = tip" in source and "control.title = tip" in source, (
        f"{name}: the tip belongs on the label and the control"
    )
