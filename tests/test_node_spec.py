"""Single node-spec guardrail against canvas drift.

Three canvases (`dashboard/dist/index.js`, `desktop/plugin.js`, `widgets/designer.html`) each
hand-maintain node kinds, fields and tooltips, and they have drifted before. This does not unify
them — it fails loudly the next time one of them gains a field the others (or `schema.py`) do not
know about, which is the whole value: a canvas offering a field the runner ignores, or a run
accepting a field no canvas can set, is caught here instead of by a confused user.

`node-spec.json` is hand-written on purpose: a spec generated from the code would agree with the
code by construction and guard nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from visual_workflow_hermes import schema

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "node-spec.json").read_text(encoding="utf-8"))
CANVASES = {
    "dashboard": ROOT / "dashboard" / "dist" / "index.js",
    "desktop": ROOT / "desktop" / "plugin.js",
    "widget": ROOT / "widgets" / "designer.html",
}
@pytest.fixture(scope="module", params=sorted(CANVASES))
def source(request) -> str:
    """Each canvas file in turn, so a drift fails naming the file that drifted."""
    return CANVASES[request.param].read_text(encoding="utf-8")


def _kinds() -> dict:
    return {row["kind"]: row for row in SPEC["kinds"]}


def test_spec_covers_every_kind_the_validator_accepts_plus_the_note():
    assert sorted(_kinds()) == sorted([*schema.NODE_KINDS, schema.NOTE_KIND])


def test_spec_required_fields_mirror_the_validator():
    expected = {kind: list(fields) for kind, fields in schema.REQUIRED_FIELDS.items()}
    expected[schema.NOTE_KIND] = []
    assert {kind: row["required"] for kind, row in _kinds().items()} == expected


def test_spec_enums_and_limits_mirror_the_constants():
    assert SPEC["trigger_modes"] == list(schema.TRIGGER_MODES)
    assert SPEC["deliver_modes"] == list(schema.DELIVER_MODES)
    assert SPEC["note_colors"] == list(schema.NOTE_COLORS)
    assert SPEC["limits"] == {
        "max_nodes": schema.MAX_NODES,
        "max_retries": schema.MAX_RETRIES,
        "max_timeout_minutes": schema.MAX_TIMEOUT_MINUTES,
    }


def test_spec_only_names_fields_the_python_side_actually_reads():
    """A spec field nobody validates or converts would be a control that does nothing."""
    backend = "".join(
        (ROOT / "visual_workflow_hermes" / name).read_text(encoding="utf-8")
        for name in ("schema.py", "convert.py")
    )
    for kind, row in _kinds().items():
        if kind == schema.NOTE_KIND:
            # A note's payload is deliberately unread by the backend: it annotates the canvas
            # and is dropped by the converter, so only its tooltips are asserted here.
            continue
        for field in row["fields"]:
            name = field["name"]
            assert f'"{name}"' in backend, f"{kind}.{name} is never read by schema/convert"


def test_required_fields_are_the_prefix_of_every_canvas_field_list():
    for kind, row in _kinds().items():
        listed = [f["name"] for f in row["fields"]]
        assert set(row["required"]) <= set(listed), kind


def test_every_canvas_offers_exactly_the_spec_kinds(source):
    for kind in _kinds():
        assert f'data-kind="{kind}"' in source, f"missing palette button for {kind!r}"


def test_every_canvas_defines_every_spec_tooltip(source):
    """Field tooltips are the contract users read; a field without one is a guess."""
    for kind, row in _kinds().items():
        # The map is a JS object literal, so the key may be bare (`trigger:`) or quoted.
        assert re.search(rf'(^|[\s{{,]){kind}["\']?\s*:', source, re.M), (
            f"no tip text defined for {kind!r}"
        )
        # Defined is not wired: an orphaned field entry in the TIPS map renders nothing. The
        # accepted forms match tests/test_tooltips.py, which owns the wording of every tip (and
        # which this file deliberately does not restate): the exact key, a more specific one
        # (`output.target.custom`), or the parent's (`output.target` for `.custom`). Kind-level
        # tips are read through `TIPS[n.type]`, so the definition assert above covers them.
        tips = [f["tip"] for f in row["fields"]] + list(row["tips"])
        for tip in tips:
            parent = tip.rsplit(".", 1)[0]
            wired = any(
                form in source
                for form in (f'TIPS["{tip}"]', f'TIPS["{tip}.', f'TIPS["{parent}"]')
            )
            assert wired, f"{kind}: {tip!r} is not wired to a control"
