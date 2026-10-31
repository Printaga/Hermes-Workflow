"""Live test #1: send a TEST notification to the home channel via the real delivery seam."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])
HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
for _p in (_REPO, str(HOME / "hermes-agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# The hermes CLI loads <home>/.env into the process before it runs; a bare python process must
# do the same or the send seam cannot see TELEGRAM_HOME_CHANNEL.
def _load_dotenv() -> None:
    env = HOME / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    _load_dotenv()

    from visual_workflow_hermes import channels, delivery

    targets = channels.list_delivery_targets()
    print("targets discovered:", json.dumps(targets, indent=1))

    home = [t for t in targets if t.get("kind") == "home"]
    if not home:
        print("NO HOME CHANNEL; aborting")
        sys.exit(2)
    platform = home[0]["platform"]
    print("chosen target:", platform)

    text = (
        "TEST — visual-workflow live delivery test\n\n"
        "This is a test notification from the Hermes visual-workflow plugin.\n"
        "If you can read this, the notification delivery path works.\n"
        "No workflow data is attached."
    )
    receipt = delivery.deliver_output(
        {"id": "live-test", "deliver": "notification", "target": platform},
        {"message": text, "sent_at": "2026-10-29"},
        run_name="live-delivery-test",
    )
    print("receipt:", json.dumps(receipt, indent=1))


if __name__ == "__main__":
    # Importing this module must never send a live message.
    main()
