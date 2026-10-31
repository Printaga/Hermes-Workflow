"""Diagnose: call the host send seam directly with a full traceback."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])
HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
for _p in (_REPO, str(HOME / "hermes-agent")):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)


def main(live: bool = False) -> None:
    env = HOME / ".env"
    try:
        lines = env.read_text(encoding="utf-8", errors="ignore").splitlines()
    except FileNotFoundError:
        print(f"warn: no env file at {env}, continuing", file=sys.stderr)
        lines = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    print("interpreter:", sys.executable)
    import ruamel.yaml  # noqa: F401

    print("ruamel ok")
    from tools.send_message_tool import send_message_tool

    if not live:
        print("dry run: pass --live to send a test message")
        return
    try:
        out = send_message_tool(
            {"action": "send", "target": "telegram", "message": "TEST — visual-workflow seam probe"}
        )
        print("raw:", out)
    except Exception:
        traceback.print_exc()
        # A probe that failed must not look successful to CI/automation.
        sys.exit(1)


if __name__ == "__main__":
    main(live="--live" in sys.argv[1:])
