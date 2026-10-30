"""Split one entangled working-tree diff into per-item patches.

Each hunk is assigned to exactly one queue item by the first rule that matches its
added/removed lines, so the four items can be reviewed (and reverted) independently.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PATCH = Path("/tmp/all.patch")
OUT = Path("/tmp/items")

# Ordered rules: the first match wins. Order matters where a hunk mentions two concerns.
RULES = [
    # item 4 — the Connect button and the click-click link queue it fed.
    ("item4", re.compile(
        r"connect\b|Connect|linkQueue|linkArm|bar\.connect|finishLink\(linkArm")),
    # item 3 — model catalog select, and the provider field/carry-through it replaces.
    ("item3", re.compile(
        r"modelField|modelCatalog|setModels|/models|agent\.model|current\.provider|"
        r'"provider"|provider \(|agent\.provider|profiles\.provider')),
    # item 2 — the node bar must not grow vertically.
    ("item2", re.compile(r"vw-kit\{|kit \{|flex: 0 0 auto|flex:0 0 auto|node bar")),
    # item 1 — a run/validate outcome the user cannot miss.
    ("item1", re.compile(
        r"banner|is not saved|Validate failed|Run failed|paused|aria-live|role=\\\\?\"status")),
]

HUNK_RE = re.compile(r"^@@ ")
FILE_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)$")


def main() -> int:
    lines = PATCH.read_text().splitlines(keepends=True)
    files: list[tuple[str, list[str]]] = []   # (header, hunk_lines)
    header: list[str] = []
    size = 0
    for line in lines:
        if FILE_RE.match(line):
            header = [line]
            size = 0
        elif line.startswith("index ") or line.startswith("--- ") or line.startswith("+++ "):
            header.append(line)
        elif HUNK_RE.match(line):
            size += 1
            files.append(("\n".join(h.rstrip("\n") for h in header), [line]))
        elif size:
            files[-1][1].append(line)
        else:  # pragma: no cover - unexpected diff preamble
            print("?? unhandled line:", line[:80])

    buckets: dict[str, list[tuple[str, list[str]]]] = {}
    for head, body in files:
        added = "".join(l for l in body if l[:1] in "+-")
        item = "rest"
        for name, rx in RULES:
            if rx.search(added):
                item = name
                break
        buckets.setdefault(item, []).append((head, body))
        first = body[0].strip()
        print(f"{item:6} {head.split('/')[-1]:16} {first[:60]}")

    OUT.mkdir(exist_ok=True)
    for item, chunks in buckets.items():
        parts = []
        for head, body in chunks:
            parts.append(head + "\n" + "".join(body))
        text = "\n".join(parts)
        if not text.endswith("\n"):
            text += "\n"
        (OUT / f"{item}.patch").write_text(text)
        print(f"wrote {item}.patch ({len(chunks)} hunk(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
