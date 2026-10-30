"""Diagnose: call the host send seam directly with a full traceback."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

_REPO = "/home/lenovo/Development/Hermes-Workflow"
for _p in (_REPO, "/home/lenovo/.hermes/hermes-agent"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

env = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")) / ".env"
for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

print("interpreter:", sys.executable)
import ruamel.yaml  # noqa: F401

print("ruamel ok")
from tools.send_message_tool import send_message_tool

try:
    out = send_message_tool(
        {"action": "send", "target": "telegram", "message": "TEST — visual-workflow seam probe"}
    )
    print("raw:", out)
except Exception:
    traceback.print_exc()
